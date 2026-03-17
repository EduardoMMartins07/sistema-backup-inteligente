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


if __name__ == "__main__":

    print("Iniciando Smart Backup...")

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