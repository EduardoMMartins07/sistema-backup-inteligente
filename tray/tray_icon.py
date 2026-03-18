import pystray
from pystray import MenuItem as item
from PIL import Image, ImageDraw
import threading

from interface.gui import start_gui
from scanner.scanner import run_scanner


def create_image():

    # cria um ícone simples
    image = Image.new("RGB", (64, 64), (0, 120, 215))
    dc = ImageDraw.Draw(image)

    dc.rectangle((16, 16, 48, 48), fill="white")

    return image


def open_gui(icon, item):

    threading.Thread(target=start_gui).start()


def run_backup(icon, item):

    print("Executando scanner manual...")
    run_scanner()


def exit_app(icon, item):

    print("Encerrando sistema...")
    icon.stop()


def start_tray():

    icon = pystray.Icon(
        "SmartBackup",
        create_image(),
        "Sistema de Backup Inteligente",
        menu=pystray.Menu(
            item("Abrir painel", open_gui),
            item("Executar scan", run_backup),
            item("Sair", exit_app)
        )
    )

    icon.run()
