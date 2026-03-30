from abc import ABC, abstractmethod


class Translator(ABC):
    @abstractmethod
    async def translate(self, text: str, target_language: str) -> str: ...
