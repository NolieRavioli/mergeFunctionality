"""Centralised ESI request buffering with floating window rate limiting support."""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional, Tuple
from urllib.parse import urlparse

import requests
from requests import Request, Response
from requests.structures import CaseInsensitiveDict

logger = logging.getLogger(__name__)

# Token costs based on the ESI floating window specification.
TOKEN_COSTS = {
    2: 2,  # 2XX responses
    3: 1,  # 3XX responses
    4: 5,  # 4XX responses
    5: 0,  # 5XX responses
}

DEFAULT_WINDOW_SECONDS = 15 * 60  # 15 minutes
DEFAULT_TOKEN_LIMIT = 1800  # Conservative default: ~1 request / second for 2XX responses.
_CACHE_LOCK = threading.Lock()


@dataclass(frozen=True)
class _CacheRule:
    method: str
    path: str
    ttl: int
    match_prefix: bool = False


_CACHE_RULES: tuple[_CacheRule, ...] = (
    _CacheRule(method="GET", path="/latest/universe/structures/", ttl=7 * 24 * 3600),
    _CacheRule(method="GET", path="/latest/markets/structures/", ttl=30 * 60, match_prefix=True),
)


_CacheKey = Tuple[str, str, bytes, Optional[str]]
_CACHE: dict[_CacheKey, tuple[float, dict]] = {}


def _resolve_cache_ttl(method: str, path: str) -> Optional[int]:
    for rule in _CACHE_RULES:
        if method != rule.method:
            continue
        if rule.match_prefix and path.startswith(rule.path):
            return rule.ttl
        if not rule.match_prefix and path == rule.path:
            return rule.ttl
    return None


def _prepare_cache_key(method: str, url: str, kwargs: dict) -> tuple[requests.PreparedRequest, Optional[_CacheKey], Optional[int]]:
    headers = kwargs.get("headers") or {}
    req = Request(
        method=method,
        url=url,
        headers=headers,
        params=kwargs.get("params"),
        data=kwargs.get("data"),
        json=kwargs.get("json"),
    )
    prepared = req.prepare()
    parsed = urlparse(prepared.url)
    ttl = _resolve_cache_ttl(prepared.method, parsed.path)
    if not ttl:
        return prepared, None, None

    body = prepared.body or b""
    if isinstance(body, str):
        body = body.encode("utf-8")

    cache_key: _CacheKey = (
        prepared.method,
        prepared.url,
        body,
        headers.get("Authorization"),
    )
    return prepared, cache_key, ttl


def _build_cached_response(payload: dict, prepared: requests.PreparedRequest) -> Response:
    resp = Response()
    resp.status_code = payload.get("status_code", 0)
    resp._content = payload.get("content", b"")
    resp.headers = CaseInsensitiveDict(payload.get("headers", {}))
    resp.encoding = payload.get("encoding")
    resp.reason = payload.get("reason")
    resp.url = payload.get("url", prepared.url)
    resp.request = prepared
    return resp


def _get_cached_response(key: _CacheKey, prepared: requests.PreparedRequest) -> Optional[Response]:
    now = time.time()
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
        if not entry:
            return None
        expiry, payload = entry
        if expiry <= now:
            del _CACHE[key]
            return None
    return _build_cached_response(payload, prepared)


def _store_cached_response(
    key: _CacheKey,
    response: requests.Response,
    ttl: int,
    prepared: requests.PreparedRequest,
) -> None:
    payload = {
        "status_code": response.status_code,
        "headers": dict(response.headers),
        "content": response.content,
        "encoding": response.encoding,
        "reason": response.reason,
        "url": response.url or prepared.url,
    }
    expires = time.time() + ttl
    with _CACHE_LOCK:
        _CACHE[key] = (expires, payload)


def _token_cost_for_status(status_code: int) -> int:
    """Return the token cost for a given HTTP status code."""

    bucket = status_code // 100
    return TOKEN_COSTS.get(bucket, 5)


class _TokenBucket:
    """Simple floating-window token bucket implementation."""

    def __init__(self, limit: int = DEFAULT_TOKEN_LIMIT, window: int = DEFAULT_WINDOW_SECONDS) -> None:
        self.limit = max(1, limit)
        self.window = max(1, window)
        self._entries: Deque[tuple[float, int]] = deque()
        self._total = 0
        self._lock = threading.Lock()

    def configure(self, *, limit: Optional[int] = None, window: Optional[int] = None) -> None:
        with self._lock:
            if limit is not None and limit > 0:
                if limit != self.limit:
                    logger.debug("[RateLimiter] Updating limit: %s -> %s", self.limit, limit)
                self.limit = limit
            if window is not None and window > 0:
                if window != self.window:
                    logger.debug("[RateLimiter] Updating window: %s -> %s", self.window, window)
                self.window = window

    def _prune(self, now: float) -> None:
        while self._entries and now - self._entries[0][0] >= self.window:
            _, cost = self._entries.popleft()
            self._total -= cost

    def acquire(self, cost: int) -> None:
        """Block until the bucket can accommodate *cost* tokens."""

        cost = max(0, cost)
        while True:
            with self._lock:
                now = time.monotonic()
                self._prune(now)
                if self._total + cost <= self.limit:
                    if cost:
                        self._entries.append((now, cost))
                        self._total += cost
                    return
                wait_time = self._entries[0][0] + self.window - now if self._entries else 1
            if wait_time > 0:
                time.sleep(min(wait_time, 1.0))

    def adjust(self, delta: int) -> None:
        """Adjust the token usage for the most recent request."""

        if delta == 0:
            return

        with self._lock:
            if delta > 0:
                # Consume additional tokens immediately if available.
                self.acquire(delta)
            else:
                # Return tokens by trimming from the newest entry.
                to_return = -delta
                while to_return and self._entries:
                    ts, cost = self._entries.pop()
                    remove = min(cost, to_return)
                    remaining = cost - remove
                    self._total -= remove
                    to_return -= remove
                    if remaining:
                        self._entries.append((ts, remaining))
                        self._total += remaining
                        break


class EsiRateLimiter:
    """Serialize ESI requests through a single floating-window token bucket."""

    def __init__(
        self,
        *,
        token_limit: int = DEFAULT_TOKEN_LIMIT,
        window_seconds: int = DEFAULT_WINDOW_SECONDS,
        max_retries: int = 5,
        default_retry_after: int = 2,
    ) -> None:
        self._bucket = _TokenBucket(limit=token_limit, window=window_seconds)
        self._max_retries = max(1, max_retries)
        self._default_retry_after = max(1, default_retry_after)

    def request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Perform an HTTP request against ESI obeying rate limits and retries."""

        attempt = 0
        initial_cost = TOKEN_COSTS[2]

        prepared, cache_key, ttl = _prepare_cache_key(method, url, kwargs)
        if ttl and cache_key:
            cached = _get_cached_response(cache_key, prepared)
            if cached is not None:
                logger.debug("[RateLimiter] Using cached response for %s", prepared.url)
                return cached

        while True:
            attempt += 1
            self._bucket.acquire(initial_cost)
            try:
                response = requests.request(method, url, **kwargs)
            except Exception:
                # Return the reserved tokens since no response was obtained.
                self._bucket.adjust(-initial_cost)
                raise

            # Adjust for the actual status cost if different from optimistic reservation.
            actual_cost = _token_cost_for_status(response.status_code)
            delta = actual_cost - initial_cost
            if delta:
                self._bucket.adjust(delta)

            self._update_limits_from_headers(response.headers)

            if ttl and cache_key and 200 <= response.status_code < 400:
                _store_cached_response(cache_key, response, ttl, prepared)

            if response.status_code == 429 and attempt < self._max_retries:
                retry_after = self._parse_retry_after(response.headers.get("Retry-After"))
                logger.warning(
                    "[RateLimiter] 429 received for %s %s. Sleeping %ss (attempt %s/%s)",
                    method.upper(),
                    url,
                    retry_after,
                    attempt,
                    self._max_retries,
                )
                time.sleep(retry_after)
                continue

            return response

    def _parse_retry_after(self, header_value: Optional[str]) -> int:
        if not header_value:
            return self._default_retry_after
        try:
            delay = int(float(header_value))
            return max(self._default_retry_after, delay)
        except (TypeError, ValueError):
            return self._default_retry_after

    def _update_limits_from_headers(self, headers: Dict[str, str]) -> None:
        """Refresh the bucket configuration based on ESI rate limit headers if present."""

        limit = self._extract_int(headers, "X-RateLimit-Limit")
        if limit is None:
            limit = self._extract_int(headers, "X-Esi-Rate-Limit-Limit")
        window = self._extract_int(headers, "X-RateLimit-Window")
        if window is None:
            window = self._extract_int(headers, "X-Esi-Rate-Limit-Window")

        if limit is not None or window is not None:
            self._bucket.configure(limit=limit, window=window)

    @staticmethod
    def _extract_int(headers: Dict[str, str], key: str) -> Optional[int]:
        value = headers.get(key)
        if value is None:
            return None
        try:
            # Some providers may supply comma-delimited values; use the first token.
            value = value.split(",")[0]
            return int(float(value))
        except (ValueError, TypeError):
            logger.debug("[RateLimiter] Failed to parse header %s=%s", key, value)
            return None


_GLOBAL_LIMITER: Optional[EsiRateLimiter] = None
_GLOBAL_LOCK = threading.Lock()


def get_esi_rate_limiter() -> EsiRateLimiter:
    global _GLOBAL_LIMITER
    if _GLOBAL_LIMITER is None:
        with _GLOBAL_LOCK:
            if _GLOBAL_LIMITER is None:
                _GLOBAL_LIMITER = EsiRateLimiter()
    return _GLOBAL_LIMITER


def esi_request(method: str, url: str, **kwargs) -> requests.Response:
    """Execute an HTTP request routed through the shared ESI rate limiter."""

    limiter = get_esi_rate_limiter()
    return limiter.request(method, url, **kwargs)


def esi_get(url: str, **kwargs) -> requests.Response:
    return esi_request("GET", url, **kwargs)


def esi_post(url: str, **kwargs) -> requests.Response:
    return esi_request("POST", url, **kwargs)


def esi_put(url: str, **kwargs) -> requests.Response:
    return esi_request("PUT", url, **kwargs)


def esi_delete(url: str, **kwargs) -> requests.Response:
    return esi_request("DELETE", url, **kwargs)

