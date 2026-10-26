from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from ..services.queue import job_manager

router = APIRouter()

@router.get("/download/{job_id}")
async def download_video(job_id: str, attachment: bool = Query(False)):
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    if job["status"] != "completed" or not job.get("video_path"):
        raise HTTPException(status_code=400, detail="Video is not ready yet.")

    video_path = Path(job["video_path"])
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video file missing on server.")

    filename = job.get("video_filename") or f"{job_id}_video.mp4"
    disposition = "attachment" if attachment else "inline"

    return FileResponse(
        path=str(video_path),
        media_type="video/mp4",
        filename=filename,
        headers={"Content-Disposition": f"{disposition}; filename=\"{filename}\""}
    )
