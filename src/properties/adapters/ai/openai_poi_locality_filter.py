"""LangChain + GPT-5-mini implementation of `PoiLocalityFilter`.

Structured output with one boolean per candidate. The model only sees
each POI's `name` + provider-returned `address` and the property's own
free-text address — enough to answer "same municipality / same city?"
without us pre-extracting the property's administrative components.
The PT prompt nudges the model toward `concelho` reasoning; the
generic prompt asks for city.

Failure handling: any exception falls open (returns every candidate).
A flaky LLM should not silently erase POIs the agent expected to see.
"""

from __future__ import annotations

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from properties.application.ports.poi_locality_filter import (
    PoiCandidate,
    PoiLocalityFilter,
)
from properties.domain.services.locality_scope import LocalityKind

log = structlog.get_logger()


_SYSTEM_PROMPT_PT = """You decide which points-of-interest (POIs) share
the SAME PORTUGUESE MUNICIPALITY (concelho) as a real-estate property.

INPUT
- A property's free-text address in Portugal.
- A list of POIs, each with `name` and `address`.

TASK
For each POI, return `is_same_locality=true` if its address resolves
to the same `concelho` (municipality) as the property's address.
Return `false` only when you can clearly see the POI is in a
DIFFERENT municipality (e.g. property in "Lisboa" and POI address says
"Oeiras", "Loures", "Cascais", "Sintra", "Almada", "Amadora" — all
distinct concelhos despite the metropolitan-area overlap).

RULES
- Concelho, NOT freguesia: a POI in a different freguesia of the same
  concelho is `true`.
- A property in concelho-and-district names that overlap (Lisboa,
  Porto, Coimbra, Aveiro, Braga, Évora, Faro, Beja, Castelo Branco,
  Guarda, Leiria, Portalegre, Santarém, Setúbal, Viana do Castelo,
  Vila Real, Viseu, Bragança) refers to the concelho — match by that.
- When the POI address is empty, ambiguous, or mentions only a street
  name with no city/concelho, default to `true`. Dropping a real
  match is worse than keeping a cross-boundary one.
- Return one verdict per POI in the SAME ORDER as the input list."""


_SYSTEM_PROMPT_GENERIC = """You decide which points-of-interest (POIs)
share the SAME CITY as a real-estate property.

INPUT
- A property's free-text address.
- A list of POIs, each with `name` and `address`.

TASK
For each POI, return `is_same_locality=true` if its address is in the
same CITY as the property's address. Return `false` only when you can
clearly see the POI is in a DIFFERENT city.

RULES
- A POI in a different neighborhood of the same city is `true`.
- When the POI address is empty, ambiguous, or only mentions a street
  name with no city, default to `true`. Dropping a real match is
  worse than keeping a cross-boundary one.
- Return one verdict per POI in the SAME ORDER as the input list."""


class _CandidateVerdict(BaseModel):
    """The model returns one of these per candidate, parallel to the
    input list. `place_id` is echoed back so we can detect ordering
    drift defensively."""

    place_id: str = Field(description="The candidate's place_id, echoed unchanged.")
    is_same_locality: bool = Field(
        description="True when the POI sits in the same locality as the property."
    )


class _BatchVerdict(BaseModel):
    verdicts: list[_CandidateVerdict]


class OpenAiPoiLocalityFilter(PoiLocalityFilter):
    """Default `PoiLocalityFilter` impl: one batched LLM call per
    property. Fails open — any exception keeps every candidate."""

    def __init__(self, *, openai_api_key: str, model: str = "gpt-5-mini") -> None:
        self._llm = ChatOpenAI(
            model=model,
            api_key=openai_api_key,
            temperature=0,
        ).with_structured_output(_BatchVerdict)

    async def keep_in_locality(
        self,
        *,
        property_address: str,
        country: str,
        locality_kind: LocalityKind,
        candidates: list[PoiCandidate],
    ) -> list[PoiCandidate]:
        if not candidates:
            return []

        system_prompt = (
            _SYSTEM_PROMPT_PT
            if locality_kind is LocalityKind.MUNICIPALITY
            else _SYSTEM_PROMPT_GENERIC
        )
        user_message = self._format_user_message(property_address, country, candidates)

        try:
            result = await self._llm.ainvoke(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_message),
                ]
            )
        except Exception:
            log.exception(
                "poi_locality_filter.llm_failed_keeping_all",
                country=country,
                candidate_count=len(candidates),
            )
            return list(candidates)

        # Index by place_id so we tolerate the model reordering or
        # dropping rows. Missing rows default to KEEP — fail-open is
        # the same invariant as the exception path above.
        verdicts: dict[str, bool] = {
            v.place_id: v.is_same_locality for v in result.verdicts  # type: ignore[union-attr]
        }
        kept = [c for c in candidates if verdicts.get(c.place_id, True)]

        log.info(
            "poi_locality_filter.batch_done",
            country=country,
            locality_kind=locality_kind.value,
            input_count=len(candidates),
            kept_count=len(kept),
            dropped_count=len(candidates) - len(kept),
        )
        return kept

    @staticmethod
    def _format_user_message(
        property_address: str,
        country: str,
        candidates: list[PoiCandidate],
    ) -> str:
        lines = [
            f"PROPERTY COUNTRY: {country}",
            f"PROPERTY ADDRESS: {property_address}",
            "",
            "POIs:",
        ]
        for c in candidates:
            address = c.address.strip() or "(no address provided)"
            lines.append(f"- place_id={c.place_id} | name={c.name} | address={address}")
        return "\n".join(lines)
