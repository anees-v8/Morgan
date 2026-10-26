import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from .overlay import VideoOverlay
from .effects import render_interactive_scene_frames
from .exporter import VideoExporter
from ..audio.tts import NeuralTTS
from ..audio.mixer import AudioMixer
from ..config import config


def _render_scene_job(job: Dict[str, Any]) -> Tuple[str, float]:
    """Renders one scene in-process (used as the fallback when a worker subprocess fails)."""
    out, click_time = render_interactive_scene_frames(**job)
    return str(out), float(click_time)


def _jsonable(job: Dict[str, Any]) -> Dict[str, Any]:
    return {k: (str(v) if isinstance(v, Path) else v) for k, v in job.items()}


def _run_worker_blocking(job: Dict[str, Any]) -> Tuple[str, float]:
    """
    Render one scene in a fresh `python -m ...render_worker` subprocess. A plain subprocess (rather
    than multiprocessing/spawn) never re-imports the caller's __main__ and works under any event-loop
    policy. Raises on failure so the caller can fall back to rendering in-process.
    """
    out_mp4: Path = Path(job["output_mp4"])
    job_file = out_mp4.with_suffix(".job.json")
    result_file = out_mp4.with_suffix(".result.json")
    result_file.unlink(missing_ok=True)
    job_file.write_text(json.dumps(_jsonable(job)), encoding="utf-8")
    root = Path(__file__).resolve().parents[3]      # directory that contains the `webreel` package
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-m", "webreel.engine.video.render_worker", str(job_file), str(result_file)],
        cwd=str(root), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    if proc.returncode != 0 or not result_file.exists():
        raise RuntimeError("render worker failed: " + proc.stderr.decode("utf-8", "ignore")[-600:])
    data = json.loads(result_file.read_text(encoding="utf-8"))
    job_file.unlink(missing_ok=True)
    result_file.unlink(missing_ok=True)
    return str(data["output"]), float(data["click_time"])


def _clip_info(live_clip_path: Optional[str]) -> Tuple[Optional[float], Optional[Tuple[float, float]]]:
    """(duration, normalised end-cursor position) of a recorded live clip, if readable."""
    if not live_clip_path:
        return None, None
    try:
        p = Path(live_clip_path)
        if not p.exists():
            return None, None
        meta = json.loads(p.read_text(encoding="utf-8"))
        vp = meta["viewport"]
        end = meta["cursor"]["end"]
        return float(meta["duration"]), (end[0] / vp["width"], end[1] / vp["height"])
    except Exception:
        return None, None


class VideoProducer:
    def __init__(self):
        self.overlay = VideoOverlay(width=config.video_width, height=config.video_height)
        self.exporter = VideoExporter(fps=config.video_fps)
        self.tts = NeuralTTS()
        self.mixer = AudioMixer()

    def get_audio_duration(self, audio_path: Path) -> float:
        """
        Uses ffprobe to get exact audio duration in seconds.
        """
        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(audio_path)
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            return float(res.stdout.strip())
        except Exception:
            return 8.0

    async def _render_all(self, jobs: List[Dict[str, Any]]) -> List[Tuple[str, float]]:
        """
        Render every scene: up to N worker subprocesses at a time. Any scene whose worker fails
        is simply rendered in-process instead, so a worker problem can never fail the video.
        """
        workers = max(1, min(len(jobs), int(os.getenv("WEBREEL_RENDER_WORKERS", str(max(1, min(3, (os.cpu_count() or 2) - 1)))))))
        gate = asyncio.Semaphore(workers)

        async def render_one(job: Dict[str, Any]) -> Tuple[str, float]:
            async with gate:
                if workers > 1:
                    try:
                        return await asyncio.to_thread(_run_worker_blocking, job)
                    except Exception:
                        pass
                return await asyncio.to_thread(_render_scene_job, dict(job))

        return list(await asyncio.gather(*[render_one(j) for j in jobs]))

    async def assemble_full_video_async(
        self,
        brand: Dict[str, str],
        scenes: List[Dict[str, Any]],
        job_dir: Path,
        feature_cards: Optional[List[Dict[str, str]]] = None,
        include_watermark: bool = True
    ) -> Path:
        """
        Orchestrates full agency-grade scene video generation asynchronously.
        Outputs final 1080p MP4.
        """
        rendered_clips: List[Path] = []
        domain = brand.get("clean_domain", "example.com")
        fps = config.video_fps
        watermark_path = job_dir / "watermark.png"
        if include_watermark:
            self.overlay.create_watermark(watermark_path)
        else:
            watermark_path = None

        # The renderer burns the watermark into the frames (one less lossy video generation).
        # If it cannot, the compositor falls back to overlaying it as before.
        bake_watermark = False
        if watermark_path is not None:
            from .showcase import load_watermark
            bake_watermark = load_watermark(watermark_path) is not None

        site_plan = next((sc.get("site_plan") for sc in scenes if sc.get("site_plan")), None) or {}
        brand_rgb = tuple(site_plan["brand_rgb"]) if site_plan.get("brand_rgb") else None

        # ---- Phase 1: voice-over + timing for every scene (sequential, as before) ----
        plans: List[Dict[str, Any]] = []
        global_t = 0.0
        prev_card: Optional[int] = None
        prev_cursor: Optional[Tuple[float, float]] = None
        for idx, scene in enumerate(scenes):
            scene_id = scene.get("scene_id", f"scene_{idx:02d}")
            narration = scene.get("narration", f"Experience {brand.get('company_name')}.")
            raw_img = Path(scene.get("screenshot_path"))

            # Step A: Synthesize Microsoft Studio Neural Voiceover (asynchronously)
            voice_raw = job_dir / f"{scene_id}_voice.mp3"
            await self.tts.generate_speech_async(narration, voice_raw)
            audio_duration = self.get_audio_duration(voice_raw)
            scene_duration = max(7.0, audio_duration + 0.6)

            live_path = scene.get("live_clip")
            live_len, end_cursor = _clip_info(live_path)
            if live_len:
                # never cut the recorded interaction short
                scene_duration = max(scene_duration, live_len + 0.35)

            cta_coords = scene.get("cta_coordinates")
            target_xy = (cta_coords["x"], cta_coords["y"]) if cta_coords else (1600, 68)
            active_idx = scene.get("active_card_idx", idx % 3)

            plans.append({
                "scene_id": scene_id,
                "voice_raw": voice_raw,
                "duration": scene_duration,
                "job": dict(
                    image_path=raw_img,
                    output_mp4=job_dir / f"{scene_id}_motion.mp4",
                    duration_sec=scene_duration,
                    domain=domain,
                    cards=feature_cards,
                    active_card_idx=active_idx,
                    target_xy=target_xy,
                    zoom_in=(idx % 2 == 0),
                    fps=fps,
                    live_clip=Path(live_path) if (live_path and live_len) else None,
                    prev_active_card_idx=prev_card,
                    is_first_scene=(idx == 0),
                    global_time_offset=global_t,
                    prev_cursor_norm=prev_cursor,
                    seed=idx * 17 + 3,
                    watermark_path=watermark_path if bake_watermark else None,
                    brand_rgb=brand_rgb,
                    do_click=bool(scene.get("target_present", True)),
                ),
            })
            global_t += scene_duration
            prev_card = active_idx
            prev_cursor = end_cursor if end_cursor else prev_cursor

        # ---- Branded outro (same stage, static card) ----
        outro_img = job_dir / "scene_outro.png"
        self.overlay.create_outro_card(brand, outro_img)
        outro_voice = job_dir / "scene_outro_voice.mp3"
        outro_line = site_plan.get("outro_say") or f"Start creating today at {brand.get('clean_domain')}."
        await self.tts.generate_speech_async(outro_line, outro_voice)
        outro_dur = max(6.0, self.get_audio_duration(outro_voice) + 0.6)
        plans.append({
            "scene_id": "scene_outro",
            "voice_raw": outro_voice,
            "duration": outro_dur,
            "job": dict(
                image_path=outro_img,
                output_mp4=job_dir / "scene_outro_motion.mp4",
                duration_sec=outro_dur,
                domain=domain,
                cards=feature_cards,
                active_card_idx=2,
                target_xy=(960, 618),          # centre of the "Visit <domain>" pill on the outro card
                zoom_in=True,
                fps=fps,
                live_clip=None,
                prev_active_card_idx=prev_card,
                is_first_scene=False,
                global_time_offset=global_t,
                prev_cursor_norm=prev_cursor,
                fade_out_sec=0.8,
                seed=991,
                target_size=(340.0, 56.0),
                watermark_path=watermark_path if bake_watermark else None,
                brand_rgb=brand_rgb,
            ),
        })

        # ---- Phase 2: render all scene motion videos (parallel processes) ----
        results = await self._render_all([p["job"] for p in plans])
        for p, (_, click_time) in zip(plans, results):
            p["click_time"] = click_time

        # ---- Phase 3: mix voice + music + click foley, mux with picture (concurrently) ----
        def finish(p: Dict[str, Any]) -> Path:
            mixed_audio = job_dir / f"{p['scene_id']}_mixed.mp3"
            # Mix voiceover with background music (auto-ducking to 8%) and millisecond-accurate click foley
            self.mixer.mix_voice_and_music(
                voiceover_path=p["voice_raw"],
                output_mixed_path=mixed_audio,
                duration=p["duration"],
                click_offset_sec=p["click_time"]
            )
            clip_path = job_dir / f"{p['scene_id']}_clip.mp4"
            self.exporter.composite_scene_clip(
                motion_video_path=p["job"]["output_mp4"],
                audio_path=mixed_audio,
                duration_sec=p["duration"],
                output_clip_path=clip_path,
                overlay_path=None,
                watermark_path=None if bake_watermark else watermark_path
            )
            return clip_path

        rendered_clips = list(await asyncio.gather(*[asyncio.to_thread(finish, p) for p in plans]))

        # 3. Concatenate all scenes into final video
        final_mp4 = job_dir / f"{brand.get('clean_domain', 'webreel')}_intro.mp4"
        self.exporter.concatenate_clips(rendered_clips, final_mp4)

        return final_mp4
