"""LangChain-backed `QueryExtractor` for PT-tuned structured extraction.

Takes a raw user query (colloquial, possibly typo'd, mixed-language)
and returns a `ParsedQuery` carrying typology, structural facets,
price/area ranges, boolean amenities, closed-vocabulary POI
categories, and a `free_text_remainder` capturing everything left.

Mirrors the existing `PortugalAddressSearcher` pattern
(`src/listings/adapters/ai/portugal_address_searcher.py`):
LangChain's `with_structured_output` requires a Pydantic BaseModel
class — NOT a frozen dataclass — so we use an internal
`_ExtractorResult` envelope and map to the domain `ParsedQuery`
after the LLM returns.

The LLM is asked to extract **only what the user explicitly
mentioned**. Missing fields stay null. Negation is conservatively
ignored ("não preciso de piscina" → has_pool=null, NOT False).
Off-vocabulary POIs ("cabeleireiro") get dropped from
`nearby_pois` and pushed into `free_text_remainder`.

Worked examples in the prompt (~10) cover:
- typology + bedroom count + amenity + POI:
  "casa T3 com piscina perto de escola"
- colloquial qualifier + off-vocab feature:
  "T2 jeitoso com varanda em Cascais"
- list-style POI-only:
  "ginásio escola supermercado"
- negation:
  "não preciso de piscina"
- off-vocab POI:
  "casa perto de cabeleireiro"

Spec: `2026-05-listing-search-structured-extraction` §4.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from listings.application.ports.query_extractor import QueryExtractor
from listings.domain.models import Typology
from listings.domain.parsed_query import ParsedQuery
from listings.domain.poi_category import PoiCategory

log = structlog.get_logger()


_SYSTEM_PROMPT = """You extract structured filters from a Portuguese real-estate
search query.

CLOSED VOCABULARIES — map surface forms onto these enum values only:

TYPOLOGY (one of these or null):
- "house"     ← casa, moradia, vivenda
- "apartment" ← apartamento, T0/T1/T2/T3/T4 etc. (T-number → set min_bedrooms)
- "land"      ← terreno, lote
- "ruin"      ← ruína

POI CATEGORIES (in `nearby_pois`; PT surface forms map to these strings):
- "school"          ← escola, primária, colégio, secundária, ensino
- "kindergarten"    ← creche, infantário, jardim de infância
- "library"         ← biblioteca
- "hospital"        ← hospital, centro de saúde, clínica
- "pharmacy"        ← farmácia
- "gym"             ← ginásio, academia
- "park"            ← parque, jardim público
- "restaurant"      ← restaurante
- "coffee_shop"     ← café, pastelaria
- "bakery"          ← padaria
- "grocery"         ← supermercado, mercearia, mini-mercado, talho (best fit)
- "shopping_mall"   ← centro comercial, shopping
- "bank"            ← banco, MB, multibanco
- "post_office"     ← correios, CTT
- "police_station"  ← esquadra, polícia, GNR, PSP
- "public_transit"  ← metro, autocarro, comboio, paragem, estação
- "gas_station"     ← bomba, posto de combustível
- "laundry"         ← lavandaria
- "tire_shop"       ← pneus
- "auto_shop"       ← oficina, mecânica

RULES
- Extract ONLY what the user explicitly mentioned. Missing fields stay null.
- No genre-defaults ("families want gardens" → has_garden=true is FORBIDDEN).
- No hallucination of features the user didn't mention.
- Treat negation conservatively: "não preciso de piscina" → has_pool=null
  (NOT false). Polarity parsing is out of scope.
- T-number → min_bedrooms: "T2" → min_bedrooms=2; "T3" → min_bedrooms=3.
- "X quartos" or "X bedrooms" → min_bedrooms=X.
- Price: "até 500k" / "menos de 500.000" → max_price=500000.
  "a partir de 250k" → min_price=250000.
- Area: "pelo menos 100m²" → min_area_m2=100. "até 200m²" → max_area_m2=200.
- When a POI surface form doesn't map cleanly (e.g. "cabeleireiro",
  "talho", "florista"): OMIT it from nearby_pois AND include the
  surface form in free_text_remainder so cosine can do something.
- `free_text_remainder` carries everything left after extraction:
  colloquial qualifiers ("jeitoso" / "bom estado"), off-vocabulary
  features ("varanda"), off-vocab POIs. STRIP filler ("uma", "que
  tenha", "pra", "na zona de").

EXAMPLES

Input:  "casa T3 com piscina perto de escola"
Output: typology="house", min_bedrooms=3, has_pool=true,
        nearby_pois=["school"], free_text_remainder=""

Input:  "T2 jeitoso com varanda em Cascais"
Output: typology="apartment", min_bedrooms=2,
        nearby_pois=[], free_text_remainder="varanda, em bom estado"
        (location "Cascais" comes from the FE selector; never extract
        location into nearby_pois or any other field)

Input:  "ginásio escola supermercado"
Output: nearby_pois=["gym", "school", "grocery"], free_text_remainder=""

Input:  "não preciso de piscina"
Output: has_pool=null, free_text_remainder="não preciso de piscina"

Input:  "casa perto de cabeleireiro"
Output: typology="house", nearby_pois=[],
        free_text_remainder="perto de cabeleireiro"

Input:  "apartamento com jardim até 500k"
Output: typology="apartment", has_garden=true, max_price=500000,
        nearby_pois=[], free_text_remainder=""
"""


class _ExtractorResult(BaseModel):
    """Internal LLM-output envelope. Field-for-field mirror of
    `ParsedQuery` — see the comment on the domain dataclass for
    semantic meaning. `list` instead of `tuple` because Pydantic's
    JSON-schema generation for structured output prefers list types.
    """

    free_text_remainder: str = ""
    typology: Typology | None = None
    min_bedrooms: int | None = None
    min_bathrooms: int | None = None
    min_area_m2: int | None = None
    max_area_m2: int | None = None
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    has_pool: bool | None = None
    has_garden: bool | None = None
    has_elevator: bool | None = None
    has_parking: bool | None = None
    nearby_pois: list[PoiCategory] = []


class LangChainQueryExtractor(QueryExtractor):
    def __init__(
        self,
        *,
        model: str,
        openai_api_key: str,
        timeout_seconds: float,
        max_output_tokens: int,
    ) -> None:
        self._llm = ChatOpenAI(
            model=model,
            api_key=openai_api_key,
            temperature=0,
            max_tokens=max_output_tokens,
        ).with_structured_output(_ExtractorResult)
        self._timeout_seconds = timeout_seconds

    async def extract(self, query: str) -> ParsedQuery:
        try:
            result = await asyncio.wait_for(
                self._llm.ainvoke(
                    [
                        SystemMessage(content=_SYSTEM_PROMPT),
                        HumanMessage(content=query),
                    ]
                ),
                timeout=self._timeout_seconds,
            )
        except Exception:
            log.exception("query_extractor.langchain.failed", query=query)
            raise

        r: _ExtractorResult = result  # type: ignore[assignment]
        return ParsedQuery(
            free_text_remainder=r.free_text_remainder,
            typology=r.typology,
            min_bedrooms=r.min_bedrooms,
            min_bathrooms=r.min_bathrooms,
            min_area_m2=r.min_area_m2,
            max_area_m2=r.max_area_m2,
            min_price=r.min_price,
            max_price=r.max_price,
            has_pool=r.has_pool,
            has_garden=r.has_garden,
            has_elevator=r.has_elevator,
            has_parking=r.has_parking,
            nearby_pois=tuple(r.nearby_pois),
        )
