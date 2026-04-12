"""MinIO object storage integration adapter."""

from __future__ import annotations

import io
import logging
from urllib.parse import urlparse

from django.conf import settings
from minio import Minio

from .common import BaseAdapter, IntegrationError

logger = logging.getLogger(__name__)


class MinIOAdapter(BaseAdapter):
    service_name = "minio"

    def __init__(self):
        endpoint_url = getattr(settings, "MINIO_ENDPOINT", "http://minio:9000")
        parsed = urlparse(endpoint_url)
        self._client = Minio(
            endpoint=parsed.netloc or parsed.path,
            access_key=getattr(settings, "MINIO_ACCESS_KEY", "minioadmin"),
            secret_key=getattr(settings, "MINIO_SECRET_KEY", "minioadmin"),
            secure=parsed.scheme == "https",
        )
        self._default_bucket = getattr(settings, "MINIO_RAW_BUCKET", "newsintel-raw")

    def ensure_bucket(self, bucket_name: str | None = None) -> bool:
        bucket = bucket_name or self._default_bucket
        try:
            if not self._client.bucket_exists(bucket):
                self._client.make_bucket(bucket)
                logger.info("Created MinIO bucket %s", bucket)
                return True
            return False
        except Exception as exc:
            raise IntegrationError(f"Failed to ensure bucket {bucket}: {exc}") from exc

    def store_raw(self, key: str, data: bytes | str, content_type: str = "text/html", bucket: str | None = None) -> str:
        bucket = bucket or self._default_bucket
        self.ensure_bucket(bucket)
        if isinstance(data, str):
            data = data.encode("utf-8")
        try:
            self._client.put_object(
                bucket_name=bucket,
                object_name=key,
                data=io.BytesIO(data),
                length=len(data),
                content_type=content_type,
            )
            return f"{bucket}/{key}"
        except Exception as exc:
            raise IntegrationError(f"Failed to store {key}: {exc}") from exc

    def fetch_raw(self, key: str, bucket: str | None = None) -> bytes:
        bucket = bucket or self._default_bucket
        try:
            response = self._client.get_object(bucket_name=bucket, object_name=key)
            return response.read()
        except Exception as exc:
            raise IntegrationError(f"Failed to fetch {key}: {exc}") from exc
        finally:
            if "response" in dir():
                response.close()
                response.release_conn()

    def delete_raw(self, key: str, bucket: str | None = None) -> None:
        bucket = bucket or self._default_bucket
        try:
            self._client.remove_object(bucket_name=bucket, object_name=key)
        except Exception as exc:
            raise IntegrationError(f"Failed to delete {key}: {exc}") from exc

    def health(self) -> bool:
        try:
            self._client.list_buckets()
            return True
        except Exception as exc:
            raise IntegrationError(f"MinIO health check failed: {exc}") from exc
