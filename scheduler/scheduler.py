import time
from datetime import datetime

from backup.backup_manager import is_schedule_due
from backup.backup_manager import is_priority_backup_policy_enabled
from backup.backup_manager import mark_schedule_executed
from backup.backup_manager import run_backup_job
from backup.backup_manager import run_priority_backup_job


def start_scheduler():
    print("Agendador de backup iniciado.")
    last_priority_check_at = None
    priority_check_interval_seconds = 600

    while True:
        now = datetime.now()

        try:
            if is_schedule_due(now):
                result = run_backup_job(
                    trigger="agendado",
                    username="sistema",
                    user_role="system"
                )
                mark_schedule_executed(now)
                print(f"Backup agendado criado: {result['backup_path']}")
        except Exception as error:
            print(f"Erro ao executar backup agendado: {error}")

        try:
            should_check_priority = (
                last_priority_check_at is None
                or (now - last_priority_check_at).total_seconds() >= priority_check_interval_seconds
            )

            if is_priority_backup_policy_enabled() and should_check_priority:
                last_priority_check_at = now
                result = run_priority_backup_job(
                    trigger="politica_prioridade",
                    username="sistema",
                    user_role="system"
                )

                if result.get("skipped"):
                    print(f"Backup por prioridade ignorado: {result.get('reason')}")
                else:
                    print(f"Backup por prioridade criado: {result['backup_path']}")
        except Exception as error:
            print(f"Erro ao executar backup por prioridade: {error}")

        time.sleep(20)
