import os
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

import numpy as np


class RawVideoWriter:
    """
    Streams raw BGR frames straight into ONE ffmpeg/x264 process.

    This replaces cv2.VideoWriter('mp4v') (a poor-quality MPEG-4 Part 2 first generation) with a
    single high-quality H.264 encode, with correct BT.709 colour tagging so colours are not
    shifted/washed out by players that assume HD = Rec.709.
    """

    def __init__(self, output_path: Path, width: int, height: int, fps: int, crf: int = 12, preset: str = "veryfast"):
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.width, self.height = width, height
        self._err = tempfile.TemporaryFile()
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{width}x{height}", "-r", str(fps), "-i", "-",
            "-vf", "scale=out_color_matrix=bt709:out_range=tv:flags=accurate_rnd+full_chroma_int,format=yuv420p",
            "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
            "-x264-params", "aq-mode=3:aq-strength=0.9",
            "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
            "-movflags", "+faststart",
            str(self.output_path),
        ]
        self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=self._err)

    def write(self, frame_bgr: np.ndarray) -> None:
        if frame_bgr.shape[1] != self.width or frame_bgr.shape[0] != self.height:
            raise ValueError("frame size does not match the writer")
        try:
            self._proc.stdin.write(np.ascontiguousarray(frame_bgr).tobytes())
        except (BrokenPipeError, OSError):
            raise RuntimeError("ffmpeg terminated early: " + self._read_err())

    def _read_err(self) -> str:
        try:
            self._err.seek(0)
            return self._err.read().decode("utf-8", "ignore")[-800:]
        except Exception:
            return ""

    def close(self) -> None:
        try:
            if self._proc.stdin:
                self._proc.stdin.close()
        except Exception:
            pass
        code = self._proc.wait()
        if code != 0 or not self.output_path.exists():
            raise RuntimeError(f"ffmpeg encode failed ({code}): {self._read_err()}")
        self._err.close()

    def abort(self) -> None:
        try:
            self._proc.kill()
        except Exception:
            pass
        try:
            self._err.close()
        except Exception:
            pass


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
        has_overlay = bool(overlay_path and overlay_path.exists())
        has_watermark = bool(watermark_path and watermark_path.exists())
        # When nothing has to be drawn on the picture (the renderer already baked the watermark
        # in), the video stream is passed through untouched: no second lossy generation.
        passthrough = not has_overlay and not has_watermark

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
        else:
            inputs.extend(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"])
        # The mixed track ends with the voice-over (~0.6s before the scene does). Left as is, every
        # concatenated scene would start its audio earlier and earlier relative to its picture, so
        # pad the audio to the exact scene length to keep narration and click foley in sync.
        audio_chain = f"[{input_idx}:a]apad=whole_dur={duration_sec:.3f}[aout]"

        if passthrough:
            cmd = [
                "ffmpeg", "-y",
                *inputs,
                "-filter_complex", audio_chain,
                "-map", "0:v",
                "-map", "[aout]",
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                "-ar", "44100",
                "-t", f"{duration_sec:.3f}",
                str(output_clip_path)
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                *inputs,
                "-filter_complex", filter_complex + ";" + audio_chain,
                "-map", current_v,
                "-map", "[aout]",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-preset", "fast",
                "-crf", "16",
                "-x264-params", "aq-mode=3:aq-strength=0.9",
                "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
                "-c:a", "aac",
                "-b:a", "192k",
                "-ar", "44100",
                "-t", f"{duration_sec:.3f}",
                str(output_clip_path)
            ]

        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return output_clip_path

    def concatenate_clips(self, clip_paths: List[Path], output_final_mp4: Path) -> Path:
        """
        Concatenates all scene clips into a single continuous MP4.
        Every clip comes from the same encoder settings, so the streams are joined losslessly
        (no extra generation of compression); if that is not possible we re-encode as before.
        """
        output_final_mp4.parent.mkdir(parents=True, exist_ok=True)
        concat_txt = output_final_mp4.parent / "concat_list.txt"

        with open(concat_txt, "w", encoding="utf-8") as f:
            for p in clip_paths:
                clean_path = str(p.resolve()).replace("\\", "/")
                f.write(f"file '{clean_path}'\n")

        copy_cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_txt),
            "-c", "copy",
            "-movflags", "+faststart",
            str(output_final_mp4)
        ]
        res = subprocess.run(copy_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        if res.returncode != 0 or not output_final_mp4.exists() or output_final_mp4.stat().st_size < 1024:
            cmd = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_txt),
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-preset", "fast",
                "-crf", "16",
                "-c:a", "aac",
                "-b:a", "192k",
                "-movflags", "+faststart",
                str(output_final_mp4)
            ]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        if concat_txt.exists():
            concat_txt.unlink(missing_ok=True)

        return output_final_mp4
