"""Portugal-specific AddressSearcher: LangChain + GPT.

Replaces the previous `LangChainAddressParser`. The PT prompt is a
country-specific implementation detail — it is tuned to PT geography
(postal-code prefix table, cities-that-are-also-districts list, parish
/ municipality / district vocabulary). Future per-country searchers
will carry their own prompts.

Spec: `2026-05-property-address-enrichment-fix.md` §AddressSearcher.
"""

from __future__ import annotations

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from listings.application.ports.address_searcher import AddressSearcher, ParsedAddress

log = structlog.get_logger()


_SYSTEM_PROMPT = """You parse Portuguese real-estate addresses into structured components:
parish (freguesia), municipality (concelho), district (distrito).

INPUT FORMAT
You receive two pieces of information from the user message:
  ADDRESS:     <free-text street address as the agent typed it>
  POSTAL CODE: <NNNN-NNN format, or "unknown" if it could not be
                extracted from the address>

The postal code (when known) is the most authoritative signal for
parish/municipality/district — use it to anchor your answer and use
the address text only to disambiguate.

OUTPUT
ALL THREE fields MUST be populated. NEVER return null.

Cities that are simultaneously municipality AND district names
(assign both fields the same value when the address or postal code
resolves to any of them):
  Lisboa, Porto, Coimbra, Aveiro, Braga, Évora, Faro, Beja,
  Castelo Branco, Guarda, Leiria, Portalegre, Santarém, Setúbal,
  Viana do Castelo, Vila Real, Viseu, Bragança.

Postal-code prefix → district (first digit):
  1xxx → Lisboa, 2xxx → Setúbal/Santarém/Lisboa region, 3xxx → Coimbra,
  4xxx → Porto, 5xxx → Vila Real/Bragança, 6xxx → Castelo Branco,
  7xxx → Évora/Beja, 8xxx → Faro, 9xxx → Madeira/Açores.

Examples:
- ADDRESS: "Arca, Ponte de Lima, Viana do Castelo" / POSTAL CODE: unknown
  → parish="Arca", municipality="Ponte de Lima",
    district="Viana do Castelo"
- ADDRESS: "Rua Augusta 1, Lisboa" / POSTAL CODE: 1100-001
  → parish="Santa Maria Maior", municipality="Lisboa",
    district="Lisboa"
- ADDRESS: "Rua A" / POSTAL CODE: 4000-001
  → parish="(best guess from postal-code area)", municipality="Porto",
    district="Porto"

If the address is genuinely unparseable AND the postal code is
"unknown" (no city, no postal code, no recognizable Portuguese place),
refuse — do not invent values that aren't supported by either signal."""


class _PortugalLLMResult(BaseModel):
    """Internal model the LLM is asked to fill. Non-optional PT fields
    so a `ValidationError` raises if the model returns null on any of
    them — the handler turns that into the existing DLQ-then-Logfire
    failure path."""

    parish: str
    municipality: str
    district: str


class PortugalAddressSearcher(AddressSearcher):
    """PT implementation: LangChain + GPT, returns a `ParsedAddress`
    with `country='Portugal'` and non-null parish/municipality/district.
    """

    def __init__(self, *, model: str, openai_api_key: str) -> None:
        self._llm = ChatOpenAI(
            model=model,
            api_key=openai_api_key,
            temperature=0,
        ).with_structured_output(_PortugalLLMResult)

    async def search(
        self,
        *,
        address: str,
        postal_code: str | None,
        country: str,
    ) -> ParsedAddress:
        # `country` is supplied by the dispatcher; we only handle PT.
        # Defensive assertion — the dispatcher should never route a
        # non-PT call here.
        assert country == "Portugal", f"PortugalAddressSearcher invoked with country={country!r}"

        user_message = (
            f"ADDRESS: {address}\nPOSTAL CODE: {postal_code if postal_code else 'unknown'}"
        )

        log.info(
            "address_searcher.portugal.parsing",
            address=address,
            postal_code=postal_code,
        )
        try:
            result = await self._llm.ainvoke(
                [
                    SystemMessage(content=_SYSTEM_PROMPT),
                    HumanMessage(content=user_message),
                ]
            )
        except Exception:
            log.exception(
                "address_searcher.portugal.failed",
                address=address,
                postal_code=postal_code,
            )
            raise

        # `with_structured_output` returns _PortugalLLMResult directly.
        pt: _PortugalLLMResult = result  # type: ignore[assignment]
        # `postal_code` was an LLM input only (helps the model resolve
        # parish/municipality/district from the prefix). We don't carry
        # it on the returned envelope — it's not persisted on the row.
        return ParsedAddress(
            country="Portugal",
            parish=pt.parish,
            municipality=pt.municipality,
            district=pt.district,
        )
