from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


def error_response(request: Request, status_code: int, code: str, message: str) -> JSONResponse:
    response = JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "correlation_id": getattr(request.state, "correlation_id", "unknown"),
            }
        },
    )
    response.headers["Cache-Control"] = "no-store"
    return response


async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    code = str(detail.get("code", "request_rejected"))
    message = str(detail.get("message", "The request could not be completed."))
    return error_response(request, exc.status_code, code, message)


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return error_response(request, 422, "validation_error", "One or more request fields are invalid.")


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return error_response(request, 500, "internal_error", "The request could not be completed.")
