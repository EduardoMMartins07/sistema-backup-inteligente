import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from scanner.scanner import run_scanner
from scanner.scanner import load_directories


class BackupMonitor(FileSystemEventHandler):

    def on_created(self, event):

        if not event.is_directory:
            print("Arquivo criado:", event.src_path)
            run_scanner()

    def on_modified(self, event):

        if not event.is_directory:
            print("Arquivo modificado:", event.src_path)
            run_scanner()

    def on_deleted(self, event):

        if not event.is_directory:
            print("Arquivo deletado:", event.src_path)
            run_scanner()


def start_monitor():

    directories = load_directories()

    if not directories:
        print("Nenhum diretório configurado.")
        return

    event_handler = BackupMonitor()
    observer = Observer()

    for directory in directories:

        print("Monitorando:", directory)

        observer.schedule(event_handler, directory, recursive=True)

    observer.start()

    try:

        while True:
            time.sleep(5)

    except KeyboardInterrupt:

        observer.stop()

    observer.join()