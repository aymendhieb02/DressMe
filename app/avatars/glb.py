"""Bounded structural checks for self-contained GLB 2.0 avatar assets."""

from __future__ import annotations

import base64
import binascii
import json
import struct
import warnings
from dataclasses import dataclass

from pygltflib import GLTF2


class AvatarAssetError(ValueError):
    def __init__(self, code: str, message: str, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class GLBInfo:
    size: int
    binary_length: int
    document: GLTF2


def _embedded_uri(uri: str, *, kind: str, max_bytes: int) -> int:
    header, separator, payload = uri.partition(",")
    if not separator or not header.lower().startswith("data:") or ";base64" not in header.lower():
        raise AvatarAssetError(
            "external_avatar_resource",
            "The GLB references a resource outside the exported model. Export a self-contained GLB and retry.",
        )
    media_type = header[5:].split(";", 1)[0].lower()
    allowed_types = {"application/octet-stream", "application/gltf-buffer"} if kind == "buffer" else {
        "image/png", "image/jpeg", "image/webp",
    }
    if media_type not in allowed_types:
        raise AvatarAssetError("invalid_avatar_glb", "The GLB contains an unsupported embedded resource type.")
    estimated_bytes = len(payload) * 3 // 4
    if estimated_bytes > max_bytes:
        raise AvatarAssetError("avatar_resource_too_large", "An embedded GLB resource exceeds the avatar size limit.", 413)
    try:
        decoded = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise AvatarAssetError("invalid_avatar_glb", "The GLB contains an invalid embedded resource.") from None
    return len(decoded)


def validate_avatar_glb(data: bytes, max_bytes: int) -> GLBInfo:
    """Parse the container and glTF document, and reject non-self-contained assets."""
    if len(data) > max_bytes:
        raise AvatarAssetError("avatar_too_large", "The exported avatar exceeds the configured upload limit.", 413)
    if len(data) < 20 or data[:4] != b"glTF":
        raise AvatarAssetError("invalid_avatar_glb", "Upload a valid binary GLB 2.0 avatar export.")
    version, declared_length = struct.unpack_from("<II", data, 4)
    if version != 2 or declared_length != len(data):
        raise AvatarAssetError("invalid_avatar_glb", "The GLB header or declared file length is invalid.")

    offset = 12
    json_chunk: bytes | None = None
    binary_length = 0
    saw_binary = False
    while offset < len(data):
        if offset + 8 > len(data):
            raise AvatarAssetError("invalid_avatar_glb", "The GLB contains a truncated chunk header.")
        chunk_length, chunk_type = struct.unpack_from("<I4s", data, offset)
        offset += 8
        end = offset + chunk_length
        if chunk_length % 4 or end > len(data):
            raise AvatarAssetError("invalid_avatar_glb", "The GLB contains an invalid or truncated chunk.")
        if json_chunk is None:
            if chunk_type != b"JSON":
                raise AvatarAssetError("invalid_avatar_glb", "The GLB JSON document must be the first chunk.")
            json_chunk = data[offset:end]
        elif chunk_type == b"JSON":
            raise AvatarAssetError("invalid_avatar_glb", "The GLB contains more than one JSON document.")
        elif chunk_type == b"BIN\x00":
            if saw_binary:
                raise AvatarAssetError("invalid_avatar_glb", "The GLB contains more than one binary buffer chunk.")
            binary_length = chunk_length
            saw_binary = True
        offset = end
    if json_chunk is None or offset != len(data):
        raise AvatarAssetError("invalid_avatar_glb", "The GLB is missing its JSON document.")
    try:
        raw_document = json.loads(json_chunk.rstrip(b" \t\r\n\x00").decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise AvatarAssetError("invalid_avatar_glb", "The GLB JSON document is invalid.") from None
    if not isinstance(raw_document, dict) or not isinstance(raw_document.get("asset"), dict):
        raise AvatarAssetError("invalid_avatar_glb", "The GLB has no glTF asset document.")
    if raw_document["asset"].get("version") != "2.0":
        raise AvatarAssetError("unsupported_avatar_format", "Only glTF 2.0 binary avatar exports are supported.")

    try:
        # pygltflib provides the maintained glTF 2.0 data model/parser. The
        # explicit chunk checks above compensate for its permissive GLB reader.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            document = GLTF2.load_from_bytes(data)
        if document is None:
            raise ValueError("empty glTF document")
        if document.asset is None or document.asset.version != "2.0":
            raise ValueError("unsupported glTF document")
        if not document.meshes or not any(mesh.primitives for mesh in document.meshes):
            raise ValueError("avatar has no renderable mesh")
        from pygltflib.validator import validate

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            validate(document)
    except Exception:
        raise AvatarAssetError("invalid_avatar_glb", "The exported GLB could not be parsed as a valid 3D model.") from None

    for buffer in document.buffers:
        if buffer.uri:
            if _embedded_uri(buffer.uri, kind="buffer", max_bytes=max_bytes) < buffer.byteLength:
                raise AvatarAssetError("invalid_avatar_glb", "The GLB contains an incomplete embedded buffer.")
        elif not saw_binary or buffer.byteLength > binary_length or binary_length - buffer.byteLength > 3:
            raise AvatarAssetError("invalid_avatar_glb", "The GLB is missing bytes required by its model.")
    for view in document.bufferViews:
        if view.buffer < 0 or view.buffer >= len(document.buffers):
            raise AvatarAssetError("invalid_avatar_glb", "The GLB references an unknown model buffer.")
        if view.byteOffset < 0 or view.byteLength < 0:
            raise AvatarAssetError("invalid_avatar_glb", "The GLB contains an invalid buffer range.")
        if view.byteOffset + view.byteLength > document.buffers[view.buffer].byteLength:
            raise AvatarAssetError("invalid_avatar_glb", "A GLB buffer view extends beyond its embedded data.")
    for mesh in document.meshes:
        for primitive in mesh.primitives:
            position_index = primitive.attributes.POSITION
            if position_index is None or position_index < 0 or position_index >= len(document.accessors):
                raise AvatarAssetError("invalid_avatar_glb", "The GLB contains a mesh without valid vertex positions.")
            positions = document.accessors[position_index]
            if positions.type != "VEC3" or positions.count <= 0 or positions.bufferView is None:
                raise AvatarAssetError("invalid_avatar_glb", "The GLB contains invalid mesh vertex positions.")
    for image in document.images:
        if image.uri:
            _embedded_uri(image.uri, kind="image", max_bytes=max_bytes)
        elif image.bufferView is None or image.bufferView >= len(document.bufferViews):
            raise AvatarAssetError("invalid_avatar_glb", "The GLB contains an image without embedded image data.")

    return GLBInfo(size=len(data), binary_length=binary_length, document=document)
