class SlotNotFoundError(Exception):
    def __init__(self, slot_id: str) -> None:
        super().__init__(f"Slot {slot_id} not found")
        self.slot_id = slot_id


class SlotNotAvailableError(Exception):
    def __init__(self, slot_id: str) -> None:
        super().__init__(f"Slot {slot_id} is not available")
        self.slot_id = slot_id


class BookingNotFoundError(Exception):
    def __init__(self, booking_id: str) -> None:
        super().__init__(f"Booking {booking_id} not found")
        self.booking_id = booking_id


class BookingNotCancellableError(Exception):
    def __init__(self, booking_id: str) -> None:
        super().__init__(f"Booking {booking_id} cannot be cancelled")
        self.booking_id = booking_id


class ApplicantRiskTooHighError(Exception):
    def __init__(self, applicant_id: str) -> None:
        super().__init__(f"Applicant {applicant_id} has HIGH risk level")
        self.applicant_id = applicant_id


class ForbiddenError(Exception):
    def __init__(self, message: str = "Not authorized") -> None:
        super().__init__(message)
