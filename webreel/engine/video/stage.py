"""
Stage assets for the showcase renderer: everything that is drawn *once* per job at high
quality (4x/2x supersampled, real typography, Gaussian shadows) and then animated per frame
as cheap sprites. All sprites are premultiplied-alpha BGRA uint8 so they can be warped
(camera, 3D tilt, parallax) and blended without dark fringes.
"""
import functools
import math
import os
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..config import ASSETS_DIR

# --------------------------------------------------------------------------- layout
W, H = 1920, 1080
WIN_X, WIN_W = 60, 1260
TOP_H = 46                       # macOS title bar
CONT_W, CONT_H = 1260, 788       # 16:10 -> exact aspect of a 1280x800 capture
WIN_H = TOP_H + CONT_H
WIN_Y = (H - WIN_H) // 2
WIN_R = 14

CARD_X, CARD_W, CARD_H = 1350, 510, 260
CARD_GAP = (WIN_H - 3 * CARD_H) // 2
CARD_Y0 = WIN_Y
CARD_PAD = 46                    # room for glow + shadow inside each card sprite

BG_BASE_RGB = (7, 10, 16)


# --------------------------------------------------------------------------- fonts
_FONT_DIR = ASSETS_DIR / "fonts"
_BUNDLED = {
    "regular": "Inter-Regular.otf",
    "semibold": "Inter-SemiBold.otf",
    "bold": "Inter-Bold.otf",
}
_SYSTEM_FALLBACKS = {
    "regular": ["C:/Windows/Fonts/segoeui.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", "/Library/Fonts/Arial.ttf",
                "C:/Windows/Fonts/arial.ttf"],
    "semibold": ["C:/Windows/Fonts/seguisb.ttf", "C:/Windows/Fonts/segoeuib.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", "C:/Windows/Fonts/arialbd.ttf"],
    "bold": ["C:/Windows/Fonts/segoeuib.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
             "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", "C:/Windows/Fonts/arialbd.ttf"],
}


@functools.lru_cache(maxsize=128)
def font(weight: str, size: float) -> ImageFont.FreeTypeFont:
    """Bundled Inter first (identical look on Windows/Linux/Docker), then system fallbacks."""
    candidates = [str(_FONT_DIR / _BUNDLED[weight])] + _SYSTEM_FALLBACKS[weight]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    try:
        return ImageFont.load_default(size=int(size))
    except Exception:
        return ImageFont.load_default()


def wrap_lines(draw: ImageDraw.ImageDraw, text: str, f, max_w: float, max_lines: int) -> List[str]:
    """Greedy word wrap by *pixel* width (never splits inside a word); ellipsizes overflow."""
    words = text.split()
    lines: List[str] = []
    cur = ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=f) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and draw.textlength(last + "…", font=f) > max_w:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return lines


def spaced_text(draw: ImageDraw.ImageDraw, xy: Tuple[float, float], text: str, f, fill, spacing: float = 1.0) -> float:
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=f, fill=fill)
        x += draw.textlength(ch, font=f) + spacing
    return x - xy[0]


def spaced_width(draw: ImageDraw.ImageDraw, text: str, f, spacing: float = 1.0) -> float:
    return sum(draw.textlength(ch, font=f) + spacing for ch in text) - spacing


# --------------------------------------------------------------------------- helpers
def pil_to_premult_bgra(img: Image.Image) -> np.ndarray:
    arr = np.asarray(img.convert("RGBA"), dtype=np.uint16)
    a = arr[:, :, 3:4]
    rgb = (arr[:, :, :3] * a + 127) // 255
    out = np.concatenate([rgb[:, :, ::-1], a], axis=2).astype(np.uint8)
    return np.ascontiguousarray(out)


def _down(img: Image.Image, ss: int) -> Image.Image:
    if ss == 1:
        return img
    return img.resize((img.width // ss, img.height // ss), Image.Resampling.LANCZOS)


def _rrect_mask(size: Tuple[int, int], box, radius, ss: int) -> Image.Image:
    m = Image.new("L", (size[0] * ss, size[1] * ss), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([c * ss for c in box], radius=radius * ss, fill=255)
    return m


def _vgrad(w: int, h: int, top: Tuple[int, int, int], bottom: Tuple[int, int, int]) -> Image.Image:
    t = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None, None]
    top_a = np.array(top, np.float32)[None, None, :]
    bot_a = np.array(bottom, np.float32)[None, None, :]
    arr = (top_a + (bot_a - top_a) * t) * np.ones((1, w, 1), np.float32)
    return Image.fromarray(arr.astype(np.uint8), "RGB")


# --------------------------------------------------------------------------- window chrome
@functools.lru_cache(maxsize=4)
def build_window_chrome() -> np.ndarray:
    """macOS window frame without the URL text: title bar, traffic lights, hairlines (BGRA premult)."""
    ss = 3
    w, h = WIN_W, WIN_H
    layer = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))

    body_mask = _rrect_mask((w, h), (0, 0, w, h), WIN_R, ss)
    # Title bar gradient + dark content placeholder
    bar = _vgrad(w * ss, TOP_H * ss, (52, 55, 62), (38, 41, 47))
    fill = Image.new("RGB", (w * ss, h * ss), (18, 22, 28))
    fill.paste(bar, (0, 0))
    layer = Image.composite(fill.convert("RGBA"), layer, body_mask)
    d = ImageDraw.Draw(layer, "RGBA")

    # hairline under the title bar
    d.rectangle([0, TOP_H * ss - ss, w * ss, TOP_H * ss], fill=(0, 0, 0, 90))
    d.rectangle([0, TOP_H * ss - 2 * ss, w * ss, TOP_H * ss - ss], fill=(255, 255, 255, 10))

    # traffic lights
    cy = TOP_H * ss // 2
    for i, col in enumerate(((255, 95, 87), (254, 188, 46), (40, 200, 64))):
        cx = (22 + i * 20) * ss
        r = 6 * ss
        d.ellipse([cx - r - ss // 2, cy - r - ss // 2, cx + r + ss // 2, cy + r + ss // 2], fill=(0, 0, 0, 55))
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col + (255,))
        d.ellipse([cx - r + 2 * ss, cy - r + ss, cx + r - 2 * ss, cy - r // 4], fill=(255, 255, 255, 38))

    # 1px outer border, brighter on top (inner light)
    border = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
    bd = ImageDraw.Draw(border)
    bd.rounded_rectangle([0, 0, w * ss - 1, h * ss - 1], radius=WIN_R * ss, outline=(255, 255, 255, 40), width=ss)
    bd.rounded_rectangle([ss, ss, w * ss - 1 - ss, 3 * ss], radius=WIN_R * ss, outline=(255, 255, 255, 26), width=ss)
    border = Image.composite(border, Image.new("RGBA", border.size, (0, 0, 0, 0)), body_mask)
    layer = Image.alpha_composite(layer, border)

    out = _down(layer, ss)
    return pil_to_premult_bgra(out)


@functools.lru_cache(maxsize=1)
def window_content_alpha() -> np.ndarray:
    """Alpha for the content area: opaque, with the macOS rounded bottom corners."""
    ss = 4
    m = Image.new("L", (CONT_W * ss, CONT_H * ss), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([0, -WIN_R * ss * 2, CONT_W * ss, CONT_H * ss], radius=WIN_R * ss, fill=255)
    m = m.resize((CONT_W, CONT_H), Image.Resampling.LANCZOS)
    return np.asarray(m, dtype=np.uint8)


def format_url(url: str, fallback_domain: str) -> Tuple[str, str]:
    """('campusweb.co.in', '/pricing') for display in the address pill."""
    try:
        p = urlparse(url if "//" in url else "https://" + url)
        host = (p.netloc or fallback_domain).lower()
        if host.startswith("www."):
            host = host[4:]
        path = p.path if p.path and p.path != "/" else ""
        if p.fragment:
            path += "#" + p.fragment
        if len(path) > 26:
            path = path[:25] + "…"
        return host or fallback_domain, path
    except Exception:
        return fallback_domain, ""


@functools.lru_cache(maxsize=64)
def build_url_pill(host: str, path: str) -> Tuple[np.ndarray, int, int]:
    """Address-bar pill sprite (BGRA premult) + its top-left position inside the window."""
    ss = 3
    f = font("regular", 13.5)
    fb = font("semibold", 13.5)
    tmp = ImageDraw.Draw(Image.new("L", (4, 4)))
    host_w = tmp.textlength(host, font=fb)
    path_w = tmp.textlength(path, font=f) if path else 0
    pill_w = int(max(300, 44 + host_w + path_w + 24))
    pill_h = 30
    layer = Image.new("RGBA", (pill_w * ss, pill_h * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer, "RGBA")
    d.rounded_rectangle([0, 0, pill_w * ss - 1, pill_h * ss - 1], radius=9 * ss, fill=(26, 29, 36, 255),
                        outline=(255, 255, 255, 22), width=ss)
    # lock icon (vector: shackle + body)
    lx, ly = 16 * ss, pill_h * ss // 2
    col = (150, 160, 176, 255)
    d.arc([lx - 3.6 * ss, ly - 8.2 * ss, lx + 3.6 * ss, ly + 0.8 * ss], 180, 360, fill=col, width=int(1.5 * ss))
    d.rounded_rectangle([lx - 5.2 * ss, ly - 3.2 * ss, lx + 5.2 * ss, ly + 5.8 * ss], radius=int(1.8 * ss), fill=col)
    small = _down(layer, ss)
    sd = ImageDraw.Draw(small, "RGBA")
    total_w = host_w + path_w
    tx = int(32 + (pill_w - 32 - 12 - total_w) / 2)
    ty = (pill_h - 17) // 2 - 1
    sd.text((tx, ty), host, font=fb, fill=(226, 231, 240, 255))
    if path:
        sd.text((tx + host_w, ty), path, font=f, fill=(138, 148, 166, 255))
    x = (WIN_W - pill_w) // 2
    y = (TOP_H - pill_h) // 2
    return pil_to_premult_bgra(small), x, y


def blend_premult_inplace(dst_bgra: np.ndarray, src_bgra: np.ndarray, x: int, y: int) -> None:
    """Premultiplied 'over' of src onto dst (both BGRA), used to stamp the URL pill on the chrome."""
    h, w = src_bgra.shape[:2]
    roi = dst_bgra[y:y + h, x:x + w]
    inv = 255 - src_bgra[:, :, 3:4]
    roi[:] = (roi.astype(np.uint16) * inv // 255 + src_bgra).clip(0, 255).astype(np.uint8)


# --------------------------------------------------------------------------- cards
def _glow_layer(size, box, radius, color, blur, alpha, ss) -> Image.Image:
    layer = Image.new("RGBA", (size[0] * ss, size[1] * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle([c * ss for c in box], radius=radius * ss, fill=color + (int(255 * alpha),))
    return layer.filter(ImageFilter.GaussianBlur(blur * ss))


def build_card_sprite(card: Dict[str, str], index: int, accent_rgb: Tuple[int, int, int], active: bool) -> np.ndarray:
    """One benefit card (BGRA premult) including its baked shadow/glow; PAD px of margin all round."""
    ss = 2
    pad = CARD_PAD
    sw, sh = CARD_W + 2 * pad, CARD_H + 2 * pad
    box = (pad, pad, pad + CARD_W, pad + CARD_H)
    rad = 22

    layer = Image.new("RGBA", (sw * ss, sh * ss), (0, 0, 0, 0))
    # contact + ambient shadow
    sh_box = (box[0], box[1] + 14, box[2], box[3] + 14)
    layer = Image.alpha_composite(layer, _glow_layer((sw, sh), sh_box, rad, (0, 0, 0), 20, 0.62, ss))
    layer = Image.alpha_composite(layer, _glow_layer((sw, sh), (box[0] + 6, box[1] + 5, box[2] - 6, box[3] + 5),
                                                     rad, (0, 0, 0), 5, 0.45, ss))
    if active:
        layer = Image.alpha_composite(layer, _glow_layer((sw, sh), box, rad, accent_rgb, 22, 0.40, ss))

    body_mask = _rrect_mask((sw, sh), box, rad, ss)
    if active:
        grad = _vgrad(sw * ss, sh * ss, (33, 45, 64), (20, 28, 42))
        body = grad.convert("RGBA")
        body.putalpha(Image.eval(body_mask, lambda v: int(v * 0.97)))
    else:
        body = Image.new("RGBA", (sw * ss, sh * ss), (16, 21, 29, 255))
        body.putalpha(Image.eval(body_mask, lambda v: int(v * 0.86)))
    layer = Image.alpha_composite(layer, body)

    d = ImageDraw.Draw(layer, "RGBA")
    if active:
        d.rounded_rectangle([c * ss for c in box], radius=rad * ss, outline=accent_rgb + (225,), width=int(1.8 * ss))
        # soft inner top highlight
        d.rounded_rectangle([(box[0] + 2) * ss, (box[1] + 2) * ss, (box[2] - 2) * ss, (box[3] - 2) * ss],
                            radius=(rad - 2) * ss, outline=(255, 255, 255, 16), width=ss)
    else:
        d.rounded_rectangle([c * ss for c in box], radius=rad * ss, outline=(255, 255, 255, 24), width=ss)

    # category pill background (text is drawn at 1x afterwards for crisp hinting)
    cat = card.get("category", "FEATURE").upper()
    f_cat = font("semibold", 12 * ss)
    cat_w = spaced_width(d, cat, f_cat, 1.3 * ss) / ss
    px, py = box[0] + 28, box[1] + 26
    pill_w, pill_h = int(cat_w + 26), 28
    pill_fill = accent_rgb + (40,) if active else (255, 255, 255, 14)
    d.rounded_rectangle([px * ss, py * ss, (px + pill_w) * ss, (py + pill_h) * ss], radius=8 * ss, fill=pill_fill)

    img = _down(layer, ss)
    t = ImageDraw.Draw(img, "RGBA")

    pill_txt = accent_rgb if active else (140, 152, 172)
    spaced_text(t, (px + 13, py + 7), cat, font("semibold", 12), pill_txt + (255,), 1.3)

    num = f"0{index + 1}"
    f_num = font("semibold", 13)
    t.text((box[2] - 28 - t.textlength(num, font=f_num), py + 7), num, font=f_num,
           fill=((190, 204, 224, 255) if active else (84, 96, 116, 255)))

    f_title = font("semibold", 28)
    f_desc = font("regular", 17)
    title_col = (255, 255, 255, 255) if active else (206, 213, 224, 255)
    desc_col = (172, 186, 208, 255) if active else (118, 130, 150, 255)
    inner_w = CARD_W - 56
    title_lines = wrap_lines(t, card.get("title", ""), f_title, inner_w, 2)
    desc_lines = wrap_lines(t, card.get("desc", ""), f_desc, inner_w, 3 if len(title_lines) < 2 else 2)
    # Vertically balance the copy between the pill row and the progress-bar rail.
    block_h = len(title_lines) * 35 + 8 + len(desc_lines) * 26
    top_free = box[1] + 26 + pill_h
    bottom_free = box[3] - 44
    ty = int(top_free + max(14, (bottom_free - top_free - block_h) / 2))
    for ln in title_lines:
        t.text((box[0] + 28, ty), ln, font=f_title, fill=title_col)
        ty += 35
    ty += 8
    for ln in desc_lines:
        t.text((box[0] + 28, ty), ln, font=f_desc, fill=desc_col)
        ty += 26
    return pil_to_premult_bgra(img)


def draw_progress_bar(sprite_bgra: np.ndarray, progress: float, accent_bgr: Tuple[int, int, int],
                      ox: int = 0, oy: int = 0) -> None:
    """Sub-pixel accurate progress bar drawn into an (active) card sprite, in place.
    (ox, oy) is the card sprite's top-left inside `sprite_bgra` (non-zero for the combined card layer)."""
    pad = CARD_PAD
    x0, x1 = ox + pad + 28, ox + pad + CARD_W - 28
    y0 = oy + pad + CARD_H - 30
    rows = [0.30, 0.85, 1.0, 1.0, 0.85, 0.30]
    track_a = 0.10
    fill_w = (x1 - x0) * max(0.0, min(1.0, progress))
    xs = np.arange(x1 - x0, dtype=np.float32)
    cover = np.clip(fill_w - xs, 0.0, 1.0)
    acc = np.array(accent_bgr, np.float32)
    for r, ra in enumerate(rows):
        row = sprite_bgra[y0 + r, x0:x1].astype(np.float32)
        # track (white, premult) then fill (accent) over it
        a_track = track_a * ra
        row[:, :3] = row[:, :3] * (1 - a_track) + 255.0 * a_track
        row[:, 3] = row[:, 3] * (1 - a_track) + 255.0 * a_track
        a_fill = (cover * ra * 0.95)[:, None]
        row[:, :3] = row[:, :3] * (1 - a_fill) + acc[None, :] * a_fill
        row[:, 3] = row[:, 3] * (1 - a_fill[:, 0]) + 255.0 * a_fill[:, 0]
        sprite_bgra[y0 + r, x0:x1] = np.clip(row, 0, 255).astype(np.uint8)


# --------------------------------------------------------------------------- cursor
@functools.lru_cache(maxsize=1)
def build_cursor_sprite() -> Tuple[np.ndarray, Tuple[float, float], float]:
    """
    macOS-style arrow (black fill, white keyline, soft shadow) at 4x supersample, returned as a
    2x BGRA premult sprite plus its hotspot (tip) position in sprite pixels and its sprite scale.
    """
    ss = 8
    pad = 10
    tip = [(0.0, 0.0), (0.0, 17.0), (4.0, 13.4), (6.9, 19.8), (9.7, 18.5), (6.8, 12.3), (12.2, 12.3)]
    w_pts, h_pts = 14, 22
    sw, sh = (w_pts + 2 * pad), (h_pts + 2 * pad)

    def poly(offset=(0.0, 0.0), grow=0.0):
        pts = [((x + pad + offset[0]) * ss, (y + pad + offset[1]) * ss) for x, y in tip]
        return pts

    shadow = Image.new("RGBA", (sw * ss, sh * ss), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).polygon(poly((1.4, 2.6)), fill=(0, 0, 0, 120))
    shadow = shadow.filter(ImageFilter.GaussianBlur(1.6 * ss))

    key = Image.new("RGBA", (sw * ss, sh * ss), (0, 0, 0, 0))
    kd = ImageDraw.Draw(key)
    kd.polygon(poly(), fill=(255, 255, 255, 255))
    kd.line(poly() + [poly()[0]], fill=(255, 255, 255, 255), width=int(2.4 * ss), joint="curve")
    body = Image.new("RGBA", (sw * ss, sh * ss), (0, 0, 0, 0))
    bd = ImageDraw.Draw(body)
    # shrink body toward its centroid so the white keyline shows
    cx = sum(p[0] for p in tip) / len(tip)
    cy = sum(p[1] for p in tip) / len(tip)
    inner = [((cx + (x - cx) * 0.80) + pad, (cy + (y - cy) * 0.80) + pad) for x, y in tip]
    # re-anchor tip so the hotspot stays put (move inner so its tip coincides with the outer tip)
    dx, dy = inner[0][0] - (tip[0][0] + pad), inner[0][1] - (tip[0][1] + pad)
    inner = [((x - dx + 1.0) * ss, (y - dy + 1.6) * ss) for x, y in inner]
    bd.polygon(inner, fill=(14, 14, 16, 255))

    comp = Image.alpha_composite(Image.alpha_composite(shadow, key), body)
    # 2x sprite (cv2.warpAffine later scales it to the exact on-screen size)
    sprite = comp.resize((sw * 2, sh * 2), Image.Resampling.LANCZOS)
    return pil_to_premult_bgra(sprite), (pad * 2.0, pad * 2.0), 2.0


# --------------------------------------------------------------------------- background
class Background:
    """
    Slowly drifting, brand-tinted studio backdrop. Gradients are computed in float at low
    resolution, upscaled and dithered (triangular noise) before quantisation, which is what
    prevents the banding that stepped 8-bit gradients show after H.264 compression.
    """

    LOW_W, LOW_H = 480, 270

    def __init__(self, palette: Dict[str, Tuple[int, int, int]]):
        # BGR order throughout so no channel flip is needed on the way out
        self.glow = np.array(palette["glow"], np.float32)[::-1].copy()
        self.glow2 = np.array(palette["glow_secondary"], np.float32)[::-1].copy()
        self.accent = np.array(palette["accent_rgb"], np.float32)[::-1].copy()
        ys, xs = np.mgrid[0:self.LOW_H, 0:self.LOW_W].astype(np.float32)
        self.X = xs * (W / self.LOW_W)
        self.Y = ys * (H / self.LOW_H)
        rng = np.random.default_rng(7)
        noise = rng.random((H, W), dtype=np.float32) + rng.random((H, W), dtype=np.float32) - 1.0
        self.noise = np.repeat(noise[:, :, None], 3, axis=2).astype(np.float32) * 1.15
        vx = (self.X - W / 2) / (W * 0.62)
        vy = (self.Y - H / 2) / (H * 0.70)
        self.vignette = np.clip(1.0 - 0.34 * (vx ** 2 + vy ** 2), 0.55, 1.0)[:, :, None]
        self._cache_key = None
        self._cache = None

    def _blob(self, cx, cy, sigma):
        return np.exp(-(((self.X - cx) ** 2 + (self.Y - cy) ** 2) / (2.0 * sigma * sigma)))[:, :, None]

    def render(self, tg: float) -> np.ndarray:
        key = int(tg * 4)            # refresh at 4 Hz; the drift is far slower than that
        if key == self._cache_key and self._cache is not None:
            return self._cache
        base = np.array(BG_BASE_RGB, np.float32)[::-1][None, None, :]
        b1 = self._blob(520 + 46 * math.sin(tg / 3.1), 560 + 34 * math.cos(tg / 4.3), 430)
        b2 = self._blob(1560 + 52 * math.cos(tg / 3.7), 820 + 40 * math.sin(tg / 2.9), 460)
        b3 = self._blob(1500 + 60 * math.sin(tg / 5.2), 170 + 30 * math.cos(tg / 3.4), 300)
        b4 = self._blob(180 + 40 * math.cos(tg / 4.6), 170 + 24 * math.sin(tg / 3.8), 340)
        img = base + b1 * self.glow * 0.95 + b2 * self.glow2 * 0.85 + b3 * self.accent * 0.10 + b4 * self.glow2 * 0.35
        img = img * self.vignette
        up = cv2.resize(img.astype(np.float32), (W, H), interpolation=cv2.INTER_CUBIC)
        bgr = cv2.convertScaleAbs(cv2.add(up, self.noise))
        self._cache_key, self._cache = key, bgr
        return bgr
