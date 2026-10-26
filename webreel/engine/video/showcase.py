"""
Showcase renderer: turns a ScenePlan into 1920x1080 frames.

Layer order (back to front), all driven by the same per-frame state so nothing can drift apart:

    drifting studio backdrop (dithered)
    -> soft window shadow (derived from the *warped* window alpha, so it follows the tilt)
    -> macOS window  = [live page -> spring camera crop -> pointer + click ripple] + chrome
       warped by a real pinhole 3D projection (tilt relaxes while the camera zooms in to read)
    -> 3 benefit cards (own parallax layer, activation hand-off, progress rail synced to the scene)

Pointer and camera live in *page space*: the pointer is stamped into the camera-cropped
content, i.e. it is zoomed/panned/tilted exactly like the page it points at.
"""
import math
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from ..motion import clamp, ease_out_back, ease_out_cubic, ease_out_expo, smoothstep, spring_step
from . import stage as S
from .exporter import RawVideoWriter
from .scene_plan import ScenePlan

SUB = 4                 # camera simulation sub-steps per output frame (also the motion-blur resolution)
OMEGA_PAN = 4.3         # spring stiffness (rad/s): ~0.9s to settle a pan
OMEGA_ZOOM = 3.7
FOCAL = 2100.0          # pinhole focal length in canvas px (perspective strength)
CURSOR_PX = 25.0        # on-screen height of the arrow at zoom 1.0
PROFILE = os.getenv("WEBREEL_PROFILE") == "1"


# =============================================================================== assets
class Assets:
    """Everything expensive that is identical for every scene of a job (built once, cached)."""

    def __init__(self, domain: str, palette: Dict, cards: List[Dict[str, str]]):
        self.domain = domain
        self.palette = palette
        self.accent_rgb: Tuple[int, int, int] = tuple(palette["accent_rgb"])
        self.accent_bgr: Tuple[int, int, int] = self.accent_rgb[::-1]
        self.chrome = S.build_window_chrome()
        self.content_alpha = S.window_content_alpha()
        n = min(3, len(cards))
        self.card_inactive = [S.build_card_sprite(cards[i], i, self.accent_rgb, False) for i in range(n)]
        self.card_active = [S.build_card_sprite(cards[i], i, self.accent_rgb, True) for i in range(n)]
        self.cursor, self.cursor_hot, self.cursor_sc = S.build_cursor_sprite()
        self.background = S.Background(palette)
        self._windows: Dict[Tuple[str, str], np.ndarray] = {}
        self.combined: Dict[Tuple[int, int], Tuple[np.ndarray, int, int]] = {}
        r = S.WIN_R + 2
        self._corner_l = self.content_alpha[S.CONT_H - r:, :r].copy()
        self._corner_r = self.content_alpha[S.CONT_H - r:, S.CONT_W - r:].copy()
        self.corner_r = r
        # sheen ramp (diagonal band) in content space
        ys, xs = np.mgrid[0:S.CONT_H, 0:S.CONT_W].astype(np.float32)
        self.sheen_u = xs * 0.82 + ys * 0.57

    def window_base(self, host: str, path: str) -> np.ndarray:
        key = (host, path)
        if key not in self._windows:
            base = self.chrome.copy()
            pill, px, py = S.build_url_pill(host, path)
            S.blend_premult_inplace(base, pill, px, py)
            self._windows[key] = base
        return self._windows[key]

    def finish_window(self, win: np.ndarray, content: np.ndarray) -> None:
        """Insert the content into the window sprite, rounding the two bottom corners."""
        cv2.cvtColor(content, cv2.COLOR_BGR2BGRA, dst=win[S.TOP_H:])      # also sets alpha = 255
        r = self.corner_r
        for sl, m in ((slice(0, r), self._corner_l), (slice(S.WIN_W - r, S.WIN_W), self._corner_r)):
            p = win[S.WIN_H - r:, sl]
            p[:, :, :3] = (p[:, :, :3].astype(np.uint16) * m[:, :, None] // 255).astype(np.uint8)
            p[:, :, 3] = m


_ASSET_CACHE: Dict[Tuple, Assets] = {}


def get_assets(domain: str, palette: Dict, cards: List[Dict[str, str]]) -> Assets:
    key = (domain, tuple(palette["accent_rgb"]), tuple((c.get("category"), c.get("title"), c.get("desc")) for c in cards[:3]))
    if key not in _ASSET_CACHE:
        if len(_ASSET_CACHE) > 3:
            _ASSET_CACHE.clear()
        _ASSET_CACHE[key] = Assets(domain, palette, cards)
    return _ASSET_CACHE[key]


# =============================================================================== blending
def blend_premult(dst: np.ndarray, src: np.ndarray, x: int, y: int, opacity: float = 1.0) -> None:
    """dst(BGR) = src(BGRA premult) over dst, clipped to the canvas, SIMD via OpenCV."""
    h, w = src.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(dst.shape[1], x + w), min(dst.shape[0], y + h)
    if x1 <= x0 or y1 <= y0 or opacity <= 0.002:
        return
    s = src[y0 - y:y1 - y, x0 - x:x1 - x]
    roi = dst[y0:y1, x0:x1]
    rgb = s[:, :, :3]
    a = s[:, :, 3]
    if opacity < 0.998:
        rgb = cv2.convertScaleAbs(rgb, alpha=opacity)
        a = cv2.convertScaleAbs(a, alpha=opacity)
    inv = cv2.cvtColor(cv2.bitwise_not(a), cv2.COLOR_GRAY2BGR)
    tmp = cv2.multiply(roi, inv, scale=1.0 / 255.0)
    cv2.add(tmp, rgb, dst=roi)


def blend_window(dst: np.ndarray, patch: np.ndarray, x0: int, y0: int, opacity: float,
                 inner: Optional[Tuple[int, int, int, int]]) -> None:
    """
    Composite the (opaque-interior) window patch. The big inner rectangle is a straight copy;
    only the thin border strips (rounded corners, anti-aliased edges) need real alpha blending.
    """
    ph, pw = patch.shape[:2]
    if (opacity < 0.998 or inner is None or x0 < 0 or y0 < 0 or x0 + pw > dst.shape[1] or y0 + ph > dst.shape[0]):
        blend_premult(dst, patch, x0, y0, opacity)
        return
    ix0, iy0, ix1, iy1 = inner
    ix0, iy0, ix1, iy1 = max(0, ix0), max(0, iy0), min(pw, ix1), min(ph, iy1)
    if ix1 - ix0 < 16 or iy1 - iy0 < 16:
        blend_premult(dst, patch, x0, y0, opacity)
        return
    roi_in = dst[y0 + iy0:y0 + iy1, x0 + ix0:x0 + ix1]
    roi_in[:] = cv2.cvtColor(patch[iy0:iy1, ix0:ix1], cv2.COLOR_BGRA2BGR)
    if iy0 > 0:
        blend_premult(dst, patch[0:iy0, :], x0, y0)
    if iy1 < ph:
        blend_premult(dst, patch[iy1:ph, :], x0, y0 + iy1)
    if ix0 > 0:
        blend_premult(dst, patch[iy0:iy1, 0:ix0], x0, y0 + iy0)
    if ix1 < pw:
        blend_premult(dst, patch[iy0:iy1, ix1:pw], x0 + ix1, y0 + iy0)


def _stamp_affine(content: np.ndarray, sprite: np.ndarray, hot: Tuple[float, float], sc: float,
                  x: float, y: float) -> None:
    """Stamp a premult BGRA sprite so its hotspot lands on (x, y) at sub-pixel precision."""
    sh, sw = sprite.shape[:2]
    ox, oy = x - hot[0] * sc, y - hot[1] * sc
    rx0, ry0 = int(math.floor(ox)) - 1, int(math.floor(oy)) - 1
    rw, rh = int(math.ceil(sw * sc)) + 4, int(math.ceil(sh * sc)) + 4
    A = np.float32([[sc, 0.0, ox - rx0], [0.0, sc, oy - ry0]])
    patch = cv2.warpAffine(sprite, A, (rw, rh), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
    blend_premult(content, patch, rx0, ry0)


def _draw_click_feedback(content: np.ndarray, x: float, y: float, dt: float, press: float,
                        color_bgr: Tuple[int, int, int], zoom: float) -> None:
    """
    Click feedback modelled on a real press instead of a game-style ripple:
      mouse DOWN  -> a soft translucent highlight blooms under the pointer and compresses a little
      mouse UP    -> it releases outward as ONE thin ring that fades away (~0.5 s)
    Sub-pixel circles (shift=4), brand-coloured so it reads on both light and dark pages.
    """
    rel = dt - press
    if dt < -0.01 or rel > 0.52:
        return
    zf = max(1.0, zoom)
    if rel <= 0.0:                                   # button is held down
        k = ease_out_cubic(max(0.0, dt) / 0.09)
        radius, a_fill, a_ring = (22.0 - 8.0 * k) * zf, 0.30 * k, 0.0
    else:                                            # released
        u = rel / 0.52
        e = ease_out_cubic(u)
        radius, a_fill, a_ring = (14.0 + 22.0 * e) * zf, 0.27 * (1.0 - u) ** 2, 0.60 * (1.0 - u) ** 1.5
    R = int(46 * zf) + 6
    x0, y0 = int(x) - R, int(y) - R
    cx0, cy0 = max(0, x0), max(0, y0)
    cx1, cy1 = min(content.shape[1], x0 + 2 * R), min(content.shape[0], y0 + 2 * R)
    if cx1 <= cx0 or cy1 <= cy0:
        return
    patch = content[cy0:cy1, cx0:cx1]
    ctr = (int((x - cx0) * 16), int((y - cy0) * 16))
    if a_fill > 0.004:
        disc = patch.copy()
        cv2.circle(disc, ctr, int(radius * 16), color_bgr, -1, cv2.LINE_AA, 4)
        cv2.addWeighted(disc, a_fill, patch, 1.0 - a_fill, 0, dst=patch)
    if a_ring > 0.004:
        ring = patch.copy()
        cv2.circle(ring, ctr, int(radius * 16), color_bgr, max(1, int(round(1.8 * zf))), cv2.LINE_AA, 4)
        cv2.addWeighted(ring, a_ring, patch, 1.0 - a_ring, 0, dst=patch)



def load_watermark(path: Optional[Path]) -> Optional[Tuple[np.ndarray, int, int]]:
    """Full-canvas RGBA PNG -> (premultiplied BGRA crop of its visible box, x, y), or None."""
    if not path:
        return None
    try:
        img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if img is None or img.ndim != 3 or img.shape[2] != 4:
            return None
        if (img.shape[1], img.shape[0]) != (S.W, S.H):
            img = cv2.resize(img, (S.W, S.H), interpolation=cv2.INTER_AREA)
        ys, xs = np.nonzero(img[:, :, 3] > 0)
        if len(xs) == 0:
            return None
        x0, x1, y0, y1 = int(xs.min()), int(xs.max()) + 1, int(ys.min()), int(ys.max()) + 1
        crop = img[y0:y1, x0:x1].astype(np.uint16)
        a = crop[:, :, 3:4]
        crop[:, :, :3] = (crop[:, :, :3] * a + 127) // 255
        return np.ascontiguousarray(crop.astype(np.uint8)), x0, y0
    except Exception:
        return None


# =============================================================================== 3D pose
def project_quad(cx: float, cy: float, w: float, h: float, rx: float, ry: float, rz: float, scale: float) -> np.ndarray:
    """Real pinhole projection of a flat rectangle rotated about its centre (angles in radians)."""
    hw, hh = w / 2.0 * scale, h / 2.0 * scale
    pts = np.array([[-hw, -hh, 0.0], [hw, -hh, 0.0], [hw, hh, 0.0], [-hw, hh, 0.0]], dtype=np.float64)
    cx_, sx_ = math.cos(rx), math.sin(rx)
    cy_, sy_ = math.cos(ry), math.sin(ry)
    cz_, sz_ = math.cos(rz), math.sin(rz)
    Rx = np.array([[1, 0, 0], [0, cx_, -sx_], [0, sx_, cx_]])
    Ry = np.array([[cy_, 0, sy_], [0, 1, 0], [-sy_, 0, cy_]])
    Rz = np.array([[cz_, -sz_, 0], [sz_, cz_, 0], [0, 0, 1]])
    p = pts @ (Rz @ Rx @ Ry).T
    k = FOCAL / (FOCAL + p[:, 2])
    return np.stack([cx + p[:, 0] * k, cy + p[:, 1] * k], axis=1).astype(np.float32)


# =============================================================================== renderer
class ShowcaseRenderer:
    def __init__(
        self,
        plan: ScenePlan,
        assets: Assets,
        fps: int,
        active_idx: int,
        prev_idx: Optional[int],
        is_first: bool,
        fade_out: float,
        global_offset: float,
        watermark_path: Optional[Path] = None,
    ):
        self.plan = plan
        self.a = assets
        self.fps = fps
        self.total = max(1, int(round(plan.duration * fps)))
        self.active_idx = max(0, min(len(assets.card_active) - 1, active_idx))
        self.prev_idx = prev_idx if (prev_idx is not None and prev_idx != self.active_idx and 0 <= prev_idx < len(assets.card_active)) else None
        self.is_first = is_first
        self.fade_out = fade_out
        self.g0 = global_offset
        self.sw, self.sh = plan.src_size
        self.bs = max(S.CONT_W / self.sw, S.CONT_H / self.sh)
        self._shadow = None
        self.watermark = load_watermark(watermark_path)
        self._simulate_camera()
        self.prof: Dict[str, float] = {}

    # ------------------------------------------------------------------ camera
    def _simulate_camera(self) -> None:
        n = self.total * SUB + SUB + 2
        dt = 1.0 / (self.fps * SUB)
        cam = np.empty((n, 3), np.float64)
        st = np.array([self.sw / 2.0, self.sh / 2.0, 1.0])
        vel = np.zeros(3)
        for k in range(n):
            t = k * dt
            tx, ty, tz = self.plan.camera_target(t, t + self.g0)
            st[0], vel[0] = spring_step(st[0], vel[0], tx, OMEGA_PAN, dt)
            st[1], vel[1] = spring_step(st[1], vel[1], ty, OMEGA_PAN, dt)
            st[2], vel[2] = spring_step(st[2], vel[2], tz, OMEGA_ZOOM, dt)
            cam[k] = st
        self.cam = cam

    def _affine(self, cx: float, cy: float, z: float) -> np.ndarray:
        s = self.bs * z
        vis_w, vis_h = S.CONT_W / s, S.CONT_H / s
        cx = clamp(cx, vis_w / 2.0, max(vis_w / 2.0, self.sw - vis_w / 2.0))
        cy = clamp(cy, vis_h / 2.0, max(vis_h / 2.0, self.sh - vis_h / 2.0))
        return np.float32([[s, 0.0, S.CONT_W / 2.0 - s * cx], [0.0, s, S.CONT_H / 2.0 - s * cy]])

    # ----------------------------------------------------------------- content
    def _press_scale(self, t: float) -> float:
        s = 1.0
        for c in self.plan.clicks:
            dt = t - c.t
            if dt <= -0.01 or dt >= c.press + 0.22:
                continue
            if dt <= c.press:
                v = 1.0 - 0.18 * smoothstep(dt / 0.06)                      # mouse-down: dip to 0.82
            else:
                v = 0.82 + 0.18 * ease_out_back((dt - c.press) / 0.20, 2.2)  # mouse-up: springs back, tiny overshoot
            if abs(v - 1.0) > abs(s - 1.0):
                s = v
        return s

    def _render_content(self, t: float, cam: np.ndarray, sheen: float = 0.0, src: Optional[np.ndarray] = None,
                        sharp: bool = True) -> np.ndarray:
        # `src` pins the page frame: motion blur is for camera + pointer only. The page's own
        # scrolling stays razor sharp, like a real screen recording.
        if src is None:
            src = self.plan.frame_at(t)
        cx, cy, z = cam
        M = self._affine(cx, cy, z)
        interp = cv2.INTER_CUBIC if sharp else cv2.INTER_LINEAR
        content = cv2.warpAffine(src, M, (S.CONT_W, S.CONT_H), flags=interp, borderMode=cv2.BORDER_REPLICATE)

        if sheen > 0.002:
            u0 = -180.0 + (S.CONT_W * 0.82 + S.CONT_H * 0.57 + 360.0) * clamp(sheen)
            band = np.exp(-np.square((self.a.sheen_u - u0) / 80.0)) * (0.11 * math.sin(math.pi * clamp(sheen)))
            lift = np.clip(band * 255.0, 0, 255).astype(np.uint8)
            cv2.add(content, cv2.merge([lift, lift, lift]), dst=content)

        # click ripples (behind the pointer)
        for c in self.plan.clicks:
            dt = t - c.t
            if -0.01 <= dt <= c.press + 0.53:
                px, py = M[0, 0] * c.x + M[0, 2], M[1, 1] * c.y + M[1, 2]
                _draw_click_feedback(content, px, py, dt, c.press, self.a.accent_bgr, z)

        # pointer in page space -> content space
        ux, uy = self.plan.cursor_at(t)
        px, py = M[0, 0] * ux + M[0, 2], M[1, 1] * uy + M[1, 2]
        if -40 < px < S.CONT_W + 40 and -40 < py < S.CONT_H + 40:
            # slightly larger when zoomed so it stays legible, smaller when pressed
            size_px = CURSOR_PX * (1.0 + 0.45 * (z - 1.0)) * self._press_scale(t)
            sc = size_px / (22.0 * self.a.cursor_sc)
            _stamp_affine(content, self.a.cursor, self.a.cursor_hot, sc, px, py)
        return content

    # ------------------------------------------------------------------- pose
    def _pose(self, t: float, tg: float, z: float) -> Tuple[float, float, float, float, float, float, float]:
        zoomness = smoothstep((z - 1.0) / 0.2)
        k = 1.0 - zoomness                             # read flat (pixel-exact), establish tilted
        ry = (-5.0 + 1.4 * math.sin(2 * math.pi * tg / 12.0 + 0.4)) * k
        rx = (-1.6 + 0.9 * math.sin(2 * math.pi * tg / 9.0 + 1.3)) * k
        rz = 0.22 * math.sin(2 * math.pi * tg / 15.0) * k
        scale, dx, dy, alpha = 1.0, 0.0, 0.0, 1.0
        if self.is_first:
            e = ease_out_expo(t / 1.5)
            ry += -17.0 * (1.0 - e)
            rx += 7.0 * (1.0 - e)
            scale *= 0.90 + 0.10 * e
            dy += 46.0 * (1.0 - e)
            alpha = smoothstep((t - 0.05) / 0.7)
        return rx, ry, rz, scale, dx, dy, alpha

    # ------------------------------------------------------------------ frame
    def compose(self, f: int) -> np.ndarray:
        P = self.prof
        t0 = time.perf_counter() if PROFILE else 0.0
        t = f / self.fps
        tg = t + self.g0
        k = min(f * SUB, len(self.cam) - 1)
        cam_c = self.cam[k]

        # --- how much is moving this frame? (decides motion-blur sub-samples)
        ka, kb = max(0, k - SUB // 2), min(len(self.cam) - 1, k + SUB // 2)
        ca, cb = self.cam[ka], self.cam[kb]
        s_img = self.bs * cam_c[2]
        cam_px = math.hypot((cb[0] - ca[0]) * s_img, (cb[1] - ca[1]) * s_img) + abs(cb[2] - ca[2]) * 0.5 * S.CONT_W
        h = 0.5 / self.fps
        c0, c1 = self.plan.cursor_at(t - h), self.plan.cursor_at(t + h)
        cur_px = math.hypot(c1[0] - c0[0], c1[1] - c0[1]) * s_img
        motion = max(cam_px, cur_px)
        nsub = int(clamp(math.ceil(motion / 3.0), 1, 5))

        sheen = 0.0
        if self.is_first and 0.9 < t < 2.4:
            sheen = (t - 0.9) / 1.5
        if nsub == 1:
            content = self._render_content(t, cam_c, sheen)
        else:
            page = self.plan.frame_at(t)
            acc = None
            for j in range(nsub):
                frac = (j / (nsub - 1) - 0.5) * 0.65          # ~234 degree shutter, centred on the frame
                kj = int(clamp(k + round(frac * SUB), 0, len(self.cam) - 1))
                cj = self._render_content(t + frac / self.fps, self.cam[kj], sheen, src=page, sharp=False).astype(np.uint16)
                acc = cj if acc is None else acc + cj
            content = ((acc + nsub // 2) // nsub).astype(np.uint8)
        if PROFILE:
            P["content"] = P.get("content", 0.0) + time.perf_counter() - t0
            t0 = time.perf_counter()

        # --- window sprite with current address bar
        url = self.plan.url_at(t)
        host, path = S.format_url(url, self.plan.fallback_domain) if url else (self.plan.fallback_domain, "")
        win = self.a.window_base(host, path).copy()
        self.a.finish_window(win, content)

        # --- 3D pose -> perspective warp
        rx, ry, rz, scale, dx, dy, w_alpha = self._pose(t, tg, cam_c[2])
        m = S.WIN_R + 3
        if abs(rx) < 0.04 and abs(ry) < 0.04 and abs(rz) < 0.04 and abs(scale - 1.0) < 1e-4:
            # Flat: blit pixel-exact (no resampling at all) - text is as sharp as the source.
            patch, x0, y0 = win, S.WIN_X + int(round(dx)), S.WIN_Y + int(round(dy))
            inner = (m, m, S.WIN_W - m, S.WIN_H - m)
        else:
            cxw = S.WIN_X + (S.WIN_W - 1) / 2.0 + dx
            cyw = S.WIN_Y + (S.WIN_H - 1) / 2.0 + dy
            dst = project_quad(cxw, cyw, S.WIN_W - 1, S.WIN_H - 1, math.radians(rx), math.radians(ry), math.radians(rz), scale)
            pad = 4
            x0 = max(0, int(math.floor(dst[:, 0].min())) - pad)
            y0 = max(0, int(math.floor(dst[:, 1].min())) - pad)
            x1 = min(S.W, int(math.ceil(dst[:, 0].max())) + pad + 1)
            y1 = min(S.H, int(math.ceil(dst[:, 1].max())) + pad + 1)
            src_q = np.float32([[0, 0], [S.WIN_W - 1, 0], [S.WIN_W - 1, S.WIN_H - 1], [0, S.WIN_H - 1]])
            Hm = cv2.getPerspectiveTransform(src_q, dst - np.float32([x0, y0]))
            patch = cv2.warpPerspective(win, Hm, (x1 - x0, y1 - y0), flags=cv2.INTER_LINEAR,
                                        borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
            # largest axis-aligned rectangle that is certainly opaque (inset past the rounded corners)
            inner = (int(math.ceil(max(dst[0, 0], dst[3, 0]))) - x0 + m,
                     int(math.ceil(max(dst[0, 1], dst[1, 1]))) - y0 + m,
                     int(math.floor(min(dst[1, 0], dst[2, 0]))) - x0 - m,
                     int(math.floor(min(dst[2, 1], dst[3, 1]))) - y0 - m)
        if PROFILE:
            P["window_warp"] = P.get("window_warp", 0.0) + time.perf_counter() - t0
            t0 = time.perf_counter()

        # --- backdrop + shadow cast by the warped window
        frame = self.a.background.render(tg).copy()
        self._cast_shadow(frame, patch, x0, y0, w_alpha, t)
        blend_window(frame, patch, x0, y0, w_alpha, inner)
        if PROFILE:
            P["bg_shadow_blend"] = P.get("bg_shadow_blend", 0.0) + time.perf_counter() - t0
            t0 = time.perf_counter()

        # --- cards
        self._draw_cards(frame, t, tg, ry, rx)
        if PROFILE:
            P["cards"] = P.get("cards", 0.0) + time.perf_counter() - t0

        # --- global fades
        fade = 1.0
        if self.is_first:
            fade *= smoothstep(t / 0.8)
        if self.fade_out > 0:
            fade *= 1.0 - smoothstep((t - (self.plan.duration - self.fade_out)) / self.fade_out)
        if fade < 0.998:
            frame = cv2.convertScaleAbs(frame, alpha=fade)
        if self.watermark is not None:
            wm, wx, wy = self.watermark
            blend_premult(frame, wm, wx, wy)
        return frame

    def _cast_shadow(self, frame: np.ndarray, patch: np.ndarray, x0: int, y0: int, opacity: float, t: float) -> None:
        """
        Soft ambient + contact shadow derived from the (possibly warped) window alpha.
        The shadow is blurred ~28px so it is recomputed at 20 Hz and re-applied every frame.
        """
        c = self._shadow
        if c is None or t - c[0] >= 0.05 or abs(opacity - c[1]) > 0.01 or t < c[0]:
            q = 4
            # Work in a quarter-resolution tile covering the window plus the shadow's reach.
            ph, pw = patch.shape[:2]
            tx0 = max(0, (x0 - 96) // q * q)
            ty0 = max(0, (y0 - 64) // q * q)
            tx1 = min(S.W, ((x0 + pw + 96) + q - 1) // q * q)
            ty1 = min(S.H, ((y0 + ph + 160) + q - 1) // q * q)
            tw, th = (tx1 - tx0) // q, (ty1 - ty0) // q
            small = np.zeros((th, tw), np.uint8)
            a_s = cv2.resize(patch[:, :, 3], (max(1, pw // q), max(1, ph // q)), interpolation=cv2.INTER_AREA)
            sx, sy = (x0 - tx0) // q, (y0 - ty0) // q
            h2, w2 = min(a_s.shape[0], th - sy), min(a_s.shape[1], tw - sx)
            small[sy:sy + h2, sx:sx + w2] = a_s[:h2, :w2]
            amb = np.roll(cv2.GaussianBlur(small, (0, 0), 7.5), 9, axis=0)    # light from above: shadow falls down
            con = np.roll(cv2.GaussianBlur(small, (0, 0), 2.0), 2, axis=0)
            k_amb, k_con = 0.62 * opacity, 0.42 * opacity
            dark = (1.0 - k_amb * amb.astype(np.float32) / 255.0) * (1.0 - k_con * con.astype(np.float32) / 255.0)
            mask = cv2.resize((dark * 255.0).astype(np.uint8), (tx1 - tx0, ty1 - ty0), interpolation=cv2.INTER_LINEAR)
            mask3 = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
            c = self._shadow = (t, opacity, tx0, ty0, mask3)
        _, _, tx0, ty0, mask3 = c
        th_, tw_ = mask3.shape[:2]
        roi = frame[ty0:ty0 + th_, tx0:tx0 + tw_]
        cv2.multiply(roi, mask3, dst=roi, scale=1.0 / 255.0)

    # ------------------------------------------------------------------ cards
    def _combined_cards(self, active: int, margin: int) -> Tuple[np.ndarray, int, int]:
        """All three cards (final steady state) pre-composited into ONE layer, cached per active card."""
        key = (active, margin)
        hit = self.a.combined.get(key)
        if hit is not None:
            return hit
        n = len(self.a.card_active)
        spr_h, spr_w = self.a.card_inactive[0].shape[:2]
        total_h = 3 * S.CARD_H + 2 * S.CARD_GAP + 2 * S.CARD_PAD
        layer = np.zeros((total_h + 2 * margin, spr_w + 2 * margin, 4), np.uint8)
        for i in range(n):
            spr = self.a.card_active[i] if i == active else self.a.card_inactive[i]
            y = margin + i * (S.CARD_H + S.CARD_GAP)
            roi = layer[y:y + spr_h, margin:margin + spr_w]
            inv = cv2.cvtColor(cv2.bitwise_not(spr[:, :, 3]), cv2.COLOR_GRAY2BGRA)
            cv2.add(cv2.multiply(roi, inv, scale=1.0 / 255.0), spr, dst=roi)
        ox, oy = S.CARD_X - S.CARD_PAD - margin, S.CARD_Y0 - S.CARD_PAD - margin
        self.a.combined[key] = (layer, ox, oy)
        return self.a.combined[key]

    def _draw_cards_static(self, frame: np.ndarray, tg: float, ry_deg: float, rx_deg: float, progress: float) -> None:
        margin = 10
        layer, ox, oy = self._combined_cards(self.active_idx, margin)
        px = -ry_deg * 2.6
        py = rx_deg * 1.8 + 3.0 * math.sin(2 * math.pi * tg / 6.3)
        layer = layer.copy()
        S.draw_progress_bar(layer, progress, self.a.accent_bgr, ox=margin,
                            oy=margin + self.active_idx * (S.CARD_H + S.CARD_GAP))
        fx, fy = px - math.floor(px), py - math.floor(py)
        A = np.float32([[1.0, 0.0, fx], [0.0, 1.0, fy]])
        patch = cv2.warpAffine(layer, A, (layer.shape[1], layer.shape[0]), flags=cv2.INTER_LINEAR,
                               borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
        blend_premult(frame, patch, ox + int(math.floor(px)), oy + int(math.floor(py)))

    def _draw_cards(self, frame: np.ndarray, t: float, tg: float, ry_deg: float, rx_deg: float) -> None:
        animating = (self.is_first and t < 2.7) or (self.prev_idx is not None and t < 0.95)
        if not animating:
            self._draw_cards_static(frame, tg, ry_deg, rx_deg, clamp(t / max(self.plan.duration, 1e-6)))
            return
        n = len(self.a.card_active)
        handoff = ease_out_cubic(t / 0.75)
        pop = 0.0
        if self.prev_idx is not None:
            pop = math.sin(math.pi * clamp(t / 0.9)) * 0.018
        progress = clamp(t / max(self.plan.duration, 1e-6))
        for i in range(n):
            if i == self.active_idx:
                act = handoff if self.prev_idx is not None or self.is_first else 1.0
            elif i == self.prev_idx:
                act = 1.0 - handoff
            else:
                act = 0.0
            if self.is_first and i == self.active_idx:
                act = 1.0

            # entrance (first scene): cards glide in from the right with a stagger
            alpha, off_x = 1.0, 0.0
            margin = 8
            if self.is_first:
                p = ease_out_expo((t - (0.45 + 0.15 * i)) / 1.0)
                alpha = clamp(p * 1.4)
                off_x = 90.0 * (1.0 - p)
                margin = 100 if p < 0.999 else 8
            # parallax: cards sit nearer the viewer than the window -> shift against the tilt
            px = -ry_deg * 2.6 + off_x
            py = rx_deg * 1.8 + 3.0 * math.sin(2 * math.pi * tg / 6.3)
            sc = 1.0 + (pop if i == self.active_idx else 0.0)

            base_x = S.CARD_X - S.CARD_PAD
            base_y = S.CARD_Y0 + i * (S.CARD_H + S.CARD_GAP) - S.CARD_PAD
            spr_h, spr_w = self.a.card_inactive[i].shape[:2]
            out_w, out_h = spr_w + 2 * margin, spr_h + 2 * margin
            ox, oy = int(math.floor(base_x + px)) - margin, int(math.floor(base_y + py)) - margin
            fx, fy = (base_x + px) - math.floor(base_x + px), (base_y + py) - math.floor(base_y + py)
            cxs, cys = spr_w / 2.0, spr_h / 2.0
            A = np.float32([[sc, 0.0, margin + fx + cxs * (1 - sc)], [0.0, sc, margin + fy + cys * (1 - sc)]])

            def stamp(sprite, opacity):
                patch = cv2.warpAffine(sprite, A, (out_w, out_h), flags=cv2.INTER_LINEAR,
                                       borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
                blend_premult(frame, patch, ox, oy, opacity=opacity * alpha)

            if act < 0.985:
                stamp(self.a.card_inactive[i], 1.0)
            if act > 0.004:
                spr = self.a.card_active[i]
                if i == self.active_idx:
                    spr = spr.copy()
                    S.draw_progress_bar(spr, progress, self.a.accent_bgr)
                stamp(spr, act)

    # ------------------------------------------------------------------- run
    def render(self, output_mp4, crf: int = 18, preset: str = "veryfast") -> float:
        writer = RawVideoWriter(output_mp4, S.W, S.H, self.fps, crf=crf, preset=preset)
        try:
            for f in range(self.total):
                writer.write(self.compose(f))
            writer.close()
        except Exception:
            writer.abort()
            raise
        if PROFILE:
            print({k: round(v / self.total * 1000, 2) for k, v in self.prof.items()}, "ms/frame")
        return self.plan.click_time
