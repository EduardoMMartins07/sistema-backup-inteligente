from typing import Any

from pydantic import BaseModel, Field


class FirstAdminPayload(BaseModel):
    companyName: str = Field(default="Empresa")
    name: str
    email: str
    password: str


class CompanyCreatePayload(BaseModel):
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


class BackupMetadataPayload(BaseModel):
    backup_id: str | None = None
    backupId: str | None = None
    company_id: str | None = None
    companyId: str | None = None
    user_id: str | None = None
    userId: str | None = None
    user_name: str | None = None
    userName: str | None = None
    backup_name: str | None = None
    backupName: str | None = None
    name: str | None = None
    backup_type: str | None = None
    backupType: str | None = None
    type: str | None = None
    priority: str | None = None
    status: str | None = None
    created_at: str | None = None
    createdAt: str | None = None
    started_at: str | None = None
    startedAt: str | None = None
    finished_at: str | None = None
    finishedAt: str | None = None
    file_count: int | None = None
    fileCount: int | None = None
    total_size_bytes: int | None = None
    totalSizeBytes: int | None = None
    sizeBytes: int | None = None
    storage_target: str | None = None
    storageTarget: str | None = None
    remote_path: str | None = None
    remotePath: str | None = None
    local_path: str | None = None
    localPath: str | None = None
    items: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] | None = None


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


class DesktopConfigPayload(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)
    history: list[dict[str, Any]] = Field(default_factory=list)
    deviceId: str | None = None
