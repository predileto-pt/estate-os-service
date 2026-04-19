class PropertyNotFoundError(Exception):
    def __init__(self, property_id: str) -> None:
        super().__init__(f"Property not found: {property_id}")


class AddressParseError(Exception):
    """The address parser (LLM) failed to resolve a property's address.

    Raised by the enrichment handler; causes the shared `SQSWorker` to
    nack the enrichment event so SQS redelivers it up to
    `maxReceiveCount` before the message lands in the DLQ. The
    `property_listings` row is left in place with NULL location.
    """

    def __init__(self, address: str) -> None:
        super().__init__(f"Failed to parse address: {address!r}")
        self.address = address
