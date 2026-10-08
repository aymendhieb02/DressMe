"""Persisted adapter contract shared by dispatch and worker delivery."""

from collections.abc import Mapping


MOCK_ADAPTER = "mock-preview-v1"
UNSUPPORTED_ADAPTER = "unsupported_vton_adapter"


def supports_mock_profile(mode: str, settings: object) -> bool:
    """Only an explicitly selected mock profile may enter the mock adapter."""
    return (
        mode == "mock"
        and isinstance(settings, Mapping)
        and settings.get("mode") == "mock"
        and settings.get("adapter") == MOCK_ADAPTER
    )
