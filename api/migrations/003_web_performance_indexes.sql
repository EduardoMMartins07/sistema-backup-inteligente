CREATE INDEX IF NOT EXISTS idx_backups_company_created
    ON backups(company_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_backups_company_status_created
    ON backups(company_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_backups_company_device_created
    ON backups(company_id, device_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_devices_company_last_seen
    ON devices(company_id, last_seen_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_logs_company_created
    ON audit_logs(company_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_snapshots_company_created
    ON snapshots(company_id, created_at DESC);
