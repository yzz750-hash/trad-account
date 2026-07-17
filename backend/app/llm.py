import litellm
import logging
from pydantic import BaseModel
from typing import Optional, Any, AsyncGenerator
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Prevent LiteLLM from logging API keys in error messages
litellm.suppress_debug_info = True
litellm.set_verbose = False
os_module = __import__('os')
if not os_module.environ.get("LITELLM_LOG"):
    os_module.environ["LITELLM_LOG"] = "ERROR"


# Allowlist of LLM provider hostnames. base_url is user-configurable via the
# Ledger table, so without an allowlist a malicious or compromised admin could
# point it at internal services (e.g. http://169.254.169.254/ cloud metadata,
# http://localhost:8000/api/... to forge internal requests). This is a
# classic SSRF vector.
#
# Add new providers here when extending the system. All entries must be HTTPS
# (or http://localhost for local dev models — never http in production).
_ALLOWED_LLM_HOSTS = {
    "api.deepseek.com",
    "api.openai.com",
    "api.anthropic.com",
    "generativelanguage.googleapis.com",
    "dashscope.aliyuncs.com",
    "open.bigmodel.cn",
    "api.minimax.chat",
    "api.moonshot.cn",
    "api.baichuan-ai.com",
    "api.lingyiwanwu.com",
    "api.01.ai",
    "api.siliconflow.cn",
}
# Local dev models (Ollama, vLLM, LM Studio, etc.) — only allowed in
# non-production environments.
_LOCAL_DEV_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0"}
_ENV = os_module.environ.get("ENVIRONMENT", "development")


class LLMConfig(BaseModel):
    provider: str
    api_key: str
    model_name: str
    base_url: Optional[str] = None


def _validate_base_url(base_url: Optional[str]) -> Optional[str]:
    """Validate that base_url points to an allowlisted LLM provider.

    Raises ValueError if the URL is malformed, uses a disallowed scheme,
    or points to a host not in the allowlist. Returns the validated URL.
    """
    if not base_url:
        return base_url

    parsed = urlparse(base_url)
    if not parsed.scheme or not parsed.hostname:
        raise ValueError(f"Invalid LLM base_url: {base_url!r} (missing scheme or host)")

    # Production must use HTTPS. Dev allows http://localhost for local models.
    if parsed.scheme != "https":
        if parsed.scheme == "http" and parsed.hostname in _LOCAL_DEV_HOSTS and _ENV != "production":
            pass  # allow local dev models
        else:
            raise ValueError(
                f"LLM base_url must use HTTPS (got {parsed.scheme}://). "
                f"HTTP is only allowed for localhost in non-production environments."
            )

    # Block userinfo (user:pass@host) — never legitimate for an LLM endpoint
    # and could be used to smuggle credentials into error logs.
    if parsed.username or parsed.password:
        raise ValueError(f"LLM base_url must not contain userinfo: {base_url!r}")

    host = parsed.hostname.lower()
    if host in _LOCAL_DEV_HOSTS:
        if _ENV == "production":
            raise ValueError(
                f"LLM base_url points to {host} which is forbidden in production. "
                f"Configure a real provider URL."
            )
        return base_url

    # Allow subdomains of allowlisted hosts (e.g. api-east.deepseek.com).
    if not any(
        host == allowed or host.endswith("." + allowed)
        for allowed in _ALLOWED_LLM_HOSTS
    ):
        raise ValueError(
            f"LLM base_url host {host!r} is not in the allowlist. "
            f"Allowed providers: {sorted(_ALLOWED_LLM_HOSTS)}. "
            f"To add a new provider, update _ALLOWED_LLM_HOSTS in app/llm.py."
        )

    return base_url


# ponytail: LiteLLM 1.83.7 deepseek native route hits /beta/ which rejects the key.
# Remap to openai provider + /v1 until LiteLLM fixes it.
def _resolve_model_and_base(config: "LLMConfig"):
    if config.provider == "deepseek":
        base = config.base_url or "https://api.deepseek.com/v1"
    else:
        base = config.base_url
    # Validate even the default URL to catch environment misconfiguration.
    base = _validate_base_url(base)
    if config.provider == "deepseek":
        return "openai/deepseek-chat", base
    return f"{config.provider}/{config.model_name}", base


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
    model, api_base = _resolve_model_and_base(config)
    kwargs = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "api_key": config.api_key,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "timeout": timeout,
    }

    if api_base:
        kwargs["api_base"] = api_base

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

    model, api_base = _resolve_model_and_base(config)
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": msgs,
        "api_key": config.api_key,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "timeout": timeout,
        "stream": True,
    }

    if api_base:
        kwargs["api_base"] = api_base

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
