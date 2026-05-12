"""Port: LLM-backed property description rewrite.

A pure interface so the use case doesn't import OpenAI / LangChain.
The default adapter lives in `properties.adapters.ai.langchain_description_enhancer`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PropertyDescriptionContext:
    """The structured signals an enhancer can use to anchor the rewrite.

    Kept minimal on purpose — every field is optional except
    `current_description`. The adapter formats them into the prompt;
    new signals can be added without changing the use case shape.
    """

    current_description: str | None
    title: str | None = None
    address: str | None = None
    listing_type: str | None = None  # "sale" | "purchase"
    typology: str | None = None  # "house" | "apartment" | "land" | "ruin"
    area_in_m2: float | None = None
    num_of_bedrooms: int | None = None
    num_of_bathrooms: int | None = None
    has_pool: bool | None = None
    has_garden: bool | None = None
    has_elevator: bool | None = None


class DescriptionEnhancer(Protocol):
    """Rewrite a property's free-text description into polished marketing copy."""

    async def enhance(self, context: PropertyDescriptionContext) -> str:
        """Return the enhanced description.

        Implementations must not invent factual details beyond what the
        context provides. On LLM failure, raise — the use case decides
        the user-facing error.
        """
        ...
