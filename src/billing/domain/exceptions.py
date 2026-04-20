class DomainError(Exception):
    pass


class SubscriptionNotFoundError(DomainError):
    def __init__(self, identifier: str = "") -> None:
        super().__init__(
            f"Subscription not found: {identifier}" if identifier else "Subscription not found"
        )


class UnknownStripePriceError(DomainError):
    def __init__(self, price_id: str = "") -> None:
        super().__init__(
            f"Unknown Stripe price id: {price_id}" if price_id else "Unknown Stripe price id"
        )


class BillingCustomerMissingError(DomainError):
    def __init__(self) -> None:
        super().__init__("Organization has no Stripe customer — start a checkout session first")
