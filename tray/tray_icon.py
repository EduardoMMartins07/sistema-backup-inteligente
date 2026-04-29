import pystray
from pystray import MenuItem as item
from PIL import Image, ImageDraw
import threading
import os
import json

from auth.permissions import can
from interface.login import login_user
from interface.gui import start_gui
from scanner.scanner import run_scanner

ICON_PATH = os.path.join("assets", "nuvem.png")
CONFIG_PATH = os.path.join("config", "config.json")
HISTORY_PATH = os.path.join("config", "backup_history.json")
MAX_TRAY_TITLE_LENGTH = 120
MAX_MENU_PATH_LENGTH = 48


def create_image():
    if os.path.exists(ICON_PATH):
        try:
            return Image.open(ICON_PATH)
        except OSError:
            pass

    # cria um ícone simples
    image = Image.new("RGB", (64, 64), (0, 120, 215))
    dc = ImageDraw.Draw(image)

    dc.rectangle((16, 16, 48, 48), fill="white")

    return image


def load_json(path, default):
    if not os.path.exists(path):
        return default

    with open(path, "r", encoding="utf-8") as file:
        try:
            data = json.load(file)
        except json.JSONDecodeError:
            return default

    return data if isinstance(data, type(default)) else default


def get_backup_destination():
    config = load_json(CONFIG_PATH, {})
    return config.get("backup_destination", "backups")


def get_latest_backup_timestamp():
    history = load_json(HISTORY_PATH, [])

    if not history:
        return "Nenhum backup"

    return history[-1].get("timestamp", "Data desconhecida")


def shorten_text(text, max_length):
    if len(text) <= max_length:
        return text

    return f"{text[:max_length - 3]}..."


def format_destination_for_menu(path):
    normalized_path = str(path)
    return shorten_text(normalized_path, MAX_MENU_PATH_LENGTH)


def build_tray_title():
    title = (
        "SmartBackup | "
        f"Ultimo backup: {get_latest_backup_timestamp()}"
    )
    return shorten_text(title, MAX_TRAY_TITLE_LENGTH)


def build_menu():
    return pystray.Menu(
        item("Abrir painel", open_gui, default=True),
        item(f"Ultimo backup: {get_latest_backup_timestamp()}", None, enabled=False),
        item(
            f"Destino: {format_destination_for_menu(get_backup_destination())}",
            None,
            enabled=False
        ),
        item("Executar scan", run_backup),
        item("Sair", exit_app)
    )


def open_gui(icon, item):

    threading.Thread(target=start_gui).start()


def run_backup(icon, item):

    user = login_user()

    if not can(user, "run_backup"):
        print("Acesso negado para executar scanner manual.")
        return

    print(f"Executando scanner manual por {user.get('username')}...")
    run_scanner()


def exit_app(icon, item):

    print("Encerrando sistema...")
    icon.stop()


def start_tray():

    icon = pystray.Icon(
        "SmartBackup",
        create_image(),
        build_tray_title(),
        menu=build_menu()
    )

    icon.run()
