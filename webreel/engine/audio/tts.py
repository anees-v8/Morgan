import os
import subprocess
from pathlib import Path
from typing import Optional
from ..config import config

VOICE_MAP = {
    "male_confident": "en-US-ChristopherNeural",
    "female_warm": "en-US-JennyNeural",
    "female_clear": "en-US-AriaNeural",
    "male_deep": "en-US-GuyNeural",
    "british_male": "en-GB-RyanNeural",
    "british_female": "en-GB-SoniaNeural"
}

class NeuralTTS:
    def __init__(self, voice: Optional[str] = None):
        self.voice = voice or "en-US-ChristopherNeural"

    async def generate_speech_async(self, text: str, output_path: Path) -> Path:
        """
        Synthesizes crystal-clear Microsoft Studio Neural Voiceover asynchronously.
        Outputs pristine MP3.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        actual_voice = VOICE_MAP.get(self.voice, self.voice)
        rate_str = "+8%"

        try:
            import edge_tts
            # Generate directly as MP3
            c = edge_tts.Communicate(text, actual_voice, rate=rate_str)
            await c.save(str(output_path))
            if output_path.exists() and output_path.stat().st_size > 500:
                return output_path
        except Exception as e:
            pass

        # Fallback to SAPI
        try:
            import comtypes.client
            voice = comtypes.client.CreateObject("SAPI.SpVoice")
            stream = comtypes.client.CreateObject("SAPI.SpFileStream")
            wav_temp = output_path.with_suffix(".wav")
            stream.Open(str(wav_temp), 3, False)
            voice.AudioOutputStream = stream
            voice.Speak(text)
            stream.Close()
            cmd = ["ffmpeg", "-y", "-i", str(wav_temp), "-c:a", "libmp3lame", "-b:a", "192k", str(output_path)]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            wav_temp.unlink(missing_ok=True)
            return output_path
        except Exception:
            pass

        return output_path

    def generate_speech(self, text: str, output_path: Path) -> Path:
        """Synchronous wrapper for script execution outside an event loop."""
        import asyncio
        return asyncio.run(self.generate_speech_async(text, output_path))
