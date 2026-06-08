import pystray
from pystray import MenuItem as item
from PIL import Image, ImageDraw
import os
import json
from auth.local_context import get_current_user
from utils import user_data_paths

ICON_PATH = os.path.join("assets", "nuvem.png")
CONFIG_PATH = os.path.join("config", "config.json")
HISTORY_PATH = os.path.join("config", "backup_history.json")
DEFAULT_CONFIG_PATH = CONFIG_PATH
DEFAULT_HISTORY_PATH = HISTORY_PATH
MAX_TRAY_TITLE_LENGTH = 120
MAX_MENU_PATH_LENGTH = 48
_on_open_gui = None
_on_run_backup = None
_on_exit = None
_active_icon = None


def configure_tray_callbacks(on_open_gui=None, on_run_backup=None, on_exit=None):
    global _on_open_gui
    global _on_run_backup
    global _on_exit

    _on_open_gui = on_open_gui
    _on_run_backup = on_run_backup
    _on_exit = on_exit


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


def resolve_user_scoped_path(configured_path, default_path, filename):
    if os.path.abspath(configured_path) != os.path.abspath(default_path):
        return configured_path

    scoped_path = user_data_paths.get_current_user_file_path(filename)
    return scoped_path or configured_path


def get_backup_destination():
    config = load_json(
        resolve_user_scoped_path(CONFIG_PATH, DEFAULT_CONFIG_PATH, "config.json"),
        {},
    )
    return config.get("backup_destination", "backups")


def get_latest_backup_timestamp():
    history = load_json(
        resolve_user_scoped_path(
            HISTORY_PATH,
            DEFAULT_HISTORY_PATH,
            "backup_history.json",
        ),
        [],
    )

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


def is_exit_enabled(user=None):
    current_user = user if user is not None else get_current_user()
    role = (current_user or {}).get("role")
    return role in {"admin", "operator"}


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
        item("Sair", exit_app, enabled=is_exit_enabled())
    )


def open_gui(icon, item):

    if callable(_on_open_gui):
        _on_open_gui()
        return

    print("Painel nao pode ser aberto: callback da interface nao configurado.")


def run_backup(icon, item):

    if callable(_on_run_backup):
        _on_run_backup()
        return

    print("Scanner nao pode ser executado: callback nao configurado.")


def exit_app(icon, item):

    if callable(_on_exit):
        _on_exit()


def stop_tray():
    if _active_icon is not None:
        _active_icon.stop()


def start_tray(on_open_gui=None, on_run_backup=None, on_exit=None):
    global _active_icon

    configure_tray_callbacks(
        on_open_gui=on_open_gui,
        on_run_backup=on_run_backup,
        on_exit=on_exit,
    )

    icon = pystray.Icon(
        "SmartBackup",
        create_image(),
        build_tray_title(),
        menu=build_menu()
    )

    _active_icon = icon
    try:
        icon.run()
    finally:
        if _active_icon is icon:
            _active_icon = None
