from typing import Any

from pydantic import BaseModel, Field


class FirstAdminPayload(BaseModel):
    companyName: str = Field(default="Empresa")
    name: str
    email: str
    password: str


class LoginPayload(BaseModel):
    email: str
    password: str


class UserCreatePayload(BaseModel):
    name: str
    email: str
    password: str
    role: str


class UserUpdatePayload(BaseModel):
    name: str | None = None
    role: str | None = None
    status: str | None = None


class DeviceRegisterPayload(BaseModel):
    name: str
    hostname: str
    identifier: str


class MonitoredFolderPayload(BaseModel):
    deviceId: str
    path: str
    alias: str | None = None


class BackupCreatePayload(BaseModel):
    deviceId: str
    folderId: str
    name: str
    type: str = "INCREMENTAL"
    status: str | None = None
    priority: str = "NORMAL"
    sizeBytes: int = 0
    fileCount: int = 0
    checksum: str | None = ""
    metadata: dict[str, Any] | None = None
    companyId: str | None = None


class BackupFinishPayload(BaseModel):
    status: str
    finishedAt: str | None = None
    s3Key: str | None = None
    errorMessage: str | None = None


class PresignedUrlPayload(BaseModel):
    backupId: str
    fileName: str = "backup.zip"
    contentType: str = "application/zip"
    sizeBytes: int = 0


class SnapshotPayload(BaseModel):
    backupId: str
    name: str
    s3Key: str | None = None
    sizeBytes: int = 0
    fileCount: int = 0
    checksum: str | None = ""
