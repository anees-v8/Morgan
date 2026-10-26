import subprocess
from pathlib import Path
from typing import List, Optional

class VideoExporter:
    def __init__(self, fps: int = 30):
        self.fps = fps

    def composite_scene_clip(
        self,
        motion_video_path: Path,
        audio_path: Optional[Path],
        duration_sec: float,
        output_clip_path: Path,
        overlay_path: Optional[Path] = None,
        watermark_path: Optional[Path] = None
    ) -> Path:
        """
        Takes the rendered interactive motion clip, composites lower-third and watermark,
        and synchronizes narration audio.
        """
        output_clip_path.parent.mkdir(parents=True, exist_ok=True)

        inputs = ["-i", str(motion_video_path)]
        filter_complex = "[0:v]null[base]"
        current_v = "[base]"
        input_idx = 1

        if overlay_path and overlay_path.exists():
            inputs.extend(["-loop", "1", "-i", str(overlay_path)])
            filter_complex += f";{current_v}[{input_idx}:v]overlay=0:0:eof_action=repeat[v_ov]"
            current_v = "[v_ov]"
            input_idx += 1

        if watermark_path and watermark_path.exists():
            inputs.extend(["-loop", "1", "-i", str(watermark_path)])
            filter_complex += f";{current_v}[{input_idx}:v]overlay=0:0:eof_action=repeat[v_wm]"
            current_v = "[v_wm]"
            input_idx += 1

        if audio_path and audio_path.exists():
            inputs.extend(["-i", str(audio_path)])
            audio_map = f"{input_idx}:a"
        else:
            inputs.extend(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"])
            audio_map = f"{input_idx}:a"

        cmd = [
            "ffmpeg", "-y",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", current_v,
            "-map", audio_map,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "faster",
            "-crf", "18",
            "-c:a", "aac",
            "-b:a", "192k",
            "-t", str(duration_sec),
            str(output_clip_path)
        ]

        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return output_clip_path

    def concatenate_clips(self, clip_paths: List[Path], output_final_mp4: Path) -> Path:
        """
        Concatenates all scene clips into a single continuous MP4.
        """
        output_final_mp4.parent.mkdir(parents=True, exist_ok=True)
        concat_txt = output_final_mp4.parent / "concat_list.txt"

        with open(concat_txt, "w", encoding="utf-8") as f:
            for p in clip_paths:
                clean_path = str(p.resolve()).replace("\\", "/")
                f.write(f"file '{clean_path}'\n")

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_txt),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "fast",
            "-crf", "18",
            "-c:a", "aac",
            "-b:a", "192k",
            str(output_final_mp4)
        ]

        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if concat_txt.exists():
            concat_txt.unlink(missing_ok=True)

        return output_final_mp4
