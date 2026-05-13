class PropertyNotFoundError(Exception):
    def __init__(self, property_id: str) -> None:
        super().__init__(f"Property not found: {property_id}")


class EmptyLocationFilterError(Exception):
    """A `LocationFilter` was constructed with all three levels None.

    The route handler's 422 guard exists so this never happens in
    practice; `LocationFilter.__post_init__` raises this as the
    last-line defense if the guard is bypassed. See spec
    `2026-05-listing-semantic-search-read-path` §"Required-location
    validation".
    """

    def __init__(self) -> None:
        super().__init__(
            "LocationFilter requires at least one of parish, municipality, district to be set."
        )


class AddressParseError(Exception):
    """The address parser (LLM) failed to resolve a property's address.

    Raised by the enrichment handler; causes the shared `EventBusWorker` to
    nack the enrichment event so the broker redelivers it up to the
    queue's delivery limit before the message lands in the DLQ. The
    `property_listings` row is left in place with NULL location.
    """

    def __init__(self, address: str) -> None:
        super().__init__(f"Failed to parse address: {address!r}")
        self.address = address
