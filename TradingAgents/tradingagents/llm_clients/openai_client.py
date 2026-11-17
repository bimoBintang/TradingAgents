import os
import re
from typing import Any, Optional

from langchain_openai import ChatOpenAI

from .base_client import BaseLLMClient
from .validators import validate_model


class UnifiedChatOpenAI(ChatOpenAI):
    """ChatOpenAI subclass that strips temperature/top_p for GPT-5 family models.

    GPT-5 family models use reasoning natively. temperature/top_p are only
    accepted when reasoning.effort is 'none'; with any other effort level
    (or for older GPT-5/GPT-5-mini/GPT-5-nano which always reason) the API
    rejects these params. Langchain defaults temperature=0.7, so we must
    strip it to avoid errors.

    Non-GPT-5 models (GPT-4.1, xAI, Ollama, etc.) are unaffected.
    """

    def __init__(self, **kwargs):
        if "gpt-5" in kwargs.get("model", "").lower():
            kwargs.pop("temperature", None)
            kwargs.pop("top_p", None)
        super().__init__(**kwargs)


_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)
_THINK_OPEN = re.compile(r"<think>.*\Z", re.DOTALL)  # cut off before </think>


def strip_think(text: str) -> str:
    """Remove deepseek-r1 style <think>...</think> reasoning (closed or truncated)."""
    if not isinstance(text, str) or "<think>" not in text:
        return text
    return _THINK_OPEN.sub("", _THINK_BLOCK.sub("", text)).strip()


class ThinkStrippingChatOpenAI(UnifiedChatOpenAI):
    """Ollama reasoning models put their chain of thought inline in the answer.
    Left in, it pollutes debate arguments and the text the execution engine parses
    for <TRADE_DECISION>. The raw text is kept in additional_kwargs["reasoning"]."""

    def _create_chat_result(self, response, generation_info=None):
        result = super()._create_chat_result(response, generation_info)
        for gen in result.generations:
            msg = gen.message
            if isinstance(msg.content, str) and "<think>" in msg.content:
                msg.additional_kwargs["reasoning"] = msg.content
                msg.content = strip_think(msg.content)
                gen.text = msg.content
        return result


class OpenAIClient(BaseLLMClient):
    """Client for OpenAI, Ollama, OpenRouter, and xAI providers."""

    def __init__(
        self,
        model: str,
        base_url: Optional[str] = None,
        provider: str = "openai",
        **kwargs,
    ):
        super().__init__(model, base_url, **kwargs)
        self.provider = provider.lower()

    def get_llm(self) -> Any:
        """Return configured ChatOpenAI instance."""
        llm_kwargs = {"model": self.model}

        if self.provider == "xai":
            llm_kwargs["base_url"] = "https://api.x.ai/v1"
            api_key = os.environ.get("XAI_API_KEY")
            if api_key:
                llm_kwargs["api_key"] = api_key
        elif self.provider == "openrouter":
            llm_kwargs["base_url"] = "https://openrouter.ai/api/v1"
            api_key = os.environ.get("OPENROUTER_API_KEY")
            if api_key:
                llm_kwargs["api_key"] = api_key
        elif self.provider == "ollama":
            # Env only: self.base_url is shared by every tier and may be another provider's URL.
            llm_kwargs["base_url"] = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
            llm_kwargs["api_key"] = "ollama"  # Ollama doesn't require auth
            if "deepseek-r1" in self.model.lower() and "temperature" not in self.kwargs:
                llm_kwargs["temperature"] = 0.6  # DeepSeek's recommended range is 0.5-0.7
        elif self.base_url:
            llm_kwargs["base_url"] = self.base_url

        for key in ("timeout", "max_retries", "reasoning_effort", "api_key", "callbacks", "http_client", "http_async_client"):
            if key in self.kwargs:
                llm_kwargs[key] = self.kwargs[key]

        cls = ThinkStrippingChatOpenAI if self.provider == "ollama" else UnifiedChatOpenAI
        return cls(**llm_kwargs)

    def validate_model(self) -> bool:
        """Validate model for the provider."""
        return validate_model(self.provider, self.model)
