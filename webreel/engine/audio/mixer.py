import subprocess
from pathlib import Path
from typing import Optional
from ..config import config

class AudioMixer:
    def __init__(self):
        self.music_dir = Path(__file__).resolve().parent / "music"
        self.music_dir.mkdir(parents=True, exist_ok=True)

    def mix_voice_and_music(
        self,
        voiceover_path: Path,
        output_mixed_path: Path,
        background_music_path: Optional[Path] = None,
        duration: Optional[float] = None
    ) -> Path:
        """
        Mixes speech voiceover with background music, applying auto-ducking (voice 100%, music 8%).
        Outputs pristine MP3.
        """
        output_mixed_path.parent.mkdir(parents=True, exist_ok=True)
        
        music_file = background_music_path
        if not music_file or not music_file.exists():
            available = list(self.music_dir.glob("*.mp3"))
            if available:
                music_file = available[0]

        if music_file and music_file.exists():
            # Mix voiceover with ducked music loop
            dur_filter = f",atrim=0:{duration}" if duration else ""
            filter_complex = (
                f"[1:a]volume=0.08{dur_filter}[music];"
                "[0:a][music]amix=inputs=2:duration=first:dropout_transition=2[aout]"
            )
            cmd = [
                "ffmpeg", "-y",
                "-i", str(voiceover_path),
                "-stream_loop", "-1", "-i", str(music_file),
                "-filter_complex", filter_complex,
                "-map", "[aout]",
                "-c:a", "libmp3lame",
                "-b:a", "192k",
                str(output_mixed_path)
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-i", str(voiceover_path),
                "-c:a", "libmp3lame",
                "-b:a", "192k",
                str(output_mixed_path)
            ]

        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return output_mixed_path
