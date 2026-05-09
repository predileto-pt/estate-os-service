class JobNotFoundError(Exception):
    """Raised when a Job lookup by id returns no row."""

    def __init__(self, job_id: str) -> None:
        super().__init__(f"Job not found: {job_id}")
        self.job_id = job_id


class InvalidJobTransitionError(Exception):
    """Raised when a Job state transition is illegal — e.g. complete after
    fail, or update_entity_id after termination."""
