class PropertyNotFoundError(Exception):
    def __init__(self, property_id: str) -> None:
        super().__init__(f"Property not found: {property_id}")
