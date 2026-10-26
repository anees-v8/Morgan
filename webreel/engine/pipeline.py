import asyncio
import uuid
import time
from pathlib import Path
from typing import Dict, Any, Optional, Callable

from .config import config, OUTPUT_DIR
from .browser.agent import AutonomousBrowserAgent
from .ai.summarizer import extract_brand_summary
from .ai.scriptwriter import ScriptWriter
from .video.producer import VideoProducer

async def run_pipeline(
    url: str,
    job_id: Optional[str] = None,
    progress_callback: Optional[Callable[[int, str], None]] = None
) -> Dict[str, Any]:
    """
    Main WebReel pipeline execution function.
    Takes any live website URL and returns the finalized cinematic video.
    """
    if not job_id:
        job_id = str(uuid.uuid4())[:8]

    job_dir = OUTPUT_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    def report(percent: int, stage_desc: str):
        if progress_callback:
            progress_callback(percent, stage_desc)

    start_time = time.time()
    
    # Ensure URL has protocol
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    report(5, "Launching autonomous Chromium browser...")
    agent = AutonomousBrowserAgent(headless=config.headless)

    # 1. Autonomous Exploration & Screenshot Capture
    report(20, "Navigating website and capturing high-res viewports...")
    scenes = await agent.explore_and_record(
        base_url=url,
        job_dir=job_dir,
        max_pages=config.max_pages_to_visit
    )

    if not scenes:
        raise RuntimeError("Failed to capture any pages from website.")

    # 2. Brand Summary & Visual Extraction
    report(45, "Multimodal vision analyzing headlines and brand assets...")
    home_scene = scenes[0]
    brand = extract_brand_summary(
        domain_or_url=url,
        title=home_scene.get("title", ""),
        meta_desc=home_scene.get("meta_description", "")
    )

    # 3. Synchronized Script Generation
    report(60, "Writing synchronized narrator script...")
    scriptwriter = ScriptWriter()
    scenes, feature_cards = scriptwriter.generate_script(brand, scenes)

    # 4. Cinematic Production, Voiceover & Assembly
    report(75, "Synthesizing studio voiceover and rendering Ken Burns frames...")
    producer = VideoProducer()
    
    report(85, "Compositing MacBook showcase, cursor clicks and rendering MP4...")
    final_video_path = await producer.assemble_full_video_async(
        brand=brand,
        scenes=scenes,
        feature_cards=feature_cards,
        job_dir=job_dir,
        include_watermark=True
    )

    elapsed = round(time.time() - start_time, 1)
    report(100, f"Video generated successfully in {elapsed}s!")

    return {
        "job_id": job_id,
        "status": "completed",
        "url": url,
        "brand": brand,
        "feature_cards": feature_cards,
        "scenes_count": len(scenes),
        "video_path": str(final_video_path),
        "video_filename": final_video_path.name,
        "duration_seconds": elapsed,
        "scenes": scenes
    }
