import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from backup.backup_manager import get_backup_destination
from backup.backup_manager import get_monitored_directories
from backup.backup_manager import is_backup_job_running
from backup.backup_manager import is_path_ignored
from scanner.scanner import run_scanner
from scanner.scanner import run_classification_background
from scanner.scanner import is_shutdown_requested
from scanner.scanner import wait_for_shutdown


class BackupMonitor(FileSystemEventHandler):

    def __init__(self, cooldown_seconds=2):
        super().__init__()
        self.cooldown_seconds = cooldown_seconds
        self.last_scan_at = 0

    def should_scan(self, path):
        if is_shutdown_requested():
            return False
        if not path or is_path_ignored(path):
            return False

        now = time.time()

        if now - self.last_scan_at < self.cooldown_seconds:
            return False

        self.last_scan_at = now
        return True

    def _trigger_scan(self):
        """Executa o scanner rapido e dispara classificacao em background."""
        if is_shutdown_requested():
            return
        if is_backup_job_running():
            print("Scanner do monitor ignorado: backup em andamento.")
            return
        try:
            run_scanner(classify_files=False)
            run_classification_background()
        except Exception as error:
            print(f"Erro no scanner do monitor: {error}")

    def on_created(self, event):

        if not event.is_directory and self.should_scan(event.src_path):
            print("Arquivo criado:", event.src_path)
            self._trigger_scan()

    def on_modified(self, event):

        if not event.is_directory and self.should_scan(event.src_path):
            print("Arquivo modificado:", event.src_path)
            self._trigger_scan()

    def on_deleted(self, event):

        if not event.is_directory and self.should_scan(event.src_path):
            print("Arquivo deletado:", event.src_path)
            self._trigger_scan()

    def on_moved(self, event):

        if not event.is_directory and self.should_scan(event.dest_path):
            print("Arquivo movido:", event.dest_path)
            self._trigger_scan()


def start_monitor():

    directories = get_monitored_directories()

    if not directories:
        print("Nenhum diretório configurado.")
        return

    event_handler = BackupMonitor()
    observer = Observer()
    backup_destination = get_backup_destination()

    for directory in directories:
        if is_path_ignored(directory, backup_destination=backup_destination):
            continue

        print("Monitorando:", directory)

        observer.schedule(event_handler, directory, recursive=True)

    observer.start()

    try:
        while True:
            if is_shutdown_requested() or wait_for_shutdown(5):
                print("Monitor interrompido (shutdown).")
                break
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join()
