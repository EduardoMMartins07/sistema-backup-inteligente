import threading
import os
import json

from scanner.scanner import run_scanner
from monitor.monitor import start_monitor
from tray.tray_icon import start_tray
from interface.gui import start_gui

CONFIG_FILE = "config/config.json"


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


if __name__ == "__main__":

    print("Iniciando Smart Backup...")
    ensure_folders()

    # verificar primeira execução
    if first_run():
        print("Primeira execução detectada")
        start_gui()

    # scanner inicial
    run_scanner()

    # iniciar monitoramento
    monitor_thread = threading.Thread(target=start_monitor)
    monitor_thread.daemon = True
    monitor_thread.start()

    # iniciar tray icon
    start_tray()