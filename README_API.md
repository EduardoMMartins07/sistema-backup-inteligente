# API Central Smart Backup

Base local: `http://127.0.0.1:8000`

Autenticacao: use `Authorization: Bearer <token>` nas rotas JSON protegidas. O painel web usa cookie JWT `HttpOnly`.

## Operacao

### `GET /health`
- Publico.
- Verifica se a API esta online.
- Resposta: `{"status":"ok","service":"backup-api","version":"1.0.0","environment":"development","timestamp":"..."}`.

### `GET /ready`
- Publico.
- Verifica banco, S3 e variaveis obrigatorias.
- `200` quando pronto; `503` quando algum item falha.

### `GET /version`
- Publico.
- Retorna nome, versao e ambiente.

## Auth

### `POST /setup/first-admin`
- Publico apenas quando a base nao possui usuarios.
- Payload:
```json
{"companyName":"Empresa Demo","name":"Admin","email":"admin@demo.com","password":"senha-forte"}
```

### `POST /auth/login`
- Publico, com rate limit basico.
- Payload:
```json
{"email":"admin@demo.com","password":"senha-forte"}
```
- Resposta: token JWT e usuario.

### `GET /auth/me`
- Requer JWT.
- Roles: `ADMIN_EMPRESA`, `OPERADOR`, `VIEWER`.

## Agente

### `POST /devices/register`
- Requer JWT.
- Roles: `ADMIN_EMPRESA`, `OPERADOR`.
- Payload:
```json
{"name":"Notebook Joao","hostname":"JOAO-PC","identifier":"uuid-do-agente"}
```

### `POST /monitored-folders`
- Requer JWT.
- Roles: `ADMIN_EMPRESA`, `OPERADOR`.
- Payload:
```json
{"deviceId":"device_id","path":"C:/Projetos","alias":"Projetos"}
```

### `POST /backups`
- Requer JWT.
- Roles: `ADMIN_EMPRESA`, `OPERADOR`.
- A API ignora `companyId` vindo do cliente.
- Payload:
```json
{
  "deviceId": "device_id",
  "folderId": "folder_id",
  "name": "backup.zip",
  "type": "INCREMENTAL",
  "priority": "HIGH",
  "sizeBytes": 10485760,
  "fileCount": 25,
  "checksum": "sha256",
  "metadata": {"os": "Windows"}
}
```

### `POST /backups/presigned-url`
- Requer JWT.
- Roles: `ADMIN_EMPRESA`, `OPERADOR`.
- Gera URL pre-assinada para upload direto no S3.
- Payload:
```json
{"backupId":"backup_id","fileName":"backup.zip","contentType":"application/zip","sizeBytes":10485760}
```
- Erro comum: `503` se S3 nao estiver configurado.

### `POST /backups/{backupId}/upload`
- Requer JWT.
- Roles: `ADMIN_EMPRESA`, `OPERADOR`.
- Upload via backend em `multipart/form-data`, campo `file`.
- Respeita `MAX_UPLOAD_SIZE_MB`.

### `PATCH /backups/{backupId}/finish`
- Requer JWT.
- Roles: `ADMIN_EMPRESA`, `OPERADOR`.
- Payload:
```json
{"status":"SUCCESS","s3Key":"backups/.../backup.zip"}
```

### `GET /backups`
- Requer JWT.
- Admin e viewer veem backups da empresa; operador ve os proprios.
- Filtros: `userId`, `deviceId`, `folderId`, `status`, `type`, `priority`, `startDate`, `endDate`.

## Admin

### `GET /admin/dashboard`
- Requer `ADMIN_EMPRESA`.
- Retorna resumo da empresa e backups recentes.

### `GET /admin/users`
- Requer `ADMIN_EMPRESA`.

### `POST /admin/users`
- Requer `ADMIN_EMPRESA`.
- Payload:
```json
{"name":"Operador","email":"op@empresa.com","password":"senha-forte","role":"OPERADOR"}
```

### `GET /admin/users/{userId}/backups`
- Requer `ADMIN_EMPRESA`.
- Valida que o usuario pertence a mesma empresa.

### `GET /admin/devices/{deviceId}/backups`
- Requer `ADMIN_EMPRESA`.
- Valida que o dispositivo pertence a mesma empresa.

### `GET /admin/audit-logs`
- Requer `ADMIN_EMPRESA`.
- Filtros: `event`, `startDate`, `endDate`.

## Snapshots

### `POST /snapshots`
- Requer JWT.
- Roles: `ADMIN_EMPRESA`, `OPERADOR`.
- Payload:
```json
{"backupId":"backup_id","name":"snapshot-final","sizeBytes":123,"fileCount":10}
```

### `GET /snapshots`
- Requer JWT.

### `GET /backups/{backupId}/snapshots`
- Requer JWT.

