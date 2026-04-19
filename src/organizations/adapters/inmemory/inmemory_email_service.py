from dataclasses import dataclass

from customers.application.ports.email_service import EmailService


@dataclass
class SentEmail:
    to: str
    subject: str
    html: str
    from_email: str


class InMemoryEmailService(EmailService):
    def __init__(self) -> None:
        self.sent_emails: list[SentEmail] = []

    async def send(
        self,
        *,
        to: str,
        subject: str,
        html: str,
        from_email: str = "noreply@predileto.pt",
    ) -> None:
        self.sent_emails.append(SentEmail(to=to, subject=subject, html=html, from_email=from_email))
