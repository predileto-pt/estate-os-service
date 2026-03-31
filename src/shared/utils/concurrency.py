import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")


async def gather_with_concurrency(
    limit: int,
    *coros: Coroutine[Any, Any, T],
) -> list[T]:
    """Run coroutines concurrently with a max concurrency limit.

    Uses an asyncio.Semaphore to cap how many coroutines execute
    simultaneously.  Safe to call from any async context — does not
    create new event loops or threads.  The semaphore is scoped to
    this invocation so concurrent callers do not interfere.

    Args:
        limit: Maximum number of coroutines executing at the same time.
        *coros: The coroutines to run.

    Returns:
        A list of results in the same order as the input coroutines.
    """
    semaphore = asyncio.Semaphore(limit)

    async def _sem_task(coro: Coroutine[Any, Any, T]) -> T:
        async with semaphore:
            return await coro

    return list(await asyncio.gather(*(_sem_task(c) for c in coros)))
