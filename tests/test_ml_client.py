import asyncio

import httpx
import pytest

from app.ml.client import BO6Client, BO6Rejected, BO6ServiceError, BO6Unavailable


def test_health_response_matches_bo6_contract():
    async def run():
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
            "status": "ok", "model_version": "model-1", "taxonomy_version": "dressme-v0.2",
            "description_version": "tmpl-v0.4", "quality_version": "quality-1",
        }))
        result = await BO6Client("http://ml-service", transport).health()
        assert result.taxonomy_version == "dressme-v0.2"
    asyncio.run(run())


def test_analysis_uses_existing_multipart_contract_and_preserves_payload():
    async def run():
        def handler(request):
            assert request.url.path == "/analyze"
            assert b'name="image"' in request.content
            return httpx.Response(200, json={"quality": {"advisory_only": True}, "prediction": {"score_type": "uncalibrated_softmax"}})
        response = await BO6Client("http://ml-service", httpx.MockTransport(handler)).analyze(b"image", "shirt.png", "image/png")
        assert response.prediction["score_type"] == "uncalibrated_softmax"
    asyncio.run(run())


def test_timeout_is_translated_to_service_unavailable():
    async def run():
        def handler(request):
            raise httpx.ReadTimeout("upstream timeout")
        with pytest.raises(BO6Unavailable) as error:
            await BO6Client("http://ml-service", httpx.MockTransport(handler)).health()
        assert error.value.status_code == 503
    asyncio.run(run())


def test_upstream_validation_and_server_errors_are_distinguished():
    async def run():
        rejected = BO6Client("http://ml-service", httpx.MockTransport(lambda request: httpx.Response(422))).health
        with pytest.raises(BO6Rejected):
            await rejected()
        unavailable = BO6Client("http://ml-service", httpx.MockTransport(lambda request: httpx.Response(503))).health
        with pytest.raises(BO6Unavailable):
            await unavailable()
    asyncio.run(run())


def test_invalid_json_payload_is_rejected():
    async def run():
        client = BO6Client("http://ml-service", httpx.MockTransport(lambda request: httpx.Response(200, content=b"nope")))
        with pytest.raises(BO6ServiceError):
            await client.health()
    asyncio.run(run())
