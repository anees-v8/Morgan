import os
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

def draw_cursor(img_bgr: np.ndarray, x: int, y: int):
    """
    Draws a clean, modern white macOS/Windows cursor with dark drop shadow.
    """
    poly = np.array([
        [x, y],
        [x, y + 26],
        [x + 7, y + 19],
        [x + 14, y + 29],
        [x + 19, y + 26],
        [x + 11, y + 16],
        [x + 20, y + 16]
    ], dtype=np.int32)

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

def get_brand_palette(domain: str) -> Dict[str, Any]:
    """
    Extracts brand-tailored color accents and ambient lighting.
    """
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
    fps: int = 30
) -> Path:
    """
    Renders agency-grade MacBook showcase video frames:
    - macOS floating application window + ambient background
    - 3 Synchronized right-hand benefit cards
    - Natural cubic ease-out mouse glide to target element inside the Mac window
    - Expanding glowing click ripple on button arrival
    - Parallax floating camera motion
    """
    output_mp4.parent.mkdir(parents=True, exist_ok=True)
    if not cards:
        cards = [
            {"category": "HIGHLIGHTING FEATURES", "title": "Modern Architecture", "desc": "Built for speed, scale, and high performance."},
            {"category": "IMPORTANTS", "title": "Automated Workflows", "desc": "Eliminate repetitive busywork with unified control."},
            {"category": "OTHER BENEFITS", "title": "Enterprise Reliability", "desc": "Bank-grade data privacy and 100% uptime."}
        ]

    # Pre-render the master Mac canvas (takes ~50ms once!)
    base_bgr, (vp_x, vp_y), (vp_w, vp_h) = compose_mac_showcase_canvas(
        image_path=image_path,
        domain=domain,
        cards=cards,
        active_card_idx=active_card_idx
    )

    palette = get_brand_palette(domain)
    ripple_color = palette["accent_bgr"]

    total_frames = max(30, int(duration_sec * fps))
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(output_mp4), fourcc, fps, (1920, 1080))

    # Map target coordinates into the MacBook inner viewport
    orig_tx, orig_ty = target_xy
    dest_x = vp_x + int(orig_tx * (vp_w / 1920.0))
    dest_y = vp_y + int(orig_ty * (vp_h / 1080.0))

    # Clamp coordinates to stay within Mac window
    dest_x = max(vp_x + 10, min(vp_x + vp_w - 20, dest_x))
    dest_y = max(vp_y + 10, min(vp_y + vp_h - 20, dest_y))

    start_x = vp_x + (vp_w // 2)
    start_y = vp_y + (vp_h // 2) + 60

    glide_end_frame = int(total_frames * 0.40)
    click_frame = glide_end_frame

    for f in range(total_frames):
        frame = base_bgr.copy()

        # 1. Parallax subtle floating motion (breathing camera effect)
        t = f / float(total_frames)
        float_dy = int(3.0 * np.sin(2 * np.pi * t))

        # 2. Cursor glide physics
        if f < glide_end_frame:
            ease = ease_out_cubic(f / float(glide_end_frame))
            cur_x = int(start_x + (dest_x - start_x) * ease)
            cur_y = int(start_y + (dest_y - start_y) * ease) + float_dy
        else:
            cur_x = dest_x
            cur_y = dest_y + float_dy

        # 3. Expanding click ripple
        if f >= click_frame and f < click_frame + 28:
            ripple_t = (f - click_frame) / 28.0
            draw_click_ripple(frame, dest_x, dest_y + float_dy, ripple_t, color_bgr=ripple_color)

        # 4. Draw pointer cursor
        draw_cursor(frame, cur_x, cur_y)

        writer.write(frame)

    writer.release()
    return output_mp4
