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
        duration: Optional[float] = None,
        click_offset_sec: Optional[float] = None
    ) -> Path:
        """
        Mixes speech voiceover with background music (auto-ducking to 8%)
        and synchronizes a tactile mechanical mouse click transient sound at click_offset_sec.
        Outputs pristine MP3.
        """
        output_mixed_path.parent.mkdir(parents=True, exist_ok=True)
        
        music_file = background_music_path
        if not music_file or not music_file.exists():
            available = list(self.music_dir.glob("*.mp3"))
            if available:
                music_file = available[0]

        click_file = self.music_dir / "mouse_click.wav"
        has_click = click_file.exists() and (click_offset_sec is not None and click_offset_sec > 0)

        inputs = ["-i", str(voiceover_path)]
        input_idx = 1

        if music_file and music_file.exists():
            inputs.extend(["-stream_loop", "-1", "-i", str(music_file)])
            music_idx = input_idx
            input_idx += 1
        else:
            music_idx = None

        if has_click:
            inputs.extend(["-i", str(click_file)])
            click_idx = input_idx
            input_idx += 1
        else:
            click_idx = None

        filter_parts = []
        amix_inputs = ["[0:a]"]

        if music_idx is not None:
            dur_filter = f",atrim=0:{duration}" if duration else ""
            filter_parts.append(f"[{music_idx}:a]volume=0.08{dur_filter}[music]")
            amix_inputs.append("[music]")

        if click_idx is not None:
            delay_ms = int(click_offset_sec * 1000)
            filter_parts.append(f"[{click_idx}:a]adelay={delay_ms}|{delay_ms},volume=0.62[click]")
            amix_inputs.append("[click]")

        if len(amix_inputs) > 1:
            filter_parts.append(f"{''.join(amix_inputs)}amix=inputs={len(amix_inputs)}:duration=first:dropout_transition=2[mixed];[mixed]volume=6dB,alimiter=limit=0.95:level=disabled[aout]")
            filter_complex = ";".join(filter_parts)
            cmd = [
                "ffmpeg", "-y",
                *inputs,
                "-filter_complex", filter_complex,
                "-map", "[aout]",
                "-c:a", "libmp3lame",
                "-b:a", "192k",
                str(output_mixed_path)
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                *inputs,
                "-c:a", "libmp3lame",
                "-b:a", "192k",
                str(output_mixed_path)
            ]

        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return output_mixed_path
