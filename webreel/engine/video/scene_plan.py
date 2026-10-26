"""
ScenePlan: everything the renderer needs to know about one scene, expressed in *scene time*
(seconds since the scene's first frame, at the voice-over-driven duration):

  - which source pixels are on screen          (frame_at)
  - where the pointer is                       (cursor_at, in source pixel space)
  - when/where it presses                      (clicks)
  - what the virtual camera should look at     (camera_events)
  - what the address bar should read           (url_at)

Live plans re-time a recorded browser beat (see engine.browser.live_capture) onto the scene
duration: the narration is usually longer than the interaction, so the extra seconds are
spent where a human presenter would spend them - lingering on what they are talking about -
instead of one long frozen tail.
"""
import bisect
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

import cv2
import numpy as np

from ..motion import CursorMove, CursorSegment, clamp, evaluate_track, idle_drift
from .live_clip import LiveClip
from . import stage as S

Vec = Tuple[float, float]


@dataclass
class ClickEvent:
    t: float
    x: float
    y: float
    press: float = 0.095
    performed: bool = True


@dataclass
class CameraEvent:
    t: float
    cx: float
    cy: float
    zoom: float
    kind: str = "focus"       # focus | neutral


class TimeMap:
    """Piecewise-linear map between scene time and clip time with 'freeze' plateaus."""

    def __init__(self, clip_len: float, scene_len: float, freezes: List[Tuple[float, float]], pre: float):
        self.tout: List[float] = [0.0]
        self.tau: List[float] = [0.0]
        cur_out, cur_tau = 0.0, 0.0
        if pre > 1e-6:
            cur_out += pre
            self.tout.append(cur_out)
            self.tau.append(0.0)
        for tau_k, ext in sorted(freezes):
            tau_k = clamp(tau_k, cur_tau, clip_len)
            cur_out += tau_k - cur_tau
            cur_tau = tau_k
            self.tout.append(cur_out)
            self.tau.append(cur_tau)
            if ext > 1e-6:
                cur_out += ext
                self.tout.append(cur_out)
                self.tau.append(cur_tau)
        cur_out += max(0.0, clip_len - cur_tau)
        self.tout.append(cur_out)
        self.tau.append(clip_len)
        if scene_len > cur_out:
            self.tout.append(scene_len)
            self.tau.append(clip_len)
        self.clip_len = clip_len
        self._tout = np.asarray(self.tout)
        self._tau = np.asarray(self.tau)

    def tau_of(self, t: float) -> float:
        return float(np.interp(t, self._tout, self._tau))

    def t_of_tau(self, tau: float) -> float:
        """Scene time at which clip time `tau` is first reached."""
        for i in range(1, len(self.tau)):
            a, b = self.tau[i - 1], self.tau[i]
            if b > a and a - 1e-9 <= tau <= b + 1e-9:
                f = (tau - a) / (b - a)
                return self.tout[i - 1] + f * (self.tout[i] - self.tout[i - 1])
        return self.tout[-1] if tau >= self.clip_len else 0.0


class ScenePlan:
    def __init__(
        self,
        duration: float,
        src_size: Tuple[int, int],
        frame_at: Callable[[float], np.ndarray],
        cursor_base: Callable[[float], Vec],
        clicks: List[ClickEvent],
        camera_events: List[CameraEvent],
        urls: List[Tuple[float, str]],
        seed: int = 0,
        live: bool = False,
    ):
        self.duration = duration
        self.src_size = src_size
        self.frame_at = frame_at
        self._cursor_base = cursor_base
        self.clicks = sorted(clicks, key=lambda c: c.t)
        self.camera_events = sorted(camera_events, key=lambda e: e.t)
        self._cam_times = [e.t for e in self.camera_events]
        self.urls = sorted(urls, key=lambda u: u[0])
        self._url_times = [u[0] for u in self.urls]
        self.seed = seed
        self.live = live
        self.fallback_domain = ""
        self.click_time: float = self.clicks[0].t if self.clicks else 0.0

    # --------------------------------------------------------------- pointer
    def cursor_at(self, t: float) -> Vec:
        x, y = self._cursor_base(t)
        # hand tremor, faded out right around presses so the click lands exactly on target
        w = 1.0
        for c in self.clicks:
            d = abs(t - c.t)
            if d < 0.7:
                w = min(w, d / 0.7)
        dx, dy = idle_drift(t, self.seed, amplitude=1.3 * w)
        return x + dx, y + dy

    # ---------------------------------------------------------------- camera
    def camera_target(self, t: float, tg: float) -> Tuple[float, float, float]:
        sw, sh = self.src_size
        i = bisect.bisect_right(self._cam_times, t) - 1
        ev = self.camera_events[i] if i >= 0 else CameraEvent(0.0, sw / 2.0, sh / 2.0, 1.0, "neutral")
        cx, cy, z = ev.cx, ev.cy, ev.zoom
        if ev.kind in ("focus", "scan"):
            # slow push-in while lingering on a subject: the shot keeps breathing
            z *= 1.0 + (0.03 if ev.kind == "focus" else 0.012) * (1.0 - np.exp(-(t - ev.t) / 2.6))
        # ambient breathing so even a "static" hold is alive
        z *= 1.0 + 0.007 * np.sin(2 * np.pi * tg / 11.0)
        cx += 3.0 * np.sin(2 * np.pi * tg / 9.1)
        cy += 2.0 * np.sin(2 * np.pi * tg / 7.3 + 1.0)
        # keep the visible rectangle inside the page (cover-fit aspect)
        bs = max(S.CONT_W / sw, S.CONT_H / sh)
        vis_w, vis_h = S.CONT_W / (bs * z), S.CONT_H / (bs * z)
        cx = clamp(cx, vis_w / 2.0, max(vis_w / 2.0, sw - vis_w / 2.0))
        cy = clamp(cy, vis_h / 2.0, max(vis_h / 2.0, sh - vis_h / 2.0))
        return cx, cy, z

    # ------------------------------------------------------------------- url
    def url_at(self, t: float) -> Optional[str]:
        if not self.urls:
            return None
        i = bisect.bisect_right(self._url_times, t) - 1
        return self.urls[max(0, i)][1]


# ------------------------------------------------------------------------- builders
def focus_for_box(box, to, src_size, scan: bool = False) -> Tuple[float, float, float]:
    """
    Camera framing for an element. Zoom is reserved for things that get PRESSED: small controls
    get a firm push. Something the pointer merely rests on (scan) only gets a hint of a push,
    so the camera never dives into content for no reason.
    """
    sw, sh = src_size
    cx, cy = box["x"] + box["width"] / 2.0, box["y"] + box["height"] / 2.0
    frac_w = clamp(box["width"] / (0.62 * sw))
    frac_h = clamp(box["height"] / (0.55 * sh))
    z = (1.0 + 0.05 * (1.0 - max(frac_w, frac_h))) if scan else (1.30 - 0.17 * max(frac_w, frac_h))
    # lean toward where the pointer is heading, not just the element centre
    cx = 0.55 * cx + 0.45 * to[0]
    cy = 0.55 * cy + 0.45 * to[1]
    return cx, cy, z


def build_live_plan(clip: LiveClip, duration: float, fallback_domain: str, seed: int = 0) -> ScenePlan:
    L = clip.duration
    sw, sh = clip.size

    # ---- where to spend the narration's extra seconds (cursor "dwell" moments) ----
    freezes: List[Tuple[float, float, float]] = []   # (tau, weight, cap)
    moves = sorted(clip.focus, key=lambda f: f["t"])
    for i, f in enumerate(moves):
        if f["kind"] not in ("scan", "target") or "arrive" not in f:
            continue
        nxt = next((g["t"] for g in moves[i + 1:] if g["kind"] in ("scan", "target")), L)
        tau = min(f["arrive"] + (0.45 if f["kind"] == "scan" else 0.40), max(f["arrive"] + 0.1, nxt - 0.12))
        freezes.append((tau, 1.0 if f["kind"] == "scan" else 0.8, 3.4))

    slack = duration - L
    pre = 0.0
    freeze_ext: List[Tuple[float, float]] = []
    if slack > 0:
        pre = min(2.2, 0.20 * slack)
        post_target = min(3.0, 0.18 * slack)
        pool = max(0.0, slack - pre - post_target)
        wsum = sum(w for _, w, _ in freezes) or 1.0
        for tau, w, cap in freezes:
            freeze_ext.append((tau, min(cap, pool * w / wsum)))
    tm = TimeMap(L, duration, freeze_ext, pre)
    # If the scene is shorter than the clip, the clip is simply cut at the scene end.

    # ---- pointer, clicks, address bar ----
    def cursor_base(t: float) -> Vec:
        return clip.cursor_at(tm.tau_of(t))

    clicks = [ClickEvent(t=tm.t_of_tau(c["t"]), x=c["x"], y=c["y"], press=c.get("press", 0.095),
                         performed=bool(c.get("performed", True))) for c in clip.clicks]

    urls: List[Tuple[float, str]] = []
    for u in clip.url_events:
        urls.append((0.0 if not urls else tm.t_of_tau(u["t"]) + 0.12, u["url"]))

    # ---- camera script ----
    events: List[CameraEvent] = [CameraEvent(0.0, sw / 2.0, sh / 2.0, 1.0, "neutral")]
    for f in moves:
        if f["kind"] in ("scan", "target") and f.get("box"):
            is_scan = f["kind"] == "scan"
            cx, cy, z = focus_for_box(f["box"], f.get("to", (f["box"]["x"], f["box"]["y"])), (sw, sh), scan=is_scan)
            events.append(CameraEvent(max(0.0, tm.t_of_tau(max(0.0, f["t"] - 0.12))), cx, cy, z, "scan" if is_scan else "focus"))
        elif f["kind"] == "release":
            events.append(CameraEvent(tm.t_of_tau(min(f["t"], L)), sw / 2.0, sh / 2.0, 1.0, "neutral"))
    last_t = events[-1].t
    if events[-1].kind != "neutral":
        events.append(CameraEvent(min(duration - 0.5, last_t + 1.0), sw / 2.0, sh / 2.0, 1.0, "neutral"))

    def frame_at(t: float) -> np.ndarray:
        return clip.frame_at(tm.tau_of(t))

    plan = ScenePlan(duration, (sw, sh), frame_at, cursor_base, clicks, events, urls, seed=seed, live=True)
    plan.fallback_domain = fallback_domain
    return plan


def build_static_plan(
    image_bgr: np.ndarray,
    duration: float,
    target_xy: Tuple[float, float],
    start_norm: Optional[Tuple[float, float]] = None,
    seed: int = 0,
    domain: str = "",
    zoom_in: bool = True,
    target_size: Tuple[float, float] = (160.0, 48.0),
    do_click: bool = True,
) -> ScenePlan:
    """
    Screenshot-driven plan (live capture unavailable, or the outro card): same camera and
    pointer language as the live plan, but the page itself is a still image.
    `target_xy` is in the *image's* pixel space.
    """
    ih, iw = image_bgr.shape[:2]
    # Work at 1.2x the on-screen content size so zoomed moves stay sharp.
    sw, sh = int(S.CONT_W * 1.2), int(S.CONT_H * 1.2)
    k = max(sw / iw, sh / ih)
    interp = cv2.INTER_AREA if k < 1.0 else cv2.INTER_LANCZOS4
    resized = cv2.resize(image_bgr, (max(sw, int(round(iw * k))), max(sh, int(round(ih * k)))), interpolation=interp)
    rh, rw = resized.shape[:2]
    ox, oy = (rw - sw) // 2, (rh - sh) // 2
    src = np.ascontiguousarray(resized[oy:oy + sh, ox:ox + sw])
    tx = clamp(target_xy[0] * k - ox, 20, sw - 20)
    ty = clamp(target_xy[1] * k - oy, 20, sh - 20)

    if start_norm is not None:
        start = (start_norm[0] * sw, start_norm[1] * sh)
    else:
        start = (sw * 0.62, sh * 0.80)

    click_t = max(1.6, 0.42 * duration)
    move = CursorMove(start, (tx, ty), target_width=max(target_size[0] * k, 60.0), seed=seed + 5)
    move_t0 = max(0.45, click_t - 0.50 - move.duration)
    segs = [CursorSegment(t0=move_t0, move=move)]
    click_t = max(click_t, move_t0 + move.duration + 0.50)

    def cursor_base(t: float) -> Vec:
        return evaluate_track(segs, start, t)

    clicks = [ClickEvent(t=click_t, x=tx, y=ty, performed=True)] if do_click else []

    box = {"x": tx - target_size[0] * k / 2, "y": ty - target_size[1] * k / 2,
           "width": target_size[0] * k, "height": target_size[1] * k}
    cx, cy, z = focus_for_box(box, (tx, ty), (sw, sh))
    if not zoom_in:
        z = min(z, 1.12)
    events = [CameraEvent(0.0, sw / 2.0, sh / 2.0, 1.0, "neutral"),
              CameraEvent(max(0.0, move_t0 - 0.10), cx, cy, z, "focus"),
              CameraEvent(min(duration - 0.4, click_t + 1.0), sw / 2.0, sh / 2.0, 1.0, "neutral")]
    plan = ScenePlan(duration, (sw, sh), lambda t: src, cursor_base, clicks, events,
                     [(0.0, f"https://{domain}")] if domain else [], seed=seed, live=False)
    plan.fallback_domain = domain
    return plan
