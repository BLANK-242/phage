"""Shared Gemini call helpers: exponential backoff and tolerant JSON extraction.

Centralized so every PHAGE agent (VACCINATOR, SENTINEL, MARROW) inherits the
same rate-limit handling — a fresh project's Gemini quota rate-limits easily.
"""

from __future__ import annotations

import json
import random
import re
import time
from typing import Any, Optional

from google.genai import errors

_RETRYABLE = (429, 500, 503)


def generate_with_backoff(client, *, model, contents, config, max_attempts: int = 5, base_delay: float = 1.0):
    """One logical generate_content call, retried with exponential backoff + jitter.

    Retries transient errors (429 rate limit, 500/503); anything else (including
    a content-level decline, which is a normal 200) fails fast to the caller.
    """
    delay = base_delay
    for attempt in range(1, max_attempts + 1):
        try:
            return client.models.generate_content(model=model, contents=contents, config=config)
        except errors.APIError as exc:
            code = getattr(exc, "code", None)
            if code not in _RETRYABLE or attempt == max_attempts:
                raise
            time.sleep(delay + random.uniform(0, 0.5))
            delay *= 2
    raise RuntimeError("unreachable")


_FENCE = re.compile(r"```(?:json)?", re.IGNORECASE)


def extract_json(text: Optional[str]) -> Optional[Any]:
    """Best-effort parse of a JSON value that may be wrapped in ``` fences or prose."""
    if not text:
        return None
    s = _FENCE.sub("", text).strip().strip("`").strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    for open_c, close_c in (("[", "]"), ("{", "}")):
        i, j = s.find(open_c), s.rfind(close_c)
        if 0 <= i < j:
            try:
                return json.loads(s[i : j + 1])
            except Exception:
                continue
    return None
