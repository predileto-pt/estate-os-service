from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt


@dataclass(frozen=True)
class BookingTokenClaims:
    applicant_id: str
    property_id: str
    organization_id: str
    email: str


def generate_booking_token(
    secret: str,
    applicant_id: str,
    property_id: str,
    organization_id: str,
    email: str,
    ttl: timedelta = timedelta(days=7),
) -> tuple[str, datetime]:
    expires_at = datetime.now(timezone.utc) + ttl
    payload = {
        "applicant_id": applicant_id,
        "property_id": property_id,
        "organization_id": organization_id,
        "email": email,
        "type": "booking_invitation",
        "exp": expires_at,
        "iat": datetime.now(timezone.utc),
    }
    token = jwt.encode(payload, secret, algorithm="HS256")
    return token, expires_at


def validate_booking_token(secret: str, token_str: str) -> BookingTokenClaims:
    payload = jwt.decode(token_str, secret, algorithms=["HS256"])

    if payload.get("type") != "booking_invitation":
        raise jwt.InvalidTokenError("Token is not a booking invitation")

    return BookingTokenClaims(
        applicant_id=payload["applicant_id"],
        property_id=payload["property_id"],
        organization_id=payload["organization_id"],
        email=payload["email"],
    )
