import resend
import structlog

from customers.application.ports.email_service import EmailService

log = structlog.get_logger()


class ResendEmailService(EmailService):
    def __init__(self, api_key: str) -> None:
        resend.api_key = api_key

    async def send(
        self,
        *,
        to: str,
        subject: str,
        html: str,
        from_email: str = "noreply@predileto.pt",
    ) -> None:
        resend.Emails.send(
            {
                "from": from_email,
                "to": [to],
                "subject": subject,
                "html": html,
            }
        )
        log.info("email_sent", to=to, subject=subject)
