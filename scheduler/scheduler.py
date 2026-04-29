import time
from datetime import datetime

from backup.backup_manager import is_schedule_due
from backup.backup_manager import mark_schedule_executed
from backup.backup_manager import run_backup_job


def start_scheduler():
    print("Agendador de backup iniciado.")

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

        time.sleep(20)
