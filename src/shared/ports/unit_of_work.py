from abc import ABC, abstractmethod


class UnitOfWork(ABC):
    """Base Unit of Work port.

    Provides a transaction boundary for services. Use as an async context
    manager — rollback is automatic on unhandled exceptions.

    Each bounded context defines its own subclass that exposes the
    repositories relevant to that context as attributes.
    """

    @abstractmethod
    async def commit(self) -> None: ...

    @abstractmethod
    async def rollback(self) -> None: ...

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            await self.rollback()
