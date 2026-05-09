from __future__ import annotations

from shared.jobs.adapters.tracking.default_job_tracker import DefaultJobTracker
from shared.jobs.application.ports.job_repository import JobRepository
from shared.jobs.application.use_cases.get_job import GetJob
from shared.jobs.application.use_cases.list_jobs import ListJobs


class SharedJobsContainer:
    """Composition root for the shared `jobs` infrastructure module.

    Exposes:
    - `job_tracker` — the write port (concrete `DefaultJobTracker`)
      that producing-context containers inject.
    - `list_jobs` / `get_job` — the read use cases the API routes call.
    """

    def __init__(self, job_repo: JobRepository) -> None:
        self.job_repo = job_repo
        self.job_tracker = DefaultJobTracker(job_repo)
        self.list_jobs = ListJobs(job_repo)
        self.get_job = GetJob(job_repo)
