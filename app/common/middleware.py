import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        supplied = request.headers.get("X-Request-ID", "")
        try:
            correlation_id = str(uuid.UUID(supplied)) if supplied else str(uuid.uuid4())
        except (ValueError, AttributeError):
            correlation_id = str(uuid.uuid4())
        request.state.correlation_id = correlation_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = correlation_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        if request.url.path.startswith(("/auth", "/api/", "/garments", "/person-photos", "/try-on", "/avatars")):
            response.headers["Cache-Control"] = (
                "private, no-store"
                if request.url.path.endswith(("/image", "/result", "/model"))
                or request.url.path == "/avatars/current/render/export"
                else "no-store"
            )
            response.headers["Vary"] = "Cookie"
        return response
