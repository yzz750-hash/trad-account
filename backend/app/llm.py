import litellm
import logging
from pydantic import BaseModel
from typing import Optional, Any, AsyncGenerator

logger = logging.getLogger(__name__)

# Prevent LiteLLM from logging API keys in error messages
litellm.suppress_debug_info = True
litellm.set_verbose = False
os_module = __import__('os')
if not os_module.environ.get("LITELLM_LOG"):
    os_module.environ["LITELLM_LOG"] = "ERROR"


class LLMConfig(BaseModel):
    provider: str
    api_key: str
    model_name: str
    base_url: Optional[str] = None


def get_llm_response(
    prompt: str,
    config: LLMConfig,
    response_format: Optional[Any] = None,
    max_tokens: int = 4000,
    temperature: float = 0.1,
    timeout: float = 120.0,
) -> str:
    """
    Agnostic LLM Configuration Base.
    Wraps LiteLLM to dynamically call any provider based on the Ledger's configuration.
    """
    kwargs = {
        "model": f"{config.provider}/{config.model_name}",
        "messages": [{"role": "user", "content": prompt}],
        "api_key": config.api_key,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "timeout": timeout,
    }

    if config.base_url:
        kwargs["api_base"] = config.base_url

    if response_format:
        kwargs["response_format"] = response_format

    logger.info(
        "LLM call: provider=%s model=%s tokens=%d temp=%.2f timeout=%.0fs",
        config.provider, config.model_name, max_tokens, temperature, timeout,
    )

    try:
        response = litellm.completion(**kwargs)
    except Exception as exc:
        sanitized = str(exc)
        # Redact API key if it leaked into the error message
        if config.api_key and len(config.api_key) > 8 and config.api_key in sanitized:
            sanitized = sanitized.replace(config.api_key, "[REDACTED]")
        logger.error("LLM call failed: %s", sanitized)
        raise RuntimeError("LLM request failed") from None
    return response.choices[0].message.content


async def stream_llm_response(
    prompt: str,
    config: LLMConfig,
    messages: list[dict] | None = None,
    max_tokens: int = 4000,
    temperature: float = 0.1,
    timeout: float = 120.0,
) -> AsyncGenerator[str, None]:
    """
    Async streaming LLM response via LiteLLM.
    Yields token strings as they arrive.
    """
    if messages is not None:
        msgs = messages
    else:
        msgs = [{"role": "user", "content": prompt}]

    kwargs: dict[str, Any] = {
        "model": f"{config.provider}/{config.model_name}",
        "messages": msgs,
        "api_key": config.api_key,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "timeout": timeout,
        "stream": True,
    }

    if config.base_url:
        kwargs["api_base"] = config.base_url

    logger.info(
        "LLM stream: provider=%s model=%s tokens=%d",
        config.provider, config.model_name, max_tokens,
    )

    try:
        response = await litellm.acompletion(**kwargs)
        async for chunk in response:
            delta = chunk.choices[0].delta.content or ""
            if delta:
                # Redact potential API key leaks in stream
                if config.api_key and len(config.api_key) > 8 and config.api_key in delta:
                    delta = delta.replace(config.api_key, "[REDACTED]")
                yield delta
    except Exception as exc:
        sanitized = str(exc)
        if config.api_key and len(config.api_key) > 8 and config.api_key in sanitized:
            sanitized = sanitized.replace(config.api_key, "[REDACTED]")
        logger.error("LLM stream failed: %s", sanitized)
        raise RuntimeError("LLM streaming request failed") from None
