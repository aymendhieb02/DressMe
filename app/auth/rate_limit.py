from collections import defaultdict, deque
import time

from fastapi import Request
from fastapi.responses import JSONResponse

from ..config import settings
from ..common.errors import error_response


class LoginLimiter:
    """Small process-local abuse guard for the single-worker development API."""

    def __init__(self) -> None:
        self._attempts: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        events = self._attempts[key]
        while events and events[0] <= now - settings.login_window_seconds:
            events.popleft()
        if len(events) >= settings.login_limit_count:
            return False
        events.append(now)
        if len(self._attempts) > 5000:
            for stale_key in [k for k, values in self._attempts.items() if not values or values[-1] <= now - settings.login_window_seconds]:
                self._attempts.pop(stale_key, None)
        return True


login_limiter = LoginLimiter()


def rate_limit_login(request: Request, key: str) -> JSONResponse | None:
    host = request.client.host if request.client else "unknown"
    if login_limiter.allow(f"{host}:{key}"):
        return None
    return error_response(request, 429, "rate_limited", "Too many authentication attempts. Try again shortly.")
