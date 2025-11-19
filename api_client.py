"""GreenPT API client for chat and model listing."""
import time
from functools import lru_cache
from typing import List, Optional

import requests

from config import (
    DEFAULT_GREENPT_MODELS_URL,
    DEFAULT_MODEL,
    GREENPT_API_KEY,
    GREENPT_API_URL,
    GREENPT_MODEL,
    GREENPT_SYSTEM_PROMPT,
)


def _greenpt_headers() -> dict:
    if not GREENPT_API_KEY:
        raise ValueError(
            "Missing GREENPT_API_KEY. Set it in your environment or a .env file."
        )
    return {
        "Authorization": f"Bearer {GREENPT_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


@lru_cache(maxsize=1)
def list_greenpt_models() -> List[str]:
    """Fetch available model IDs so users can pick a valid one."""
    response = requests.get(
        DEFAULT_GREENPT_MODELS_URL,
        headers=_greenpt_headers(),
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    models = [item["id"] for item in data.get("data", []) if "id" in item]
    return models or [DEFAULT_MODEL]


def call_greenpt_chat(
    prompt: str,
    tone: Optional[str] = None,
    model: Optional[str] = None,
    history: Optional[List[dict]] = None,
    max_tokens: int = 2000,
    timeout: Optional[int] = None,
    max_retries: int = 2,
) -> str:
    """
    Call the GreenPT chat API using a system prompt + user message.
    """
    if timeout is None:
        timeout = max(60, int(max_tokens / 50))
    
    user_content = prompt
    if tone:
        user_content = f"{prompt}\n\nPreferred tone: {tone}"

    if history:
        messages: List[dict] = [
            {"role": "system", "content": GREENPT_SYSTEM_PROMPT},
            *[dict(msg) for msg in history],
            {"role": "user", "content": user_content},
        ]
    else:
        messages = [
            {"role": "system", "content": GREENPT_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

    payload = {
        "model": model or GREENPT_MODEL,
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": max_tokens,
    }

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            response = requests.post(
                GREENPT_API_URL,
                json=payload,
                headers=_greenpt_headers(),
                timeout=timeout,
            )
            response.raise_for_status()
            break
        except requests.Timeout as timeout_err:
            last_error = timeout_err
            if attempt < max_retries:
                wait_time = (attempt + 1) * 5
                time.sleep(wait_time)
                continue
            else:
                raise requests.RequestException(
                    f"Request timed out after {timeout}s (tried {max_retries + 1} times). "
                    f"The API may be slow or your request is too large. Try reducing max_tokens or check your network connection."
                ) from timeout_err
        except requests.RequestException as req_err:
            if attempt < max_retries:
                wait_time = (attempt + 1) * 2
                time.sleep(wait_time)
                continue
            raise
    
    data = response.json()

    choices = data.get("choices") or []
    if not choices:
        raise ValueError("GreenPT returned no choices in the response.")

    message = choices[0].get("message") or {}
    content = (message.get("content") or "").strip()
    if not content:
        content = (data.get("summary") or data.get("message") or "").strip()

    if not content:
        raise ValueError("GreenPT did not include any assistant content.")

    return content

