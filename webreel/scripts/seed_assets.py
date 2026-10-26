import subprocess
from pathlib import Path
from PIL import Image, ImageDraw

def seed():
    base_dir = Path(__file__).resolve().parent.parent
    assets_dir = base_dir / "engine" / "assets"
    music_dir = base_dir / "engine" / "audio" / "music"
    
    assets_dir.mkdir(parents=True, exist_ok=True)
    music_dir.mkdir(parents=True, exist_ok=True)

    # 1. Generate ambient background music track using FFmpeg synth
    ambient_mp3 = music_dir / "minimal_ambient.mp3"
    if not ambient_mp3.exists():
        print("Generating ambient background loop via FFmpeg...")
        # Generates a pleasant low-frequency ambient pad chord (A2 + E3 + A3) with gentle chorus
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", "sine=frequency=110:duration=120,volume=0.08[a1];sine=frequency=164.81:duration=120,volume=0.06[a2];sine=frequency=220:duration=120,volume=0.04[a3];[a1][a2][a3]amix=inputs=3[out]",
            "-map", "[out]",
            "-c:a", "libmp3lame",
            "-b:a", "192k",
            str(ambient_mp3)
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"Ambient music seeded at {ambient_mp3}")

    # 2. Generate cursor.png sprite
    cursor_png = assets_dir / "cursor.png"
    if not cursor_png.exists():
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        poly = [(4, 4), (4, 38), (14, 30), (22, 46), (28, 42), (18, 26), (30, 26)]
        draw.polygon([(x+2, y+2) for x, y in poly], fill=(0, 0, 0, 160))
        draw.polygon(poly, fill=(255, 255, 255, 255), outline=(15, 23, 42, 255))
        img.save(str(cursor_png))
        print(f"Cursor sprite seeded at {cursor_png}")

if __name__ == "__main__":
    seed()
