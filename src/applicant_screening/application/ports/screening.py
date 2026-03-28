from abc import ABC, abstractmethod

from applicant_screening.domain.models import Applicant, ExtractedData, ScreeningReport


class ScreeningAssessor(ABC):
    @abstractmethod
    async def assess(self, applicant: Applicant, extracted_data: list[ExtractedData]) -> ScreeningReport: ...
