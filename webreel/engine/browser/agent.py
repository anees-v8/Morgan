import asyncio
from pathlib import Path
from typing import List, Dict, Any

from .recorder import BrowserRecorder

class AutonomousBrowserAgent:
    def __init__(self, headless: bool = True):
        self.recorder = BrowserRecorder(headless=headless)

    async def explore_and_record(
        self,
        base_url: str,
        job_dir: Path,
        max_pages: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Coordinates full browser exploration, capturing real rendered sections
        with perfect CSS, WebGL, fonts, and interaction hotspots.
        """
        await self.recorder.start()
        try:
            scenes = await self.recorder.capture_page_sections(
                url=base_url,
                job_dir=job_dir
            )
            return scenes
        finally:
            await self.recorder.close()
