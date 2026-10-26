from fastapi import APIRouter, HTTPException
from ..models.job import JobStatusResponse
from ..services.queue import job_manager

router = APIRouter()

@router.get("/status/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    video_url = f"/api/download/{job_id}" if job["status"] == "completed" else None
    download_url = f"/api/download/{job_id}?attachment=true" if job["status"] == "completed" else None

    return JobStatusResponse(
        job_id=job["job_id"],
        status=job["status"],
        progress_percent=job["progress_percent"],
        current_stage=job["current_stage"],
        url=job["url"],
        brand=job.get("brand"),
        video_url=video_url,
        download_url=download_url,
        scenes_count=job.get("scenes_count"),
        duration_seconds=job.get("duration_seconds"),
        scenes=job.get("scenes"),
        error=job.get("error")
    )
