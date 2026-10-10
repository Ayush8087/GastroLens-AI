from typing import Protocol


class LanguageModelProvider(Protocol):
    """Replaceable boundary for language-model providers such as OpenAI."""

    async def generate(self, prompt: str) -> str:
        """Generate a response; callers remain responsible for evidence validation."""
        ...
