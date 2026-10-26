import os
from pathlib import Path
from pydantic import BaseModel
from typing import Dict, Any

BASE_DIR = Path(__file__).resolve().parent.parent
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
    video_fps: int = int(os.getenv("VIDEO_FPS", "30"))
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

config = WebReelConfig()
