import os
import re
import tempfile
from pathlib import Path

from fastapi import HTTPException

from ..config import get_settings

KEY_RE = re.compile(r"^[0-9a-f]{32}\.png$")


class LocalPrivateStorage:
    def __init__(self, root: Path | None = None):
        self.root = (root or get_settings().storage_path).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        if not KEY_RE.fullmatch(key):
            raise HTTPException(status_code=404, detail={"code": "image_not_found", "message": "Image not found."})
        path = (self.root / key).resolve()
        if path.parent != self.root:
            raise HTTPException(status_code=404, detail={"code": "image_not_found", "message": "Image not found."})
        return path

    def put(self, data: bytes) -> str:
        import secrets

        key = secrets.token_hex(16) + ".png"
        destination = self._path(key)
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

    def read(self, key: str) -> bytes:
        path = self._path(key)
        try:
            return path.read_bytes()
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail={"code": "image_not_found", "message": "Image not found."}) from None

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)
