from abc import ABC, abstractmethod


class EmailService(ABC):
    @abstractmethod
    async def send(
        self,
        *,
        to: str,
        subject: str,
        html: str,
        from_email: str = "noreply@predileto.pt",
    ) -> None: ...
