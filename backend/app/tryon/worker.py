import argparse
import os
import sys

from redis import Redis
from redis.exceptions import RedisError
from rq import Queue, SimpleWorker, Worker
from rq.serializers import JSONSerializer

from ..config import get_settings
from .dispatcher import QUEUE_NAME


def run_worker(*, simple_mock: bool = False, burst: bool = False, max_jobs: int | None = None) -> None:
    settings = get_settings()
    if settings.vton_mode != "mock":
        raise RuntimeError("The real VTON adapter is unavailable; no mock result was substituted.")
    if max_jobs is not None and max_jobs < 1:
        raise ValueError("max_jobs must be positive")
    if simple_mock and settings.environment not in {"development", "test"}:
        raise RuntimeError("--simple-mock is restricted to development/test demonstrations.")
    if os.name == "nt" and not simple_mock:
        raise RuntimeError("The isolated RQ worker requires Linux/Compose. For a local mock demonstration, explicitly use --simple-mock.")
    worker_class = SimpleWorker if simple_mock else Worker
    if simple_mock:
        print("MOCK ONLY: SimpleWorker executes each job in this worker process without per-job process isolation.", file=sys.stderr)
    redis = Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2, health_check_interval=30)
    try:
        redis.ping()
        queue = Queue(QUEUE_NAME, connection=redis, serializer=JSONSerializer)
        worker_class([queue], connection=redis, serializer=JSONSerializer).work(burst=burst, max_jobs=max_jobs)
    finally:
        redis.close()


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the DressMe mock RQ worker.")
    parser.add_argument("--simple-mock", action="store_true", help="development/test only: execute labelled mock jobs without per-job process isolation")
    parser.add_argument("--burst", action="store_true", help="exit when the queue is empty")
    parser.add_argument("--max-jobs", type=_positive_int, help="exit after processing this many deliveries")
    args = parser.parse_args(argv)
    try:
        run_worker(simple_mock=args.simple_mock, burst=args.burst, max_jobs=args.max_jobs)
    except RedisError:
        print("Try-on worker startup failed: Redis is unavailable. Check REDIS_URL and start the broker.", file=sys.stderr)
        return 1
    except (RuntimeError, ValueError) as error:
        print(f"Try-on worker startup failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
