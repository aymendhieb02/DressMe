import os
import re
import tempfile
from pathlib import Path

from fastapi import HTTPException

from ..config import get_settings

IMAGE_KEY_RE = re.compile(r"^[0-9a-f]{32}\.png$")
AVATAR_KEY_RE = re.compile(r"^[0-9a-f]{32}\.glb$")


class LocalPrivateStorage:
    def __init__(self, root: Path | None = None):
        self.root = (root or get_settings().storage_path).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str, allowed: re.Pattern[str] = IMAGE_KEY_RE) -> Path:
        if not allowed.fullmatch(key):
            raise HTTPException(status_code=404, detail={"code": "image_not_found", "message": "Image not found."})
        path = (self.root / key).resolve()
        if path.parent != self.root:
            raise HTTPException(status_code=404, detail={"code": "image_not_found", "message": "Image not found."})
        return path

    def _put(self, data: bytes, extension: str) -> str:
        import secrets

        key = secrets.token_hex(16) + extension
        allowed = AVATAR_KEY_RE if extension == ".glb" else IMAGE_KEY_RE
        destination = self._path(key, allowed)
        fd, temp_name = tempfile.mkstemp(prefix=".upload-", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            Path(temp_name).replace(destination)
        except Exception:
            Path(temp_name).unlink(missing_ok=True)
            raise
        return key

    def put(self, data: bytes) -> str:
        return self._put(data, ".png")

    def put_avatar(self, data: bytes) -> str:
        return self._put(data, ".glb")

    def read(self, key: str) -> bytes:
        return self._read(key, IMAGE_KEY_RE)

    def read_avatar(self, key: str) -> bytes:
        return self._read(key, AVATAR_KEY_RE)

    def _read(self, key: str, allowed: re.Pattern[str]) -> bytes:
        path = self._path(key, allowed)
        try:
            return path.read_bytes()
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail={"code": "image_not_found", "message": "Image not found."}) from None

    def delete(self, key: str) -> None:
        allowed = AVATAR_KEY_RE if AVATAR_KEY_RE.fullmatch(key) else IMAGE_KEY_RE
        self._path(key, allowed).unlink(missing_ok=True)
