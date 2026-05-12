"""LangChain + GPT-4o-mini implementation of `DescriptionEnhancer`.

The adapter formats the `PropertyDescriptionContext` into a prompt
that asks the model to rewrite the description as polished real-estate
marketing copy — same language as the input, never inventing facts.
"""

from __future__ import annotations

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from properties.application.ports.description_enhancer import (
    DescriptionEnhancer,
    PropertyDescriptionContext,
)

log = structlog.get_logger()


_SYSTEM_PROMPT = """You are a senior real-estate copywriter rewriting a
property description for a public listing. The agent supplies the
current description plus structured facts about the property; you
return ONLY the improved description — no headers, no preamble, no
markdown fences, no quotes around it.

RULES
- Match the language of the input description. If the input is in
  Portuguese, respond in Portuguese; if in English, respond in English.
  If the description is empty, default to Portuguese.
- Write 2–4 short paragraphs. Each paragraph 1–4 sentences. Easy to
  scan on mobile.
- Lead with the strongest selling point inferred from the facts (e.g.
  "casa de campo com piscina e jardim", "T2 no centro com elevador").
- Weave in the supplied structured facts naturally — don't bullet them.
- NEVER invent details. If a fact (year built, view, neighborhood
  amenities) is not in the inputs, do not mention it. You may polish
  vague language ("nice area" → "área tranquila") only if the original
  description supports it.
- Avoid clichés ("must-see!", "dream home"). No emojis.
- Skip pricing, owner contact, agency name — those live elsewhere in
  the listing UI.
- If the input description is empty or near-empty, write a short
  factual description from the structured facts only.
"""


def _format_context(ctx: PropertyDescriptionContext) -> str:
    """Render the context as a compact, model-readable block."""
    lines: list[str] = []
    if ctx.title:
        lines.append(f"TITLE: {ctx.title}")
    if ctx.address:
        lines.append(f"ADDRESS: {ctx.address}")
    if ctx.listing_type:
        lines.append(f"LISTING TYPE: {ctx.listing_type}")
    if ctx.typology:
        lines.append(f"TYPOLOGY: {ctx.typology}")
    if ctx.area_in_m2 is not None:
        lines.append(f"AREA: {ctx.area_in_m2:g} m²")
    if ctx.num_of_bedrooms is not None:
        lines.append(f"BEDROOMS: {ctx.num_of_bedrooms}")
    if ctx.num_of_bathrooms is not None:
        lines.append(f"BATHROOMS: {ctx.num_of_bathrooms}")
    if ctx.has_pool:
        lines.append("FEATURE: pool")
    if ctx.has_garden:
        lines.append("FEATURE: garden")
    if ctx.has_elevator:
        lines.append("FEATURE: elevator")
    facts = "\n".join(lines) if lines else "(no structured facts available)"
    current = (ctx.current_description or "").strip() or "(no current description)"
    return f"STRUCTURED FACTS:\n{facts}\n\nCURRENT DESCRIPTION:\n{current}"


class LangChainDescriptionEnhancer(DescriptionEnhancer):
    """Default `DescriptionEnhancer` impl.

    Constructor accepts the model name so the env var
    `DESCRIPTION_ENHANCER_MODEL` can flip variants without code change.
    """

    def __init__(self, *, openai_api_key: str, model: str = "gpt-4o-mini") -> None:
        self._llm = ChatOpenAI(
            model=model,
            api_key=openai_api_key,
            temperature=0.5,
            # Bounded latency: the listing UX shouldn't hang on a slow LLM.
            timeout=30,
        )

    async def enhance(self, context: PropertyDescriptionContext) -> str:
        user_message = _format_context(context)
        try:
            result = await self._llm.ainvoke(
                [
                    SystemMessage(content=_SYSTEM_PROMPT),
                    HumanMessage(content=user_message),
                ]
            )
        except Exception:
            log.exception(
                "description_enhancer.llm_failed",
                has_current=bool(context.current_description),
            )
            raise

        content = result.content
        text = content if isinstance(content, str) else str(content)
        return text.strip()
