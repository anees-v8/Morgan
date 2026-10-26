import subprocess
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional

from .overlay import VideoOverlay
from .effects import render_interactive_scene_frames
from .exporter import VideoExporter
from ..audio.tts import NeuralTTS
from ..audio.mixer import AudioMixer
from ..config import config

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
        watermark_path = job_dir / "watermark.png"
        if include_watermark:
            self.overlay.create_watermark(watermark_path)
        else:
            watermark_path = None

        # 1. Produce each individual scene
        for idx, scene in enumerate(scenes):
            scene_id = scene.get("scene_id", f"scene_{idx:02d}")
            category = scene.get("scene_type", "Feature").title()
            title = scene.get("title", "").split("|")[0].split("—")[0].strip() or category
            narration = scene.get("narration", f"Experience {brand.get('company_name')}.")
            raw_img = Path(scene.get("screenshot_path"))

            # Step A: Synthesize Microsoft Studio Neural Voiceover (asynchronously)
            voice_raw = job_dir / f"{scene_id}_voice.mp3"
            await self.tts.generate_speech_async(narration, voice_raw)
            audio_duration = self.get_audio_duration(voice_raw)
            scene_duration = max(7.0, audio_duration + 0.6)

            # Step B: Mix voiceover with background music (auto-ducking to 8%)
            mixed_audio = job_dir / f"{scene_id}_mixed.mp3"
            self.mixer.mix_voice_and_music(voice_raw, mixed_audio, duration=scene_duration)

            # Step C: Render agency-grade MacBook showcase motion video (gliding cursor + ripples + 3 cards)
            motion_mp4 = job_dir / f"{scene_id}_motion.mp4"
            cta_coords = scene.get("cta_coordinates")
            target_xy = (cta_coords["x"], cta_coords["y"]) if cta_coords else (1600, 68)

            render_interactive_scene_frames(
                image_path=raw_img,
                output_mp4=motion_mp4,
                duration_sec=scene_duration,
                domain=domain,
                cards=feature_cards,
                active_card_idx=scene.get("active_card_idx", idx % 3),
                target_xy=target_xy,
                zoom_in=(idx % 2 == 0),
                fps=config.video_fps
            )

            # Step D: Composite scene video with audio and watermark
            clip_path = job_dir / f"{scene_id}_clip.mp4"
            self.exporter.composite_scene_clip(
                motion_video_path=motion_mp4,
                audio_path=mixed_audio,
                duration_sec=scene_duration,
                output_clip_path=clip_path,
                overlay_path=None,
                watermark_path=watermark_path
            )
            rendered_clips.append(clip_path)

        # 2. Add Branded Outro Screen
        outro_img = job_dir / "scene_outro.png"
        self.overlay.create_outro_card(brand, outro_img)
        outro_voice = job_dir / "scene_outro_voice.mp3"
        await self.tts.generate_speech_async(f"Start creating today at {brand.get('clean_domain')}.", outro_voice)
        outro_dur = max(6.0, self.get_audio_duration(outro_voice) + 0.6)
        
        outro_mixed = job_dir / "scene_outro_mixed.mp3"
        self.mixer.mix_voice_and_music(outro_voice, outro_mixed, duration=outro_dur)

        outro_motion = job_dir / "scene_outro_motion.mp4"
        render_interactive_scene_frames(
            image_path=outro_img,
            output_mp4=outro_motion,
            duration_sec=outro_dur,
            target_xy=(960, 570),
            zoom_in=True,
            fps=config.video_fps
        )

        outro_clip = job_dir / "scene_outro_clip.mp4"
        self.exporter.composite_scene_clip(
            motion_video_path=outro_motion,
            audio_path=outro_mixed,
            duration_sec=outro_dur,
            output_clip_path=outro_clip,
            overlay_path=None,
            watermark_path=watermark_path
        )
        rendered_clips.append(outro_clip)

        # 3. Concatenate all scenes into final video
        final_mp4 = job_dir / f"{brand.get('clean_domain', 'webreel')}_intro.mp4"
        self.exporter.concatenate_clips(rendered_clips, final_mp4)

        return final_mp4
