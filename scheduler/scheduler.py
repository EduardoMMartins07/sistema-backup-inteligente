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


def _ts():
    return datetime.now().strftime("%H:%M:%S")


def execute_scheduled_backup_once(now=None):
    now = now or datetime.now()

    if not is_schedule_due(now):
        return None

    if is_backup_job_running():
        print(f"[{_ts()}] Backup agendado ignorado: outro backup esta em andamento.")
        return None

    schedule = load_schedule()
    context = get_schedule_run_context(schedule)
    mark_schedule_running(now)

    try:
        result = run_backup_job(
            trigger="agendado",
            username=context["username"],
            user_role=context["user_role"],
            company_id=context["company_id"],
            now=now
        )
        mark_schedule_executed(now)
        print(f"[{_ts()}] Backup agendado criado: {result['backup_path']}")
        return True
    except Exception as error:
        mark_schedule_failed(error, now=now, context=context)
        print(f"[{_ts()}] Erro ao executar backup agendado: {error}")
        return False


def start_scheduler():
    print(f"[{_ts()}] Agendador de backup iniciado.")
    last_priority_check_at = None
    priority_check_interval_seconds = get_priority_scheduler_check_interval_seconds()
    print(
        f"[{_ts()}] Intervalo de verificacao da politica de prioridade: "
        f"{priority_check_interval_seconds}s"
    )

    while True:
        if is_shutdown_requested():
            print(f"[{_ts()}] Agendador interrompido (shutdown).")
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

                from backup.backup_manager import is_dev_mode_enabled
                if is_dev_mode_enabled():
                    print(f"[{_ts()}] [DEV MODE] Verificando arquivos por prioridade...")

                schedule = load_schedule()
                context = get_schedule_run_context(schedule)
                result = run_priority_backup_job(
                    trigger="politica_prioridade",
                    username=context["username"],
                    user_role=context["user_role"],
                    company_id=context["company_id"],
                    now=now
                )

                if result.get("skipped"):
                    print(f"[{_ts()}] Backup por prioridade ignorado: {result.get('reason')}")
                elif is_dev_mode_enabled():
                    print(f"[{_ts()}] [DEV MODE] Backup por prioridade criado: {result['backup_path']}")
                else:
                    print(f"[{_ts()}] Backup por prioridade criado: {result['backup_path']}")
            elif priority_policy_enabled and should_check_priority and is_backup_job_running():
                print(f"[{_ts()}] Backup por prioridade ignorado: outro backup esta em andamento.")
        except Exception as error:
            import traceback
            print(f"[{_ts()}] Erro ao executar backup por prioridade: {error}")
            traceback.print_exc()

        if wait_for_shutdown(20):
            print(f"[{_ts()}] Agendador interrompido (shutdown).")
            break
