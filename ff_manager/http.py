"""HTTP utility module providing retry logic and session helpers."""

import logging
import time
from typing import Any, Optional, Tuple

try:
    import requests
    from requests.exceptions import ConnectionError as RequestsConnectionError
    from requests.exceptions import Timeout as RequestsTimeout
except ImportError:
    requests = None
    RequestsConnectionError = ()  # type: ignore
    RequestsTimeout = ()  # type: ignore

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_FACTOR = 1.0
DEFAULT_RETRY_STATUSES = (429, 500, 502, 503, 504)

RETRYABLE_EXCEPTIONS: Tuple[type, ...] = (TimeoutError,)
if requests is not None:
    RETRYABLE_EXCEPTIONS = (
        RequestsTimeout,
        RequestsConnectionError,
        TimeoutError,
    )


def request_with_retry(
    session: Any,
    method: str,
    url: str,
    timeout: int = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    platform_name: str = "HTTP",
    retry_statuses: Tuple[int, ...] = DEFAULT_RETRY_STATUSES,
    **kwargs,
) -> Any:
    """
    Execute an HTTP request with retry logic for transient network errors and server errors.

    Retries on:
      - RequestsTimeout (ReadTimeout, ConnectTimeout)
      - RequestsConnectionError
      - TimeoutError
      - HTTP status codes in retry_statuses (429, 500, 502, 503, 504)

    Args:
        session: requests.Session or mock object.
        method: HTTP method (e.g. 'GET', 'POST').
        url: Request URL.
        timeout: Request timeout in seconds.
        max_retries: Total number of attempts.
        backoff_factor: Base multiplier for exponential backoff delay.
        platform_name: Identifier for log messages.
        retry_statuses: Tuple of HTTP status codes considered transient.
        **kwargs: Extra parameters passed to session request (headers, json, params, etc.).

    Returns:
        The HTTP response object.

    Raises:
        The last exception if all attempts fail.
    """
    if session is None:
        raise RuntimeError("HTTP session not initialized (requests library required).")

    kwargs.setdefault("timeout", timeout)
    method_upper = method.upper()

    last_error: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            if method_upper == "GET" and hasattr(session, "get"):
                resp = session.get(url, **kwargs)
            elif method_upper == "POST" and hasattr(session, "post"):
                resp = session.post(url, **kwargs)
            elif hasattr(session, "request"):
                resp = session.request(method_upper, url, **kwargs)
            elif hasattr(session, method.lower()):
                resp = getattr(session, method.lower())(url, **kwargs)
            else:
                raise RuntimeError(f"Session object {session} does not support method {method_upper}")

            status = getattr(resp, "status_code", None)
            if isinstance(status, int) and status in retry_statuses:
                if attempt < max_retries:
                    delay = backoff_factor * (2 ** (attempt - 1))
                    logger.warning(
                        f"[{platform_name}] {method_upper} {url} returned HTTP {status} "
                        f"(attempt {attempt}/{max_retries}). Retrying in {delay:.1f}s..."
                    )
                    time.sleep(delay)
                    continue
                else:
                    logger.warning(
                        f"[{platform_name}] {method_upper} {url} returned HTTP {status} "
                        f"after {max_retries} attempts."
                    )

            if attempt > 1:
                logger.info(
                    f"[{platform_name}] {method_upper} {url} succeeded on retry (attempt {attempt}/{max_retries})."
                )

            return resp

        except RETRYABLE_EXCEPTIONS as e:
            last_error = e
            if attempt < max_retries:
                delay = backoff_factor * (2 ** (attempt - 1))
                logger.warning(
                    f"[{platform_name}] {method_upper} {url} failed with {type(e).__name__}: {e} "
                    f"(attempt {attempt}/{max_retries}). Retrying in {delay:.1f}s..."
                )
                time.sleep(delay)
            else:
                logger.error(
                    f"[{platform_name}] {method_upper} {url} failed after {max_retries} attempts: {e}"
                )
                raise

    if last_error:
        raise last_error
