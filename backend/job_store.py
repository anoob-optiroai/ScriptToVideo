"""
In-memory job store for tracking background tasks.
For production, replace with Redis or a database.
"""
import uuid
import time
from typing import Dict, Any, Optional
from dataclasses import dataclass, field


@dataclass
class Job:
    job_id: str
    status: str = "pending"       # pending | processing | done | error
    progress: int = 0             # 0–100
    message: str = ""
    result: Optional[Dict] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def update(self, status: str = None, progress: int = None, message: str = None,
               result: Dict = None, error: str = None):
        if status:
            self.status = status
        if progress is not None:
            self.progress = progress
        if message:
            self.message = message
        if result:
            self.result = result
        if error:
            self.error = error
            self.status = "error"
        self.updated_at = time.time()


class JobStore:
    def __init__(self):
        self._jobs: Dict[str, Job] = {}

    def create(self) -> Job:
        job_id = str(uuid.uuid4())
        job = Job(job_id=job_id)
        self._jobs[job_id] = job
        return job

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def all(self) -> Dict[str, Job]:
        return self._jobs

    def cleanup_old(self, max_age_seconds: int = 3600):
        """Remove jobs older than max_age_seconds."""
        cutoff = time.time() - max_age_seconds
        to_delete = [jid for jid, job in self._jobs.items() if job.created_at < cutoff]
        for jid in to_delete:
            del self._jobs[jid]


# Global singleton
job_store = JobStore()
