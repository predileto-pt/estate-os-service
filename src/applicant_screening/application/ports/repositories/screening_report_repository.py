from abc import ABC, abstractmethod
from uuid import UUID

from applicant_screening.domain.models import ScreeningReport


class ScreeningReportRepository(ABC):
    @abstractmethod
    async def save(self, report: ScreeningReport) -> ScreeningReport: ...

    @abstractmethod
    async def get_by_applicant_id(self, applicant_id: UUID) -> ScreeningReport | None: ...
