"""Small, bounded Redis readiness probe used by the Windows demo launcher."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any


RedisLoader = Callable[[], tuple[Any, type[BaseException]]]


def _load_redis() -> tuple[Any, type[BaseException]]:
    from redis import Redis
    from redis.exceptions import RedisError

    return Redis, RedisError


def probe_redis(redis_url: str | None, *, redis_loader: RedisLoader | None = None) -> tuple[int, str]:
    """Return a redacted status and exit code without exposing connection details."""
    if not redis_url:
        return 2, "Redis probe configuration error: REDIS_URL is not set."

    try:
        redis_class, redis_error = (redis_loader or _load_redis)()
    except ImportError:
        return 3, "Redis probe dependency missing: redis."

    client = None
    failure: tuple[int, str] | None = None
    try:
        client = redis_class.from_url(
            redis_url,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        client.ping()
    except redis_error as error:
        failure = (1, f"Redis broker unavailable ({type(error).__name__}).")
    except (OSError, TimeoutError) as error:
        failure = (1, f"Redis broker unavailable ({type(error).__name__}).")
    except (TypeError, ValueError) as error:
        failure = (2, f"Redis probe configuration error: invalid REDIS_URL ({type(error).__name__}).")
    except Exception as error:  # Keep an unexpected probe error inside this process boundary.
        failure = (4, f"Redis probe failed ({type(error).__name__}).")
    finally:
        if client is not None:
            try:
                client.close()
            except Exception as error:
                if failure is None:
                    failure = (4, f"Redis probe failed ({type(error).__name__}).")

    if failure is not None:
        return failure
    return 0, "Redis broker: available."


def main() -> int:
    exit_code, message = probe_redis(os.environ.get("REDIS_URL"))
    # Diagnostics contain only a category and exception class, never the URL or
    # exception message (which can include credentials and host details).
    print(message)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
