from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Iterable, Optional

import requests


DEFAULT_USER_AGENTS = [
    # A small, reasonable rotation set.
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
]


@dataclass(frozen=True)
class FetchResult:
    url: str
    status_code: int
    text: str
    elapsed_s: float
    error: Optional[str] = None


def _sleep_with_jitter(base_s: float, jitter_s: float = 0.25) -> None:
    time.sleep(max(0.0, base_s + random.uniform(0.0, jitter_s)))


def fetch_html(
    url: str,
    *,
    session: Optional[requests.Session] = None,
    user_agents: Optional[Iterable[str]] = None,
    timeout_s: float = 25.0,
    max_attempts: int = 6,
    backoff_base_s: float = 1.2,
    backoff_multiplier: float = 1.8,
    raise_on_failure: bool = True,
    verbose: bool = False,
) -> FetchResult:
    """
    Fetch HTML with rotating user agents and exponential backoff.
    Retries on common rate-limit / transient statuses.
    """
    uas = list(user_agents) if user_agents is not None else list(DEFAULT_USER_AGENTS)
    if not uas:
        uas = list(DEFAULT_USER_AGENTS)

    sess = session or requests.Session()
    last_exc: Optional[Exception] = None
    last_status: Optional[int] = None
    last_text: str = ""
    last_elapsed: float = 0.0

    for attempt in range(1, max_attempts + 1):
        headers = {
            "User-Agent": random.choice(uas),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "DNT": "1",
            "Upgrade-Insecure-Requests": "1",
            "Referer": "https://www.redfin.com/",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
        }
        t0 = time.time()
        try:
            if verbose:
                print(f"[fetch] attempt {attempt}/{max_attempts}: GET {url}")
            resp = sess.get(url, headers=headers, timeout=timeout_s)
            elapsed = time.time() - t0
            last_status = resp.status_code
            last_elapsed = elapsed
            last_text = resp.text or ""
            if resp.status_code in (200,):
                return FetchResult(url=url, status_code=resp.status_code, text=resp.text, elapsed_s=elapsed)

            # Retryable statuses: rate limit, forbidden, transient server errors
            if resp.status_code in (403, 405, 429, 500, 502, 503, 504):
                # "Warm up" cookies on block-like responses (helps in some environments)
                if resp.status_code in (403, 405, 429):
                    try:
                        sess.get("https://www.redfin.com/", headers=headers, timeout=timeout_s)
                    except Exception:
                        pass
                sleep_s = backoff_base_s * (backoff_multiplier ** (attempt - 1))
                if verbose:
                    print(f"[fetch] got HTTP {resp.status_code}; retrying after {sleep_s:.1f}s")
                _sleep_with_jitter(sleep_s)
                continue

            # Non-retryable
            return FetchResult(url=url, status_code=resp.status_code, text=resp.text, elapsed_s=elapsed)
        except (requests.Timeout, requests.ConnectionError, requests.SSLError) as exc:
            last_exc = exc
            sleep_s = backoff_base_s * (backoff_multiplier ** (attempt - 1))
            if verbose:
                print(f"[fetch] error {type(exc).__name__}: {exc}; retrying after {sleep_s:.1f}s")
            _sleep_with_jitter(sleep_s)
            continue

    msg_parts = [f"Failed to fetch {url} after {max_attempts} attempts"]
    if last_status is not None:
        msg_parts.append(f"(last HTTP status: {last_status})")
    if last_exc is not None:
        msg_parts.append(f"(last error: {type(last_exc).__name__}: {last_exc})")
    msg = " ".join(msg_parts)

    if raise_on_failure:
        raise RuntimeError(msg) from last_exc

    return FetchResult(
        url=url,
        status_code=last_status or 0,
        text=last_text,
        elapsed_s=last_elapsed,
        error=msg,
    )

