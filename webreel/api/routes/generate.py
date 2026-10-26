import uuid
import asyncio
from fastapi import APIRouter, BackgroundTasks, HTTPException
from ..models.job import GenerateVideoRequest, JobStatusResponse
from ..services.queue import job_manager

router = APIRouter()

@router.post("/generate", response_model=JobStatusResponse)
async def generate_video(req: GenerateVideoRequest, background_tasks: BackgroundTasks):
    target_url = req.url.strip()
    if not target_url:
        raise HTTPException(status_code=400, detail="Target URL cannot be empty.")

    job_id = str(uuid.uuid4())[:8]
    job_data = job_manager.create_job(job_id=job_id, url=target_url)

    # Launch generation in background
    background_tasks.add_task(job_manager.execute_job, job_id)

    return JobStatusResponse(
        job_id=job_id,
        status="pending",
        progress_percent=0,
        current_stage="Job initiated. Browser agent preparing...",
        url=target_url
    )
