import os
import colorsys
import cv2
import numpy as np
import textwrap
from pathlib import Path
from typing import Tuple, List, Dict, Any, Optional
from PIL import Image, ImageDraw, ImageFont

def ease_out_cubic(t: float) -> float:
    return 1.0 - (1.0 - t) ** 3

def ease_in_out_sine(t: float) -> float:
    return -(np.cos(np.pi * t) - 1.0) / 2.0

def get_system_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    """
    Loads clean modern Segoe UI font on Windows, falling back to Arial or default.
    """
    candidates = [
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"
    ]
    for c in candidates:
        if os.path.exists(c):
            try:
                return ImageFont.truetype(c, size)
            except Exception:
                pass
    return ImageFont.load_default()

def draw_cursor(img_bgr: np.ndarray, x: int, y: int, scale: float = 1.0):
    """
    Draws a clean, modern white macOS/Windows cursor with dark drop shadow,
    supporting physical tactile click scaling.
    """
    base_poly = np.array([
        [0.0, 0.0],
        [0.0, 26.0],
        [7.0, 19.0],
        [14.0, 29.0],
        [19.0, 26.0],
        [11.0, 16.0],
        [20.0, 16.0]
    ], dtype=np.float32)

    scaled = (base_poly * scale).astype(np.int32)
    poly = scaled + [x, y]

    shadow = poly + [2, 2]
    cv2.fillPoly(img_bgr, [shadow], (10, 10, 10))
    cv2.fillPoly(img_bgr, [poly], (255, 255, 255))
    cv2.polylines(img_bgr, [poly], True, (20, 25, 35), 1, cv2.LINE_AA)

def draw_click_ripple(img_bgr: np.ndarray, x: int, y: int, progress: float, color_bgr: Tuple[int, int, int] = (163, 229, 0)):
    """
    Draws expanding pulsing concentric rings with fading alpha on click.
    """
    if progress <= 0 or progress > 1.0:
        return

    r = int(progress * 48)
    alpha = max(0.0, 1.0 - progress)
    c1 = (int(color_bgr[0] * alpha), int(color_bgr[1] * alpha), int(color_bgr[2] * alpha))
    cv2.circle(img_bgr, (x, y), r, c1, 2, cv2.LINE_AA)
    if r > 12:
        c2 = (int(255 * alpha * 0.8), int(255 * alpha * 0.8), int(255 * alpha * 0.8))
        cv2.circle(img_bgr, (x, y), int(r * 0.55), c2, 1, cv2.LINE_AA)

def palette_from_accent(rgb: Tuple[int, int, int]) -> Dict[str, Any]:
    """Studio lighting derived from the colour the site itself uses for its buttons."""
    h, l, s = colorsys.rgb_to_hls(rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0)

    def to255(c):
        return tuple(int(round(max(0.0, min(1.0, v)) * 255)) for v in c)

    accent = to255(colorsys.hls_to_rgb(h, min(0.66, max(0.54, l)), max(0.65, s)))      # vivid on dark UI
    glow = to255(colorsys.hls_to_rgb(h, 0.22, min(0.75, max(0.45, s))))                 # deep tinted bloom
    glow2 = to255(colorsys.hls_to_rgb((h + 0.08) % 1.0, 0.17, 0.5))                     # analogous fill
    return {"glow": glow, "accent_rgb": accent, "accent_bgr": accent[::-1], "glow_secondary": glow2}


def get_brand_palette(domain: str, accent_rgb: Optional[Tuple[int, int, int]] = None) -> Dict[str, Any]:
    """
    Extracts brand-tailored color accents and ambient lighting.
    A colour read from the site itself (accent_rgb) wins over the built-in presets below.
    """
    if accent_rgb:
        return palette_from_accent(tuple(int(c) for c in accent_rgb))
    d = domain.lower()
    if "campusweb" in d:
        return {
            "glow": (18, 85, 60),
            "accent_rgb": (0, 229, 163),      # Emerald
            "accent_bgr": (163, 229, 0),
            "glow_secondary": (12, 60, 80)
        }
    elif "linear" in d:
        return {
            "glow": (70, 45, 120),
            "accent_rgb": (124, 58, 237),     # Violet
            "accent_bgr": (237, 58, 124),
            "glow_secondary": (25, 35, 75)
        }
    elif "stripe" in d:
        return {
            "glow": (40, 60, 140),
            "accent_rgb": (99, 91, 255),      # Indigo
            "accent_bgr": (255, 91, 99),
            "glow_secondary": (15, 80, 110)
        }
    elif "notion" in d:
        return {
            "glow": (50, 50, 60),
            "accent_rgb": (245, 245, 247),
            "accent_bgr": (247, 245, 245),
            "glow_secondary": (30, 30, 35)
        }
    else:
        return {
            "glow": (25, 55, 85),
            "accent_rgb": (0, 210, 255),      # Electric Cyan
            "accent_bgr": (255, 210, 0),
            "glow_secondary": (20, 35, 50)
        }

def compose_mac_showcase_canvas(
    image_path: Path,
    domain: str,
    cards: List[Dict[str, str]],
    active_card_idx: int = 0
) -> Tuple[np.ndarray, Tuple[int, int], Tuple[int, int]]:
    """
    Composes the 1920x1080 master canvas:
    - Ambient radial gradient background
    - Floating MacBook window with traffic lights (🔴 🟡 🟢) and URL pill
    - Scaled live website screenshot
    - 3 Right-hand feature cards with TrueType typography
    Returns (base_bgr_image, mac_viewport_top_left, mac_viewport_size)
    """
    canvas = Image.new("RGB", (1920, 1080), (10, 14, 20))
    draw = ImageDraw.Draw(canvas, "RGBA")

    palette = get_brand_palette(domain)
    g1, g2 = palette["glow"], palette["glow_secondary"]
    accent_rgb = palette["accent_rgb"]

    # 1. Radial ambient background glows
    draw.ellipse([150, 80, 1050, 950], fill=(g1[0], g1[1], g1[2], 55))
    draw.ellipse([1150, 350, 1900, 1100], fill=(g2[0], g2[1], g2[2], 40))

    # 2. MacBook Floating Window Frame
    win_x, win_y = 60, 75
    win_w, win_h = 1260, 930
    topbar_h = 44

    # Drop shadow
    for s in range(25, 0, -5):
        s_alpha = int(18 * (1.0 - s / 25.0))
        draw.rounded_rectangle(
            [win_x - s, win_y - s, win_x + win_w + s, win_y + win_h + s],
            radius=20,
            fill=(0, 0, 0, s_alpha)
        )

    # Mac Chrome Header
    draw.rounded_rectangle(
        [win_x, win_y, win_x + win_w, win_y + win_h],
        radius=18,
        fill=(22, 27, 36, 255),
        outline=(255, 255, 255, 30),
        width=1
    )

    # Traffic Light Buttons
    dot_y = win_y + topbar_h // 2
    draw.ellipse([win_x + 22, dot_y - 6, win_x + 34, dot_y + 6], fill=(255, 95, 87))   # 🔴
    draw.ellipse([win_x + 42, dot_y - 6, win_x + 54, dot_y + 6], fill=(255, 189, 46))  # 🟡
    draw.ellipse([win_x + 62, dot_y - 6, win_x + 74, dot_y + 6], fill=(39, 201, 63))   # 🟢

    # Centered Address Bar Pill
    pill_w = 340
    pill_x = win_x + (win_w - pill_w) // 2
    draw.rounded_rectangle(
        [pill_x, win_y + 8, pill_x + pill_w, win_y + topbar_h - 8],
        radius=8,
        fill=(14, 18, 25, 255),
        outline=(255, 255, 255, 22),
        width=1
    )
    font_url = get_system_font(13, bold=False)
    draw.text((pill_x + 24, win_y + 13), f"🔒  https://{domain}", fill=(160, 175, 195), font=font_url)

    # 3. Paste Website Viewport
    inner_w, inner_h = win_w, win_h - topbar_h
    if image_path.exists():
        web_img = Image.open(str(image_path)).convert("RGB")
        web_scaled = web_img.resize((inner_w, inner_h), Image.Resampling.LANCZOS)
    else:
        web_scaled = Image.new("RGB", (inner_w, inner_h), (20, 25, 35))

    canvas.paste(web_scaled, (win_x, win_y + topbar_h))

    # Outer border outline for crispness
    draw.rounded_rectangle(
        [win_x, win_y, win_x + win_w, win_y + win_h],
        radius=18,
        outline=(255, 255, 255, 25),
        width=1
    )

    # 4. Right Side Feature Cards (User's Exact 3 Cards)
    card_x = 1350
    card_w = 510
    card_h = 200
    card_gap = 25
    start_card_y = 120

    font_title = get_system_font(20, bold=True)
    font_cat = get_system_font(12, bold=True)
    font_desc = get_system_font(15, bold=False)

    for idx, c in enumerate(cards[:3]):
        cy = start_card_y + idx * (card_h + card_gap)
        is_active = (idx == active_card_idx)

        # Card shadow
        for cs in range(16, 0, -4):
            draw.rounded_rectangle(
                [card_x - cs, cy - cs, card_x + card_w + cs, cy + card_h + cs],
                radius=18,
                fill=(0, 0, 0, int(22 * (1.0 - cs / 16.0)))
            )

        card_bg = (25, 35, 50, 248) if is_active else (15, 20, 28, 210)
        card_border = (accent_rgb[0], accent_rgb[1], accent_rgb[2], 230) if is_active else (255, 255, 255, 30)
        card_bw = 2 if is_active else 1

        draw.rounded_rectangle(
            [card_x, cy, card_x + card_w, cy + card_h],
            radius=16,
            fill=card_bg,
            outline=card_border,
            width=card_bw
        )

        # Category Pill
        cat_text = c.get("category", "FEATURE").upper()
        pill_color = (accent_rgb[0], accent_rgb[1], accent_rgb[2], 40) if is_active else (255, 255, 255, 15)
        pill_txt_color = accent_rgb if is_active else (140, 155, 175)
        pill_w_text = int(draw.textlength(cat_text, font=font_cat)) + 24
        draw.rounded_rectangle(
            [card_x + 24, cy + 22, card_x + 24 + pill_w_text, cy + 48],
            radius=6,
            fill=pill_color
        )
        draw.text((card_x + 36, cy + 27), cat_text, fill=pill_txt_color, font=font_cat)

        # Title
        draw.text((card_x + 24, cy + 68), c.get("title", ""), fill=(255, 255, 255), font=font_title)

        # Description (Clean word-wrapping)
        raw_desc = c.get("desc", "")
        wrapped_lines = textwrap.wrap(raw_desc, width=44)
        for line_idx, line in enumerate(wrapped_lines[:3]):
            draw.text((card_x + 24, cy + 104 + (line_idx * 24)), line, fill=(165, 180, 200), font=font_desc)

    base_bgr = np.array(canvas)[:, :, ::-1] # Convert RGB to BGR for OpenCV
    viewport_tl = (win_x, win_y + topbar_h)
    viewport_sz = (inner_w, inner_h)
    return base_bgr, viewport_tl, viewport_sz

def render_interactive_scene_frames(
    image_path: Path,
    output_mp4: Path,
    duration_sec: float,
    domain: str = "example.com",
    cards: Optional[List[Dict[str, str]]] = None,
    active_card_idx: int = 0,
    target_xy: Tuple[int, int] = (1600, 68),
    zoom_in: bool = True,
    fps: int = 30,
    live_clip: Optional[Path] = None,
    prev_active_card_idx: Optional[int] = None,
    is_first_scene: bool = False,
    global_time_offset: float = 0.0,
    prev_cursor_norm: Optional[Tuple[float, float]] = None,
    fade_out_sec: float = 0.0,
    seed: int = 0,
    target_size: Optional[Tuple[float, float]] = None,
    watermark_path: Optional[Path] = None,
    brand_rgb: Optional[Tuple[int, int, int]] = None,
    do_click: bool = True,
) -> Tuple[Path, float]:
    """
    Renders one agency-grade showcase scene (1920x1080) and returns (output_mp4_path, click_time_sec).

    With `live_clip` (a recorded browser beat, see engine.browser.live_capture) the *real* page is
    on screen: hover states, scrolling, route transitions, plus a spring-physics camera that
    frames what the narrator talks about, a human-like pointer, motion blur, a softly tilted
    3D window and three benefit cards whose active state / progress rail follow the scene.
    Without it (or if it cannot be read) the static screenshot is animated with the same camera
    and pointer language, so the product never fails to produce a video.

    click_time_sec is when the pointer presses, in scene time (0.0 if nothing is clicked); the
    audio mixer lays the click foley on it.
    """
    # Imported here: showcase/scene_plan build on this module's palette helper.
    from .live_clip import LiveClip
    from .scene_plan import build_live_plan, build_static_plan
    from .showcase import ShowcaseRenderer, get_assets
    from ..config import config as _cfg

    output_mp4.parent.mkdir(parents=True, exist_ok=True)
    if not cards:
        cards = [
            {"category": "HIGHLIGHTING FEATURES", "title": "Modern Architecture", "desc": "Built for speed, scale, and high performance."},
            {"category": "IMPORTANTS", "title": "Automated Workflows", "desc": "Eliminate repetitive busywork with unified control."},
            {"category": "OTHER BENEFITS", "title": "Enterprise Reliability", "desc": "Bank-grade data privacy and 100% uptime."}
        ]

    palette = get_brand_palette(domain, brand_rgb)
    assets = get_assets(domain, palette, cards)

    plan = None
    clip = None
    if live_clip:
        try:
            clip = LiveClip(live_clip)
            plan = build_live_plan(clip, duration_sec, domain, seed=seed)
        except Exception:
            clip, plan = None, None

    if plan is None:
        img = None
        try:
            img = cv2.imdecode(np.fromfile(str(image_path), dtype=np.uint8), cv2.IMREAD_COLOR)
        except Exception:
            img = None
        if img is None:
            img = np.full((800, 1280, 3), (35, 25, 20), dtype=np.uint8)
        plan = build_static_plan(
            img, duration_sec, (float(target_xy[0]), float(target_xy[1])),
            start_norm=prev_cursor_norm, seed=seed, domain=domain, zoom_in=zoom_in,
            target_size=target_size or (160.0, 48.0), do_click=do_click,
        )

    renderer = ShowcaseRenderer(
        plan, assets, fps=fps, active_idx=active_card_idx, prev_idx=prev_active_card_idx,
        is_first=is_first_scene, fade_out=fade_out_sec, global_offset=global_time_offset,
        watermark_path=watermark_path,
    )
    click_time_sec = renderer.render(output_mp4)

    if clip is not None and not _cfg.keep_live_frames:
        clip.cleanup()
    return output_mp4, click_time_sec
