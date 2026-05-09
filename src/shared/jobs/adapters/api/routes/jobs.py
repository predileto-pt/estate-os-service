from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from identity.domain.models.user import User
from organizations.domain.models.membership import Membership
from shared.api.dependencies import require_org_member
from shared.jobs.adapters.api.schemas import JobResponse
from shared.jobs.domain.job import Job, JobEntityType, JobKind, JobStatus

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _job_response(job: Job) -> dict:
    return {
        "id": job.id,
        "organization_id": job.organization_id,
        "requested_by_user_id": job.requested_by_user_id,
        "kind": job.kind,
        "status": job.status,
        "entity_type": job.entity_type,
        "entity_id": job.entity_id,
        "title": job.title,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "result_summary": job.result_summary,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def _parse_statuses(raw: str | None) -> list[JobStatus] | None:
    if not raw:
        return None
    out: list[JobStatus] = []
    for piece in raw.split(","):
        piece = piece.strip()
        if not piece:
            continue
        try:
            out.append(JobStatus(piece))
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid status filter: {piece}",
            )
    return out or None


@router.get(
    "/",
    response_model=list[JobResponse],
    summary="List background jobs for an organization",
    description=(
        "Returns the most recent jobs scoped to the caller's organization, "
        "ordered by `created_at` descending. Filter by `status` (comma-"
        "separated), `kind`, `entity_type`, `entity_id`. No pagination — "
        "callers ask for the last N (default 10, max 50)."
    ),
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Not a member of this organization"},
    },
)
async def list_jobs(
    organization_id: UUID,
    request: Request,
    status: str | None = Query(default=None),
    kind: JobKind | None = Query(default=None),
    entity_type: JobEntityType | None = Query(default=None),
    entity_id: UUID | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=50),
    _member: tuple[User, Membership] = Depends(require_org_member),
):
    statuses = _parse_statuses(status)
    use_case = request.app.state.jobs_container.list_jobs
    jobs = await use_case.execute(
        organization_id=organization_id,
        statuses=statuses,
        kind=kind,
        entity_type=entity_type,
        entity_id=entity_id,
        limit=limit,
    )
    return [_job_response(j) for j in jobs]


@router.get(
    "/{job_id}",
    response_model=JobResponse,
    summary="Get a single background job",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Not a member of this organization"},
        404: {"description": "Job not found (or belongs to a different organization)"},
    },
)
async def get_job(
    job_id: UUID,
    organization_id: UUID,
    request: Request,
    _member: tuple[User, Membership] = Depends(require_org_member),
):
    use_case = request.app.state.jobs_container.get_job
    job = await use_case.execute(job_id)
    # Cross-org existence-leak prevention: 404, not 403, when the row
    # exists but belongs to another org. Same shape as 'not found'.
    if job is None or job.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_response(job)
