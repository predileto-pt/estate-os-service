from abc import ABC, abstractmethod

from booking_management.domain.models.applicant import BookingApplicant


class BookingApplicantRepository(ABC):
    @abstractmethod
    async def create(self, applicant: BookingApplicant) -> BookingApplicant: ...

    @abstractmethod
    async def find_by_external_id(self, external_id: str) -> BookingApplicant | None: ...

    @abstractmethod
    async def find_by_supabase_user_id(self, supabase_user_id: str) -> BookingApplicant | None: ...

    @abstractmethod
    async def link_supabase_account(self, applicant_id: str, supabase_user_id: str) -> None: ...
