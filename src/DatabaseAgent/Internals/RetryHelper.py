import asyncio
import logging
import math
import random
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import TypeVar

from openai import RateLimitError

T = TypeVar("T")


class RetryHelper:

    @staticmethod
    def rate_limit_error(exception: BaseException) -> RateLimitError | None:
        pending = [exception]
        seen = set()
        while pending:
            current = pending.pop()
            if id(current) in seen:
                continue
            seen.add(id(current))
            if isinstance(current, RateLimitError):
                return current
            pending.extend(
                item
                for item in (current.__cause__, current.__context__, *current.args)
                if isinstance(item, BaseException)
            )
        return None

    @staticmethod
    def _retry_delay(error: RateLimitError, attempt: int, logger: logging.Logger) -> float:
        headers = error.response.headers
        for header, scale in (
            ("retry-after-ms", 0.001),
            ("x-ms-retry-after-ms", 0.001),
            ("retry-after", 1.0),
        ):
            value = headers.get(header)
            if value is None:
                continue
            try:
                try:
                    delay = float(value) * scale
                except ValueError:
                    if header != "retry-after":
                        raise
                    retry_at = parsedate_to_datetime(value)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=timezone.utc)
                    delay = max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
                if math.isfinite(delay) and delay > 0:
                    return delay
            except (ValueError, TypeError, OverflowError):
                pass
            logger.warning("Ignoring invalid or elapsed %s rate-limit retry header.", header)
        return min(60.0 * 2**attempt, 120.0) + random.uniform(0, 1)

    @staticmethod
    async def retry_rate_limited(
        func: Callable[[], Awaitable[T]],
        count: int = 5,
        logger: logging.Logger | None = None,
    ) -> T:
        """Retry only HTTP 429s, including SK-wrapped errors, honoring server retry delays.

        Without retry headers, wait 60 seconds initially, then up to 120 seconds
        plus jitter. Exhaustion propagates the original exception.
        """
        if count < 1:
            raise ValueError("count must be at least 1")
        log = logger or logging.getLogger(__name__)
        for attempt in range(count):
            try:
                return await func()
            except Exception as exc:
                error = RetryHelper.rate_limit_error(exc)
                if error is None:
                    raise
                if attempt == count - 1:
                    log.warning("Rate limit persisted after %s attempts.", count, exc_info=True)
                    raise
                delay = RetryHelper._retry_delay(error, attempt, log)
                log.warning(
                    "Rate limited; retrying in %.2f seconds (attempt %s/%s).",
                    delay, attempt + 2, count,
                )
                await asyncio.sleep(delay)
        raise RuntimeError("Failed to execute the function.")

    @staticmethod
    async def try_function(
        func,
        count: int = 5,
        logger=None,
    ):
        last_exception = None

        for i in range(count):
            try:
                return await func(last_exception)

            except Exception as ex:
                if RetryHelper.rate_limit_error(ex) is not None:
                    raise

                if i == count - 1:
                    log = logger or logging.getLogger("DatabaseAgentFactory")

                    log.warning(
                        "Failed to execute the function after %s attempts.",
                        count,
                        exc_info=ex,
                    )

                    raise

                last_exception = ex

                await asyncio.sleep(0.2)

        raise RuntimeError("Failed to execute the function.")