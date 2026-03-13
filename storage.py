import os
import mimetypes
import shutil
from abc import ABC, abstractmethod
from pathlib import Path

from botocore.exceptions import ClientError


class StorageBackend(ABC):
    @abstractmethod
    def download(self, remote_key: str, local_path: str) -> None:
        """Download a file. Raises on failure."""

    @abstractmethod
    def upload(self, local_path: str, remote_key: str, content_type: str | None = None) -> None:
        """Upload a file. Raises on failure."""

    @abstractmethod
    def delete(self, remote_key: str) -> None:
        """Upload a file. Raises on failure."""

class S3StorageBackend(StorageBackend):
    def __init__(self, client, bucket: str, public_read: bool = True):
        self._client = client
        self._bucket = bucket
        self._public_read = public_read

    def download(self, remote_key: str, local_path: str) -> None:
        try:
            self._client.download_file(self._bucket, remote_key, local_path)
        except ClientError as e:
            raise IOError(f"S3 download failed for {remote_key}: {e}") from e

    def upload(self, local_path: str, remote_key: str, content_type: str | None = None) -> None:
        if content_type is None:
            guessed, _ = mimetypes.guess_type(local_path)
            content_type = guessed or "application/octet-stream"

        extra: dict = {"ContentType": content_type}
        if self._public_read:
            extra["ACL"] = "public-read"

        try:
            self._client.upload_file(local_path, self._bucket, remote_key, ExtraArgs=extra)
        except ClientError as e:
            raise IOError(f"S3 upload failed for {remote_key}: {e}") from e

    def delete(self, remote_key: str) -> None:
        try:
            self._client.delete_object(
                Bucket=self._bucket,
                Key=remote_key,
            )
        except ClientError as e:
            raise IOError(f"S3 delete failed for {remote_key}: {e}") from e


class LocalStorageBackend(StorageBackend):
    """
    Mirrors a remote bucket as a local directory tree.
    Useful for integration tests and local dev runs without real S3.

        backend = LocalStorageBackend("/tmp/fake-bucket")
    """

    def __init__(self, root: str):
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def download(self, remote_key: str, local_path: str) -> None:
        src = self._root / remote_key
        if not src.exists():
            raise IOError(f"LocalStorage: key not found: {remote_key}")
        shutil.copy2(src, local_path)

    def upload(self, local_path: str, remote_key: str, content_type: str | None = None) -> None:
        dest = self._root / remote_key
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local_path, dest)

    def delete(self, remote_key):
        os.remove(remote_key)
