import threading
import os
import json
import queue
import sys
import traceback


# Hook global: qualquer excecao nao capturada em qualquer thread sera
# impressa no terminal com traceback completo.
def _global_exception_hook(exc_type, exc_value, exc_traceback):
    print("\n=== ERRO NAO CAPTURADO ===", file=sys.stderr)
    traceback.print_exception(exc_type, exc_value, exc_traceback)
    print("==========================\n", file=sys.stderr)


sys.excepthook = _global_exception_hook
threading.excepthook = lambda args: _global_exception_hook(
    args.exc_type, args.exc_value, args.exc_traceback
)

from monitor.monitor import start_monitor
from scheduler.scheduler import start_scheduler
from tray.tray_icon import start_tray
from interface.gui import start_gui
from interface.login import login_user
from auth.permissions import can
from auth.users import users_exist
from scanner.scanner import run_scanner
from scanner.scanner import set_shutdown_event

CONFIG_FILE = "config/config.json"
TRAY_OPEN_GUI_EVENT = "open_gui"
TRAY_RUN_BACKUP_EVENT = "run_backup"
TRAY_EXIT_EVENT = "exit"

# Evento global de encerramento: quando setado, todas as threads em segundo
# plano (monitor, scheduler, classificacao) devem parar imediatamente.
SHUTDOWN_EVENT = threading.Event()


def shutdown_all():
    """Sinaliza parada para todas as threads e aguarda finalizacao."""
    if SHUTDOWN_EVENT.is_set():
        return
    print("\nEncerrando sistema...")
    SHUTDOWN_EVENT.set()


def wait_for_background_threads(threads, join_timeout=2.0):
    for thread in threads or []:
        if not thread or thread is threading.current_thread():
            continue

        if thread.is_alive():
            thread.join(timeout=join_timeout)


def first_run():

    if not os.path.exists(CONFIG_FILE):
        return True

    try:
        with open(CONFIG_FILE) as f:
            data = json.load(f)

            if not data.get("directories"):
                return True

    except:
        return True

    return False


def ensure_folders():
    os.makedirs("config", exist_ok=True)
    os.makedirs("dataset", exist_ok=True)
    os.makedirs("ml", exist_ok=True)


def run_tray_event_loop(tray_events, tray_thread):
    while tray_thread.is_alive():
        try:
            event = tray_events.get(timeout=0.2)
        except queue.Empty:
            if SHUTDOWN_EVENT.is_set():
                break
            continue

        if event == TRAY_OPEN_GUI_EVENT:
            start_gui()
        elif event == TRAY_RUN_BACKUP_EVENT:
            run_tray_backup_request()
        elif event == TRAY_EXIT_EVENT:
            shutdown_all()
            break

    tray_thread.join()


def run_tray_backup_request():
    user = login_user()

    if not can(user, "run_backup"):
        print("Acesso negado para executar scanner manual.")
        return

    print(f"Executando scanner manual por {user.get('username')}...")
    from scanner.scanner import run_classification_background
    run_scanner(classify_files=False, should_cancel=SHUTDOWN_EVENT.is_set)
    run_classification_background()


if __name__ == "__main__":

    print("Iniciando Smart Backup...")
    ensure_folders()
    set_shutdown_event(SHUTDOWN_EVENT)

    if first_run() or not users_exist():
        print("Primeira execução detectada")

    # iniciar monitoramento
    monitor_thread = threading.Thread(target=start_monitor)
    monitor_thread.daemon = True
    monitor_thread.start()

    # iniciar agendador de backup
    scheduler_thread = threading.Thread(target=start_scheduler)
    scheduler_thread.daemon = True
    scheduler_thread.start()

    # abrir login/painel na thread principal do Tkinter
    try:
        start_gui()
    except SystemExit:
        raise
    except Exception as error:
        print(f"\nERRO na interface grafica: {error}")
        traceback.print_exc()
        print("O sistema continuara em segundo plano na bandeja.\n")

    print("\n[DEBUG] start_gui() retornou - continuando para a bandeja...")

    # após fechar a janela, o sistema continua em segundo plano na bandeja
    print("\nO sistema continua ativo na bandeja do Windows (icone ao lado do relogio).")
    print("Use o icone para abrir o painel, executar backup manual ou encerrar.\n")
    tray_events = queue.Queue()

    def request_open_gui():
        tray_events.put(TRAY_OPEN_GUI_EVENT)

    def request_run_backup():
        tray_events.put(TRAY_RUN_BACKUP_EVENT)

    def request_exit():
        shutdown_all()
        tray_events.put(TRAY_EXIT_EVENT)

    tray_thread = threading.Thread(
        target=start_tray,
        kwargs={
            "on_open_gui": request_open_gui,
            "on_run_backup": request_run_backup,
            "on_exit": request_exit,
        },
        daemon=False,
    )
    tray_thread.start()
    run_tray_event_loop(tray_events, tray_thread)
    wait_for_background_threads([monitor_thread, scheduler_thread])

    print("\nSistema encerrado.")
