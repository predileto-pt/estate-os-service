from typing import Any

import structlog
from langchain_openai import ChatOpenAI
from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler

logger = structlog.get_logger()

SYSTEM_PROMPT = "Translate the following text to {target_language}. Preserve formatting. Return only the translation."


class LangChainTranslator:
    def __init__(self, openai_api_key: str) -> None:
        self._llm = ChatOpenAI(model="gpt-5-mini", api_key=openai_api_key, temperature=0)  # type: ignore[arg-type]

    @staticmethod
    def _langfuse_config(*, step_name: str) -> dict[str, Any]:
        handler = LangfuseCallbackHandler()
        metadata: dict[str, Any] = {"langfuse_tags": ["translation", step_name]}
        return {"callbacks": [handler], "run_name": step_name, "metadata": metadata}

    async def translate(self, text: str, target_language: str) -> str:
        config = self._langfuse_config(step_name="translate_justification")
        messages = [
            ("system", SYSTEM_PROMPT.format(target_language=target_language)),
            ("human", text),
        ]
        response = await self._llm.ainvoke(messages, config=config)  # type: ignore[arg-type]
        return str(response.content)
