"""LangChain-backed adapter for `AddressParser`.

Uses `ChatOpenAI(...).with_structured_output(ParsedAddress)` so the
pydantic shape enforces the response schema. Prompt is locked to
"Portuguese real estate addresses; output parish / municipality /
district; leave null if unknown".

Model pinned at instantiation time; the exact string is a settings
value (so we can change it without code deploys). The "gpt-5-mini
class" requirement from the spec is satisfied by the live value at
deploy time.
"""

from __future__ import annotations

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from listings.application.ports.address_parser import AddressParser, ParsedAddress

log = structlog.get_logger()

_SYSTEM_PROMPT = (
    "You parse Portuguese real-estate addresses into structured components: "
    "parish (freguesia), municipality (concelho), district (distrito). "
    "Examples:\n"
    "  'Arca, Ponte de Lima, Viana do Castelo' -> parish='Arca', "
    "municipality='Ponte de Lima', district='Viana do Castelo'.\n"
    "  'Rua Augusta 1, Lisboa' -> parish=null, municipality='Lisboa', "
    "district='Lisboa'.\n"
    "Leave a field null if the source address doesn't contain it. "
    "Do not invent values. Never guess when uncertain."
)


class LangChainAddressParser(AddressParser):
    def __init__(self, *, model: str, openai_api_key: str) -> None:
        self._llm = ChatOpenAI(
            model=model,
            api_key=openai_api_key,
            temperature=0,
        ).with_structured_output(ParsedAddress)

    async def parse(self, address: str) -> ParsedAddress:
        log.info("address_parser.parsing", address=address)
        try:
            result = await self._llm.ainvoke(
                [
                    SystemMessage(content=_SYSTEM_PROMPT),
                    HumanMessage(content=address),
                ]
            )
        except Exception:
            log.exception("address_parser.failed", address=address)
            raise
        # `with_structured_output` returns a ParsedAddress directly.
        return result  # type: ignore[return-value]
