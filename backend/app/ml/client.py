from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from ..config import settings


class BO6ServiceError(Exception):
    status_code = 502
    code = "bo6_service_error"

    def __init__(self, message: str):
        super().__init__(message)


class BO6Unavailable(BO6ServiceError):
    status_code = 503
    code = "bo6_unavailable"


class BO6Rejected(BO6ServiceError):
    status_code = 422
    code = "bo6_rejected_input"


class BO6Health(BaseModel):
    model_config = ConfigDict(extra="allow")
    status: str
    model_version: str
    taxonomy_version: str
    description_version: str
    quality_version: str


class BO6AnalyzeResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    quality: dict[str, Any]
    prediction: dict[str, Any]


class BO6DescribeResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    text: str
    fields: dict[str, Any]
    provenance: dict[str, Any]
    schema_version: str


class BO6Client:
    """Internal-only BO6 HTTP client; the browser must call the application API."""

    def __init__(
        self,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or settings.bo6_service_url).rstrip("/")
        self.transport = transport
        self.timeout = httpx.Timeout(
            connect=settings.bo6_connect_timeout_seconds,
            read=settings.bo6_read_timeout_seconds,
            write=settings.bo6_write_timeout_seconds,
            pool=2.0,
        )

    async def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                follow_redirects=False,
                transport=self.transport,
            ) as client:
                response = await client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise BO6Unavailable("The BO6 service timed out.") from exc
        except httpx.RequestError as exc:
            raise BO6Unavailable("The BO6 service is unavailable.") from exc
        if response.status_code in (413, 415, 422):
            raise BO6Rejected("The BO6 service rejected the image or fields.")
        if response.status_code >= 500 or response.status_code in (404, 429):
            raise BO6Unavailable("The BO6 service could not complete the request.")
        if not response.is_success:
            raise BO6ServiceError("The BO6 service returned an unexpected response.")
        try:
            payload = response.json()
        except ValueError as exc:
            raise BO6ServiceError("The BO6 service returned an invalid response.") from exc
        if not isinstance(payload, dict):
            raise BO6ServiceError("The BO6 service returned an invalid response.")
        return payload

    async def health(self) -> BO6Health:
        payload = await self._request("GET", "/health")
        try:
            return BO6Health.model_validate(payload)
        except ValidationError as exc:
            raise BO6ServiceError("The BO6 service health response did not match its contract.") from exc

    async def analyze(self, image_bytes: bytes, filename: str, content_type: str) -> BO6AnalyzeResponse:
        payload = await self._request(
            "POST",
            "/analyze",
            files={"image": (filename, image_bytes, content_type)},
        )
        try:
            return BO6AnalyzeResponse.model_validate(payload)
        except ValidationError as exc:
            raise BO6ServiceError("The BO6 analysis response did not match its contract.") from exc

    async def describe(self, confirmed: dict[str, str]) -> BO6DescribeResponse:
        payload = await self._request("POST", "/describe", json={"confirmed": confirmed})
        try:
            return BO6DescribeResponse.model_validate(payload)
        except ValidationError as exc:
            raise BO6ServiceError("The BO6 description response did not match its contract.") from exc
