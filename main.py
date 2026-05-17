import threading
import os
import json
import queue

from monitor.monitor import start_monitor
from scheduler.scheduler import start_scheduler
from tray.tray_icon import start_tray
from interface.gui import start_gui
from interface.login import login_user
from auth.permissions import can
from auth.users import users_exist
from scanner.scanner import run_scanner

CONFIG_FILE = "config/config.json"
TRAY_OPEN_GUI_EVENT = "open_gui"
TRAY_RUN_BACKUP_EVENT = "run_backup"
TRAY_EXIT_EVENT = "exit"


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
    import os

    os.makedirs("config", exist_ok=True)
    os.makedirs("dataset", exist_ok=True)
    os.makedirs("ml", exist_ok=True)


def run_tray_event_loop(tray_events, tray_thread):
    while tray_thread.is_alive():
        try:
            event = tray_events.get(timeout=0.2)
        except queue.Empty:
            continue

        if event == TRAY_OPEN_GUI_EVENT:
            start_gui()
        elif event == TRAY_RUN_BACKUP_EVENT:
            run_tray_backup_request()
        elif event == TRAY_EXIT_EVENT:
            break

    tray_thread.join()


def run_tray_backup_request():
    user = login_user()

    if not can(user, "run_backup"):
        print("Acesso negado para executar scanner manual.")
        return

    print(f"Executando scanner manual por {user.get('username')}...")
    run_scanner()


if __name__ == "__main__":

    print("Iniciando Smart Backup...")
    ensure_folders()

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
    start_gui()

    # após fechar a janela, o sistema continua em segundo plano na bandeja
    tray_events = queue.Queue()

    def request_open_gui():
        tray_events.put(TRAY_OPEN_GUI_EVENT)

    def request_run_backup():
        tray_events.put(TRAY_RUN_BACKUP_EVENT)

    def request_exit():
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
