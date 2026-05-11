"""LangChain-backed `QueryUnderstandingService` for PT-tuned query
understanding.

Takes a raw user query (colloquial, possibly typo'd, mixed-language)
and returns a canonical retrieval form that aligns with the
canonical-text composer's PT vocabulary (`NEARBY:`, `FEATURES:`,
typology terms). Does NOT extract location — the user supplies that
structurally via the FE selector.

Worked examples (from the spec):

| Raw                                              | Rewritten                                       |
|--------------------------------------------------|-------------------------------------------------|
| "Uma casa com varanda que tenha uma academia perto" | "casa com varanda, perto de ginásio"           |
| "T2 jeitoso na zona de cascais com piscina"      | "apartamento T2 em Cascais com piscina, em bom estado" |
| "casa pra família grande com jardim e perto de escola" | "casa familiar com jardim, perto de escolas" |
| "ginasio escola supermercado"                    | "perto de ginásio, escola, supermercado"        |

Spec: `2026-05-listing-semantic-search-read-path` §"Components to
build" #2 and §`QueryUnderstandingService` — the prompt for better
retrieval.
"""

from __future__ import annotations

import asyncio

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from listings.application.ports.query_understanding import QueryUnderstandingService

log = structlog.get_logger()


_SYSTEM_PROMPT = """You rewrite a Portuguese real-estate search query into a canonical
retrieval form that aligns with how listings are described in the index.

INPUT
A single free-text PT real-estate query from a user. May contain:
- colloquialisms ("jeitoso", "pra", "que tenha")
- typos / missing accents ("ginasio" → "ginásio")
- mixed casing
- typology shorthand ("T2", "T3")
- list-style queries ("ginasio escola supermercado")

OUTPUT
A short, canonical PT phrase suitable for embedding. Specifically:
- Normalize colloquialisms ("jeitoso" → "em bom estado") and strip
  filler ("uma", "que tenha", "pra").
- Expand intent ("família grande" → "familiar"); surface implicit
  features.
- Normalize synonyms toward the canonical-text vocabulary
  ("academia" → "ginásio", "casa de banho" stays the same).
- Use comma-separated phrases for list-style queries ("ginasio escola
  supermercado" → "perto de ginásio, escola, supermercado").
- Typology: "T0/T1/T2/..." stays as-is; "apartamento" / "casa" /
  "terreno" / "ruína" are the canonical typology terms.
- "perto de X" is the canonical proximity phrase (matches the
  canonical-text `NEARBY:` line).

DO NOT
- Extract location (parish/municipality/district). The user supplies
  location structurally; never mention specific neighbourhoods,
  parishes, municipalities, or districts in the rewrite.
- Add features the user did not mention (no hallucinated "varanda",
  "piscina", "garagem" etc.).
- Translate to English. Output stays in PT.
- Quote the user back verbatim if the query is already canonical;
  return it unchanged.

EXAMPLES

Input:  "Uma casa com varanda que tenha uma academia perto"
Output: "casa com varanda, perto de ginásio"

Input:  "T2 jeitoso na zona de cascais com piscina"
Output: "apartamento T2 com piscina, em bom estado"

Input:  "casa pra família grande com jardim e perto de escola"
Output: "casa familiar com jardim, perto de escolas"

Input:  "ginasio escola supermercado"
Output: "perto de ginásio, escola, supermercado"
"""


class _RewriteResult(BaseModel):
    rewritten: str


class LangChainQueryUnderstandingService(QueryUnderstandingService):
    """LLM-backed PT query rewriter.

    `timeout_seconds` bounds the underlying LLM call; on timeout or
    error, the call raises and the calling use case
    (`SearchListings`) falls back to the raw query.
    """

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
        ).with_structured_output(_RewriteResult)
        self._timeout_seconds = timeout_seconds

    async def rewrite(self, query: str) -> str:
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
            log.exception("query_understanding.langchain.failed", query=query)
            raise

        parsed: _RewriteResult = result  # type: ignore[assignment]
        return parsed.rewritten
