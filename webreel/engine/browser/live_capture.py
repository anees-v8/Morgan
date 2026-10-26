"""
Live "beat" capture: records the *real* page (hover states, scroll, route transitions,
CSS animations) as timestamped frames while a human-like mouse choreography runs.

Why CDP screencast and not Playwright's record_video:
  - record_video is a low-bitrate VP8 stream that starts at page creation, so syncing it
    to events is guesswork. Screencast frames carry exact timestamps (same clock as
    time.time()), are JPEG at a quality we choose, and arrive at ~60fps (measured).
  - It also works on every Playwright >=1.48 (we talk raw CDP), unlike page.screencast (>=1.59).

The cursor is intentionally NOT part of the pixels (headless never draws one). Instead the
exact analytic cursor track is saved next to the frames and the renderer draws a crisp,
motion-blurred cursor in the same coordinate space as the page, so camera zoom/pan and
the 3D window tilt can never detach it from the content.
"""
import asyncio
import base64
import json
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..motion import CursorMove, CursorSegment, sample_track

Vec = Tuple[float, float]

# Smooth, eased, compositor-friendly scroll executed *inside* the page (rAF), so every
# captured frame is a genuine intermediate state (sub-pixel scroll positions included).
_SMOOTH_SCROLL_JS = """
(args) => new Promise(res => {
  const [target, dur] = args;
  const y0 = window.scrollY, t0 = performance.now();
  const max = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
  const y1 = Math.max(0, Math.min(max, target));
  const ease = t => t < .5 ? 4*t*t*t : 1 - Math.pow(-2*t + 2, 3) / 2;
  function step(now) {
    const t = Math.min(1, (now - t0) / dur);
    window.scrollTo(0, y0 + (y1 - y0) * ease(t));
    if (t < 1) requestAnimationFrame(step); else res(true);
  }
  requestAnimationFrame(step);
})
"""

# Boxes worth looking at while the narrator talks: headings first, then hero media, then copy.
# Navigation/footers/dialogs are excluded so a hover never opens a menu over the content.
_ANCHORS_JS = """
() => {
  const vw = innerWidth, vh = innerHeight;
  const vis = e => {
    const r = e.getBoundingClientRect(), cs = getComputedStyle(e);
    return r.width > 60 && r.height > 18 && r.top >= 4 && r.bottom <= vh - 4 && r.left >= 0 && r.right <= vw &&
           cs.visibility !== 'hidden' && cs.display !== 'none' && parseFloat(cs.opacity) > 0.05;
  };
  const skip = e => !!e.closest('nav, footer, [role=dialog], [aria-modal=true], [role=menu], [role=navigation]');
  const box = e => { const r = e.getBoundingClientRect(); return {x: r.x, y: r.y, width: r.width, height: r.height, tag: e.tagName}; };
  const pick = (sel, n) => [...document.querySelectorAll(sel)].filter(e => vis(e) && !skip(e)).slice(0, n).map(box);
  const media = [...document.querySelectorAll('img, video, canvas, svg, picture')]
      .filter(e => vis(e) && !skip(e) && e.getBoundingClientRect().width > 220 && e.getBoundingClientRect().height > 140)
      .sort((a, b) => {const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect(); return rb.width*rb.height - ra.width*ra.height;})
      .slice(0, 2).map(box);
  return {headings: pick('h1, h2, h3', 3), media: media, copy: pick('p', 2)};
}
"""


def _box_center(b: Dict[str, float]) -> Vec:
    return (b["x"] + b["width"] / 2.0, b["y"] + b["height"] / 2.0)


class LiveBeat:
    """
    One recorded interaction. Typical use inside the recorder:

        beat = LiveBeat(page, cdp, out_dir, "scene_00_hero", (1280, 800), start_pos)
        await beat.start()
        await beat.hold(0.7)
        await beat.scan(anchor_box)             # optional "reading" hover
        await beat.approach(target_box)         # curved human move + dwell
        await beat.click(perform=True)          # real mouse down/up
        await beat.hold(1.6)                    # let the page react, live
        meta_path = await beat.stop()

    Every public coroutine is exception-safe from the caller's point of view: a failure marks
    the beat as `failed` and the recorder falls back to the classic instant click.
    """

    def __init__(
        self,
        page,
        cdp,
        out_dir: Path,
        scene_id: str,
        viewport: Tuple[int, int],
        start_pos: Vec,
        seed: int = 0,
        quality: int = 92,
    ):
        self.page = page
        self.cdp = cdp
        self.scene_id = scene_id
        self.vw, self.vh = viewport
        self.seed = seed
        self.quality = quality
        self.frames_dir = out_dir / f"{scene_id}_live"
        if self.frames_dir.exists():
            shutil.rmtree(self.frames_dir, ignore_errors=True)
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self.meta_path = self.frames_dir / "clip.json"

        self.pos: Vec = (float(start_pos[0]), float(start_pos[1]))
        self.start_pos: Vec = self.pos
        self.segments: List[CursorSegment] = []
        self.clicks: List[Dict[str, Any]] = []
        self.focus: List[Dict[str, Any]] = []
        self.phases: Dict[str, float] = {}
        self.url_events: List[Dict[str, Any]] = []
        self.frame_times: List[float] = []
        self.failed = False
        self.error: Optional[str] = None
        self.click_done = False
        self._t0 = 0.0
        self._started = False
        self._pending_acks: set = set()
        self._handler = None
        self._move_counter = 0

    # ------------------------------------------------------------------ clock
    def now(self) -> float:
        return time.time() - self._t0

    async def _sleep_until(self, t_rel: float):
        remaining = (self._t0 + t_rel) - time.time()
        if remaining > 0:
            await asyncio.sleep(remaining)

    # ----------------------------------------------------------------- frames
    def _on_frame(self, event: Dict[str, Any]):
        try:
            meta = event.get("metadata") or {}
            ts = float(meta.get("timestamp") or time.time())
            idx = len(self.frame_times)
            (self.frames_dir / f"{idx:05d}.jpg").write_bytes(base64.b64decode(event["data"]))
            self.frame_times.append(ts - self._t0)
        except Exception as e:
            self.failed = True
            self.error = self.error or repr(e)
        finally:
            task = asyncio.ensure_future(self._ack(event.get("sessionId")))
            self._pending_acks.add(task)
            task.add_done_callback(self._pending_acks.discard)

    async def _ack(self, session_id):
        try:
            await self.cdp.send("Page.screencastFrameAck", {"sessionId": session_id})
        except Exception:
            pass

    async def start(self):
        self._handler = self._on_frame
        self.cdp.on("Page.screencastFrame", self._handler)
        self._t0 = time.time()
        await self.cdp.send(
            "Page.startScreencast",
            {"format": "jpeg", "quality": self.quality, "maxWidth": self.vw, "maxHeight": self.vh, "everyNthFrame": 1},
        )
        self._started = True
        self.url_events.append({"t": 0.0, "url": self.page.url})
        # Park the real pointer where the previous beat left it so hover state is continuous.
        try:
            await self.page.mouse.move(*self.pos)
        except Exception:
            pass

    async def nudge_frames(self):
        """Force a fresh frame (Chromium only emits frames on visual change)."""
        try:
            await self.cdp.send(
                "Page.startScreencast",
                {"format": "jpeg", "quality": self.quality, "maxWidth": self.vw, "maxHeight": self.vh, "everyNthFrame": 1},
            )
        except Exception:
            pass

    async def stop(self) -> Optional[Path]:
        if not self._started:
            return None
        try:
            await self.nudge_frames()
            await asyncio.sleep(0.12)
        except Exception:
            pass
        duration = self.now()
        try:
            await self.cdp.send("Page.stopScreencast")
        except Exception:
            pass
        try:
            self.cdp.remove_listener("Page.screencastFrame", self._handler)
        except Exception:
            pass
        if self._pending_acks:
            await asyncio.gather(*list(self._pending_acks), return_exceptions=True)
        self._started = False

        # Chromium only emits frames when pixels change, so a still page legitimately yields just
        # one or two. Sample-and-hold needs a single frame; zero means capture really broke.
        if len(self.frame_times) < 1:
            self.failed = True
            self.error = self.error or "no frames received"
            return None

        meta = {
            "version": 1,
            "scene_id": self.scene_id,
            "viewport": {"width": self.vw, "height": self.vh},
            "duration": round(max(duration, self.frame_times[-1]), 4),
            "frame_times": [round(t, 4) for t in self.frame_times],
            "cursor": {
                "start": [round(self.start_pos[0], 2), round(self.start_pos[1], 2)],
                "end": [round(self.pos[0], 2), round(self.pos[1], 2)],
                "track": sample_track(self.segments, self.start_pos, duration, hz=120),
            },
            "clicks": self.clicks,
            "focus": self.focus,
            "phases": self.phases,
            "url_events": self.url_events,
        }
        self.meta_path.write_text(json.dumps(meta), encoding="utf-8")
        return self.meta_path

    # ------------------------------------------------------------ choreography
    async def hold(self, seconds: float):
        await self._sleep_until(self.now() + max(0.0, seconds))

    async def scroll_smooth(self, target_y: float, duration_ms: int = 1300):
        t = self.now()
        self.phases.setdefault("scroll_start", t)
        await self.page.evaluate(_SMOOTH_SCROLL_JS, [target_y, duration_ms])
        self.phases["scroll_end"] = self.now()

    async def scroll_by_smooth(self, dy: float, duration_ms: int = 1300):
        y = await self.page.evaluate("() => window.scrollY")
        await self.scroll_smooth(y + dy, duration_ms)

    async def find_anchors(self) -> Dict[str, List[Dict[str, float]]]:
        try:
            return await self.page.evaluate(_ANCHORS_JS)
        except Exception:
            return {"headings": [], "media": [], "copy": []}

    async def _glide(self, to: Vec, target_width: float, slow: float, overshoot: bool, kind: str) -> CursorMove:
        self._move_counter += 1
        move = CursorMove(
            self.pos, to, target_width=target_width, seed=self.seed * 131 + self._move_counter,
            slow=slow, overshoot=overshoot,
        )
        t0 = self.now()
        self.segments.append(CursorSegment(t0=t0, move=move))
        wall0 = time.time()
        while True:
            el = time.time() - wall0
            x, y = move.pos(el)
            await self.page.mouse.move(x, y)
            if el >= move.duration:
                break
            await asyncio.sleep(0.004)
        await self.page.mouse.move(*move.p1)
        self.pos = move.p1
        return move

    async def scan(self, box: Dict[str, float], dwell: float = 0.75, x_bias: Optional[float] = None):
        """Glide to a point inside `box` (hover only, no click) and linger like a reader."""
        cx, cy = _box_center(box)
        if x_bias is not None:
            cx = box["x"] + min(box["width"] * x_bias, 320.0)
        cx = max(8.0, min(self.vw - 8.0, cx))
        cy = max(8.0, min(self.vh - 8.0, cy))
        t_move = self.now()
        self.focus.append({"t": round(t_move, 3), "box": box, "kind": "scan", "to": [cx, cy]})
        await self._glide((cx, cy), target_width=max(box["width"], 120.0), slow=1.0, overshoot=False, kind="scan")
        self.focus[-1]["arrive"] = round(self.now(), 3)
        await self.hold(dwell)

    async def approach(self, box: Dict[str, float], dwell: float = 0.5):
        """Glide to the exact element that will be clicked, with a slight human offset."""
        cx, cy = _box_center(box)
        # Land a touch off-centre on big targets (people never hit the exact middle).
        jitter_x = max(-0.06 * box["width"], min(0.06 * box["width"], (self.seed % 7 - 3) * 0.02 * box["width"]))
        cx += jitter_x
        cx = max(8.0, min(self.vw - 8.0, cx))
        cy = max(8.0, min(self.vh - 8.0, cy))
        t_move = self.now()
        self.phases["action_start"] = min(self.phases.get("action_start", t_move), t_move)
        self.focus.append({"t": round(t_move, 3), "box": box, "kind": "target", "to": [cx, cy]})
        await self._glide((cx, cy), target_width=max(min(box["width"], box["height"] * 3), 24.0),
                          slow=1.0, overshoot=True, kind="approach")
        self.focus[-1]["arrive"] = round(self.now(), 3)
        self.phases["hover_start"] = self.now()
        await self.hold(dwell)

    async def click(self, perform: bool = True, press_ms: int = 95):
        """Press/release at the current pointer position. perform=False only *shows* a click."""
        t = self.now()
        x, y = self.pos
        self.clicks.append({"t": round(t, 3), "x": round(x, 2), "y": round(y, 2), "performed": bool(perform),
                            "press": press_ms / 1000.0})
        self.phases["click"] = t
        if perform:
            await self.page.mouse.down()
            await asyncio.sleep(press_ms / 1000.0)
            await self.page.mouse.up()
            self.click_done = True

    async def settle(self, seconds: float):
        """Post-click live recording; polls the URL so the address bar can follow navigation."""
        end = self.now() + seconds
        last = self.page.url
        nudged = False
        while self.now() < end:
            await asyncio.sleep(0.08)
            try:
                url = self.page.url
            except Exception:
                break
            if url != last:
                self.url_events.append({"t": round(self.now(), 3), "url": url})
                last = url
            if not nudged and self.now() > self.phases.get("click", 0.0) + 0.55:
                nudged = True
                await self.nudge_frames()
        self.phases["react_end"] = self.now()

    def release_camera(self):
        self.focus.append({"t": round(self.phases.get("click", self.now()) + 0.9, 3), "box": None, "kind": "release"})
