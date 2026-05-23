from dataclasses import dataclass

from fastapi import HTTPException

from api.config import get_settings, s3_configured


class StorageConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class S3ObjectMetadata:
    key: str
    size_bytes: int | None = None
    etag: str | None = None
    content_type: str | None = None


class S3StorageService:

    def __init__(self, settings=None, client=None):
        self.settings = settings or get_settings()
        self.client = client

    def require_configured(self):
        if not s3_configured(self.settings):
            raise StorageConfigurationError(
                "AWS S3 nao configurado pelas variaveis de ambiente."
            )

    def get_client(self):
        self.require_configured()

        if self.client is not None:
            return self.client

        try:
            import boto3
        except ImportError as error:
            raise StorageConfigurationError("Dependencia boto3 nao instalada.") from error

        kwargs = {
            "service_name": "s3",
            "region_name": self.settings.aws_region,
            "aws_access_key_id": self.settings.aws_access_key_id,
            "aws_secret_access_key": self.settings.aws_secret_access_key,
        }

        if self.settings.aws_endpoint_url:
            kwargs["endpoint_url"] = self.settings.aws_endpoint_url

        self.client = boto3.client(**kwargs)
        return self.client

    @property
    def bucket(self):
        self.require_configured()
        return self.settings.aws_s3_bucket

    def upload_object(self, key, body, content_type="application/octet-stream"):
        client = self.get_client()
        client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
        )
        return {"bucket": self.bucket, "key": key}

    def delete_object(self, key):
        self.get_client().delete_object(Bucket=self.bucket, Key=key)
        return {"bucket": self.bucket, "key": key, "deleted": True}

    def get_object_metadata(self, key):
        response = self.get_client().head_object(Bucket=self.bucket, Key=key)
        return S3ObjectMetadata(
            key=key,
            size_bytes=response.get("ContentLength"),
            etag=response.get("ETag"),
            content_type=response.get("ContentType"),
        )

    def create_presigned_upload_url(self, key, content_type="application/zip", expires_seconds=None):
        expires_seconds = expires_seconds or self.settings.presigned_url_expires_seconds
        url = self.get_client().generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ContentType": content_type,
            },
            ExpiresIn=expires_seconds,
        )
        return {
            "url": url,
            "method": "PUT",
            "bucket": self.bucket,
            "key": key,
            "expiresIn": expires_seconds,
            "headers": {"Content-Type": content_type},
        }

    def create_presigned_download_url(self, key, expires_seconds=None):
        expires_seconds = expires_seconds or self.settings.presigned_url_expires_seconds
        url = self.get_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_seconds,
        )
        return {
            "url": url,
            "method": "GET",
            "bucket": self.bucket,
            "key": key,
            "expiresIn": expires_seconds,
        }


def enforce_upload_size(size_bytes, settings=None):
    settings = settings or get_settings()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024

    if int(size_bytes or 0) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Arquivo excede o limite de {settings.max_upload_size_mb} MB.",
        )

    return max_bytes

