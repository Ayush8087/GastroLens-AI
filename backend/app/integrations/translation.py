import json
import logging

import httpx
from pydantic import SecretStr

from app.schemas.restaurant_search import MenuItem

logger = logging.getLogger(__name__)


class OpenAITranslationProvider:
    endpoint = "https://api.openai.com/v1/chat/completions"

    def __init__(
        self,
        api_key: SecretStr | None,
        *,
        model: str = "gpt-4o-mini",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.client = client

    async def translate(self, items: list[MenuItem], language: str) -> bool:
        if not items:
            return True
        if self.api_key is None or not self.api_key.get_secret_value().strip():
            return False
        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Translate menu item text faithfully. Return JSON with a "
                        "translations array "
                        "in the same order. Do not add ingredients, dietary claims, or prices."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "target_language": language,
                            "items": [item.original_text for item in items],
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        }
        owns_client = self.client is None
        client = (
            self.client
            if self.client is not None
            else httpx.AsyncClient(timeout=httpx.Timeout(15.0), trust_env=False)
        )
        try:
            response = await client.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {self.api_key.get_secret_value()}"},
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            decoded = json.loads(content)
            translations = decoded.get("translations") if isinstance(decoded, dict) else None
            if not isinstance(translations, list) or len(translations) != len(items):
                return False
            for item, translated in zip(items, translations, strict=True):
                if isinstance(translated, str) and 0 < len(translated) <= 400:
                    item.translated_text = translated
                else:
                    return False
            return True
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            logger.info("translation_unavailable", extra={"error_type": type(exc).__name__})
            return False
        finally:
            if owns_client:
                await client.aclose()
