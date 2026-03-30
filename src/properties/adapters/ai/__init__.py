import functools
import logging

logger = logging.getLogger(__name__)


@functools.cache
def get_langfuse_handler():
    """Lazily build and cache a single Langfuse CallbackHandler."""
    try:
        from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler

        return LangfuseCallbackHandler()
    except Exception:
        logger.warning("langfuse_init_failed", exc_info=True)
        return None
