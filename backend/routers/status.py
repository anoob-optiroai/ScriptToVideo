"""
Job status router — poll this to track background task progress.
"""
from fastapi import APIRouter, HTTPException
from job_store import job_store

router = APIRouter()


@router.get("/{job_id}")
def get_status(job_id: str):
    """Poll job progress. Returns status, progress (0-100), message, and result when done."""
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job.job_id,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "result": job.result,
        "error": job.error,
    }


@router.get("/")
def list_jobs():
    """List all jobs (useful for debugging)."""
    jobs = job_store.all()
    return [
        {
            "job_id": jid,
            "status": j.status,
            "progress": j.progress,
            "created_at": j.created_at,
        }
        for jid, j in jobs.items()
    ]
