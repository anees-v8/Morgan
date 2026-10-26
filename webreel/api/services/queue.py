import asyncio
from typing import Dict, Any, Optional
from ..models.job import JobStatusResponse
from ...engine.pipeline import run_pipeline

class JobManager:
    def __init__(self):
        self.jobs: Dict[str, Dict[str, Any]] = {}
        self._load_cached_jobs()

    def _load_cached_jobs(self):
        # Register verified demo jobs
        from ...engine.config import OUTPUT_DIR
        campusweb_v3_mp4 = OUTPUT_DIR / "campusweb_interactive_v3" / "campusweb.co.in_intro.mp4"
        campusweb_path = campusweb_v3_mp4 if campusweb_v3_mp4.exists() else (OUTPUT_DIR / "campusweb_agency_v2" / "campusweb.co.in_intro.mp4")
        if campusweb_path.exists():
            campusweb_job = {
                "job_id": "campusweb_interactive_v3",
                "url": "https://campusweb.co.in",
                "status": "completed",
                "progress_percent": 100,
                "current_stage": "Interactive Video generation complete!",
                "brand": {
                    "company_name": "CampusWeb",
                    "clean_domain": "campusweb.co.in",
                    "tagline": "Built for Coaching. Crafted for Speed & Scale."
                },
                "video_path": str(campusweb_path),
                "video_filename": "campusweb.co.in_intro.mp4",
                "scenes_count": 4,
                "duration_seconds": 59.4,
                "scenes": [
                    { "scene_type": "Hero", "title": "CampusWeb Operating Suite", "duration_sec": 14, "narration": "Meet CampusWeb. Built for coaching, crafted for speed and scale. Built from the ground up to eliminate daily busywork and deliver unmatched speed, scale, and operational control." },
                    { "scene_type": "Dashboard", "title": "Directors & Admins Control", "duration_sec": 11, "narration": "Inside the core dashboard, everything is unified. From 1-tap dynamic QR attendance to automated tracking, manage your entire operations effortlessly from a single screen." },
                    { "scene_type": "Features", "title": "Save 2+ Hours Daily for Teachers", "duration_sec": 11, "narration": "Engineered for high performance. Experience automated WhatsApp receipts, instant synchronization, and workflows that keep your entire organization moving forward without friction." },
                    { "scene_type": "Pricing", "title": "Pricing Plans That Grow with You", "duration_sec": 13, "narration": "Transparent, flexible plans backed by our zero commission guarantee. Zero paperwork, zero hidden friction. Take your operations to the next level today at campusweb.co.in." }
                ],
                "error": None
            }
            self.jobs["campusweb_interactive_v3"] = campusweb_job
            self.jobs["campusweb_agency_v2"] = campusweb_job

        linear_v3_mp4 = OUTPUT_DIR / "linear_interactive_v3" / "linear.app_intro.mp4"
        linear_path = linear_v3_mp4 if linear_v3_mp4.exists() else (OUTPUT_DIR / "linear_agency_v2" / "linear.app_intro.mp4")
        if linear_path.exists():
            linear_job = {
                "job_id": "linear_interactive_v3",
                "url": "https://linear.app",
                "status": "completed",
                "progress_percent": 100,
                "current_stage": "Interactive Video generation complete!",
                "brand": {
                    "company_name": "Linear",
                    "clean_domain": "linear.app",
                    "tagline": "The product development system for teams and agents."
                },
                "video_path": str(linear_path),
                "video_filename": "linear.app_intro.mp4",
                "scenes_count": 4,
                "duration_seconds": 53.7,
                "scenes": [
                    { "scene_type": "Hero", "title": "Linear Product System", "duration_sec": 13, "narration": "Meet Linear. The purpose-built platform for teams and agents. Built from the ground up to eliminate daily busywork and deliver unmatched speed, scale, and operational control." },
                    { "scene_type": "Dashboard", "title": "Lightning Issue Tracking", "duration_sec": 11, "narration": "Inside the core dashboard, everything is unified. From lightning issue tracking to automated tracking, manage your entire operations effortlessly from a single screen." },
                    { "scene_type": "Features", "title": "Automated Cycle Planning", "duration_sec": 11, "narration": "Engineered for high performance. Experience automated cycle planning, instant synchronization, and workflows that keep your entire organization moving forward without friction." },
                    { "scene_type": "Pricing", "title": "Enterprise Git Sync", "duration_sec": 12, "narration": "Transparent, flexible plans backed by enterprise git sync. Zero paperwork, zero hidden friction. Take your operations to the next level today at linear.app." }
                ],
                "error": None
            }
            self.jobs["linear_interactive_v3"] = linear_job
            self.jobs["linear_agency_v2"] = linear_job

    def create_job(self, job_id: str, url: str) -> Dict[str, Any]:
        job_data = {
            "job_id": job_id,
            "url": url,
            "status": "pending",
            "progress_percent": 0,
            "current_stage": "Queued for generation...",
            "brand": None,
            "video_path": None,
            "video_filename": None,
            "scenes_count": 0,
            "duration_seconds": 0.0,
            "error": None
        }
        self.jobs[job_id] = job_data
        return job_data

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        return self.jobs.get(job_id)

    async def execute_job(self, job_id: str):
        job = self.jobs.get(job_id)
        if not job:
            return

        job["status"] = "processing"

        def on_progress(percent: int, stage: str):
            job["progress_percent"] = percent
            job["current_stage"] = stage

        try:
            result = await run_pipeline(
                url=job["url"],
                job_id=job_id,
                progress_callback=on_progress
            )
            job["status"] = "completed"
            job["progress_percent"] = 100
            job["current_stage"] = "Video generation complete!"
            job["brand"] = result.get("brand")
            job["video_path"] = result.get("video_path")
            job["video_filename"] = result.get("video_filename")
            job["scenes_count"] = result.get("scenes_count", 0)
            job["duration_seconds"] = result.get("duration_seconds", 0.0)
            job["scenes"] = result.get("scenes", [])
        except Exception as e:
            job["status"] = "failed"
            job["error"] = str(e)
            job["current_stage"] = f"Failed: {str(e)}"

job_manager = JobManager()
