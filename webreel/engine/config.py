import os
from pathlib import Path
from pydantic import BaseModel
from typing import Dict, Any

BASE_DIR = Path(__file__).resolve().parent.parent

# Optional webreel/.env (GEMINI_API_KEY etc.). Real environment variables always win.
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env", override=False)
except Exception:
    pass
OUTPUT_DIR = BASE_DIR / "output"
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
MUSIC_DIR = Path(__file__).resolve().parent / "audio" / "music"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
(ASSETS_DIR / "fonts").mkdir(parents=True, exist_ok=True)
(ASSETS_DIR / "overlays").mkdir(parents=True, exist_ok=True)
MUSIC_DIR.mkdir(parents=True, exist_ok=True)

class WebReelConfig(BaseModel):
    # App & Runtime
    app_env: str = os.getenv("APP_ENV", "development")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    
    # Video Specifications
    video_width: int = int(os.getenv("VIDEO_RESOLUTION_W", "1920"))
    video_height: int = int(os.getenv("VIDEO_RESOLUTION_H", "1080"))
    video_fps: int = int(os.getenv("VIDEO_FPS", "60"))   # 60: live scroll/hover motion and pointer glide stay smooth
    video_target_duration: int = int(os.getenv("VIDEO_DURATION_TARGET", "90"))
    max_pages_to_visit: int = int(os.getenv("MAX_PAGES_TO_VISIT", "5"))
    
    # Audio & TTS
    # Default to high-quality neural voice (edge-tts / kokoro compatible)
    tts_default_voice: str = os.getenv("TTS_DEFAULT_VOICE", "en-US-ChristopherNeural")
    tts_speed: float = float(os.getenv("TTS_SPEED", "1.08"))
    music_volume: float = 0.08  # -22dB auto-ducking
    voice_volume: float = 1.0
    
    # Browser Settings
    viewport_width: int = 1920
    viewport_height: int = 1080
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    )
    headless: bool = True
    timeout_ms: int = 30000

    # Cinematic live capture (real page motion instead of frozen screenshots).
    # 1280x800 is a real MacBook "looks like" resolution (16:10) and maps ~1:1 onto the
    # showcase window, so text stays crisp. Set WEBREEL_LIVE_CAPTURE=0 to use screenshots only.
    live_capture: bool = os.getenv("WEBREEL_LIVE_CAPTURE", "1") != "0"
    capture_width: int = int(os.getenv("WEBREEL_CAPTURE_W", "1280"))
    capture_height: int = int(os.getenv("WEBREEL_CAPTURE_H", "800"))
    keep_live_frames: bool = os.getenv("WEBREEL_KEEP_LIVE_FRAMES", "0") == "1"

    # Dynamic story: scout the site -> Gemini "director" plans the film from the site's own
    # content (OCR + DOM) -> the journey clicks the site's own buttons. Without a Gemini key the
    # same pipeline runs from the page text alone (no LLM). WEBREEL_DYNAMIC_STORY=0 restores the
    # legacy fixed journey.
    dynamic_story: bool = os.getenv("WEBREEL_DYNAMIC_STORY", "1") != "0"
    # Tried in order; a model that is retired / not on your tier / out of quota is skipped.
    gemini_models: str = os.getenv(
        "GEMINI_MODELS",
        "gemini-3.6-flash,gemini-3.1-flash-lite,gemini-3.5-flash-lite",
    )
    narration_language: str = os.getenv("WEBREEL_NARRATION_LANGUAGE", "English")
    story_scenes: int = int(os.getenv("WEBREEL_SCENES", "4"))

config = WebReelConfig()
