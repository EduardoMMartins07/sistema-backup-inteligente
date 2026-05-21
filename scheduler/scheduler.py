from datetime import datetime

from backup.backup_manager import is_schedule_due
from backup.backup_manager import is_priority_backup_policy_enabled
from backup.backup_manager import get_priority_scheduler_check_interval_seconds
from backup.backup_manager import get_schedule_run_context
from backup.backup_manager import is_backup_job_running
from backup.backup_manager import load_schedule
from backup.backup_manager import mark_schedule_executed
from backup.backup_manager import mark_schedule_failed
from backup.backup_manager import mark_schedule_running
from backup.backup_manager import run_backup_job
from backup.backup_manager import run_priority_backup_job
from scanner.scanner import is_shutdown_requested
from scanner.scanner import wait_for_shutdown


def execute_scheduled_backup_once(now=None):
    now = now or datetime.now()

    if not is_schedule_due(now):
        return None

    if is_backup_job_running():
        print("Backup agendado ignorado: outro backup esta em andamento.")
        return None

    schedule = load_schedule()
    context = get_schedule_run_context(schedule)
    mark_schedule_running(now)

    try:
        result = run_backup_job(
            trigger="agendado",
            username=context["username"],
            user_role=context["user_role"],
            company_id=context["company_id"]
        )
        mark_schedule_executed(now)
        print(f"Backup agendado criado: {result['backup_path']}")
        return True
    except Exception as error:
        mark_schedule_failed(error, now=now, context=context)
        print(f"Erro ao executar backup agendado: {error}")
        return False


def start_scheduler():
    print("Agendador de backup iniciado.")
    last_priority_check_at = None
    priority_check_interval_seconds = get_priority_scheduler_check_interval_seconds()
    print(
        "Intervalo de verificacao da politica de prioridade: "
        f"{priority_check_interval_seconds}s"
    )

    while True:
        if is_shutdown_requested():
            print("Agendador interrompido (shutdown).")
            break

        now = datetime.now()
        priority_check_interval_seconds = get_priority_scheduler_check_interval_seconds()

        execute_scheduled_backup_once(now)

        try:
            should_check_priority = (
                last_priority_check_at is None
                or (now - last_priority_check_at).total_seconds() >= priority_check_interval_seconds
            )

            priority_policy_enabled = is_priority_backup_policy_enabled()

            if (
                priority_policy_enabled
                and should_check_priority
                and not is_backup_job_running()
            ):
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
            elif priority_policy_enabled and should_check_priority and is_backup_job_running():
                print("Backup por prioridade ignorado: outro backup esta em andamento.")
        except Exception as error:
            print(f"Erro ao executar backup por prioridade: {error}")

        if wait_for_shutdown(20):
            print("Agendador interrompido (shutdown).")
            break
