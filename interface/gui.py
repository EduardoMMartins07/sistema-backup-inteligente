import csv
import json
import os
import queue
import re
import shutil
import tempfile
import threading
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from auth.permissions import can
from auth.permissions import can_view_backup_entry
from auth.permissions import get_role_label
from auth.permissions import get_role_options
from auth.users import create_user
from auth.users import delete_user
from auth.users import list_public_users
from auth.users import update_user
from backup.backup_manager import BackupCancelledError
from backup.backup_manager import build_recovered_file_path
from backup.backup_manager import build_recovered_folder_path
from backup.backup_manager import build_restore_target
from backup.backup_manager import get_latest_backup_path
from backup.backup_manager import get_user_backup_destination
from backup.backup_manager import inspect_restore_changes
from backup.backup_manager import is_path_ignored
from backup.backup_manager import export_snapshot_to_zip
from backup.backup_manager import restore_recoverable_changes
from backup.backup_manager import restore_snapshot
from backup.backup_manager import run_backup_job

CONFIG_PATH = "config/config.json"
BACKUP_DIR = "backups"
HISTORY_PATH = "config/backup_history.json"
SCHEDULE_PATH = "config/backup_schedule.json"
ICON_PATH = os.path.join("assets", "nuvem.png")
DEFAULT_PRIORITY_BACKUP_POLICY_ENABLED = True

BG_COLOR = "#283241"
PANEL_COLOR = "#1F2733"
TITLE_COLOR = "#FF990F"
LIGHT_BUTTON = "#D9D9D9"
TEXT_COLOR = "#101010"
SUBTLE_TEXT = "#E7EAF0"
BORDER_COLOR = "#3A4657"
CARD_COLOR = "#344153"
CARD_ACCENT = "#3F5067"
HOME_PANEL_COLOR = "#2E3949"
MUTED_PANEL_COLOR = "#25303F"
DEFAULT_FONT = ("Segoe UI", 10)
BODY_FONT = ("Segoe UI", 10)
BODY_BOLD_FONT = ("Segoe UI", 10, "bold")
TABLE_FONT = ("Segoe UI", 10, "bold")
TABLE_HEADING_FONT = ("Segoe UI", 10, "bold")
SUGGESTION_FONT = ("Segoe UI", 10, "bold")
TITLE_FONT = ("Segoe UI Black", 22, "bold")
MENU_TITLE_FONT = ("Segoe UI Black", 30, "bold")
MENU_BUTTON_FONT = ("Segoe UI", 13, "bold")
BUTTON_FONT = ("Segoe UI", 10, "bold")
HOME_TITLE_FONT = ("Segoe UI Black", 28, "bold")
HOME_SUBTITLE_FONT = ("Segoe UI", 12)
CARD_VALUE_FONT = ("Segoe UI Black", 24, "bold")
CARD_LABEL_FONT = ("Segoe UI", 11, "bold")

BACKUP_STATUS_IN_BACKUP = "Em backup"
BACKUP_STATUS_PENDING = "Fará backup"
BACKUP_STATUS_PENDING_DELETE = "Será excluído"
BACKUP_STATUS_OPTIONS = (
    BACKUP_STATUS_IN_BACKUP,
    BACKUP_STATUS_PENDING,
    BACKUP_STATUS_PENDING_DELETE,
)

_background_root = None
_background_gui = None


def normalize_file_source_key(path):
    if not path:
        return ""

    return os.path.normcase(os.path.abspath(os.path.normpath(str(path))))


def normalize_file_archive_key(archive_name):
    return str(archive_name or "").replace("\\", "/").strip("/")


def get_history_backup_label(entry):
    return entry.get("backup_name", "") or entry.get("backup_file", "-")


def get_file_extension(file_name):
    return os.path.splitext(str(file_name or ""))[1].lstrip(".").lower()


def format_size_kb_to_mb(size_kb):
    try:
        size_mb = float(size_kb) / 1024
    except (TypeError, ValueError):
        size_mb = 0.0

    return f"{size_mb:.2f}"


def format_size_bytes_to_mb(size_bytes):
    try:
        size_mb = float(size_bytes) / (1024 * 1024)
    except (TypeError, ValueError):
        size_mb = 0.0

    return f"{size_mb:.2f}"


def format_size_bytes_human(size_bytes):
    try:
        size = float(size_bytes)
    except (TypeError, ValueError):
        return "0 B"

    if size >= 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024 * 1024):.2f} GB"

    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.2f} MB"

    if size >= 1024:
        return f"{size / 1024:.2f} KB"

    return f"{int(size)} B"


def iter_history_snapshot_files(entry):
    snapshot = entry.get("file_snapshot", {})

    if not isinstance(snapshot, dict):
        return

    for archive_name, file_data in snapshot.items():
        if not isinstance(file_data, dict):
            continue

        yield normalize_file_archive_key(archive_name), file_data


def build_history_backup_lookup(history):
    added_by_source = {}
    added_by_archive = {}
    latest_snapshot = {}

    for entry in history:
        timestamp = entry.get("timestamp", "-")
        backup_label = get_history_backup_label(entry)
        backup_info = {
            "added_to_backup_at": timestamp,
            "added_in_backup": backup_label,
        }

        for archive_name, file_data in iter_history_snapshot_files(entry) or []:
            source_key = normalize_file_source_key(file_data.get("source_path", ""))

            if source_key and source_key not in added_by_source:
                added_by_source[source_key] = backup_info

            if archive_name and archive_name not in added_by_archive:
                added_by_archive[archive_name] = backup_info

            latest_snapshot[archive_name] = file_data

        for change in entry.get("file_changes", []):
            if not isinstance(change, dict) or change.get("action") != "adicionado":
                continue

            source_key = normalize_file_source_key(change.get("source_path", ""))
            archive_name = normalize_file_archive_key(change.get("archive_name", ""))

            if source_key and source_key not in added_by_source:
                added_by_source[source_key] = backup_info

            if archive_name and archive_name not in added_by_archive:
                added_by_archive[archive_name] = backup_info

    for entry in reversed(history):
        snapshot = entry.get("file_snapshot", {})

        if isinstance(snapshot, dict):
            latest_snapshot = {
                normalize_file_archive_key(archive_name): file_data
                for archive_name, file_data in snapshot.items()
                if isinstance(file_data, dict)
            }
            break

    latest_by_source = {}
    latest_by_archive = {}

    for archive_name, file_data in latest_snapshot.items():
        source_key = normalize_file_source_key(file_data.get("source_path", ""))

        if source_key:
            latest_by_source[source_key] = file_data

        if archive_name:
            latest_by_archive[archive_name] = file_data

    return {
        "added_by_source": added_by_source,
        "added_by_archive": added_by_archive,
        "latest_by_source": latest_by_source,
        "latest_by_archive": latest_by_archive,
        "latest_snapshot": latest_snapshot,
    }


def get_backup_info_for_file(lookup, source_key, archive_key):
    return (
        lookup["added_by_source"].get(source_key)
        or lookup["added_by_archive"].get(archive_key)
        or {
            "added_to_backup_at": "-",
            "added_in_backup": "-",
        }
    )


def build_file_status_rows(dataset_rows, history):
    lookup = build_history_backup_lookup(history)
    rows = []
    current_source_keys = set()
    current_archive_keys = set()

    for row in dataset_rows:
        important = "Sim" if row.get("important") == "1" else "Nao"
        priority = row.get("priority", "").strip() or (
            "alta" if important == "Sim" else "baixa"
        )
        source_path = row.get("source_path", "")
        archive_key = normalize_file_archive_key(row.get("archive_name", ""))
        source_key = normalize_file_source_key(source_path)
        snapshot_file = (
            lookup["latest_by_source"].get(source_key)
            or lookup["latest_by_archive"].get(archive_key)
        )
        current_hash = row.get("file_hash", "")
        snapshot_hash = snapshot_file.get("file_hash", "") if snapshot_file else ""
        backup_status = (
            BACKUP_STATUS_IN_BACKUP
            if snapshot_file and current_hash and current_hash == snapshot_hash
            else BACKUP_STATUS_PENDING
        )
        backup_info = get_backup_info_for_file(lookup, source_key, archive_key)

        if source_key:
            current_source_keys.add(source_key)

        if archive_key:
            current_archive_keys.add(archive_key)

        rows.append(
            {
                "name": row.get("name", ""),
                "extension": row.get("extension", ""),
                "priority": priority,
                "priority_score": row.get("priority_score", ""),
                "added_to_backup_at": backup_info["added_to_backup_at"],
                "added_in_backup": backup_info["added_in_backup"],
                "backup_status": backup_status,
                "size_mb": format_size_kb_to_mb(row.get("size_kb", "0")),
                "days_since_modified": row.get("days_since_modified", ""),
                "source_path": source_path,
                "archive_name": archive_key,
            }
        )

    for archive_key, file_data in lookup["latest_snapshot"].items():
        source_path = file_data.get("source_path", "")
        source_key = normalize_file_source_key(source_path)

        if (
            (source_key and source_key in current_source_keys)
            or (archive_key and archive_key in current_archive_keys)
        ):
            continue

        file_name = file_data.get("name", "") or os.path.basename(source_path)
        backup_info = get_backup_info_for_file(lookup, source_key, archive_key)

        rows.append(
            {
                "name": file_name,
                "extension": get_file_extension(file_name),
                "priority": file_data.get("priority", "-") or "-",
                "priority_score": (
                    file_data.get("priority_score")
                    or file_data.get("score")
                    or "-"
                ),
                "added_to_backup_at": backup_info["added_to_backup_at"],
                "added_in_backup": backup_info["added_in_backup"],
                "backup_status": BACKUP_STATUS_PENDING_DELETE,
                "size_mb": format_size_bytes_to_mb(file_data.get("size_bytes", 0)),
                "days_since_modified": "-",
                "source_path": source_path,
                "archive_name": archive_key,
            }
        )

    return rows


def format_files_view_modified_at(timestamp):
    try:
        return datetime.fromtimestamp(float(timestamp)).strftime("%d/%m/%Y %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return "-"


def format_files_view_days_since_modified(timestamp):
    try:
        return str((datetime.now() - datetime.fromtimestamp(float(timestamp))).days)
    except (TypeError, ValueError, OSError):
        return "-"


class ScrollableFrame(tk.Frame):

    def __init__(
        self,
        parent,
        bg,
        scrollbar_width=14,
        stretch_body=False,
        *args,
        **kwargs
    ):
        super().__init__(parent, bg=bg, *args, **kwargs)
        self.stretch_body = stretch_body
        self.canvas = tk.Canvas(
            self,
            bg=bg,
            bd=0,
            highlightthickness=0,
            relief="flat"
        )
        self.scrollbar = ttk.Scrollbar(
            self,
            orient="vertical",
            command=self.canvas.yview,
            style="Vertical.TScrollbar"
        )
        self.body = tk.Frame(self.canvas, bg=bg)
        self.window_id = self.canvas.create_window(
            (0, 0),
            window=self.body,
            anchor="nw"
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.body.bind("<Configure>", self.sync_scroll_region, add="+")
        self.canvas.bind("<Configure>", self.sync_canvas_width, add="+")
        self.canvas.bind("<Enter>", self.bind_mousewheel, add="+")
        self.canvas.bind("<Leave>", self.unbind_mousewheel, add="+")

        self.scrollbar_width = scrollbar_width

    def sync_scroll_region(self, _event=None):
        if self.stretch_body:
            self.canvas.itemconfigure(
                self.window_id,
                height=max(self.canvas.winfo_height(), self.body.winfo_reqheight())
            )
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.canvas.xview_moveto(0)
        self.update_scrollbar_visibility()

    def sync_canvas_width(self, event):
        self.canvas.itemconfigure(self.window_id, width=event.width)
        if self.stretch_body:
            self.canvas.itemconfigure(
                self.window_id,
                height=max(event.height, self.body.winfo_reqheight())
            )
        self.canvas.xview_moveto(0)
        self.update_scrollbar_visibility()

    def update_scrollbar_visibility(self):
        try:
            body_height = self.body.winfo_reqheight()
            canvas_height = self.canvas.winfo_height()
        except tk.TclError:
            return

        if body_height > canvas_height + 1:
            self.scrollbar.grid(row=0, column=1, sticky="ns")
        else:
            self.scrollbar.grid_remove()
            self.canvas.yview_moveto(0)

    def bind_mousewheel(self, _event=None):
        self.canvas.bind_all("<MouseWheel>", self.on_mousewheel)

    def unbind_mousewheel(self, _event=None):
        self.canvas.unbind_all("<MouseWheel>")

    def on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


class FlowFrame(tk.Frame):

    def __init__(
        self,
        parent,
        bg,
        min_item_width=130,
        hgap=8,
        vgap=8,
        max_columns=None,
        equal_width=True,
        *args,
        **kwargs
    ):
        super().__init__(parent, bg=bg, *args, **kwargs)
        self.min_item_width = min_item_width
        self.hgap = hgap
        self.vgap = vgap
        self.max_columns = max_columns
        self.equal_width = equal_width
        self.items = []
        self.current_columns = None
        self.bind("<Configure>", self.reflow, add="+")

    def add(self, widget):
        self.items.append(widget)
        widget.grid_remove()
        self.after_idle(self.reflow)
        return widget

    def clear(self):
        for widget in self.items:
            widget.grid_forget()
        self.items.clear()
        self.current_columns = None

    def get_column_count(self, width):
        if not self.items:
            return 1

        item_width = max(self.min_item_width, 1)
        columns = max(1, width // (item_width + self.hgap))

        if self.max_columns is not None:
            columns = min(columns, self.max_columns)

        return min(columns, len(self.items))

    def reflow(self, event=None):
        width = event.width if event is not None else self.winfo_width()

        if width <= 1:
            width = self.winfo_reqwidth()

        columns = self.get_column_count(width)

        if columns == self.current_columns:
            return

        self.current_columns = columns

        for widget in self.items:
            widget.grid_forget()

        rows = ((len(self.items) + columns - 1) // columns) + 1

        for row in range(rows):
            self.rowconfigure(row, weight=0, minsize=0)

        for column in range(max(len(self.items), columns)):
            self.columnconfigure(
                column,
                weight=1 if column < columns else 0,
                minsize=0,
                uniform="flow" if self.equal_width and column < columns else ""
            )

        for index, widget in enumerate(self.items):
            row = index // columns
            column = index % columns
            widget.grid(
                row=row,
                column=column,
                sticky="ew",
                padx=(0 if column == 0 else self.hgap, 0),
                pady=(0 if row == 0 else self.vgap, 0)
            )


class BackupGUI:

    def __init__(self, root, current_user):
        self.root = root
        self.current_user = current_user
        self.root.title("Sistema de Backup Inteligente")
        self.root.geometry("1440x900")
        self.root.minsize(1240, 760)
        self.root.resizable(True, True)
        self.root.configure(bg=BG_COLOR)
        self.window_icon_photo = None

        self.directories = []
        self.backup_destination = BACKUP_DIR
        self.backup_in_progress = False
        self.backup_queue = queue.Queue()
        self.progress_window = None
        self.progress_label = None
        self.progress_bar = None
        self.cancel_button = None
        self.download_queue = queue.Queue()
        self.download_window = None
        self.download_label = None
        self.download_bar = None
        self.backup_button = None
        self.schedule_button = None
        self.files_button = None
        self.history_button = None
        self.download_button = None
        self.restore_button = None
        self.manage_button = None
        self.destination_button = None
        self.users_button = None
        self.sidebar_button_frame = None
        self.sidebar_footer_frame = None
        self.content_panel = None
        self.current_view = "home"
        self.dashboard_compacted_size_job_key = None
        self.dashboard_monitored_size_job_key = None
        self.dashboard_monitored_size_bytes = None
        self.dashboard_event_queue = queue.Queue()
        self.dashboard_poll_scheduled = False
        self.logout_requested = False
        self.is_closing = False
        self.pending_backup_name = ""
        self.pending_backup_description = ""
        self.pending_backup_directories = None
        self.pending_backup_trigger = "manual"
        self.cancel_backup_requested = threading.Event()
        self.responsive_font_widgets = []
        self.current_font_scale = None
        self.ui_style = None

        self.configure_window_icon()
        self.configure_widget_styles()
        self.load_directories()
        self.build_layout()
        self.root.protocol("WM_DELETE_WINDOW", self.request_close)
        self.root.bind("<Configure>", self.on_root_resize, add="+")
        self.root.after_idle(self.update_responsive_fonts)

    def configure_window_icon(self):
        if os.name == "nt":
            try:
                import ctypes

                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    "SmartBackup.App"
                )
            except Exception:
                pass

        if not os.path.exists(ICON_PATH):
            return

        try:
            self.window_icon_photo = tk.PhotoImage(file=ICON_PATH)
            self.root.iconphoto(True, self.window_icon_photo)
        except tk.TclError:
            self.window_icon_photo = None

    def configure_widget_styles(self):
        style = ttk.Style()
        self.ui_style = style

        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        self.root.option_add("*Font", DEFAULT_FONT)
        self.root.option_add("*Entry.relief", "flat")
        self.root.option_add("*Entry.highlightThickness", 1)
        self.root.option_add("*Entry.highlightBackground", BORDER_COLOR)
        self.root.option_add("*Entry.highlightColor", TITLE_COLOR)
        self.root.option_add("*Listbox.relief", "flat")
        self.root.option_add("*Listbox.highlightThickness", 1)
        self.root.option_add("*Listbox.highlightBackground", BORDER_COLOR)
        self.root.option_add("*Listbox.highlightColor", TITLE_COLOR)

        style.configure(
            "Treeview",
            background="white",
            fieldbackground="white",
            foreground=TEXT_COLOR,
            font=TABLE_FONT,
            rowheight=30,
            borderwidth=0,
            relief="flat"
        )
        style.configure(
            "Treeview.Heading",
            background="#EEF1F5",
            foreground=TEXT_COLOR,
            font=TABLE_HEADING_FONT,
            relief="flat",
            padding=(8, 7)
        )
        style.map(
            "Treeview",
            background=[("selected", "#0E7DD8")],
            foreground=[("selected", "white")]
        )
        style.configure(
            "Vertical.TScrollbar",
            background="#56667C",
            troughcolor="#18202B",
            bordercolor="#18202B",
            arrowcolor=TITLE_COLOR,
            relief="flat",
            width=12,
            arrowsize=12,
            borderwidth=0,
            lightcolor="#56667C",
            darkcolor="#56667C",
            gripcount=0
        )
        style.configure(
            "Horizontal.TScrollbar",
            background="#56667C",
            troughcolor="#18202B",
            bordercolor="#18202B",
            arrowcolor=TITLE_COLOR,
            relief="flat",
            width=12,
            arrowsize=12,
            borderwidth=0,
            lightcolor="#56667C",
            darkcolor="#56667C",
            gripcount=0
        )
        style.map(
            "Vertical.TScrollbar",
            background=[
                ("pressed", TITLE_COLOR),
                ("active", "#FFB347"),
                ("disabled", "#2A3442"),
            ],
            arrowcolor=[
                ("pressed", TEXT_COLOR),
                ("active", TEXT_COLOR),
                ("disabled", "#4A5568"),
            ],
            troughcolor=[("disabled", "#18202B")]
        )
        style.map(
            "Horizontal.TScrollbar",
            background=[
                ("pressed", TITLE_COLOR),
                ("active", "#FFB347"),
                ("disabled", "#2A3442"),
            ],
            arrowcolor=[
                ("pressed", TEXT_COLOR),
                ("active", TEXT_COLOR),
                ("disabled", "#4A5568"),
            ],
            troughcolor=[("disabled", "#18202B")]
        )
        style.configure(
            "Horizontal.TProgressbar",
            troughcolor=PANEL_COLOR,
            background=TITLE_COLOR,
            bordercolor=BORDER_COLOR,
            lightcolor=TITLE_COLOR,
            darkcolor=TITLE_COLOR,
            thickness=14
        )

    def get_font_scale(self):
        return 1.0

    def scale_font(self, font_tuple, min_size=8, scale=None):
        if scale is None:
            scale = self.get_font_scale()

        family = font_tuple[0]
        size = max(min_size, int(round(font_tuple[1] * scale)))
        options = font_tuple[2:]
        return (family, size, *options)

    def register_responsive_font(self, widget, font_tuple, min_size=8):
        self.responsive_font_widgets.append((widget, font_tuple, min_size))

        try:
            widget.configure(font=self.scale_font(font_tuple, min_size))
        except tk.TclError:
            pass

        return widget

    def on_root_resize(self, event):
        if self.is_closing:
            return

        if event.widget == self.root:
            self.update_responsive_fonts()

    def update_responsive_fonts(self):
        if self.is_closing:
            return

        scale = round(self.get_font_scale(), 2)

        if self.current_font_scale == scale:
            return

        self.current_font_scale = scale
        live_widgets = []

        for widget, font_tuple, min_size in self.responsive_font_widgets:
            try:
                if not widget.winfo_exists():
                    continue

                widget.configure(font=self.scale_font(font_tuple, min_size, scale))
                live_widgets.append((widget, font_tuple, min_size))
            except tk.TclError:
                continue

        self.responsive_font_widgets = live_widgets

        if self.ui_style is not None:
            self.ui_style.configure(
                "Treeview",
                font=self.scale_font(TABLE_FONT, 8, scale),
                rowheight=max(23, int(round(30 * scale)))
            )
            self.ui_style.configure(
                "Treeview.Heading",
                font=self.scale_font(TABLE_HEADING_FONT, 8, scale),
                padding=(8, max(5, int(round(7 * scale))))
            )

    def build_layout(self):
        self.outer_frame = tk.Frame(
            self.root,
            bg=BG_COLOR,
            highlightbackground="#202020",
            highlightthickness=7
        )
        self.outer_frame.pack(fill="both", expand=True)
        self.outer_frame.columnconfigure(0, weight=1)
        self.outer_frame.rowconfigure(0, weight=1)
        self.outer_frame.rowconfigure(1, weight=0)

        self.main_frame = tk.Frame(self.outer_frame, bg=BG_COLOR)
        self.main_frame.grid(row=0, column=0, sticky="nsew", padx=18, pady=(18, 10))
        self.main_frame.columnconfigure(0, weight=0)
        self.main_frame.columnconfigure(1, weight=1)
        self.main_frame.rowconfigure(0, weight=1)

        self.menu_frame = tk.Frame(
            self.main_frame,
            bg=PANEL_COLOR,
            highlightbackground=BORDER_COLOR,
            highlightthickness=1,
            padx=0,
            pady=0
        )
        self.menu_frame.grid(row=0, column=0, sticky="nsw", padx=(0, 20))
        self.menu_frame.grid_propagate(False)
        self.menu_frame.configure(width=250)
        self.menu_frame.columnconfigure(0, weight=1)
        self.menu_frame.rowconfigure(0, weight=1)

        self.sidebar_scroll = ScrollableFrame(
            self.menu_frame,
            bg=PANEL_COLOR,
            stretch_body=True
        )
        self.sidebar_scroll.grid(row=0, column=0, sticky="nsew")
        self.sidebar_body = self.sidebar_scroll.body
        self.sidebar_body.configure(padx=14, pady=16)
        self.sidebar_body.columnconfigure(0, weight=1)
        self.sidebar_body.rowconfigure(2, weight=1)

        menu_title_label = tk.Label(
            self.sidebar_body,
            text="MENU",
            bg=PANEL_COLOR,
            fg=TITLE_COLOR,
            font=MENU_TITLE_FONT,
            anchor="w"
        )
        self.register_responsive_font(menu_title_label, MENU_TITLE_FONT, min_size=22)
        menu_title_label.grid(row=0, column=0, sticky="ew", pady=(2, 18))

        self.sidebar_button_frame = tk.Frame(self.sidebar_body, bg=PANEL_COLOR)
        self.sidebar_button_frame.grid(row=1, column=0, sticky="new")

        self.sidebar_footer_frame = tk.Frame(self.sidebar_body, bg=PANEL_COLOR)
        self.sidebar_footer_frame.grid(row=3, column=0, sticky="sew", pady=(18, 0))

        self.content_frame = tk.Frame(
            self.main_frame,
            bg=HOME_PANEL_COLOR,
            highlightbackground=BORDER_COLOR,
            highlightthickness=1
        )
        self.content_frame.grid(row=0, column=1, sticky="nsew")
        self.content_frame.columnconfigure(0, weight=1)
        self.content_frame.rowconfigure(0, weight=1)

        self.backup_button = self.create_menu_button(
            "Realizar Backup",
            self.show_backup_panel,
            bg=TITLE_COLOR
        )
        self.schedule_button = self.create_menu_button(
            "Agendar Backup",
            self.show_schedule_panel,
            bg=TITLE_COLOR
        )
        self.files_button = self.create_menu_button(
            "Listar Arquivos",
            self.show_files_window,
            bg=LIGHT_BUTTON
        )
        self.history_button = self.create_menu_button(
            "Historico de Backups",
            self.show_history_window,
            bg=LIGHT_BUTTON
        )
        self.restore_button = self.create_menu_button(
            "Recuperar arquivos",
            self.show_restore_window,
            bg=LIGHT_BUTTON
        )
        self.download_button = self.create_menu_button(
            "Baixar backups",
            self.show_download_panel,
            bg=LIGHT_BUTTON
        )

        user_label = tk.Label(
            self.sidebar_footer_frame,
            text=self.build_user_label(),
            bg=PANEL_COLOR,
            fg=SUBTLE_TEXT,
            font=BODY_FONT,
            justify="center"
        )
        self.register_responsive_font(user_label, BODY_FONT, min_size=8)
        user_label.pack(fill="x", pady=(0, 10))

        self.manage_button = tk.Button(
            self.sidebar_footer_frame,
            text="Gerenciar diretorios",
            command=self.open_directory_manager,
            font=BUTTON_FONT,
            bg=MUTED_PANEL_COLOR,
            fg="white",
            activebackground=MUTED_PANEL_COLOR,
            activeforeground="white",
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground="#101722",
            highlightcolor="#101722",
            cursor="hand2",
            padx=10,
            pady=6
        )
        self.register_responsive_font(self.manage_button, BUTTON_FONT, min_size=8)
        self.manage_button.pack(fill="x", pady=(0, 8))
        self.apply_button_feedback(self.manage_button)

        self.destination_button = tk.Button(
            self.sidebar_footer_frame,
            text="Diretorio padrao de backup",
            command=self.choose_backup_destination,
            font=BUTTON_FONT,
            bg=MUTED_PANEL_COLOR,
            fg="white",
            activebackground=MUTED_PANEL_COLOR,
            activeforeground="white",
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground="#101722",
            highlightcolor="#101722",
            cursor="hand2",
            padx=10,
            pady=6
        )
        self.register_responsive_font(self.destination_button, BUTTON_FONT, min_size=8)
        self.destination_button.pack(fill="x", pady=(0, 8))
        self.apply_button_feedback(self.destination_button)

        if can(self.current_user, "manage_users"):
            self.users_button = tk.Button(
                self.sidebar_footer_frame,
                text="Gerenciar usuarios",
                command=self.open_user_manager,
                font=BUTTON_FONT,
                bg=MUTED_PANEL_COLOR,
                fg="white",
                activebackground=MUTED_PANEL_COLOR,
                activeforeground="white",
                relief="flat",
                bd=0,
                highlightthickness=1,
                highlightbackground="#101722",
                highlightcolor="#101722",
                cursor="hand2",
                padx=10,
                pady=6
            )
            self.register_responsive_font(self.users_button, BUTTON_FONT, min_size=8)
            self.users_button.pack(fill="x", pady=(0, 8))
            self.apply_button_feedback(self.users_button)

        logout_button = tk.Button(
            self.sidebar_footer_frame,
            text="Sair da conta",
            command=self.logout,
            font=BUTTON_FONT,
            bg=LIGHT_BUTTON,
            fg=TEXT_COLOR,
            activebackground=LIGHT_BUTTON,
            activeforeground=TEXT_COLOR,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground="#101722",
            highlightcolor="#101722",
            cursor="hand2",
            padx=10,
            pady=6
        )
        self.register_responsive_font(logout_button, BUTTON_FONT, min_size=8)
        logout_button.pack(fill="x", pady=(6, 0))
        self.apply_button_feedback(logout_button)

        footer = tk.Label(
            self.outer_frame,
            text=self.build_footer_text(),
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=("Segoe UI", 9),
            justify="center",
            wraplength=720
        )
        self.register_responsive_font(footer, ("Segoe UI", 9), min_size=8)
        footer.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 12))
        self.footer_label = footer

        self.outer_frame.bind(
            "<Configure>",
            lambda event: self.footer_label.configure(
                wraplength=max(event.width - 80, 260)
            )
            if event.widget == self.outer_frame
            else None,
            add="+"
        )

        self.apply_permissions()
        self.show_welcome_panel()

    def create_menu_button(self, text, command, bg):
        button = tk.Button(
            self.sidebar_button_frame,
            text=text,
            command=command,
            font=MENU_BUTTON_FONT,
            bg=bg,
            fg=TEXT_COLOR,
            activebackground=bg,
            activeforeground=TEXT_COLOR,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground="#101722",
            highlightcolor="#101722",
            cursor="hand2",
            anchor="w",
            padx=14,
            pady=8
        )
        self.register_responsive_font(button, MENU_BUTTON_FONT, min_size=10)
        button.pack(fill="x", pady=6)
        self.apply_button_feedback(button)
        return button

    def clear_content(self):
        for widget in self.content_frame.winfo_children():
            widget.destroy()

    def navigate_home(self):
        self.show_welcome_panel()

    def set_current_view(self, view_name):
        self.current_view = view_name

    def create_content_shell(self, title, show_back_button=True, subtitle=None):
        self.clear_content()
        self.set_current_view("section" if show_back_button else "home")

        panel = tk.Frame(self.content_frame, bg=HOME_PANEL_COLOR)
        panel.grid(row=0, column=0, sticky="nsew")
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(1, weight=1)

        header = tk.Frame(panel, bg=HOME_PANEL_COLOR, padx=22, pady=18)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)

        back_button = None
        if show_back_button:
            back_button = tk.Button(
                header,
                text="< Voltar",
                command=self.navigate_home,
                font=BUTTON_FONT,
                bg=TITLE_COLOR,
                fg=TEXT_COLOR,
                activebackground=TITLE_COLOR,
                activeforeground=TEXT_COLOR,
                relief="flat",
                bd=0,
                highlightthickness=1,
                highlightbackground="#101722",
                highlightcolor="#101722",
                cursor="hand2",
                padx=12,
                pady=6
            )
            self.register_responsive_font(back_button, BUTTON_FONT, min_size=8)
            back_button.grid(row=0, column=0, sticky="w", padx=(0, 14))
            self.apply_button_feedback(back_button)

        title_box = tk.Frame(header, bg=HOME_PANEL_COLOR)
        title_box.grid(row=0, column=1, sticky="ew")
        title_box.columnconfigure(0, weight=1)

        title_label = tk.Label(
            title_box,
            text=title,
            bg=HOME_PANEL_COLOR,
            fg=TITLE_COLOR,
            font=TITLE_FONT,
            anchor="center"
        )
        self.register_responsive_font(title_label, TITLE_FONT, min_size=16)
        title_label.grid(row=0, column=0, sticky="ew")

        subtitle_label = None
        if subtitle:
            subtitle_label = tk.Label(
                title_box,
                text=subtitle,
                bg=HOME_PANEL_COLOR,
                fg=SUBTLE_TEXT,
                font=HOME_SUBTITLE_FONT,
                anchor="center",
                justify="center",
                wraplength=760
            )
            self.register_responsive_font(subtitle_label, HOME_SUBTITLE_FONT, min_size=9)
            subtitle_label.grid(row=1, column=0, sticky="ew", pady=(4, 0))

        content = tk.Frame(panel, bg=HOME_PANEL_COLOR, padx=22, pady=0)
        content.grid(row=1, column=0, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)

        layout_state = {"compact": None}

        def configure_shell_layout(width=None):
            if width is None:
                width = panel.winfo_width()

            compact = width < 700

            if layout_state["compact"] == compact:
                if subtitle_label is not None:
                    subtitle_label.configure(wraplength=max(width - 80, 280))
                return

            layout_state["compact"] = compact
            header.configure(
                padx=12 if compact else 22,
                pady=12 if compact else 18
            )
            content.configure(padx=12 if compact else 22)

            for column in range(2):
                header.columnconfigure(column, weight=0)

            if back_button is not None:
                back_button.grid_forget()
            title_box.grid_forget()

            if compact and back_button is not None:
                header.columnconfigure(0, weight=1)
                back_button.grid(row=0, column=0, sticky="w", padx=0)
                title_box.grid(row=1, column=0, sticky="ew", pady=(10, 0))
            else:
                header.columnconfigure(1, weight=1)

                if back_button is not None:
                    back_button.grid(row=0, column=0, sticky="w", padx=(0, 14))
                    title_box.grid(row=0, column=1, sticky="ew")
                else:
                    title_box.grid(row=0, column=0, columnspan=2, sticky="ew")

            if subtitle_label is not None:
                subtitle_label.configure(wraplength=max(width - 80, 280))

        panel.bind(
            "<Configure>",
            lambda event: configure_shell_layout(event.width)
            if event.widget == panel
            else None,
            add="+"
        )
        panel.after_idle(configure_shell_layout)
        return panel, content

    def show_message_panel(self, title, message, action_text=None, action=None):
        _panel, content = self.create_content_shell(
            title,
            show_back_button=True,
            subtitle="Use esta area para executar a acao selecionada."
        )

        box = tk.Frame(
            content,
            bg=PANEL_COLOR,
            highlightbackground=BORDER_COLOR,
            highlightthickness=1,
            padx=28,
            pady=26
        )
        box.place(relx=0.5, rely=0.42, anchor="center")

        tk.Label(
            box,
            text=message,
            bg=PANEL_COLOR,
            fg=SUBTLE_TEXT,
            font=("Segoe UI", 12),
            justify="center",
            wraplength=620
        ).pack(pady=(0, 16))

        if action_text and action:
            self.create_dialog_button(box, action_text, action).pack()

    def show_welcome_panel(self):
        self.dashboard_monitored_size_bytes = None
        self.render_dashboard()

    def load_dataset_rows(self):
        dataset_path = os.path.join("dataset", "files_dataset.csv")

        if not os.path.exists(dataset_path):
            return []

        with open(dataset_path, "r", encoding="utf-8", newline="") as file:
            try:
                reader = csv.DictReader(file)
                return list(reader)
            except csv.Error:
                return []

    def count_backup_actions(self, entry):
        counts = {
            "adicionado": 0,
            "alterado": 0,
            "excluido": 0,
        }

        if not isinstance(entry, dict):
            return counts

        for change in entry.get("file_changes", []):
            action = str(change.get("action", "")).strip().lower()

            if action in counts:
                counts[action] += 1

        return counts

    def get_history_snapshot_total_size_bytes(self, entry):
        snapshot = entry.get("file_snapshot", {}) if isinstance(entry, dict) else {}

        if not isinstance(snapshot, dict):
            return 0

        total_size = 0

        for file_data in snapshot.values():
            if not isinstance(file_data, dict):
                continue

            try:
                total_size += int(file_data.get("size_bytes", 0) or 0)
            except (TypeError, ValueError):
                continue

        return total_size

    def get_history_snapshot_real_storage_size_bytes(self, entry):
        """
        Calcula o tamanho real em disco dos objetos armazenados no backup
        (arquivos comprimidos com gzip no diretorio arquivos_relacionados).
        """
        if not isinstance(entry, dict):
            return 0

        snapshot = entry.get("file_snapshot", {})
        if not isinstance(snapshot, dict):
            return 0

        backup_storage = entry.get("backup_storage", "")
        if not backup_storage or not os.path.isdir(backup_storage):
            return 0

        total_size = 0
        checked_paths = set()

        for file_data in snapshot.values():
            if not isinstance(file_data, dict):
                continue

            object_path = file_data.get("object_path", "")
            if not object_path:
                continue

            abs_path = os.path.join(backup_storage, object_path.replace("/", "\\"))
            normalized = os.path.normcase(os.path.abspath(abs_path))

            if normalized in checked_paths:
                continue
            checked_paths.add(normalized)

            if os.path.isfile(normalized):
                try:
                    total_size += os.path.getsize(normalized)
                except OSError:
                    continue

        return total_size

    def get_history_compacted_size_bytes(self, entry):
        if not isinstance(entry, dict):
            return None

        try:
            cached_size = entry.get("compacted_size_bytes")
            if cached_size is None or cached_size == "":
                return None
            return int(cached_size)
        except (TypeError, ValueError):
            return None

    def compute_history_compacted_size_bytes(self, entry):
        if not isinstance(entry, dict):
            return 0

        backup_path = entry.get("backup_path") or entry.get("snapshot_path", "")

        # Se ja existe um ZIP, retorna o tamanho dele
        if backup_path and str(backup_path).lower().endswith(".zip") and os.path.exists(backup_path):
            return os.path.getsize(backup_path)

        # Estima o tamanho do ZIP a partir do tamanho real dos objetos comprimidos
        # em disco. zstd nivel 19 e LZMA (usado no ZIP) tem taxas equivalentes,
        # entao esta estimativa e precisa o suficiente para o dashboard.
        estimated = self.get_history_snapshot_real_storage_size_bytes(entry)
        return estimated if estimated > 0 else 0

    def get_history_entry_identity(self, entry):
        if not isinstance(entry, dict):
            return ("", "", "")

        return (
            entry.get("snapshot_id", ""),
            entry.get("backup_path", "") or entry.get("snapshot_path", ""),
            entry.get("timestamp", ""),
        )

    def persist_history_compacted_size(self, entry, compacted_size_bytes):
        target_identity = self.get_history_entry_identity(entry)
        history = self.load_history()
        updated = False

        for history_entry in history:
            if self.get_history_entry_identity(history_entry) != target_identity:
                continue

            history_entry["compacted_size_bytes"] = int(compacted_size_bytes)
            updated = True
            break

        if not updated:
            return

        os.makedirs("config", exist_ok=True)

        with open(HISTORY_PATH, "w", encoding="utf-8") as file:
            json.dump(history[-50:], file, indent=4, ensure_ascii=False)

    def can_schedule_ui_callback(self):
        if self.is_closing:
            return False

        try:
            return bool(self.root.winfo_exists())
        except tk.TclError:
            return False

    def schedule_dashboard_event_poll(self):
        if self.dashboard_poll_scheduled or not self.can_schedule_ui_callback():
            return

        self.dashboard_poll_scheduled = True

        try:
            self.root.after(120, self.process_dashboard_events)
        except tk.TclError:
            self.dashboard_poll_scheduled = False

    def process_dashboard_events(self):
        self.dashboard_poll_scheduled = False

        if self.is_closing:
            return

        should_refresh_dashboard = False

        while True:
            try:
                event = self.dashboard_event_queue.get_nowait()
            except queue.Empty:
                break

            event_type = event[0]

            if event_type == "compacted_size_done":
                _, job_key = event

                if self.dashboard_compacted_size_job_key == job_key:
                    self.dashboard_compacted_size_job_key = None
                    should_refresh_dashboard = True
            elif event_type == "monitored_size_done":
                _, job_key, total_size = event

                if self.dashboard_monitored_size_job_key == job_key:
                    self.dashboard_monitored_size_job_key = None
                    self.dashboard_monitored_size_bytes = total_size
                    should_refresh_dashboard = True

        if should_refresh_dashboard and self.current_view == "home":
            try:
                self.render_dashboard()
            except tk.TclError:
                return

        if (
            self.dashboard_compacted_size_job_key is not None
            or self.dashboard_monitored_size_job_key is not None
            or not self.dashboard_event_queue.empty()
        ):
            self.schedule_dashboard_event_poll()

    def ensure_dashboard_compacted_size_async(self, entry):
        if not isinstance(entry, dict):
            return

        if self.is_closing:
            return

        if self.get_history_compacted_size_bytes(entry) is not None:
            return

        job_key = self.get_history_entry_identity(entry)

        if self.dashboard_compacted_size_job_key == job_key:
            return

        self.dashboard_compacted_size_job_key = job_key

        def worker():
            try:
                compacted_size = self.compute_history_compacted_size_bytes(entry)
                self.persist_history_compacted_size(entry, compacted_size)
            except Exception:
                pass

            self.dashboard_event_queue.put(("compacted_size_done", job_key))

        threading.Thread(target=worker, daemon=True).start()
        self.schedule_dashboard_event_poll()

    def get_monitored_size_job_key(self):
        return tuple(
            os.path.normcase(os.path.abspath(directory))
            for directory in self.directories
        )

    def compute_monitored_total_size_bytes(self):
        total_size = 0

        for directory in self.directories:
            directory_path = os.path.abspath(directory)

            if not os.path.isdir(directory_path) or is_path_ignored(directory_path):
                continue

            for current_root, dirs, files in os.walk(directory_path):
                if is_path_ignored(current_root):
                    dirs[:] = []
                    continue

                dirs[:] = [
                    current_dir
                    for current_dir in dirs
                    if not is_path_ignored(os.path.join(current_root, current_dir))
                ]

                for file_name in files:
                    file_path = os.path.join(current_root, file_name)

                    if is_path_ignored(file_path):
                        continue

                    try:
                        total_size += os.path.getsize(file_path)
                    except OSError:
                        continue

        return total_size

    def ensure_dashboard_monitored_size_async(self):
        job_key = self.get_monitored_size_job_key()

        if self.is_closing:
            return

        if not job_key:
            self.dashboard_monitored_size_bytes = 0
            return

        if self.dashboard_monitored_size_bytes is not None:
            return

        if self.dashboard_monitored_size_job_key == job_key:
            return

        self.dashboard_monitored_size_job_key = job_key

        def worker():
            try:
                total_size = self.compute_monitored_total_size_bytes()
            except Exception:
                total_size = 0

            self.dashboard_event_queue.put(
                ("monitored_size_done", job_key, total_size)
            )

        threading.Thread(target=worker, daemon=True).start()
        self.schedule_dashboard_event_poll()

    def build_dashboard_summary(self):
        latest_backup = self.get_latest_visible_history_entry()
        latest_full_backup = self.get_latest_visible_full_backup_entry()
        latest_size_backup = latest_full_backup or latest_backup
        action_counts = self.count_backup_actions(latest_backup)

        # Tamanho real em disco dos objetos comprimidos (zstd)
        real_storage_bytes = (
            self.get_history_snapshot_real_storage_size_bytes(latest_size_backup)
            if latest_size_backup
            else 0
        )

        # Tamanho do ZIP (calculado async se necessario)
        compacted_size_bytes = self.get_history_compacted_size_bytes(latest_size_backup)
        compacted_size_known = compacted_size_bytes is not None

        if not compacted_size_known and latest_size_backup:
            # Dispara calculo do ZIP em background se ainda nao foi calculado
            self.ensure_dashboard_compacted_size_async(latest_size_backup)

        monitored_size = (
            format_size_bytes_human(self.dashboard_monitored_size_bytes)
            if self.dashboard_monitored_size_bytes is not None
            else "Calculando"
        )

        return {
            "total_files": len(self.load_dataset_rows()),
            "added_files": action_counts["adicionado"],
            "changed_files": action_counts["alterado"],
            "deleted_files": action_counts["excluido"],
            "latest_backup": latest_backup,
            "latest_full_backup": latest_size_backup,
            "backup_destination": self.get_current_user_backup_destination(),
            "monitored_total_size": monitored_size,
            "backup_recovery_size": (
                format_size_bytes_human(real_storage_bytes)
                if latest_size_backup
                else "-"
            ),
            "backup_compacted_size": (
                format_size_bytes_human(compacted_size_bytes)
                if compacted_size_known
                else "Calculando"
            ),
        }

    def create_summary_card(self, parent, title, value, accent, note):
        card = tk.Frame(
            parent,
            bg=CARD_COLOR,
            highlightbackground=accent,
            highlightthickness=2,
            padx=18,
            pady=16
        )

        accent_bar = tk.Frame(card, bg=accent, height=5)
        accent_bar.pack(fill="x", pady=(0, 14))

        title_label = tk.Label(
            card,
            text=title,
            bg=CARD_COLOR,
            fg=SUBTLE_TEXT,
            font=CARD_LABEL_FONT,
            anchor="w",
            justify="left"
        )
        self.register_responsive_font(title_label, CARD_LABEL_FONT, min_size=9)
        title_label.pack(fill="x")

        value_label = tk.Label(
            card,
            text=str(value),
            bg=CARD_COLOR,
            fg="white",
            font=CARD_VALUE_FONT,
            anchor="w",
            justify="left"
        )
        self.register_responsive_font(value_label, CARD_VALUE_FONT, min_size=18)
        value_label.pack(fill="x", pady=(10, 6))

        note_label = tk.Label(
            card,
            text=note,
            bg=CARD_COLOR,
            fg=SUBTLE_TEXT,
            font=("Segoe UI", 9),
            anchor="w",
            justify="left",
            wraplength=220
        )
        self.register_responsive_font(note_label, ("Segoe UI", 9), min_size=8)
        note_label.pack(fill="x")

        def update_card_wrap(event=None):
            width = event.width if event is not None else card.winfo_width()
            wrap = max(width - 36, 150)
            title_label.configure(wraplength=wrap)
            value_label.configure(wraplength=wrap)
            note_label.configure(wraplength=wrap)

        card.bind("<Configure>", update_card_wrap, add="+")
        card.after_idle(update_card_wrap)

        return card

    def render_dashboard(self):
        summary = self.build_dashboard_summary()
        latest_full_backup = summary["latest_full_backup"]
        _panel, shell_content = self.create_content_shell(
            "Sistema de Backup",
            show_back_button=False,
            subtitle="Acompanhe rapidamente o status do sistema e das ultimas mudancas."
        )
        scroll_content = ScrollableFrame(shell_content, bg=HOME_PANEL_COLOR)
        scroll_content.grid(row=0, column=0, sticky="nsew")
        content = scroll_content.body
        content.columnconfigure(0, weight=1)
        content.rowconfigure(1, weight=0)
        content.rowconfigure(2, weight=0)

        hero = tk.Frame(
            content,
            bg=PANEL_COLOR,
            highlightbackground=BORDER_COLOR,
            highlightthickness=1,
            padx=28,
            pady=24
        )
        hero.grid(row=0, column=0, sticky="ew", pady=(0, 18))
        hero.columnconfigure(0, weight=3)
        hero.columnconfigure(1, weight=2)

        left_hero = tk.Frame(hero, bg=PANEL_COLOR)
        left_hero.grid(row=0, column=0, sticky="nsew", padx=(0, 18))

        dashboard_title_label = tk.Label(
            left_hero,
            text="Painel inicial",
            bg=PANEL_COLOR,
            fg=TITLE_COLOR,
            font=HOME_TITLE_FONT,
            anchor="w"
        )
        self.register_responsive_font(dashboard_title_label, HOME_TITLE_FONT, min_size=20)
        dashboard_title_label.pack(fill="x")

        hero_description = tk.Label(
            left_hero,
            text=(
                "Visualize os arquivos acompanhados e o impacto do ultimo backup "
                "sem sair da tela principal."
            ),
            bg=PANEL_COLOR,
            fg=SUBTLE_TEXT,
            font=HOME_SUBTITLE_FONT,
            justify="left",
            wraplength=460
        )
        self.register_responsive_font(hero_description, HOME_SUBTITLE_FONT, min_size=9)
        hero_description.pack(fill="x", pady=(10, 16))

        quick_info = tk.Frame(left_hero, bg=PANEL_COLOR)
        quick_info.pack(fill="x")

        latest_backup = summary["latest_backup"] or {}
        backup_name = latest_backup.get("backup_name") or latest_backup.get("backup_file") or "Nenhum backup registrado"
        backup_time = latest_backup.get("timestamp", "Sem historico")

        quick_value_labels = []

        for label_text, value_text in (
            ("Ultimo backup", backup_time),
            ("Identificacao", backup_name),
            ("Destino atual", summary["backup_destination"]),
        ):
            row = tk.Frame(quick_info, bg=PANEL_COLOR)
            row.pack(fill="x", pady=3)
            info_label = tk.Label(
                row,
                text=f"{label_text}:",
                bg=PANEL_COLOR,
                fg=TITLE_COLOR,
                font=("Segoe UI", 10, "bold"),
                width=15,
                anchor="w"
            )
            self.register_responsive_font(info_label, ("Segoe UI", 10, "bold"), min_size=8)
            info_label.pack(side="left")
            value_label = tk.Label(
                row,
                text=value_text,
                bg=PANEL_COLOR,
                fg="white",
                font=("Segoe UI", 10),
                anchor="w",
                justify="left",
                wraplength=360
            )
            self.register_responsive_font(value_label, ("Segoe UI", 10), min_size=8)
            value_label.pack(side="left", fill="x", expand=True)
            quick_value_labels.append(value_label)

        right_hero = tk.Frame(
            hero,
            bg=HOME_PANEL_COLOR,
            highlightbackground=BORDER_COLOR,
            highlightthickness=1,
            padx=18,
            pady=18
        )
        right_hero.grid(row=0, column=1, sticky="nsew")

        backup_summary_title = tk.Label(
            right_hero,
            text="Resumo do ultimo backup",
            bg=HOME_PANEL_COLOR,
            fg=TITLE_COLOR,
            font=("Segoe UI", 12, "bold")
        )
        self.register_responsive_font(backup_summary_title, ("Segoe UI", 12, "bold"), min_size=9)
        backup_summary_title.pack(fill="x")

        backup_summary_label = tk.Label(
            right_hero,
            text=(
                "Os indicadores abaixo refletem o dataset atual e as mudancas "
                "registradas no ultimo backup visivel."
            ),
            bg=HOME_PANEL_COLOR,
            fg=SUBTLE_TEXT,
            font=("Segoe UI", 10),
            justify="left",
            wraplength=280
        )
        self.register_responsive_font(backup_summary_label, ("Segoe UI", 10), min_size=8)
        backup_summary_label.pack(fill="x", pady=(8, 12))

        def update_dashboard_text_wrap(_event=None):
            left_width = max(left_hero.winfo_width() - 28, 220)
            right_width = max(right_hero.winfo_width() - 36, 180)
            hero_description.configure(wraplength=left_width)
            backup_summary_label.configure(wraplength=right_width)

            for value_label in quick_value_labels:
                value_label.configure(wraplength=max(left_width - 130, 180))

        left_hero.bind("<Configure>", update_dashboard_text_wrap, add="+")
        right_hero.bind("<Configure>", update_dashboard_text_wrap, add="+")

        change_count_label = tk.Label(
            right_hero,
            text=f"{summary['added_files'] + summary['changed_files'] + summary['deleted_files']}",
            bg=HOME_PANEL_COLOR,
            fg="white",
            font=("Segoe UI Black", 28, "bold")
        )
        self.register_responsive_font(change_count_label, ("Segoe UI Black", 28, "bold"), min_size=20)
        change_count_label.pack(anchor="w")

        change_caption_label = tk.Label(
            right_hero,
            text="mudancas registradas no ultimo backup",
            bg=HOME_PANEL_COLOR,
            fg=SUBTLE_TEXT,
            font=("Segoe UI", 10)
        )
        self.register_responsive_font(change_caption_label, ("Segoe UI", 10), min_size=8)
        change_caption_label.pack(anchor="w", pady=(4, 0))

        cards_frame = FlowFrame(
            content,
            bg=HOME_PANEL_COLOR,
            min_item_width=205,
            hgap=8,
            vgap=8,
            max_columns=4
        )
        cards_frame.grid(row=1, column=0, sticky="nsew")
        cards = (
            ("Arquivos totais", summary["total_files"], TITLE_COLOR, "Arquivos atualmente presentes no dataset analisado."),
            ("Adicionados", summary["added_files"], "#22C55E", "Novos arquivos incluidos no ultimo backup."),
            ("Alterados", summary["changed_files"], "#F59E0B", "Arquivos com nova versao no ultimo backup."),
            ("Excluidos", summary["deleted_files"], "#EF4444", "Arquivos removidos em relacao ao backup anterior."),
        )

        summary_cards = []
        for column_index, (title, value, accent, note) in enumerate(cards):
            card = self.create_summary_card(cards_frame, title, value, accent, note)
            cards_frame.add(card)
            summary_cards.append(card)

        size_cards_frame = FlowFrame(
            content,
            bg=HOME_PANEL_COLOR,
            min_item_width=260,
            hgap=8,
            vgap=8,
            max_columns=3
        )
        size_cards_frame.grid(row=2, column=0, sticky="ew", pady=(8, 0))

        monitored_card = self.create_summary_card(
            size_cards_frame,
            "Tamanho total monitorado",
            summary["monitored_total_size"],
            "#38BDF8",
            "Soma atual de todos os arquivos presentes nas pastas monitoradas."
        )
        size_cards_frame.add(monitored_card)

        backup_card = self.create_summary_card(
            size_cards_frame,
            "Tamanho do ultimo backup",
            summary["backup_recovery_size"],
            "#22C55E",
            "Tamanho real ocupado em disco pelos objetos comprimidos do backup."
        )
        size_cards_frame.add(backup_card)

        compacted_card = self.create_summary_card(
            size_cards_frame,
            "Backup compactado",
            summary["backup_compacted_size"],
            "#F97316",
            "Tamanho estimado do ZIP exportado a partir do ultimo backup."
        )
        size_cards_frame.add(compacted_card)

        dashboard_layout_state = {"compact": None}

        def configure_dashboard_layout(width=None):
            if width is None:
                width = scroll_content.canvas.winfo_width()

            compact = width < 900

            if dashboard_layout_state["compact"] == compact:
                update_dashboard_text_wrap()
                return

            dashboard_layout_state["compact"] = compact

            left_hero.grid_forget()
            right_hero.grid_forget()
            self.clear_grid_layout(hero, rows=3, columns=2)

            if compact:
                hero.configure(padx=16, pady=16)
                hero.columnconfigure(0, weight=1)
                hero.rowconfigure(0, weight=0)
                hero.rowconfigure(1, weight=0)
                left_hero.grid(row=0, column=0, sticky="nsew")
                right_hero.grid(row=1, column=0, sticky="nsew", pady=(14, 0))
            else:
                hero.configure(padx=28, pady=24)
                hero.columnconfigure(0, weight=3)
                hero.columnconfigure(1, weight=2)
                left_hero.grid(row=0, column=0, sticky="nsew", padx=(0, 18))
                right_hero.grid(row=0, column=1, sticky="nsew")

            hero.after_idle(update_dashboard_text_wrap)

        scroll_content.canvas.bind(
            "<Configure>",
            lambda event: configure_dashboard_layout(event.width)
            if event.widget == scroll_content.canvas
            else None,
            add="+"
        )
        content.after_idle(configure_dashboard_layout)

        if summary["monitored_total_size"] == "Calculando":
            self.ensure_dashboard_monitored_size_async()

        # Exibe apenas o valor compactado ja salvo no historico.
        # Quando nao houver valor anterior persistido, mantem "-".

    def show_backup_panel(self):
        if not self.require_permission("run_backup"):
            return

        self.show_message_panel(
            "Realizar Backup",
            "Inicie um backup manual dos diretorios cadastrados.",
            "Iniciar backup",
            self.perform_backup
        )

    def show_download_panel(self):
        if not self.require_permission("download_backup"):
            return

        self.show_download_options_panel()

    def show_schedule_panel(self):
        if not self.require_permission("schedule_backup"):
            return

        _panel, content = self.create_content_shell(
            "Agendar Backup",
            subtitle="Defina a janela de execucao automatica e a politica por prioridade."
        )

        box = tk.Frame(
            content,
            bg=PANEL_COLOR,
            highlightbackground=BORDER_COLOR,
            highlightthickness=1,
            padx=28,
            pady=24
        )
        box.place(relx=0.5, rely=0.43, anchor="center")

        form = tk.Frame(box, bg=PANEL_COLOR)
        form.columnconfigure(1, weight=1)
        form.pack(fill="both", expand=True)

        config_data = self.load_config()
        priority_policy_var = tk.BooleanVar(
            value=bool(
                config_data.get(
                    "priority_backup_policy_enabled",
                    DEFAULT_PRIORITY_BACKUP_POLICY_ENABLED
                )
            )
        )
        tk.Label(
            form,
            text="Horario inicial (HH:MM)",
            bg=PANEL_COLOR,
            fg=SUBTLE_TEXT,
            font=("Arial", 11)
        ).grid(row=0, column=0, sticky="w", pady=6)

        schedule_data = self.load_schedule()
        start_time_var = tk.StringVar(
            value=schedule_data.get("time_start") or schedule_data.get("time", "09:00")
        )
        start_time_entry = tk.Entry(
            form,
            textvariable=start_time_var,
            font=("Arial", 11),
            bg=LIGHT_BUTTON,
            fg=TEXT_COLOR,
            relief="flat",
            width=26
        )
        start_time_entry.grid(row=0, column=1, sticky="ew", padx=(10, 0), pady=6)

        tk.Label(
            form,
            text="Horario final (HH:MM)",
            bg=PANEL_COLOR,
            fg=SUBTLE_TEXT,
            font=("Arial", 11)
        ).grid(row=1, column=0, sticky="w", pady=6)

        end_time_var = tk.StringVar(
            value=schedule_data.get("time_end", "18:00")
        )
        end_time_entry = tk.Entry(
            form,
            textvariable=end_time_var,
            font=("Arial", 11),
            bg=LIGHT_BUTTON,
            fg=TEXT_COLOR,
            relief="flat",
            width=26
        )
        end_time_entry.grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=6)

        tk.Label(
            form,
            text="O backup sera executado automaticamente uma vez por dia dentro da faixa escolhida.",
            bg=PANEL_COLOR,
            fg=SUBTLE_TEXT,
            font=("Arial", 10),
            wraplength=360,
            justify="center"
        ).grid(row=2, column=0, columnspan=2, pady=(12, 14))

        priority_policy_check = tk.Checkbutton(
            form,
            text="Ativar backup automatico por prioridade",
            variable=priority_policy_var,
            bg=PANEL_COLOR,
            fg=SUBTLE_TEXT,
            activebackground=PANEL_COLOR,
            activeforeground=SUBTLE_TEXT,
            selectcolor=PANEL_COLOR,
            font=("Arial", 10, "bold")
        )
        priority_policy_check.grid(
            row=3,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(0, 14)
        )

        def save_schedule():
            start_value = start_time_var.get().strip()
            end_value = end_time_var.get().strip()

            if (
                not self.is_valid_time(start_value)
                or not self.is_valid_time(end_value)
            ):
                messagebox.showwarning(
                    "Horario invalido",
                    "Informe os horarios no formato HH:MM.",
                    parent=self.root
                )
                return

            payload = {
                "time_start": start_value,
                "time_end": end_value,
                "updated_at": datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            }

            os.makedirs("config", exist_ok=True)

            with open(SCHEDULE_PATH, "w", encoding="utf-8") as file:
                json.dump(payload, file, indent=4, ensure_ascii=False)

            config_payload = self.load_config()
            config_payload["priority_backup_policy_enabled"] = bool(
                priority_policy_var.get()
            )
            self.save_config(config_payload)

            self.refresh_footer()
            messagebox.showinfo(
                "Agendamento salvo",
                "Horario e politica por prioridade salvos com sucesso.",
                parent=self.root
            )

        self.create_dialog_button(
            form,
            "Salvar agendamento",
            save_schedule
        ).grid(row=4, column=0, columnspan=2)

    def apply_button_feedback(self, button):
        default_bg = button.cget("bg")
        default_highlight = button.cget("highlightbackground")

        def on_enter(_event):
            if str(button.cget("state")) != tk.DISABLED:
                button.config(highlightbackground="#05080D")

        def on_leave(_event):
            if button.winfo_exists():
                button.config(
                    bg=default_bg,
                    highlightbackground=default_highlight
                )

        button.bind("<Enter>", on_enter, add="+")
        button.bind("<Leave>", on_leave, add="+")

    def build_user_label(self):
        name = self.current_user.get("name") or self.current_user.get("username")
        role = get_role_label(self.current_user.get("role"))
        return f"{name}\n{role}"

    def require_permission(self, permission):
        if can(self.current_user, permission):
            return True

        messagebox.showerror(
            "Acesso negado",
            "Seu perfil nao tem permissao para executar esta acao."
        )
        return False

    def apply_permissions(self):
        permission_buttons = [
            (self.backup_button, "run_backup"),
            (self.schedule_button, "schedule_backup"),
            (self.files_button, "view_files"),
            (self.history_button, "view_history"),
            (self.restore_button, "restore_backup"),
            (self.download_button, "download_backup"),
            (self.manage_button, "manage_directories"),
            (self.destination_button, "change_backup_destination"),
        ]

        for button, permission in permission_buttons:
            if button is not None and not can(self.current_user, permission):
                button.config(state=tk.DISABLED, cursor="arrow")

    def request_close(self):
        if self.is_closing:
            return

        if self.backup_in_progress:
            messagebox.showwarning(
                "Backup em andamento",
                "Aguarde o backup terminar ou cancele a operacao antes de sair.",
                parent=self.root
            )
            return

        self.is_closing = True

        try:
            self.root.withdraw()
            self.root.quit()
        except tk.TclError:
            pass

    def logout(self):
        if self.backup_in_progress:
            messagebox.showwarning(
                "Backup em andamento",
                "Aguarde o backup terminar ou cancele a operacao antes de sair.",
                parent=self.root
            )
            return

        self.logout_requested = True
        self.is_closing = True

        try:
            self.root.quit()
        except tk.TclError:
            pass

    def show_window(self):
        self.is_closing = False

        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except tk.TclError:
            return

        self.schedule_dashboard_event_poll()

    def build_footer_text(self):
        latest_backup = self.get_latest_history_entry()
        backup_destination = self.get_current_user_backup_destination()

        if latest_backup:
            backup_text = (
                f"Ultimo backup: {latest_backup.get('timestamp', 'desconhecido')}"
            )
        else:
            backup_text = "Ultimo backup: nenhum registro"

        return (
            f"{backup_text}  |  Destino: {backup_destination}"
        )

    def refresh_footer(self):
        self.footer_label.config(text=self.build_footer_text())

    def refresh_dashboard_if_home(self):
        if self.current_view == "home":
            self.render_dashboard()

    def load_directories(self):
        data = self.load_config()
        self.directories = data.get("directories", [])
        self.backup_destination = data.get("backup_destination", BACKUP_DIR)

    def save_directories(self):
        data = self.load_config()
        data["directories"] = self.directories
        data["backup_destination"] = self.backup_destination
        self.save_config(data)
        self.dashboard_monitored_size_bytes = None
        self.refresh_footer()
        self.refresh_dashboard_if_home()

    def load_dataset_lookup(self):
        dataset_path = os.path.join("dataset", "files_dataset.csv")

        if not os.path.exists(dataset_path):
            return {}

        try:
            with open(dataset_path, "r", encoding="utf-8", newline="") as file:
                reader = csv.DictReader(file)
                return {
                    normalize_file_source_key(row.get("source_path", "")): row
                    for row in reader
                    if normalize_file_source_key(row.get("source_path", ""))
                }
        except OSError:
            return {}

    def build_monitored_file_nodes(self):
        history_lookup = build_history_backup_lookup(self.load_history())
        dataset_lookup = self.load_dataset_lookup()
        nodes = []
        summary = {
            "directories": 0,
            "missing_directories": 0,
            "files": 0,
        }

        for directory in self.directories:
            directory_path = os.path.abspath(directory)
            directory_exists = os.path.isdir(directory_path)
            root_node = {
                "name": directory_path,
                "path": directory_path,
                "is_dir": True,
                "extension": "-",
                "priority": "-",
                "priority_score": "-",
                "added_to_backup_at": "-",
                "added_in_backup": "-",
                "status": "Monitorando" if directory_exists else "Nao encontrado",
                "size": "-",
                "size_mb": "-",
                "modified_at": "-",
                "days_since_modified": "-",
                "children": [],
                "tags": ("directory_root",),
            }
            nodes.append(root_node)
            summary["directories"] += 1

            if not directory_exists:
                summary["missing_directories"] += 1
                root_node["tags"] = ("directory_missing",)
                continue

            path_to_node = {directory_path: root_node}

            for current_root, dirs, files in os.walk(directory_path):
                if is_path_ignored(current_root):
                    dirs[:] = []
                    continue

                parent_node = path_to_node.get(current_root, root_node)

                dirs[:] = sorted(
                    [
                        current_dir
                        for current_dir in dirs
                        if not is_path_ignored(os.path.join(current_root, current_dir))
                    ],
                    key=str.lower
                )

                for current_dir in dirs:
                    child_path = os.path.join(current_root, current_dir)
                    child_node = {
                        "name": current_dir,
                        "path": child_path,
                        "is_dir": True,
                        "extension": "-",
                        "priority": "-",
                        "priority_score": "-",
                        "added_to_backup_at": "-",
                        "added_in_backup": "-",
                        "status": "Pasta",
                        "size": "-",
                        "size_mb": "-",
                        "modified_at": "-",
                        "days_since_modified": "-",
                        "children": [],
                        "tags": ("directory_child",),
                    }
                    parent_node["children"].append(child_node)
                    path_to_node[child_path] = child_node

                for file_name in sorted(files, key=str.lower):
                    file_path = os.path.join(current_root, file_name)

                    if is_path_ignored(file_path):
                        continue

                    try:
                        file_stat = os.stat(file_path)
                    except OSError:
                        continue

                    source_key = normalize_file_source_key(file_path)
                    dataset_row = dataset_lookup.get(source_key, {})
                    snapshot_file = history_lookup["latest_by_source"].get(source_key, {})
                    archive_key = normalize_file_archive_key(
                        snapshot_file.get("archive_name", "")
                    )
                    backup_info = get_backup_info_for_file(
                        history_lookup,
                        source_key,
                        archive_key
                    )
                    extension = os.path.splitext(file_name)[1].lstrip(".").lower()
                    priority = (
                        str(dataset_row.get("priority", "")).strip()
                        or str(snapshot_file.get("priority", "")).strip()
                        or "Nao classificado"
                    )
                    priority_score = (
                        str(dataset_row.get("priority_score", "")).strip()
                        or str(snapshot_file.get("priority_score", "")).strip()
                        or str(snapshot_file.get("score", "")).strip()
                        or "-"
                    )
                    status = (
                        BACKUP_STATUS_IN_BACKUP
                        if snapshot_file
                        else "Monitorado"
                    )

                    parent_node["children"].append(
                        {
                            "name": file_name,
                            "path": file_path,
                            "is_dir": False,
                            "extension": extension,
                            "priority": priority,
                            "priority_score": priority_score,
                            "added_to_backup_at": backup_info["added_to_backup_at"],
                            "added_in_backup": backup_info["added_in_backup"],
                            "status": status,
                            "size": format_size_bytes_human(file_stat.st_size),
                            "size_mb": f"{file_stat.st_size / (1024 * 1024):.2f}",
                            "modified_at": format_files_view_modified_at(
                                file_stat.st_mtime
                            ),
                            "days_since_modified": format_files_view_days_since_modified(
                                file_stat.st_mtime
                            ),
                            "children": [],
                            "tags": (
                                self.get_file_backup_status_tag(status)
                                or ("file_monitored",)
                            ),
                        }
                    )
                    summary["files"] += 1

        return nodes, summary

    def filter_monitored_nodes(self, nodes, search_text):
        normalized_search = str(search_text or "").strip().lower()

        if not normalized_search:
            return nodes

        filtered_nodes = []

        for node in nodes:
            child_matches = self.filter_monitored_nodes(
                node.get("children", []),
                normalized_search
            )
            searchable_text = " ".join(
                [
                    str(node.get("name", "")),
                    str(node.get("path", "")),
                    str(node.get("priority", "")),
                    str(node.get("status", "")),
                ]
            ).lower()

            if normalized_search in searchable_text or child_matches:
                filtered_nodes.append(
                    {
                        **node,
                        "children": child_matches,
                    }
                )

        return filtered_nodes

    def insert_monitored_file_nodes(self, tree, nodes, parent=""):
        for node in nodes:
            item_id = tree.insert(
                parent,
                tk.END,
                text=node.get("name", ""),
                values=(
                    node.get("extension", "-"),
                    node.get("priority", "-"),
                    node.get("priority_score", "-"),
                    node.get("added_to_backup_at", "-"),
                    node.get("added_in_backup", "-"),
                    node.get("status", "-"),
                    node.get("size_mb", "-"),
                    node.get("days_since_modified", "-"),
                ),
                open=not parent,
                tags=node.get("tags", ()),
            )
            self.insert_monitored_file_nodes(
                tree,
                node.get("children", []),
                parent=item_id
            )

    def load_config(self):
        if not os.path.exists(CONFIG_PATH):
            return {
                "priority_backup_policy_enabled": DEFAULT_PRIORITY_BACKUP_POLICY_ENABLED
            }

        with open(CONFIG_PATH, "r", encoding="utf-8") as file:
            try:
                data = json.load(file)
            except json.JSONDecodeError:
                return {
                    "priority_backup_policy_enabled": DEFAULT_PRIORITY_BACKUP_POLICY_ENABLED
                }

        if isinstance(data, dict):
            data.setdefault(
                "priority_backup_policy_enabled",
                DEFAULT_PRIORITY_BACKUP_POLICY_ENABLED
            )
            return data

        return {
            "priority_backup_policy_enabled": DEFAULT_PRIORITY_BACKUP_POLICY_ENABLED
        }

    def save_config(self, data):
        os.makedirs("config", exist_ok=True)
        data.setdefault(
            "priority_backup_policy_enabled",
            DEFAULT_PRIORITY_BACKUP_POLICY_ENABLED
        )

        with open(CONFIG_PATH, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=4, ensure_ascii=False)

    def get_backup_destination(self):
        return self.backup_destination or BACKUP_DIR

    def get_current_user_backup_destination(self):
        return get_user_backup_destination(
            self.get_backup_destination(),
            self.current_user.get("username")
        )

    def choose_backup_destination(self):
        if not self.require_permission("change_backup_destination"):
            return

        current_directory = self.get_backup_destination()
        selected_directory = filedialog.askdirectory(
            parent=self.root,
            title="Escolher diretorio padrao de backup",
            initialdir=current_directory
        )

        if not selected_directory:
            return

        self.backup_destination = selected_directory
        self.save_directories()
        messagebox.showinfo(
            "Diretorio salvo",
            f"Novo diretorio padrao de backup:\n{selected_directory}"
        )

    def open_directory_manager(self):
        if not self.require_permission("manage_directories"):
            return

        _panel, content = self.create_content_shell(
            "Gerenciar Diretorios",
            subtitle="Adicione, remova e revise as pastas monitoradas pelo sistema."
        )
        content.columnconfigure(0, weight=1)
        content.rowconfigure(1, weight=1)

        summary_var = tk.StringVar()
        tk.Label(
            content,
            textvariable=summary_var,
            bg=HOME_PANEL_COLOR,
            fg=SUBTLE_TEXT,
            font=("Segoe UI", 10)
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))

        box = tk.Frame(
            content,
            bg=PANEL_COLOR,
            highlightbackground=BORDER_COLOR,
            highlightthickness=1,
            padx=18,
            pady=18
        )
        box.grid(row=1, column=0, sticky="nsew")
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        box.rowconfigure(1, weight=0)

        tree_frame = tk.Frame(box, bg=PANEL_COLOR)
        tree_frame.grid(row=0, column=0, sticky="nsew")

        columns = ("folder", "status")
        directory_tree = self.create_scrollable_tree(
            tree_frame,
            columns,
            height=10
        )
        self.configure_tree_columns(
            directory_tree,
            {
                "folder": "Diretorio",
                "status": "Status"
            },
            {
                "folder": {
                    "width": 560,
                    "minwidth": 360,
                    "weight": 5,
                    "anchor": "w",
                },
                "status": {
                    "width": 130,
                    "minwidth": 110,
                    "weight": 1,
                },
            }
        )
        directory_tree.tag_configure("missing", foreground="#D32F2F")

        def get_directory_status(directory):
            return "OK" if os.path.isdir(directory) else "Nao encontrado"

        def refresh_directory_table():
            for item in directory_tree.get_children():
                directory_tree.delete(item)

            for index, directory in enumerate(self.directories):
                status = get_directory_status(directory)
                tags = ("missing",) if status != "OK" else ()
                directory_tree.insert(
                    "",
                    tk.END,
                    iid=str(index),
                    values=(directory, status),
                    tags=tags
                )

            total = len(self.directories)
            active = sum(
                1
                for directory in self.directories
                if os.path.isdir(directory)
            )
            summary_var.set(
                f"{total} diretorio(s) cadastrado(s)  |  {active} disponivel(is)"
            )

        refresh_directory_table()
        original_directories = {
            os.path.normcase(os.path.abspath(directory))
            for directory in self.directories
        }

        buttons = tk.Frame(box, bg=PANEL_COLOR)
        buttons.grid(row=1, column=0, sticky="e", pady=(12, 0))

        def add_directory():
            folder = filedialog.askdirectory(parent=self.root)

            if not folder:
                return

            normalized_folder = os.path.normcase(os.path.abspath(folder))
            existing_folders = {
                os.path.normcase(os.path.abspath(directory))
                for directory in self.directories
            }

            if normalized_folder in existing_folders:
                messagebox.showinfo(
                    "Diretorio ja cadastrado",
                    "Esse diretorio ja esta na lista.",
                    parent=self.root
                )
                return

            self.directories.append(folder)
            refresh_directory_table()

        def remove_directory():
            selected = directory_tree.selection()

            if not selected:
                return

            index = int(selected[0])
            del self.directories[index]
            refresh_directory_table()

        def save_and_close():
            new_directories = [
                directory
                for directory in self.directories
                if os.path.normcase(os.path.abspath(directory))
                not in original_directories
                and os.path.isdir(directory)
            ]
            self.save_directories()
            messagebox.showinfo(
                "Sucesso",
                "Diretorios salvos com sucesso!",
                parent=self.root
            )

            if new_directories:
                if self.backup_in_progress:
                    messagebox.showinfo(
                        "Backup inicial pendente",
                        (
                            "As pastas foram salvas, mas ja existe um backup em "
                            "execucao. Inicie o backup inicial quando a execucao "
                            "atual terminar."
                        ),
                        parent=self.root
                    )
                    return

                self.start_backup_execution(
                    directories=new_directories,
                    trigger="initial_folder_backup",
                    backup_name="backup_inicial",
                    backup_description="Backup inicial automatico de nova pasta monitorada."
                )

        self.create_dialog_button(buttons, "Adicionar pasta", add_directory).grid(
            row=0, column=0, padx=6
        )
        self.create_dialog_button(buttons, "Remover", remove_directory).grid(
            row=0, column=1, padx=6
        )
        self.create_dialog_button(buttons, "Salvar", save_and_close).grid(
            row=0, column=2, padx=6
        )

    def create_dialog_button(self, parent, text, command):
        button = tk.Button(
            parent,
            text=text,
            command=command,
            font=BUTTON_FONT,
            bg=TITLE_COLOR,
            fg=TEXT_COLOR,
            activebackground=TITLE_COLOR,
            activeforeground=TEXT_COLOR,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground="#101722",
            highlightcolor="#101722",
            cursor="hand2",
            padx=12,
            pady=5
        )
        self.register_responsive_font(button, BUTTON_FONT, min_size=8)
        self.apply_button_feedback(button)
        return button

    def clear_grid_layout(self, parent, rows=8, columns=8):
        for row in range(rows):
            parent.rowconfigure(row, weight=0, minsize=0)

        for column in range(columns):
            parent.columnconfigure(column, weight=0, minsize=0, uniform="")

    def bind_responsive_button_grid(
        self,
        parent,
        buttons,
        compact_width=680,
        wide_sticky="e",
        compact_columns=2
    ):
        state = {"mode": None}

        def configure(width=None):
            if width is None:
                width = parent.winfo_width()

            mode = "compact" if width < compact_width else "wide"

            if state["mode"] == mode:
                return

            state["mode"] = mode

            for button in buttons:
                button.grid_forget()

            self.clear_grid_layout(parent, rows=4, columns=max(len(buttons), compact_columns, 1))

            if mode == "wide":
                for index, button in enumerate(buttons):
                    button.grid(
                        row=0,
                        column=index,
                        sticky=wide_sticky,
                        padx=(0 if index == 0 else 8, 0)
                    )
                return

            columns = max(1, min(compact_columns, len(buttons)))

            for column in range(columns):
                parent.columnconfigure(column, weight=1, uniform="buttons")

            for index, button in enumerate(buttons):
                row = index // columns
                column = index % columns
                button.grid(
                    row=row,
                    column=column,
                    sticky="ew",
                    padx=(0 if column == 0 else 8, 0),
                    pady=(0 if row == 0 else 8, 0)
                )

        parent.bind(
            "<Configure>",
            lambda event: configure(event.width)
            if event.widget == parent
            else None,
            add="+"
        )
        parent.after_idle(configure)

    def bind_responsive_search_bar(
        self,
        parent,
        label,
        entry,
        buttons,
        detail_widgets=None,
        compact_width=760,
        compact_columns=3
    ):
        detail_widgets = detail_widgets or []
        state = {"mode": None}

        def configure(width=None):
            if width is None:
                width = parent.winfo_width()

            mode = "compact" if width < compact_width else "wide"

            if state["mode"] == mode:
                return

            state["mode"] = mode

            for widget in [label, entry, *buttons, *detail_widgets]:
                widget.grid_forget()

            self.clear_grid_layout(parent, rows=8, columns=max(len(buttons) + 2, compact_columns))

            if mode == "wide":
                parent.columnconfigure(1, weight=1)
                label.grid(row=0, column=0, sticky="w", padx=(0, 10))
                entry.grid(row=0, column=1, sticky="ew")

                for index, button in enumerate(buttons):
                    button.grid(
                        row=0,
                        column=index + 2,
                        sticky="ew",
                        padx=(10 if index == 0 else 8, 0)
                    )

                for index, widget in enumerate(detail_widgets):
                    widget.grid(
                        row=index + 1,
                        column=1,
                        columnspan=len(buttons) + 1,
                        sticky="w",
                        pady=(4, 0)
                    )
                return

            columns = max(1, min(compact_columns, len(buttons) or 1))

            for column in range(columns):
                parent.columnconfigure(column, weight=1, uniform="actions")

            label.grid(row=0, column=0, columnspan=columns, sticky="w")
            entry.grid(row=1, column=0, columnspan=columns, sticky="ew", pady=(4, 0))

            for index, button in enumerate(buttons):
                row = 2 + (index // columns)
                column = index % columns
                button.grid(
                    row=row,
                    column=column,
                    sticky="ew",
                    padx=(0 if column == 0 else 8, 0),
                    pady=(8, 0)
                )

            details_start_row = 2 + ((len(buttons) + columns - 1) // columns)

            for index, widget in enumerate(detail_widgets):
                widget.grid(
                    row=details_start_row + index,
                    column=0,
                    columnspan=columns,
                    sticky="w",
                    pady=(4, 0)
                )

        parent.bind(
            "<Configure>",
            lambda event: configure(event.width)
            if event.widget == parent
            else None,
            add="+"
        )
        parent.after_idle(configure)

    def bind_responsive_card_grid(self, parent, cards, columns_by_width):
        state = {"columns": None}

        def get_columns(width):
            for min_width, columns in columns_by_width:
                if width >= min_width:
                    return columns

            return 1

        def configure(width=None):
            if width is None:
                width = parent.winfo_width()

            columns = max(1, min(get_columns(width), len(cards) or 1))

            if state["columns"] == columns:
                return

            state["columns"] = columns

            for card in cards:
                card.grid_forget()

            rows = ((len(cards) + columns - 1) // columns) + 1
            self.clear_grid_layout(parent, rows=rows, columns=max(len(cards), columns))

            for column in range(columns):
                parent.columnconfigure(column, weight=1, uniform=str(id(parent)))

            for index, card in enumerate(cards):
                row = index // columns
                column = index % columns
                card.grid(
                    row=row,
                    column=column,
                    sticky="nsew",
                    padx=(0 if column == 0 else 8, 0),
                    pady=(0 if row == 0 else 8, 8)
                )

        parent.bind(
            "<Configure>",
            lambda event: configure(event.width)
            if event.widget == parent
            else None,
            add="+"
        )
        parent.after_idle(configure)

    def prepare_window(self, window):
        self.configure_child_icon(window)
        self.fade_in_window(window)

    def center_window(self, window):
        try:
            window.update_idletasks()
        except tk.TclError:
            return

        root_x = self.root.winfo_rootx()
        root_y = self.root.winfo_rooty()
        root_width = self.root.winfo_width()
        root_height = self.root.winfo_height()
        window_width = window.winfo_width()
        window_height = window.winfo_height()

        if root_width <= 1 or root_height <= 1:
            screen_width = window.winfo_screenwidth()
            screen_height = window.winfo_screenheight()
            pos_x = max((screen_width - window_width) // 2, 0)
            pos_y = max((screen_height - window_height) // 2, 0)
        else:
            pos_x = max(root_x + (root_width - window_width) // 2, 0)
            pos_y = max(root_y + (root_height - window_height) // 2, 0)

        window.geometry(f"+{pos_x}+{pos_y}")

    def configure_child_icon(self, window):
        if self.window_icon_photo is None:
            return

        try:
            window.iconphoto(False, self.window_icon_photo)
        except tk.TclError:
            pass

    def fade_in_window(self, window):
        try:
            window.attributes("-alpha", 0.0)
        except tk.TclError:
            return

        def step(alpha=0.0):
            if not window.winfo_exists():
                return

            next_alpha = min(alpha + 0.18, 1.0)
            window.attributes("-alpha", next_alpha)

            if next_alpha < 1.0:
                window.after(12, lambda: step(next_alpha))

        window.after(10, step)

    def create_scrollable_tree(
        self,
        parent,
        columns,
        selectmode="browse",
        height=15,
        show="headings"
    ):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        tree = ttk.Treeview(
            parent,
            columns=columns,
            show=show,
            selectmode=selectmode,
            height=height
        )
        tree.grid(row=0, column=0, sticky="nsew")

        vertical_scrollbar = ttk.Scrollbar(
            parent,
            orient="vertical",
            command=tree.yview,
            style="Vertical.TScrollbar"
        )
        vertical_scrollbar.grid(row=0, column=1, sticky="ns")

        horizontal_scrollbar = ttk.Scrollbar(
            parent,
            orient="horizontal",
            command=tree.xview,
            style="Horizontal.TScrollbar"
        )
        horizontal_scrollbar.grid(row=1, column=0, sticky="ew")

        tree.configure(
            yscrollcommand=vertical_scrollbar.set,
            xscrollcommand=horizontal_scrollbar.set
        )

        return tree

    def configure_change_tags(self, tree):
        tree.tag_configure("change_deleted", foreground="#D32F2F")
        tree.tag_configure("change_modified", foreground="#B77900")
        tree.tag_configure("change_added", foreground="#15803D")
        tree.tag_configure("change_previous", foreground="#101010")

    def get_change_tag(self, action):
        normalized_action = str(action).strip().lower()

        if normalized_action in ("excluido", "excluído"):
            return ("change_deleted",)

        if normalized_action == "alterado":
            return ("change_modified",)

        if normalized_action == "adicionado":
            return ("change_added",)

        if normalized_action == "mantido":
            return ("change_previous",)

        return ()

    def get_file_backup_status_tag(self, status):
        if status == BACKUP_STATUS_IN_BACKUP:
            return ("backup_ok",)

        if status == BACKUP_STATUS_PENDING:
            return ("backup_pending",)

        if status == BACKUP_STATUS_PENDING_DELETE:
            return ("backup_delete",)

        return ()

    def configure_tree_columns(self, tree, headings, column_specs):
        specs = []

        for key, title in headings.items():
            column_spec = column_specs.get(key, {})
            width = column_spec.get("width", 120)
            minwidth = column_spec.get("minwidth", min(width, 90))
            anchor = column_spec.get("anchor", "center")
            weight = column_spec.get("weight", 1)

            tree.heading(key, text=title)
            tree.column(
                key,
                width=width,
                minwidth=minwidth,
                anchor=anchor,
                stretch=False
            )
            specs.append(
                {
                    "key": key,
                    "width": width,
                    "minwidth": minwidth,
                    "weight": max(weight, 1),
                    "shrink": max(width - minwidth, 0),
                }
            )

        self.bind_responsive_tree_columns(tree, specs)

    def bind_responsive_tree_columns(self, tree, specs):
        def apply_widths(available_width):
            if available_width <= 1 or not tree.winfo_exists():
                return

            preferred_total = sum(spec["width"] for spec in specs)
            min_total = sum(spec["minwidth"] for spec in specs)

            if available_width <= min_total:
                target_widths = [spec["minwidth"] for spec in specs]
            elif available_width < preferred_total:
                overflow = preferred_total - available_width
                shrink_total = sum(spec["shrink"] for spec in specs) or 1
                target_widths = []
                used_width = 0

                for index, spec in enumerate(specs):
                    if index == len(specs) - 1:
                        width = max(spec["minwidth"], available_width - used_width)
                    else:
                        shrink = int(overflow * spec["shrink"] / shrink_total)
                        width = max(spec["minwidth"], spec["width"] - shrink)
                        used_width += width

                    target_widths.append(width)
            else:
                extra = available_width - preferred_total
                weight_total = sum(spec["weight"] for spec in specs) or 1
                target_widths = []
                used_width = 0

                for index, spec in enumerate(specs):
                    if index == len(specs) - 1:
                        width = max(spec["minwidth"], available_width - used_width)
                    else:
                        width = spec["width"] + int(extra * spec["weight"] / weight_total)
                        used_width += width

                    target_widths.append(width)

            for spec, width in zip(specs, target_widths):
                tree.column(spec["key"], width=max(spec["minwidth"], width))

        tree.bind("<Configure>", lambda event: apply_widths(event.width), add="+")
        tree.after_idle(lambda: apply_widths(tree.winfo_width()))

    def perform_backup(self):
        if not self.require_permission("run_backup"):
            return

        if not self.directories:
            messagebox.showwarning(
                "Sem diretorios",
                "Adicione ao menos um diretorio antes de iniciar o backup."
            )
            return

        if self.backup_in_progress:
            messagebox.showinfo(
                "Backup em andamento",
                "Ja existe um backup em execucao."
            )
            return

        if self.current_user.get("role") == "admin":
            metadata = self.ask_backup_metadata()

            if metadata is None:
                return

            self.pending_backup_name = metadata["name"]
            self.pending_backup_description = metadata["description"]
        else:
            self.pending_backup_name = ""
            self.pending_backup_description = ""

        self.start_backup_execution(
            directories=list(self.directories),
            trigger="manual"
        )

    def start_backup_execution(
        self,
        directories,
        trigger,
        backup_name=None,
        backup_description=None
    ):
        self.backup_in_progress = True
        self.pending_backup_directories = list(directories)
        self.pending_backup_trigger = trigger

        if backup_name is not None:
            self.pending_backup_name = backup_name

        if backup_description is not None:
            self.pending_backup_description = backup_description

        self.cancel_backup_requested.clear()
        self.open_progress_window()
        self.set_backup_button_state(tk.DISABLED)

        worker = threading.Thread(target=self.run_backup_in_background, daemon=True)
        worker.start()
        self.root.after(120, self.process_backup_events)

    def run_backup_in_background(self):
        try:
            result = run_backup_job(
                directories=self.pending_backup_directories or self.directories,
                backup_destination=self.get_backup_destination(),
                trigger=self.pending_backup_trigger,
                username=self.current_user.get("username"),
                user_role=self.current_user.get("role"),
                company_id=self.current_user.get("company_id", "default"),
                user_master_key=self.current_user.get("session_master_key"),
                backup_name=self.pending_backup_name,
                backup_description=self.pending_backup_description,
                progress_callback=self.enqueue_backup_progress,
                cancel_callback=self.is_backup_cancel_requested
            )
            self.backup_queue.put(("success", result))
        except BackupCancelledError as error:
            self.backup_queue.put(("cancelled", str(error)))
        except Exception as error:
            self.backup_queue.put(("error", str(error)))

    def enqueue_backup_progress(self, percent, message):
        self.backup_queue.put(("progress", percent, message))

    def ask_backup_metadata(self):
        window = tk.Toplevel(self.root)
        window.title("Identificar backup")
        window.geometry("460x330")
        window.minsize(420, 330)
        window.configure(bg=BG_COLOR)
        window.transient(self.root)
        self.prepare_window(window)
        window.grab_set()

        result = {"value": None}

        tk.Label(
            window,
            text="Identificar Backup",
            bg=BG_COLOR,
            fg=TITLE_COLOR,
            font=TITLE_FONT
        ).pack(pady=(22, 14))

        form = tk.Frame(window, bg=BG_COLOR)
        form.pack(fill="both", expand=True, padx=34)

        tk.Label(
            form,
            text="Nome do backup",
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=("Arial", 10, "bold")
        ).pack(anchor="w", pady=(0, 4))

        name_var = tk.StringVar()
        name_entry = tk.Entry(
            form,
            textvariable=name_var,
            font=("Arial", 11),
            bg=LIGHT_BUTTON,
            fg=TEXT_COLOR,
            relief="flat"
        )
        name_entry.pack(fill="x", pady=(0, 12))

        tk.Label(
            form,
            text="Descricao",
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=("Arial", 10, "bold")
        ).pack(anchor="w", pady=(0, 4))

        description_text = tk.Text(
            form,
            height=4,
            font=("Arial", 10),
            bg=LIGHT_BUTTON,
            fg=TEXT_COLOR,
            relief="flat",
            wrap="word"
        )
        description_text.pack(fill="both", expand=True, pady=(0, 16))

        buttons = tk.Frame(window, bg=BG_COLOR)
        buttons.pack()

        def submit():
            result["value"] = {
                "name": name_var.get().strip(),
                "description": description_text.get("1.0", tk.END).strip()
            }
            window.destroy()

        def cancel():
            result["value"] = None
            window.destroy()

        self.create_dialog_button(buttons, "Continuar", submit).grid(
            row=0, column=0, padx=6
        )
        cancel_button = tk.Button(
            buttons,
            text="Cancelar",
            command=cancel,
            font=BUTTON_FONT,
            bg=LIGHT_BUTTON,
            fg=TEXT_COLOR,
            activebackground=LIGHT_BUTTON,
            activeforeground=TEXT_COLOR,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground="#101722",
            highlightcolor="#101722",
            cursor="hand2",
            padx=12,
            pady=5
        )
        cancel_button.grid(row=0, column=1, padx=6)
        self.apply_button_feedback(cancel_button)

        name_entry.focus_set()
        window.protocol("WM_DELETE_WINDOW", cancel)
        self.root.wait_window(window)
        return result["value"]

    def is_backup_cancel_requested(self):
        return self.cancel_backup_requested.is_set()

    def process_backup_events(self):
        if self.is_closing:
            return

        should_continue = True

        while True:
            try:
                event = self.backup_queue.get_nowait()
            except queue.Empty:
                break

            event_type = event[0]

            if event_type == "progress":
                _, percent, message = event
                self.update_progress_window(percent, message)
                continue

            should_continue = False

            if event_type == "success":
                _, result = event
                self.finish_backup_success(result)
            elif event_type == "cancelled":
                _, message = event
                self.finish_backup_cancelled(message)
            elif event_type == "error":
                _, error_message = event
                self.finish_backup_error(error_message)

        if should_continue and self.backup_in_progress and not self.is_closing:
            self.root.after(120, self.process_backup_events)

    def open_progress_window(self):
        self.progress_window = tk.Toplevel(self.root)
        self.progress_window.title("Executando backup")
        self.progress_window.geometry("420x170")
        self.progress_window.minsize(380, 170)
        self.progress_window.configure(bg=BG_COLOR)
        self.progress_window.transient(self.root)
        self.prepare_window(self.progress_window)
        self.progress_window.grab_set()
        self.progress_window.protocol("WM_DELETE_WINDOW", lambda: None)
        self.center_window(self.progress_window)

        tk.Label(
            self.progress_window,
            text="Realizando backup",
            bg=BG_COLOR,
            fg=TITLE_COLOR,
            font=TITLE_FONT
        ).pack(pady=(22, 14))

        self.progress_label = tk.Label(
            self.progress_window,
            text="Preparando...",
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=BODY_FONT,
            wraplength=360,
            justify="center"
        )
        self.progress_label.pack(fill="x", padx=24, pady=(0, 12))

        self.progress_bar = ttk.Progressbar(
            self.progress_window,
            orient="horizontal",
            mode="determinate",
            maximum=100
        )
        self.progress_bar.pack(fill="x", padx=40, pady=(0, 10))
        self.progress_bar["value"] = 0

        self.cancel_button = tk.Button(
            self.progress_window,
            text="Cancelar",
            command=self.request_backup_cancel,
            font=BUTTON_FONT,
            bg=LIGHT_BUTTON,
            fg=TEXT_COLOR,
            activebackground=LIGHT_BUTTON,
            activeforeground=TEXT_COLOR,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground="#101722",
            highlightcolor="#101722",
            cursor="hand2",
            padx=14,
            pady=5
        )
        self.cancel_button.pack(pady=(4, 0))
        self.apply_button_feedback(self.cancel_button)

    def update_progress_window(self, percent, message):
        if self.progress_window is None or not self.progress_window.winfo_exists():
            return

        self.progress_bar["value"] = max(0, min(percent, 100))
        self.progress_label.config(text=message)
        self.progress_window.update_idletasks()

    def close_progress_window(self):
        if self.progress_window is None:
            return

        if self.progress_window.winfo_exists():
            self.progress_window.grab_release()
            self.progress_window.destroy()

        self.progress_window = None
        self.progress_label = None
        self.progress_bar = None
        self.cancel_button = None

    def open_download_progress_window(self):
        self.download_window = tk.Toplevel(self.root)
        self.download_window.title("Baixando backup")
        self.download_window.geometry("400x150")
        self.download_window.minsize(360, 150)
        self.download_window.configure(bg=BG_COLOR)
        self.download_window.transient(self.root)
        self.prepare_window(self.download_window)
        self.download_window.grab_set()
        self.download_window.protocol("WM_DELETE_WINDOW", lambda: None)
        self.center_window(self.download_window)

        tk.Label(
            self.download_window,
            text="Baixando backup",
            bg=BG_COLOR,
            fg=TITLE_COLOR,
            font=TITLE_FONT
        ).pack(pady=(20, 12))

        self.download_label = tk.Label(
            self.download_window,
            text="Preparando...",
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=BODY_FONT,
            wraplength=340,
            justify="center"
        )
        self.download_label.pack(fill="x", padx=24, pady=(0, 12))

        self.download_bar = ttk.Progressbar(
            self.download_window,
            orient="horizontal",
            mode="determinate",
            maximum=100
        )
        self.download_bar.pack(fill="x", padx=36, pady=(0, 6))
        self.download_bar["value"] = 0

    def update_download_progress_window(self, percent, message):
        if self.download_window is None or not self.download_window.winfo_exists():
            return

        self.download_bar["value"] = max(0, min(percent, 100))
        self.download_label.config(text=message)
        self.download_window.update_idletasks()

    def close_download_progress_window(self):
        if self.download_window is None:
            return

        if self.download_window.winfo_exists():
            self.download_window.grab_release()
            self.download_window.destroy()

        self.download_window = None
        self.download_label = None
        self.download_bar = None

    def enqueue_download_progress(self, percent, message):
        self.download_queue.put(("progress", percent, message))

    def process_download_events(self):
        if self.is_closing:
            return

        should_continue = True

        while True:
            try:
                event = self.download_queue.get_nowait()
            except queue.Empty:
                break

            event_type = event[0]

            if event_type == "progress":
                _, percent, message = event
                self.update_download_progress_window(percent, message)
                continue

            should_continue = False

            if event_type == "success":
                _, message = event
                self.update_download_progress_window(100, "Download concluido.")
                self.root.after(300, self.close_download_progress_window)
                self.root.after(
                    320,
                    lambda current_message=message: messagebox.showinfo(
                        "Backup exportado",
                        current_message,
                        parent=self.root
                    )
                )
            elif event_type == "error":
                _, error_message = event
                self.close_download_progress_window()
                messagebox.showerror(
                    "Erro ao exportar backup",
                    error_message,
                    parent=self.root
                )

        if should_continue and self.download_window is not None and not self.is_closing:
            self.root.after(120, self.process_download_events)

    def copy_file_with_progress(self, source_path, destination_path):
        total_size = max(os.path.getsize(source_path), 1)
        copied_size = 0
        chunk_size = 1024 * 1024
        destination_directory = os.path.dirname(destination_path)

        if destination_directory:
            os.makedirs(destination_directory, exist_ok=True)

        with open(source_path, "rb") as source_file:
            with open(destination_path, "wb") as target_file:
                while True:
                    chunk = source_file.read(chunk_size)

                    if not chunk:
                        break

                    target_file.write(chunk)
                    copied_size += len(chunk)
                    percent = int((copied_size / total_size) * 100)
                    self.enqueue_download_progress(
                        percent,
                        f"Copiando arquivo... {percent}%"
                    )

        shutil.copystat(source_path, destination_path)

    def set_backup_button_state(self, state):
        if self.backup_button is not None:
            self.backup_button.config(state=state)

    def request_backup_cancel(self):
        if not self.backup_in_progress or self.cancel_backup_requested.is_set():
            return

        self.cancel_backup_requested.set()
        self.update_progress_window(
            self.progress_bar["value"] if self.progress_bar is not None else 0,
            "Cancelando backup..."
        )

        if self.cancel_button is not None:
            self.cancel_button.config(state=tk.DISABLED, text="Cancelando...")

    def finish_backup_success(self, result):
        self.backup_in_progress = False
        self.cancel_backup_requested.clear()
        self.pending_backup_directories = None
        self.pending_backup_trigger = "manual"
        self.set_backup_button_state(tk.NORMAL)
        self.close_progress_window()
        self.refresh_footer()
        self.refresh_dashboard_if_home()

        warning_count = len(result.get("warnings", []))
        warning_text = ""

        if warning_count:
            warning_text = (
                f"\n\nArquivos ignorados por erro durante a copia: {warning_count}"
            )

        if result.get("storage_mode") == "incremental":
            messagebox.showinfo(
                "Backup concluido",
                (
                    "Backup incremental realizado com sucesso.\n\n"
                    f"Snapshot salvo em:\n{result.get('snapshot_path') or result.get('backup_path')}\n\n"
                    f"Armazenamento:\n{result.get('backup_storage', '')}\n\n"
                    f"Arquivos processados: {result.get('total_files', 0)}\n"
                    f"Novos objetos: {result.get('objects_stored', 0)}\n"
                    f"Referencias existentes: {result.get('objects_referenced', 0)}\n"
                    f"Sem alteracao: {result.get('files_unchanged', 0)}"
                    f"{warning_text}"
                )
            )
            return

        messagebox.showinfo(
            "Backup concluido",
            (
                "Backup realizado com sucesso.\n\n"
                f"Arquivo salvo em:\n{result['backup_path']}\n\n"
                f"Pasta do dia:\n{result['backup_folder']}\n\n"
                f"Arquivos compactados: {result['total_files']}"
                f"{warning_text}"
            )
        )

    def finish_backup_error(self, error_message):
        self.backup_in_progress = False
        self.cancel_backup_requested.clear()
        self.pending_backup_directories = None
        self.pending_backup_trigger = "manual"
        self.set_backup_button_state(tk.NORMAL)
        self.close_progress_window()
        messagebox.showerror("Erro", error_message)

    def finish_backup_cancelled(self, message):
        self.backup_in_progress = False
        self.cancel_backup_requested.clear()
        self.pending_backup_directories = None
        self.pending_backup_trigger = "manual"
        self.set_backup_button_state(tk.NORMAL)
        self.close_progress_window()
        messagebox.showinfo("Backup cancelado", message)

    def append_history(self, entry):
        history = self.load_history()
        history.append(entry)

        os.makedirs("config", exist_ok=True)

        with open(HISTORY_PATH, "w", encoding="utf-8") as file:
            json.dump(history[-50:], file, indent=4, ensure_ascii=False)

    def load_history(self):
        if not os.path.exists(HISTORY_PATH):
            return []

        with open(HISTORY_PATH, "r", encoding="utf-8") as file:
            try:
                data = json.load(file)
            except json.JSONDecodeError:
                return []

        if isinstance(data, list):
            return data

        return []

    def get_latest_history_entry(self):
        history = self.load_history()

        if not history:
            return None

        return history[-1]

    def get_latest_visible_history_entry(self):
        history = self.get_visible_history()

        if not history:
            return None

        return history[-1]

    def get_visible_history(self):
        return [
            entry
            for entry in self.load_history()
            if can_view_backup_entry(self.current_user, entry)
        ]

    def open_schedule_window(self):
        if not self.require_permission("schedule_backup"):
            return

        window = tk.Toplevel(self.root)
        window.title("Agendar backup")
        window.geometry("460x320")
        window.minsize(430, 310)
        window.configure(bg=BG_COLOR)
        window.transient(self.root)
        self.prepare_window(window)

        tk.Label(
            window,
            text="Agendar Backup",
            bg=BG_COLOR,
            fg=TITLE_COLOR,
            font=TITLE_FONT
        ).pack(pady=(18, 18))

        form = tk.Frame(window, bg=BG_COLOR)
        form.pack(fill="x", padx=28, pady=4)
        form.columnconfigure(1, weight=1)
        schedule_data = self.load_schedule()
        config_data = self.load_config()
        priority_policy_var = tk.BooleanVar(
            value=bool(
                config_data.get(
                    "priority_backup_policy_enabled",
                    DEFAULT_PRIORITY_BACKUP_POLICY_ENABLED
                )
            )
        )

        tk.Label(
            form,
            text="Horario inicial (HH:MM)",
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=("Arial", 11)
        ).grid(row=0, column=0, sticky="w", pady=6)

        start_time_var = tk.StringVar(
            value=schedule_data.get("time_start") or schedule_data.get("time", "09:00")
        )
        start_time_entry = tk.Entry(form, textvariable=start_time_var, font=("Arial", 11))
        start_time_entry.grid(row=0, column=1, sticky="ew", padx=(10, 0), pady=6)

        tk.Label(
            form,
            text="Horario final (HH:MM)",
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=("Arial", 11)
        ).grid(row=1, column=0, sticky="w", pady=6)

        end_time_var = tk.StringVar(
            value=schedule_data.get("time_end", "18:00")
        )
        end_time_entry = tk.Entry(form, textvariable=end_time_var, font=("Arial", 11))
        end_time_entry.grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=6)

        info = tk.Label(
            window,
            text="O backup sera executado automaticamente uma vez por dia dentro da faixa escolhida.",
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=("Arial", 10),
            wraplength=340,
            justify="center"
        )
        info.pack(pady=(12, 14))

        priority_policy_check = tk.Checkbutton(
            window,
            text="Ativar backup automatico por prioridade",
            variable=priority_policy_var,
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            activebackground=BG_COLOR,
            activeforeground=SUBTLE_TEXT,
            selectcolor=PANEL_COLOR,
            font=("Arial", 10, "bold")
        )
        priority_policy_check.pack(pady=(0, 14))

        def save_schedule():
            start_value = start_time_var.get().strip()
            end_value = end_time_var.get().strip()

            if (
                not self.is_valid_time(start_value)
                or not self.is_valid_time(end_value)
            ):
                messagebox.showwarning(
                    "Horario invalido",
                    "Informe os horarios no formato HH:MM.",
                    parent=window
                )
                return

            payload = {
                "time_start": start_value,
                "time_end": end_value,
                "updated_at": datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            }

            os.makedirs("config", exist_ok=True)

            with open(SCHEDULE_PATH, "w", encoding="utf-8") as file:
                json.dump(payload, file, indent=4, ensure_ascii=False)

            config_payload = self.load_config()
            config_payload["priority_backup_policy_enabled"] = bool(
                priority_policy_var.get()
            )
            self.save_config(config_payload)

            self.refresh_footer()
            messagebox.showinfo(
                "Agendamento salvo",
                "Horario e politica por prioridade salvos com sucesso.",
                parent=window
            )
            window.destroy()

        self.create_dialog_button(window, "Salvar agendamento", save_schedule).pack()

    def load_schedule(self):
        if not os.path.exists(SCHEDULE_PATH):
            return {}

        with open(SCHEDULE_PATH, "r", encoding="utf-8") as file:
            try:
                data = json.load(file)
            except json.JSONDecodeError:
                return {}

        if isinstance(data, dict):
            return data

        return {}

    def is_valid_time(self, value):
        try:
            datetime.strptime(value, "%H:%M")
            return True
        except ValueError:
            return False

    def show_files_window(self):
        if not self.require_permission("view_files"):
            return

        if not self.directories:
            self.show_message_panel(
                "Sem diretorios monitorados",
                "Adicione ao menos uma pasta em Gerenciar diretorios para listar os arquivos monitorados."
            )
            return

        _panel, shell_content = self.create_content_shell(
            "Arquivos monitorados",
            subtitle="Visualize as pastas acompanhadas pelo sistema mesmo antes do primeiro backup."
        )
        scroll_content = ScrollableFrame(shell_content, bg=HOME_PANEL_COLOR)
        scroll_content.grid(row=0, column=0, sticky="nsew")
        content = scroll_content.body
        content.columnconfigure(0, weight=1)
        content.rowconfigure(1, weight=1)

        top_bar = tk.Frame(content, bg=BG_COLOR)
        top_bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        top_bar.columnconfigure(0, weight=1)

        file_search_var = tk.StringVar()

        search_line = tk.Frame(top_bar, bg=BG_COLOR)
        search_line.grid(row=0, column=0, sticky="ew")
        search_line.columnconfigure(1, weight=1)

        search_label = tk.Label(
            search_line,
            text="Buscar arquivo",
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=BODY_BOLD_FONT
        )
        self.register_responsive_font(search_label, BODY_BOLD_FONT, min_size=8)
        search_label.grid(row=0, column=0, sticky="w", padx=(0, 10))

        file_search_entry = tk.Entry(
            search_line,
            textvariable=file_search_var,
            font=TABLE_FONT,
            bg=LIGHT_BUTTON,
            fg=TEXT_COLOR,
            relief="flat"
        )
        self.register_responsive_font(file_search_entry, TABLE_FONT, min_size=8)
        file_search_entry.grid(row=0, column=1, sticky="ew")

        action_flow = FlowFrame(
            top_bar,
            bg=BG_COLOR,
            min_item_width=120,
            hgap=8,
            vgap=8,
            max_columns=5
        )
        action_flow.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        search_button = self.create_dialog_button(
            action_flow,
            "Buscar",
            lambda: apply_file_search()
        )
        action_flow.add(search_button)

        def clear_file_search():
            file_search_var.set("")
            refresh_table()

        clear_button = self.create_dialog_button(
            action_flow,
            "Limpar",
            clear_file_search
        )
        action_flow.add(clear_button)

        expand_button = self.create_dialog_button(
            action_flow,
            "Expandir",
            lambda: set_all_nodes_open(True)
        )
        action_flow.add(expand_button)

        collapse_button = self.create_dialog_button(
            action_flow,
            "Recolher",
            lambda: set_all_nodes_open(False)
        )
        action_flow.add(collapse_button)

        refresh_button = self.create_dialog_button(
            action_flow,
            "Atualizar",
            lambda: refresh_table()
        )
        action_flow.add(refresh_button)

        filter_summary_var = tk.StringVar(value="Exibindo todos os arquivos monitorados")
        filter_summary_label = tk.Label(
            top_bar,
            textvariable=filter_summary_var,
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=BODY_FONT
        )
        self.register_responsive_font(filter_summary_label, BODY_FONT, min_size=8)
        filter_summary_label.grid(row=2, column=0, sticky="w", pady=(4, 0))

        status_var = tk.StringVar()
        status_label = tk.Label(
            top_bar,
            textvariable=status_var,
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=BODY_FONT
        )
        self.register_responsive_font(status_label, BODY_FONT, min_size=8)
        status_label.grid(row=3, column=0, sticky="w", pady=(4, 0))

        table_frame = tk.Frame(content, bg=BG_COLOR)
        table_frame.grid(row=1, column=0, sticky="nsew")

        columns = (
            "extension",
            "priority",
            "priority_score",
            "added_to_backup_at",
            "added_in_backup",
            "backup_status",
            "size_mb",
            "days_since_modified",
        )
        tree = self.create_scrollable_tree(
            table_frame,
            columns,
            height=15,
            show="tree headings"
        )
        tree.heading("#0", text="Nome")
        tree.column("#0", width=420, minwidth=260, anchor="w", stretch=True)
        self.configure_tree_columns(
            tree,
            {
                "extension": "Extensao",
                "priority": "Prioridade",
                "priority_score": "Score",
                "added_to_backup_at": "Adicionado ao backup",
                "added_in_backup": "Backup adicionado",
                "backup_status": "Status backup",
                "size_mb": "Tamanho (MB)",
                "days_since_modified": "Dias sem alterar",
            },
            {
                "extension": {"width": 100, "minwidth": 80, "weight": 1},
                "priority": {"width": 135, "minwidth": 115, "weight": 1},
                "priority_score": {"width": 80, "minwidth": 70, "weight": 1},
                "added_to_backup_at": {
                    "width": 155,
                    "minwidth": 135,
                    "weight": 2,
                },
                "added_in_backup": {
                    "width": 155,
                    "minwidth": 130,
                    "weight": 2,
                    "anchor": "w",
                },
                "backup_status": {
                    "width": 145,
                    "minwidth": 125,
                    "weight": 1,
                    "anchor": "w",
                },
                "size_mb": {"width": 110, "minwidth": 90, "weight": 1},
                "days_since_modified": {
                    "width": 120,
                    "minwidth": 105,
                    "weight": 1,
                },
            }
        )

        tree.tag_configure("backup_ok", foreground="#111827")
        tree.tag_configure("backup_pending", foreground="#B45309")
        tree.tag_configure("backup_delete", foreground="#B91C1C")
        tree.tag_configure("file_monitored", foreground="#0F172A")
        tree.tag_configure("directory_root", foreground=TITLE_COLOR, font=TABLE_FONT)
        tree.tag_configure("directory_child", foreground="#1F2937")
        tree.tag_configure("directory_missing", foreground="#D32F2F", font=TABLE_FONT)

        def apply_file_search(value=None):
            if value is not None:
                file_search_var.set(value)

            refresh_table()

        def on_file_search_changed(*_args):
            refresh_table()

        def toggle_node(item_id, expanded):
            tree.item(item_id, open=expanded)

            for child in tree.get_children(item_id):
                toggle_node(child, expanded)

        def set_all_nodes_open(expanded):
            for item in tree.get_children():
                toggle_node(item, expanded)

        def count_visible_files(nodes):
            total = 0

            for node in nodes:
                if node.get("is_dir"):
                    total += count_visible_files(node.get("children", []))
                else:
                    total += 1

            return total

        def refresh_table(*_args):
            for item in tree.get_children():
                tree.delete(item)

            nodes, summary = self.build_monitored_file_nodes()
            filtered_nodes = self.filter_monitored_nodes(
                nodes,
                file_search_var.get()
            )
            self.insert_monitored_file_nodes(tree, filtered_nodes)

            if file_search_var.get().strip():
                filter_summary_var.set(
                    f"Filtro ativo: {file_search_var.get().strip()}"
                )
            else:
                filter_summary_var.set("Exibindo todos os arquivos monitorados")

            status_var.set(
                f"{summary['directories']} diretorio(s) monitorado(s)  |  "
                f"{count_visible_files(filtered_nodes)} arquivo(s) exibido(s)  |  "
                f"{summary['missing_directories']} diretorio(s) indisponivel(is)"
            )

        file_search_var.trace_add("write", on_file_search_changed)
        file_search_entry.bind("<Return>", lambda _event: apply_file_search())
        refresh_table()
        file_search_entry.focus_set()

    def format_float(self, value):
        try:
            return f"{float(value):.2f}"
        except (TypeError, ValueError):
            return value

    def format_size_bytes(self, size_bytes):
        try:
            size = float(size_bytes)
        except (TypeError, ValueError):
            return "-"

        if size >= 1024 * 1024:
            return f"{size / (1024 * 1024):.2f} MB"

        if size >= 1024:
            return f"{size / 1024:.2f} KB"

        return f"{int(size)} B"

    def get_recoverable_changes(self, entry):
        changes = entry.get("file_changes", [])

        if not isinstance(changes, list):
            return []

        return [
            change
            for change in changes
            if (
                isinstance(change, dict)
                and change.get("action") in ("alterado", "excluido")
            )
        ]

    def count_changes_by_action(self, entry, action):
        return sum(
            1
            for change in self.get_recoverable_changes(entry)
            if change.get("action") == action
        )

    def get_history_entry_files(self, entry):
        changes = entry.get("file_changes", [])
        snapshot = entry.get("file_snapshot", {})

        if not isinstance(changes, list):
            changes = []

        if not isinstance(snapshot, dict):
            snapshot = {}

        displayed_files = []
        current_snapshot_names = set(snapshot.keys())
        changed_snapshot_names = {
            change.get("archive_name", "")
            for change in changes
            if isinstance(change, dict)
        }
        action_order = {
            "adicionado": 0,
            "alterado": 1,
            "excluido": 2,
            "mantido": 3,
        }

        for change in changes:
            if not isinstance(change, dict):
                continue

            displayed_files.append(
                {
                    "action": change.get("action", "-"),
                    "name": change.get("name", ""),
                    "priority": change.get("priority", "-") or "-",
                    "archive_name": change.get("archive_name", ""),
                    "size_bytes": change.get("size_bytes", 0),
                    "modified_at": change.get("modified_at", ""),
                }
            )

        for archive_name in sorted(current_snapshot_names):
            if archive_name in changed_snapshot_names:
                continue

            file_data = snapshot.get(archive_name, {})

            if not isinstance(file_data, dict):
                continue

            displayed_files.append(
                {
                    "action": "mantido",
                    "name": file_data.get("name", ""),
                    "priority": file_data.get("priority", "-") or "-",
                    "archive_name": archive_name,
                    "size_bytes": file_data.get("size_bytes", 0),
                    "modified_at": file_data.get("modified_at", ""),
                }
            )

        displayed_files.sort(
            key=lambda item: (
                action_order.get(str(item.get("action", "")).strip().lower(), 99),
                str(item.get("name", "")).lower(),
                str(item.get("archive_name", "")).lower(),
            )
        )

        return displayed_files

    def get_change_folder(self, change):
        target_path = build_restore_target(change)

        if target_path:
            return os.path.dirname(os.path.abspath(os.path.normpath(target_path)))

        return ""

    def sanitize_restore_name(self, name):
        sanitized = re.sub(r'[<>:"/\\|?*]+', "_", name.strip())
        sanitized = sanitized.strip(". ")
        return sanitized

    def ensure_unique_folder_path(self, folder_path):
        candidate_path = folder_path
        counter = 2

        while os.path.exists(candidate_path):
            candidate_path = f"{folder_path}_{counter}"
            counter += 1

        return candidate_path

    def build_folder_target_overrides(self, changes, folder_path, restored_folder):
        overrides = {}
        normalized_folder = os.path.abspath(os.path.normpath(folder_path))

        for change in changes:
            target_path = build_restore_target(change)

            if not target_path:
                continue

            try:
                relative_path = os.path.relpath(target_path, normalized_folder)
            except ValueError:
                relative_path = os.path.basename(target_path)

            overrides[change.get("archive_name", "")] = os.path.join(
                restored_folder,
                relative_path
            )

        return overrides

    def is_change_inside_folder(self, change, folder_path):
        if not folder_path:
            return False

        target_path = build_restore_target(change)

        if target_path:
            try:
                normalized_path = os.path.normcase(os.path.abspath(target_path))
                normalized_folder = os.path.normcase(os.path.abspath(folder_path))
                return os.path.commonpath(
                    [normalized_path, normalized_folder]
                ) == normalized_folder
            except ValueError:
                return False

        return False

    def restore_incremental_snapshot_from_file(self, parent=None):
        parent = parent or self.root
        snapshots_directory = self.get_current_user_backup_destination()
        initial_directory = (
            snapshots_directory
            if os.path.isdir(snapshots_directory)
            else self.get_backup_destination()
        )
        snapshot_path = filedialog.askopenfilename(
            title="Escolher snapshot incremental",
            initialdir=initial_directory,
            filetypes=[
                ("Snapshot JSON", "*.json"),
                ("Todos os arquivos", "*.*"),
            ],
            parent=parent
        )

        if not snapshot_path:
            return

        restore_destination = filedialog.askdirectory(
            title="Escolher pasta de restauracao",
            parent=parent
        )

        if not restore_destination:
            return

        if not messagebox.askyesno(
            "Confirmar restauracao",
            (
                "Restaurar todos os arquivos do snapshot selecionado?\n\n"
                "Arquivos existentes com conteudo diferente serao restaurados "
                "com sufixo, sem sobrescrever o original."
            ),
            parent=parent
        ):
            return

        try:
            results = restore_snapshot(
                snapshot_path,
                restore_destination,
                conflict_strategy="rename",
                user_master_key=self.current_user.get("session_master_key")
            )
        except Exception as error:
            messagebox.showerror("Erro", str(error), parent=parent)
            return

        restored = [item for item in results if item["status"] == "restored"]
        renamed = [
            item for item in results
            if item["status"] == "restored_renamed"
        ]
        identical = [
            item for item in results
            if item["status"] == "identical_existing"
        ]
        skipped = [
            item for item in results
            if item["status"] == "skipped_existing"
        ]
        missing = [item for item in results if item["status"] == "not_found"]
        errors = [item for item in results if item["status"] == "error"]

        lines = [
            f"Restaurados: {len(restored)}",
            f"Restaurados com outro nome: {len(renamed)}",
            f"Ja existiam com mesmo conteudo: {len(identical)}",
            f"Ignorados por conflito: {len(skipped)}",
            f"Objetos nao encontrados: {len(missing)}",
            f"Com erro: {len(errors)}",
            "",
            f"Destino:\n{restore_destination}",
        ]
        problem_items = (missing + errors)[:5]

        if problem_items:
            lines.append("")
            lines.append("Detalhes:")

            for item in problem_items:
                lines.append(
                    f"- {item.get('archive_name', '')}: "
                    f"{item.get('message', '')}"
                )

        messagebox.showinfo(
            "Snapshot restaurado",
            "\n".join(lines),
            parent=parent
        )

    def show_restore_window(self):
        if not self.require_permission("restore_backup"):
            return

        history = [
            (index, entry)
            for index, entry in enumerate(self.load_history())
            if can_view_backup_entry(self.current_user, entry)
        ]

        if not history:
            self.show_message_panel(
                "Sem backups",
                "Nenhum backup disponivel no historico.",
                "Restaurar snapshot",
                self.restore_incremental_snapshot_from_file
            )
            return

        indexed_history = list(reversed(history))
        current_recoverable_changes = []
        restore_filters = {
            "name": "",
            "archive_name": "",
            "source_path": "",
            "action": "Todos",
            "modified_from": "",
            "modified_to": "",
        }

        window, shell_content = self.create_content_shell("Recuperar Arquivos e Versoes")
        scroll_content = ScrollableFrame(shell_content, bg=HOME_PANEL_COLOR)
        scroll_content.grid(row=0, column=0, sticky="nsew")
        content = scroll_content.body

        search_bar = tk.Frame(content, bg=BG_COLOR)
        search_bar.columnconfigure(1, weight=1)

        search_var = tk.StringVar()

        restore_search_label = tk.Label(
            search_bar,
            text="Buscar arquivo",
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=("Arial", 10, "bold")
        )
        self.register_responsive_font(restore_search_label, ("Arial", 10, "bold"), min_size=8)
        restore_search_label.grid(row=0, column=0, sticky="w", padx=(0, 10))

        search_entry = tk.Entry(
            search_bar,
            textvariable=search_var,
            font=TABLE_FONT,
            bg=LIGHT_BUTTON,
            fg=TEXT_COLOR,
            relief="flat"
        )
        self.register_responsive_font(search_entry, TABLE_FONT, min_size=8)
        search_entry.grid(row=0, column=1, sticky="ew")

        suggestion_box = tk.Listbox(
            search_bar,
            height=4,
            font=SUGGESTION_FONT,
            bg="#F2F2F2",
            fg=TEXT_COLOR,
            selectbackground="#FFE0B2",
            selectforeground=TEXT_COLOR,
            relief="flat",
            bd=0,
            highlightthickness=2,
            highlightbackground=TITLE_COLOR,
            highlightcolor=TITLE_COLOR,
            activestyle="none"
        )
        self.register_responsive_font(suggestion_box, SUGGESTION_FONT, min_size=8)

        restore_search_button = self.create_dialog_button(
            search_bar,
            "Buscar",
            lambda: apply_restore_search()
        )
        restore_search_button.grid(row=0, column=2, padx=(10, 0))

        def clear_file_search():
            search_var.set("")
            hide_restore_suggestions()
            refresh_backups()

        restore_clear_button = self.create_dialog_button(
            search_bar,
            "Limpar",
            clear_file_search
        )
        restore_clear_button.grid(row=0, column=3, padx=(8, 0))

        restore_search_layout = {"mode": None, "suggestion_row": 1}

        def configure_restore_search_bar(width=None):
            if width is None:
                width = search_bar.winfo_width()

            mode = "compact" if width < 560 else "wide"

            if restore_search_layout["mode"] == mode:
                return

            suggestions_visible = suggestion_box.winfo_manager() == "grid"

            restore_search_layout["mode"] = mode

            for widget in (
                restore_search_label,
                search_entry,
                restore_search_button,
                restore_clear_button,
                suggestion_box,
            ):
                widget.grid_forget()

            self.clear_grid_layout(search_bar, rows=4, columns=4)

            if mode == "wide":
                search_bar.columnconfigure(1, weight=1)
                restore_search_label.grid(row=0, column=0, sticky="w", padx=(0, 10))
                search_entry.grid(row=0, column=1, sticky="ew")
                restore_search_button.grid(row=0, column=2, padx=(10, 0))
                restore_clear_button.grid(row=0, column=3, padx=(8, 0))
                restore_search_layout["suggestion_row"] = 1

                if suggestions_visible:
                    suggestion_box.grid(
                        row=1,
                        column=1,
                        columnspan=3,
                        sticky="ew",
                        pady=(4, 0)
                    )
                return

            for column in range(2):
                search_bar.columnconfigure(column, weight=1, uniform="restore_search")

            restore_search_label.grid(row=0, column=0, columnspan=2, sticky="w")
            search_entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))
            restore_search_button.grid(row=2, column=0, sticky="ew", pady=(8, 0))
            restore_clear_button.grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
            restore_search_layout["suggestion_row"] = 3

            if suggestions_visible:
                suggestion_box.grid(
                    row=3,
                    column=0,
                    columnspan=2,
                    sticky="ew",
                    pady=(4, 0)
                )

        def get_restore_search_suggestions():
            search_text = search_var.get().strip().lower()

            if not search_text:
                return []

            suggestions = []
            seen = set()

            for _, entry in indexed_history:
                for change in self.get_recoverable_changes(entry):
                    for value in (
                        change.get("name", ""),
                        change.get("archive_name", ""),
                        change.get("source_path", "")
                    ):
                        suggestion = str(value).strip()

                        if not suggestion:
                            continue

                        suggestion_key = suggestion.lower()

                        if (
                            search_text in suggestion_key
                            and suggestion_key not in seen
                        ):
                            suggestions.append(suggestion)
                            seen.add(suggestion_key)

                        if len(suggestions) >= 8:
                            return suggestions

            return suggestions

        def hide_restore_suggestions():
            suggestion_box.grid_forget()

        def update_restore_suggestions(*_args):
            suggestion_box.delete(0, tk.END)
            suggestions = get_restore_search_suggestions()

            if not suggestions:
                hide_restore_suggestions()
                return

            for suggestion in suggestions:
                suggestion_box.insert(tk.END, f"  {suggestion}")

            suggestion_box.config(height=min(len(suggestions), 5))
            suggestion_box.grid(
                row=restore_search_layout["suggestion_row"],
                column=0 if restore_search_layout["mode"] == "compact" else 1,
                columnspan=2 if restore_search_layout["mode"] == "compact" else 3,
                sticky="ew",
                pady=(4, 0)
            )

        def apply_restore_search(value=None):
            if value is not None:
                search_var.set(value)

            hide_restore_suggestions()
            refresh_backups()

        def select_restore_suggestion(_event=None):
            selection = suggestion_box.curselection()

            if selection:
                apply_restore_search(suggestion_box.get(selection[0]).strip())

        search_var.trace_add("write", update_restore_suggestions)
        search_entry.bind("<Return>", lambda _event: apply_restore_search())
        search_entry.bind("<Escape>", lambda _event: hide_restore_suggestions())
        suggestion_box.bind("<ButtonRelease-1>", select_restore_suggestion)
        suggestion_box.bind("<Double-Button-1>", select_restore_suggestion)
        suggestion_box.bind("<Return>", select_restore_suggestion)
        search_bar.bind(
            "<Configure>",
            lambda event: configure_restore_search_bar(event.width)
            if event.widget == search_bar
            else None,
            add="+"
        )
        search_bar.after_idle(configure_restore_search_bar)

        backup_label = tk.Label(
            content,
            text="Backups",
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=("Arial", 10, "bold")
        )
        self.register_responsive_font(backup_label, ("Arial", 10, "bold"), min_size=8)

        recoverable_summary = tk.StringVar(value="Arquivos recuperaveis")
        recoverable_label = tk.Label(
            content,
            textvariable=recoverable_summary,
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=("Arial", 10, "bold")
        )
        self.register_responsive_font(recoverable_label, ("Arial", 10, "bold"), min_size=8)

        backup_frame = tk.Frame(content, bg=BG_COLOR)

        backup_columns = (
            "timestamp",
            "user",
            "backup_name",
            "trigger",
            "changed",
            "deleted"
        )
        backup_tree = self.create_scrollable_tree(
            backup_frame,
            backup_columns,
            selectmode="browse"
        )

        backup_headings = {
            "timestamp": "Data",
            "user": "Usuario",
            "backup_name": "Backup",
            "trigger": "Tipo",
            "changed": "Alterados",
            "deleted": "Excluidos"
        }

        self.configure_tree_columns(
            backup_tree,
            backup_headings,
            {
                "timestamp": {"width": 135, "minwidth": 120, "weight": 2},
                "user": {"width": 80, "minwidth": 65, "weight": 1},
                "backup_name": {
                    "width": 170,
                    "minwidth": 130,
                    "weight": 3,
                    "anchor": "w",
                },
                "trigger": {"width": 80, "minwidth": 62, "weight": 1},
                "changed": {"width": 85, "minwidth": 64, "weight": 1},
                "deleted": {"width": 85, "minwidth": 64, "weight": 1},
            }
        )

        file_frame = tk.Frame(content, bg=BG_COLOR)

        file_columns = (
            "action",
            "name",
            "archive_name",
            "source_path",
            "size",
            "modified_at"
        )
        file_tree = self.create_scrollable_tree(
            file_frame,
            file_columns,
            selectmode="extended"
        )

        file_headings = {
            "action": "Acao",
            "name": "Arquivo",
            "archive_name": "Caminho no backup",
            "source_path": "Local original",
            "size": "Tamanho",
            "modified_at": "Modificado em"
        }

        self.configure_tree_columns(
            file_tree,
            file_headings,
            {
                "action": {"width": 90, "minwidth": 75, "weight": 1},
                "name": {
                    "width": 220,
                    "minwidth": 170,
                    "weight": 3,
                    "anchor": "w",
                },
                "archive_name": {
                    "width": 300,
                    "minwidth": 230,
                    "weight": 4,
                    "anchor": "w",
                },
                "source_path": {
                    "width": 360,
                    "minwidth": 260,
                    "weight": 5,
                    "anchor": "w",
                },
                "size": {"width": 95, "minwidth": 80, "weight": 1},
                "modified_at": {
                    "width": 150,
                    "minwidth": 130,
                    "weight": 2,
                },
            }
        )
        self.configure_change_tags(file_tree)

        button_bar = tk.Frame(content, bg=BG_COLOR)

        restore_layout_state = {"mode": None}

        def configure_restore_layout(width=None):
            if width is None:
                width = window.winfo_width()

            mode = "wide" if width >= 1380 else "stacked"

            if restore_layout_state["mode"] == mode:
                return

            restore_layout_state["mode"] = mode

            for widget in (
                backup_label,
                recoverable_label,
                search_bar,
                backup_frame,
                file_frame,
                button_bar,
            ):
                widget.grid_forget()

            for column in range(2):
                content.columnconfigure(column, weight=0)

            for row in range(6):
                content.rowconfigure(row, weight=0)

            if mode == "wide":
                content.columnconfigure(0, weight=5)
                content.columnconfigure(1, weight=7)
                content.rowconfigure(2, weight=1)

                search_bar.grid(
                    row=0,
                    column=0,
                    columnspan=2,
                    sticky="ew",
                    pady=(0, 10)
                )
                backup_label.grid(row=1, column=0, sticky="w", pady=(0, 6))
                recoverable_label.grid(row=1, column=1, sticky="w", pady=(0, 6))
                backup_frame.grid(
                    row=2,
                    column=0,
                    sticky="nsew",
                    padx=(0, 14)
                )
                file_frame.grid(row=2, column=1, sticky="nsew")
                button_bar.grid(
                    row=3,
                    column=0,
                    columnspan=2,
                    sticky="e",
                    pady=(10, 0)
                )
            else:
                content.columnconfigure(0, weight=1)
                content.rowconfigure(2, weight=1)
                content.rowconfigure(4, weight=2)

                search_bar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
                backup_label.grid(row=1, column=0, sticky="w", pady=(0, 6))
                backup_frame.grid(row=2, column=0, sticky="nsew")
                recoverable_label.grid(
                    row=3,
                    column=0,
                    sticky="w",
                    pady=(10, 6)
                )
                file_frame.grid(row=4, column=0, sticky="nsew")
                button_bar.grid(row=5, column=0, sticky="ew", pady=(10, 0))

        def on_restore_resize(event):
            if event.widget == window:
                configure_restore_layout(event.width)

        window.bind("<Configure>", on_restore_resize, add="+")
        window.after_idle(configure_restore_layout)

        def backup_matches_search(entry):
            search_text = search_var.get().strip().lower()

            if not search_text:
                return True

            for change in self.get_recoverable_changes(entry):
                if change_matches_file_search(change, search_text):
                    return True

            return False

        def change_matches_file_search(change, search_text=None):
            search_text = (
                search_var.get().strip().lower()
                if search_text is None
                else search_text
            )

            if not search_text:
                return True

            searchable_values = (
                change.get("name", ""),
                change.get("archive_name", ""),
                change.get("source_path", "")
            )

            return any(
                search_text in str(value).lower()
                for value in searchable_values
            )

        def refresh_backups():
            for item in backup_tree.get_children():
                backup_tree.delete(item)

            for list_index, (_, entry) in enumerate(indexed_history):
                if not backup_matches_search(entry):
                    continue

                changed_count = self.count_changes_by_action(entry, "alterado")
                deleted_count = self.count_changes_by_action(entry, "excluido")
                backup_tree.insert(
                    "",
                    tk.END,
                    iid=str(list_index),
                    values=(
                        entry.get("timestamp", "-"),
                        entry.get("user", "sistema"),
                        entry.get("backup_name", "") or entry.get("backup_file", "-"),
                        entry.get("trigger", "-"),
                        changed_count,
                        deleted_count
                    )
                )

            visible_items = backup_tree.get_children()

            if visible_items:
                backup_tree.selection_set(visible_items[0])
                refresh_recoverable_files()
            else:
                current_recoverable_changes.clear()
                recoverable_summary.set("Arquivos recuperaveis: 0")
                for item in file_tree.get_children():
                    file_tree.delete(item)
                file_tree.insert(
                    "",
                    tk.END,
                    values=(
                        "-",
                        "Nenhum backup encontrado para esta busca",
                        "",
                        "",
                        "-",
                        "-"
                    )
                )

        def get_selected_backup():
            selected = backup_tree.selection()

            if not selected:
                return None

            return indexed_history[int(selected[0])]

        def refresh_recoverable_files(event=None):
            nonlocal current_recoverable_changes

            for item in file_tree.get_children():
                file_tree.delete(item)

            selected_backup = get_selected_backup()

            if not selected_backup:
                current_recoverable_changes = []
                recoverable_summary.set("Arquivos recuperaveis")
                return

            _, entry = selected_backup
            current_recoverable_changes = self.get_recoverable_changes(entry)
            filtered_changes = [
                (index, change)
                for index, change in enumerate(current_recoverable_changes)
                if (
                    change_matches_restore_filters(change)
                    and change_matches_file_search(change)
                )
            ]

            if len(filtered_changes) == len(current_recoverable_changes):
                recoverable_summary.set(
                    f"Arquivos recuperaveis: {len(current_recoverable_changes)}"
                )
            else:
                recoverable_summary.set(
                    "Arquivos recuperaveis: "
                    f"{len(filtered_changes)} de {len(current_recoverable_changes)}"
                )

            if not current_recoverable_changes:
                file_tree.insert(
                    "",
                    tk.END,
                    values=(
                        "-",
                        "Nenhum arquivo alterado ou excluido neste backup",
                        "",
                        "",
                        "-",
                        "-"
                    )
                )
                return

            if not filtered_changes:
                file_tree.insert(
                    "",
                    tk.END,
                    values=(
                        "-",
                        "Nenhum arquivo para este filtro",
                        "",
                        "",
                        "-",
                        "-"
                    )
                )
                return

            for index, change in filtered_changes:
                action = change.get("action", "")
                file_tree.insert(
                    "",
                    tk.END,
                    iid=str(index),
                    values=(
                        action,
                        change.get("name", ""),
                        change.get("archive_name", ""),
                        change.get("source_path", ""),
                        self.format_size_bytes(change.get("size_bytes")),
                        change.get("modified_at", "")
                    ),
                    tags=self.get_change_tag(action)
                )

        def get_selected_changes():
            selected_changes = []

            for item in file_tree.selection():
                try:
                    index = int(item)
                except ValueError:
                    continue

                if 0 <= index < len(current_recoverable_changes):
                    selected_changes.append(current_recoverable_changes[index])

            return selected_changes

        def parse_restore_date(value):
            value = value.strip()

            if not value or value == "Todos":
                return None

            for date_format in ("%d/%m/%Y", "%d/%m/%Y %H:%M:%S"):
                try:
                    return datetime.strptime(value, date_format)
                except ValueError:
                    pass

            return None

        def get_restore_date_options():
            dated_options = {}

            for change in current_recoverable_changes:
                modified_date = parse_restore_date(change.get("modified_at", ""))

                if modified_date:
                    dated_options[modified_date.date()] = modified_date.strftime(
                        "%d/%m/%Y"
                    )

            return [
                dated_options[key]
                for key in sorted(dated_options.keys(), reverse=True)
            ]

        def change_matches_restore_filters(change):
            text_checks = {
                "name": change.get("name", ""),
                "archive_name": change.get("archive_name", ""),
                "source_path": change.get("source_path", ""),
            }

            for key, value in text_checks.items():
                filter_value = restore_filters[key].strip().lower()

                if filter_value and filter_value not in str(value).lower():
                    return False

            if (
                restore_filters["action"] != "Todos"
                and change.get("action", "") != restore_filters["action"]
            ):
                return False

            row_date = parse_restore_date(change.get("modified_at", ""))
            from_date = parse_restore_date(restore_filters["modified_from"])
            to_date = parse_restore_date(restore_filters["modified_to"])

            if from_date and (row_date is None or row_date < from_date):
                return False

            if to_date and (row_date is None or row_date.date() > to_date.date()):
                return False

            return True

        def open_restore_filter_window():
            filter_window = tk.Toplevel(self.root)
            filter_window.title("Filtrar arquivos recuperaveis")
            filter_window.geometry("560x390")
            filter_window.minsize(540, 370)
            filter_window.configure(bg=BG_COLOR)
            filter_window.transient(self.root)
            self.prepare_window(filter_window)
            filter_window.grab_set()

            tk.Label(
                filter_window,
                text="Filtrar Arquivos",
                bg=BG_COLOR,
                fg=TITLE_COLOR,
                font=TITLE_FONT
            ).pack(pady=(18, 12))

            form = tk.Frame(filter_window, bg=BG_COLOR)
            form.pack(fill="x", padx=28)
            form.columnconfigure(1, weight=1)
            form.columnconfigure(3, weight=1)

            date_options = ["Todos"] + get_restore_date_options()

            field_vars = {
                "name": tk.StringVar(value=restore_filters["name"]),
                "archive_name": tk.StringVar(value=restore_filters["archive_name"]),
                "source_path": tk.StringVar(value=restore_filters["source_path"]),
                "action": tk.StringVar(value=restore_filters["action"]),
                "modified_from": tk.StringVar(
                    value=restore_filters["modified_from"] or "Todos"
                ),
                "modified_to": tk.StringVar(
                    value=restore_filters["modified_to"] or "Todos"
                ),
            }

            def add_entry(label, key, row, column=0, columnspan=1):
                tk.Label(
                    form,
                    text=label,
                    bg=BG_COLOR,
                    fg=SUBTLE_TEXT,
                    font=("Arial", 10, "bold")
                ).grid(
                    row=row,
                    column=column,
                    sticky="w",
                    padx=(0 if column == 0 else 14, 0),
                    pady=(0, 4)
                )

                entry = tk.Entry(
                    form,
                    textvariable=field_vars[key],
                    font=("Arial", 10),
                    bg=LIGHT_BUTTON,
                    fg=TEXT_COLOR,
                    relief="flat"
                )
                entry.grid(
                    row=row,
                    column=column + 1,
                    columnspan=columnspan,
                    sticky="ew",
                    padx=(10, 0),
                    pady=(0, 8)
                )
                return entry

            def add_combo(label, key, row, values, column=0, columnspan=1):
                tk.Label(
                    form,
                    text=label,
                    bg=BG_COLOR,
                    fg=SUBTLE_TEXT,
                    font=("Arial", 10, "bold")
                ).grid(
                    row=row,
                    column=column,
                    sticky="w",
                    padx=(0 if column == 0 else 14, 0),
                    pady=(0, 4)
                )

                combo = ttk.Combobox(
                    form,
                    textvariable=field_vars[key],
                    values=values,
                    state="readonly"
                )
                combo.grid(
                    row=row,
                    column=column + 1,
                    columnspan=columnspan,
                    sticky="ew",
                    padx=(10, 0),
                    pady=(0, 8)
                )
                return combo

            add_entry("Nome", "name", 0, columnspan=3)
            add_entry("Caminho no backup", "archive_name", 1, columnspan=3)
            add_entry("Local original", "source_path", 2, columnspan=3)
            add_combo(
                "Tipo",
                "action",
                3,
                ["Todos", "alterado", "excluido"]
            )
            add_combo("Data inicial", "modified_from", 4, date_options)
            add_combo("Data final", "modified_to", 4, date_options, column=2)

            buttons = tk.Frame(filter_window, bg=BG_COLOR)
            buttons.pack(pady=(10, 0))

            def apply_filters():
                from_date = parse_restore_date(field_vars["modified_from"].get())
                to_date = parse_restore_date(field_vars["modified_to"].get())

                if from_date and to_date and from_date.date() > to_date.date():
                    messagebox.showwarning(
                        "Periodo invalido",
                        "A data inicial nao pode ser maior que a data final.",
                        parent=filter_window
                    )
                    return

                for key, variable in field_vars.items():
                    value = variable.get().strip()

                    if key in ("modified_from", "modified_to"):
                        restore_filters[key] = "" if value == "Todos" else value
                    else:
                        restore_filters[key] = value

                refresh_recoverable_files()
                filter_window.destroy()

            def clear_filters():
                for key in restore_filters:
                    restore_filters[key] = "Todos" if key == "action" else ""

                refresh_recoverable_files()
                filter_window.destroy()

            self.create_dialog_button(buttons, "Aplicar", apply_filters).grid(
                row=0, column=0, padx=5
            )
            self.create_dialog_button(buttons, "Limpar", clear_filters).grid(
                row=0, column=1, padx=5
            )

        def show_restore_results(results):
            if not results:
                messagebox.showwarning(
                    "Nada recuperado",
                    "Nenhum arquivo recuperavel foi selecionado.",
                    parent=window
                )
                return

            restored = [item for item in results if item["status"] == "restored"]
            renamed = [
                item for item in results
                if item["status"] == "restored_renamed"
            ]
            identical = [
                item for item in results
                if item["status"] == "identical_existing"
            ]
            skipped = [
                item for item in results
                if item["status"] == "skipped_existing"
            ]
            missing = [item for item in results if item["status"] == "not_found"]
            errors = [item for item in results if item["status"] == "error"]

            lines = [
                f"Recuperados: {len(restored)}",
                f"Recuperados com outro nome: {len(renamed)}",
                f"Ja existiam com mesmo conteudo: {len(identical)}",
                f"Ignorados por conflito: {len(skipped)}",
                f"Nao encontrados em backups anteriores: {len(missing)}",
                f"Com erro: {len(errors)}",
            ]
            problem_items = (missing + errors)[:5]

            if problem_items:
                lines.append("")
                lines.append("Detalhes:")

                for item in problem_items:
                    lines.append(
                        f"- {item.get('archive_name', '')}: "
                        f"{item.get('message', '')}"
                    )

            messagebox.showinfo(
                "Recuperacao finalizada",
                "\n".join(lines),
                parent=window
            )

        def ask_file_rename_overrides(inspections):
            conflicts = [
                item for item in inspections
                if item.get("status") == "different_existing"
            ]
            target_overrides = {}

            if not conflicts:
                return target_overrides

            choose_custom_names = True

            if len(conflicts) > 1:
                choose_custom_names = messagebox.askyesno(
                    "Arquivos diferentes",
                    (
                        f"{len(conflicts)} arquivo(s) ja existem no destino "
                        "com conteudo diferente.\n\n"
                        "Deseja escolher o nome de cada arquivo recuperado?\n"
                        "Se escolher Nao, sera usado '_recuperado'."
                    ),
                    parent=window
                )

            for inspection in conflicts:
                target_path = inspection.get("target_path", "")

                if not target_path:
                    continue

                default_path = build_recovered_file_path(target_path)
                new_path = default_path

                if len(conflicts) == 1:
                    choose_custom_names = messagebox.askyesno(
                        "Arquivo diferente",
                        (
                            "Ja existe um arquivo no destino com o mesmo nome, "
                            "mas o conteudo e diferente do backup.\n\n"
                            "Deseja escolher outro nome para o arquivo recuperado?\n"
                            f"Se escolher Nao, sera usado:\n{os.path.basename(default_path)}"
                        ),
                        parent=window
                    )

                if choose_custom_names:
                    new_name = simpledialog.askstring(
                        "Renomear arquivo",
                        "Novo nome do arquivo recuperado:",
                        initialvalue=os.path.basename(default_path),
                        parent=window
                    )

                    if new_name:
                        sanitized_name = self.sanitize_restore_name(new_name)

                        if sanitized_name:
                            new_path = os.path.join(
                                os.path.dirname(target_path),
                                sanitized_name
                            )

                target_overrides[inspection.get("archive_name", "")] = new_path

            return target_overrides

        def ask_folder_rename_overrides(changes, inspections, folder_path):
            conflicts = [
                item for item in inspections
                if item.get("status") == "different_existing"
            ]

            if not conflicts:
                return {}

            default_folder = build_recovered_folder_path(folder_path)
            restored_folder = default_folder

            choose_custom_name = messagebox.askyesno(
                "Pasta com conflitos",
                (
                    f"{len(conflicts)} arquivo(s) da pasta ja existem no destino "
                    "com conteudo diferente.\n\n"
                    "Deseja escolher outro nome para a pasta recuperada?\n"
                    f"Se escolher Nao, sera usada:\n{os.path.basename(default_folder)}"
                ),
                parent=window
            )

            if choose_custom_name:
                new_name = simpledialog.askstring(
                    "Renomear pasta",
                    "Novo nome da pasta recuperada:",
                    initialvalue=os.path.basename(default_folder),
                    parent=window
                )

                if new_name:
                    sanitized_name = self.sanitize_restore_name(new_name)

                    if sanitized_name:
                        restored_folder = os.path.join(
                            os.path.dirname(folder_path),
                            sanitized_name
                        )

            restored_folder = self.ensure_unique_folder_path(restored_folder)

            return self.build_folder_target_overrides(
                changes,
                folder_path,
                restored_folder
            )

        def restore_changes(changes, restore_mode="files", folder_path=None):
            selected_backup = get_selected_backup()

            if not selected_backup:
                return

            history_index, _ = selected_backup

            if not changes:
                messagebox.showwarning(
                    "Selecao vazia",
                    "Selecione ao menos um arquivo recuperavel.",
                    parent=window
                )
                return

            if not messagebox.askyesno(
                "Confirmar recuperacao",
                (
                    f"Iniciar a recuperacao de {len(changes)} arquivo(s)?"
                ),
                parent=window
            ):
                return

            window.config(cursor="watch")
            window.update_idletasks()

            try:
                inspections = inspect_restore_changes(
                    changes,
                    before_history_index=history_index,
                    backup_destination=self.get_backup_destination()
                )
            except Exception as error:
                window.config(cursor="")
                messagebox.showerror("Erro", str(error), parent=window)
                return
            finally:
                window.config(cursor="")

            if restore_mode == "folder" and folder_path:
                target_overrides = ask_folder_rename_overrides(
                    changes,
                    inspections,
                    folder_path
                )
            else:
                target_overrides = ask_file_rename_overrides(inspections)

            window.config(cursor="watch")
            window.update_idletasks()

            try:
                results = restore_recoverable_changes(
                    changes,
                    before_history_index=history_index,
                    backup_destination=self.get_backup_destination(),
                    conflict_strategy="rename",
                    target_overrides=target_overrides,
                    user_master_key=self.current_user.get("session_master_key")
                )
            except Exception as error:
                messagebox.showerror("Erro", str(error), parent=window)
                return
            finally:
                window.config(cursor="")

            show_restore_results(results)

        def restore_selected_files():
            restore_changes(get_selected_changes())

        def restore_selected_folder():
            selected_changes = get_selected_changes()

            if not selected_changes:
                messagebox.showwarning(
                    "Selecao vazia",
                    "Selecione um arquivo da pasta que deseja recuperar.",
                    parent=window
                )
                return

            folder_path = self.get_change_folder(selected_changes[0])

            if not folder_path:
                messagebox.showwarning(
                    "Pasta nao identificada",
                    "Nao foi possivel identificar a pasta do arquivo selecionado.",
                    parent=window
                )
                return

            folder_changes = [
                change
                for change in current_recoverable_changes
                if self.is_change_inside_folder(change, folder_path)
            ]

            restore_changes(
                folder_changes,
                restore_mode="folder",
                folder_path=folder_path
            )

        button_bar.columnconfigure(0, weight=1)
        restore_action_flow = FlowFrame(
            button_bar,
            bg=BG_COLOR,
            min_item_width=170,
            hgap=8,
            vgap=8,
            max_columns=4
        )
        restore_action_flow.grid(row=0, column=0, sticky="ew")

        restore_selected_button = self.create_dialog_button(
            restore_action_flow,
            "Recuperar selecionados",
            restore_selected_files
        )
        restore_action_flow.add(restore_selected_button)

        restore_folder_button = self.create_dialog_button(
            restore_action_flow,
            "Recuperar pasta do item",
            restore_selected_folder
        )
        restore_action_flow.add(restore_folder_button)

        filter_files_button = self.create_dialog_button(
            restore_action_flow,
            "Filtrar arquivos",
            lambda: open_restore_filter_window()
        )
        restore_action_flow.add(filter_files_button)

        restore_snapshot_button = self.create_dialog_button(
            restore_action_flow,
            "Restaurar snapshot",
            lambda: self.restore_incremental_snapshot_from_file(window)
        )
        restore_action_flow.add(restore_snapshot_button)

        backup_tree.bind("<<TreeviewSelect>>", refresh_recoverable_files)
        refresh_backups()

    def show_history_window(self):
        if not self.require_permission("view_history"):
            return

        history = self.get_visible_history()

        window, content = self.create_content_shell("Historico de Backups")

        history_top_bar = tk.Frame(content, bg=BG_COLOR)
        history_top_bar.columnconfigure(1, weight=1)

        history_filter_summary = tk.StringVar(value="Filtros: todos os backups")
        tk.Label(
            history_top_bar,
            textvariable=history_filter_summary,
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=("Arial", 10)
        ).grid(row=2, column=1, sticky="w", pady=(4, 0))

        history_filters = {
            "timestamp_from": "",
            "timestamp_to": "",
            "user": "",
            "backup_name": "",
            "backup_description": "",
            "trigger": "Todos",
        }

        file_name_var = tk.StringVar()

        tk.Label(
            history_top_bar,
            text="Buscar arquivo",
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=("Arial", 10, "bold")
        ).grid(row=0, column=0, sticky="w", padx=(0, 10))

        history_search_entry = tk.Entry(
            history_top_bar,
            textvariable=file_name_var,
            font=TABLE_FONT,
            bg=LIGHT_BUTTON,
            fg=TEXT_COLOR,
            relief="flat"
        )
        history_search_entry.grid(row=0, column=1, sticky="ew")

        history_suggestion_box = tk.Listbox(
            history_top_bar,
            height=4,
            font=SUGGESTION_FONT,
            bg="#F2F2F2",
            fg=TEXT_COLOR,
            selectbackground="#FFE0B2",
            selectforeground=TEXT_COLOR,
            relief="flat",
            bd=0,
            highlightthickness=2,
            highlightbackground=TITLE_COLOR,
            highlightcolor=TITLE_COLOR,
            activestyle="none"
        )

        self.create_dialog_button(
            history_top_bar,
            "Buscar",
            lambda: apply_history_search()
        ).grid(row=0, column=2, padx=(10, 0))

        def clear_history_search():
            file_name_var.set("")
            hide_history_suggestions()
            refresh_backup_table()

        self.create_dialog_button(
            history_top_bar,
            "Limpar",
            clear_history_search
        ).grid(row=0, column=3, padx=(8, 0))

        self.create_dialog_button(
            history_top_bar,
            "Filtrar",
            lambda: open_history_filter_window()
        ).grid(row=0, column=4, padx=(8, 0))

        filter_frame = tk.Frame(content, bg=BG_COLOR)

        tk.Label(
            filter_frame,
            text="Arquivos do backup selecionado",
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=("Arial", 10, "bold")
        ).pack(side="left")

        change_filter_controls = tk.Frame(filter_frame, bg=BG_COLOR)
        change_filter_controls.pack(side="right")

        action_var = tk.StringVar(value="Todos")
        action_combo = ttk.Combobox(
            change_filter_controls,
            textvariable=action_var,
            values=["Todos", "adicionado", "alterado", "excluido", "mantido"],
            state="readonly",
            width=14
        )
        action_combo.grid(row=0, column=1, sticky="ew")

        tk.Label(
            change_filter_controls,
            text="Tipo:",
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=("Arial", 10)
        ).grid(row=0, column=0, sticky="e", padx=(0, 6))

        backup_columns = (
            "timestamp",
            "user",
            "description",
            "trigger",
            "total",
            "changes"
        )
        backup_frame = tk.Frame(content, bg=BG_COLOR)
        backup_tree = self.create_scrollable_tree(
            backup_frame,
            backup_columns,
            height=15,
            show="tree headings"
        )
        backup_tree.heading("#0", text="Nome")
        backup_tree.column("#0", width=170, minwidth=130, anchor="w", stretch=False)

        backup_headings = {
            "timestamp": "Data",
            "user": "Usuario",
            "description": "Descricao",
            "trigger": "Tipo",
            "total": "Arquivos",
            "changes": "Mudancas"
        }

        self.configure_tree_columns(
            backup_tree,
            backup_headings,
            {
                "timestamp": {"width": 135, "minwidth": 120, "weight": 2},
                "user": {"width": 80, "minwidth": 65, "weight": 1},
                "description": {
                    "width": 180,
                    "minwidth": 130,
                    "weight": 3,
                    "anchor": "w",
                },
                "trigger": {"width": 80, "minwidth": 70, "weight": 1},
                "total": {"width": 90, "minwidth": 75, "weight": 1},
                "changes": {"width": 95, "minwidth": 75, "weight": 1},
            }
        )

        change_columns = ("action", "name", "priority", "archive_name", "size", "modified_at")
        change_frame = tk.Frame(content, bg=BG_COLOR)
        change_tree = self.create_scrollable_tree(
            change_frame,
            change_columns,
            height=15
        )

        change_headings = {
            "action": "Acao",
            "name": "Arquivo",
            "priority": "Prioridade",
            "archive_name": "Caminho no backup",
            "size": "Tamanho",
            "modified_at": "Modificado em"
        }

        self.configure_tree_columns(
            change_tree,
            change_headings,
            {
                "action": {"width": 95, "minwidth": 80, "weight": 1},
                "name": {
                    "width": 180,
                    "minwidth": 150,
                    "weight": 2,
                    "anchor": "w",
                },
                "priority": {"width": 105, "minwidth": 90, "weight": 1},
                "archive_name": {
                    "width": 300,
                    "minwidth": 220,
                    "weight": 4,
                    "anchor": "w",
                },
                "size": {"width": 100, "minwidth": 85, "weight": 1},
                "modified_at": {
                    "width": 155,
                    "minwidth": 130,
                    "weight": 2,
                },
            }
        )
        self.configure_change_tags(change_tree)

        history_layout_state = {"mode": None}

        def configure_history_layout(width=None):
            if width is None:
                width = window.winfo_width()

            mode = "wide" if width >= 1500 else "stacked"

            if history_layout_state["mode"] == mode:
                return

            history_layout_state["mode"] = mode

            for widget in (
                history_top_bar,
                filter_frame,
                backup_frame,
                change_frame,
            ):
                widget.grid_forget()

            for column in range(2):
                content.columnconfigure(column, weight=0)

            for row in range(4):
                content.rowconfigure(row, weight=0)

            if mode == "wide":
                content.columnconfigure(0, weight=6)
                content.columnconfigure(1, weight=7)
                content.rowconfigure(1, weight=1)

                history_top_bar.grid(
                    row=0,
                    column=0,
                    sticky="ew",
                    pady=(0, 6),
                    padx=(0, 14)
                )
                filter_frame.grid(row=0, column=1, sticky="ew", pady=(0, 6))
                backup_frame.grid(
                    row=1,
                    column=0,
                    sticky="nsew",
                    padx=(0, 14)
                )
                change_frame.grid(row=1, column=1, sticky="nsew")
            else:
                content.columnconfigure(0, weight=1)
                content.rowconfigure(1, weight=1)
                content.rowconfigure(3, weight=2)

                history_top_bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
                backup_frame.grid(row=1, column=0, sticky="nsew")
                filter_frame.grid(
                    row=2,
                    column=0,
                    sticky="ew",
                    pady=(10, 6)
                )
                change_frame.grid(row=3, column=0, sticky="nsew")

        def on_history_resize(event):
            if event.widget == window:
                configure_history_layout(event.width)

        window.bind("<Configure>", on_history_resize, add="+")
        window.after_idle(configure_history_layout)

        if not history:
            backup_tree.insert(
                "",
                tk.END,
                text="Nenhum backup visivel",
                values=("-", "-", "-", "-", "-", "-")
            )
            return

        def format_size(size_bytes):
            try:
                size = float(size_bytes)
            except (TypeError, ValueError):
                return "-"

            if size >= 1024 * 1024:
                return f"{size / (1024 * 1024):.2f} MB"

            if size >= 1024:
                return f"{size / 1024:.2f} KB"

            return f"{int(size)} B"

        def parse_history_date(value):
            value = value.strip()

            if not value or value == "Todos":
                return None

            for date_format in ("%d/%m/%Y", "%d/%m/%Y %H:%M:%S"):
                try:
                    return datetime.strptime(value, date_format)
                except ValueError:
                    pass

            return None

        def get_history_date_options():
            dated_options = {}

            for entry in history:
                entry_date = parse_history_date(entry.get("timestamp", ""))

                if entry_date:
                    dated_options[entry_date.date()] = entry_date.strftime("%d/%m/%Y")

            return [
                dated_options[key]
                for key in sorted(dated_options.keys(), reverse=True)
            ]

        def change_matches_history_search(change, search_text=None):
            search_text = (
                file_name_var.get().strip().lower()
                if search_text is None
                else search_text
            )

            if not search_text:
                return True

            searchable_values = (
                change.get("name", ""),
                change.get("archive_name", ""),
                change.get("source_path", "")
            )

            return any(
                search_text in str(value).lower()
                for value in searchable_values
            )

        def entry_matches_file_search(entry):
            search_text = file_name_var.get().strip().lower()

            if not search_text:
                return True

            return any(
                change_matches_history_search(change, search_text)
                for change in self.get_history_entry_files(entry)
            )

        def get_history_search_suggestions():
            search_text = file_name_var.get().strip().lower()

            if not search_text:
                return []

            suggestions = []
            seen = set()

            for entry in history:
                for change in self.get_history_entry_files(entry):
                    for value in (
                        change.get("name", ""),
                        change.get("archive_name", ""),
                    ):
                        suggestion = str(value).strip()

                        if not suggestion:
                            continue

                        suggestion_key = suggestion.lower()

                        if (
                            search_text in suggestion_key
                            and suggestion_key not in seen
                        ):
                            suggestions.append(suggestion)
                            seen.add(suggestion_key)

                        if len(suggestions) >= 8:
                            return suggestions

            return suggestions

        def hide_history_suggestions():
            history_suggestion_box.grid_forget()

        def update_history_suggestions(*_args):
            history_suggestion_box.delete(0, tk.END)
            suggestions = get_history_search_suggestions()

            if not suggestions:
                hide_history_suggestions()
                return

            for suggestion in suggestions:
                history_suggestion_box.insert(tk.END, f"  {suggestion}")

            history_suggestion_box.config(height=min(len(suggestions), 5))
            history_suggestion_box.grid(
                row=1,
                column=1,
                columnspan=4,
                sticky="ew",
                pady=(4, 0)
            )

        def apply_history_search(value=None):
            if value is not None:
                file_name_var.set(value)

            hide_history_suggestions()
            refresh_backup_table()

        def select_history_suggestion(_event=None):
            selection = history_suggestion_box.curselection()

            if selection:
                apply_history_search(history_suggestion_box.get(selection[0]).strip())

        def entry_matches_history_filters(entry):
            entry_date = parse_history_date(entry.get("timestamp", ""))
            from_date = parse_history_date(history_filters["timestamp_from"])
            to_date = parse_history_date(history_filters["timestamp_to"])

            if from_date and (entry_date is None or entry_date < from_date):
                return False

            if to_date and (entry_date is None or entry_date.date() > to_date.date()):
                return False

            text_checks = {
                "user": entry.get("user", "sistema"),
                "backup_name": entry.get("backup_name", ""),
                "backup_description": entry.get("backup_description", ""),
            }

            for key, value in text_checks.items():
                filter_value = history_filters[key].strip().lower()

                if filter_value and filter_value not in str(value).lower():
                    return False

            if (
                history_filters["trigger"] != "Todos"
                and entry.get("trigger", "") != history_filters["trigger"]
            ):
                return False

            return entry_matches_file_search(entry)

        indexed_history = {}

        def is_priority_history_entry(entry):
            return (
                entry.get("history_group_type") == "priority_snapshot"
                or entry.get("partial_backup")
                or entry.get("priority_policy")
            )

        def is_full_history_entry(entry):
            return not is_priority_history_entry(entry)

        def get_history_tree_name(entry):
            name = entry.get("backup_name", "") or entry.get("backup_file", "-")
            encrypted_suffix = " [criptografado]" if entry.get("encrypted") else ""

            if is_priority_history_entry(entry):
                scope = entry.get("priority_scope", "")

                if scope:
                    return f"Snapshot {scope}{encrypted_suffix}"

                return f"{name}{encrypted_suffix}"

            return f"{name}{encrypted_suffix}"

        def get_history_item_values(entry):
            return (
                entry.get("timestamp", "-"),
                entry.get("user", "sistema"),
                entry.get("backup_description", ""),
                entry.get("trigger", "-"),
                entry.get("total_files", 0),
                len(entry.get("file_changes", []))
            )

        def refresh_backup_table():
            nonlocal indexed_history

            for item in backup_tree.get_children():
                backup_tree.delete(item)

            indexed_history = {}
            visible_entries = [
                (index, entry)
                for index, entry in enumerate(history)
                if entry_matches_history_filters(entry)
            ]
            full_entries = [
                (index, entry)
                for index, entry in visible_entries
                if is_full_history_entry(entry)
            ]
            priority_entries = [
                (index, entry)
                for index, entry in visible_entries
                if is_priority_history_entry(entry)
            ]
            full_item_by_history_index = {}

            for index, entry in reversed(full_entries):
                item_id = f"entry:{index}"
                indexed_history[item_id] = entry
                full_item_by_history_index[index] = item_id
                backup_tree.insert(
                    "",
                    tk.END,
                    iid=item_id,
                    text=get_history_tree_name(entry),
                    values=get_history_item_values(entry),
                    open=True
                )

            for index, entry in reversed(priority_entries):
                next_full_indexes = [
                        full_index
                        for full_index in full_item_by_history_index
                    if full_index > index
                ]

                parent_id = None

                if next_full_indexes:
                    parent_id = full_item_by_history_index[min(next_full_indexes)]

                item_id = f"entry:{index}"
                indexed_history[item_id] = entry

                if parent_id:
                    backup_tree.insert(
                        parent_id,
                        tk.END,
                        iid=item_id,
                        text=get_history_tree_name(entry),
                        values=get_history_item_values(entry)
                    )
                else:
                    backup_tree.insert(
                        "",
                        0,
                        iid=item_id,
                        text=get_history_tree_name(entry),
                        values=get_history_item_values(entry)
                    )

            active_filters = []

            for key, label in (
                ("backup_name", "Nome"),
                ("backup_description", "Descricao"),
            ):
                if history_filters[key].strip():
                    active_filters.append(label)

            if history_filters["trigger"] != "Todos":
                active_filters.append("Tipo")

            if history_filters["timestamp_from"] or history_filters["timestamp_to"]:
                active_filters.append("Periodo")

            if history_filters["user"].strip():
                active_filters.append("Usuario")

            if active_filters:
                history_filter_summary.set(f"Filtros: {', '.join(active_filters)}")
            else:
                history_filter_summary.set("Filtros: todos os backups")

            for item in change_tree.get_children():
                change_tree.delete(item)

            selectable_items = list(indexed_history.keys())

            if selectable_items:
                backup_tree.selection_set(selectable_items[0])
                refresh_changes()
            else:
                change_tree.insert(
                    "",
                    tk.END,
                    values=("-", "Nenhum backup para este filtro", "-", "", "-", "-")
                )

        def refresh_changes(event=None):
            for item in change_tree.get_children():
                change_tree.delete(item)

            selected = backup_tree.selection()

            if not selected:
                return

            entry = indexed_history.get(selected[0])

            if not entry:
                change_tree.insert(
                    "",
                    tk.END,
                    values=("-", "Selecione um backup ou snapshot", "-", "", "-", "-")
                )
                return

            selected_action = action_var.get()
            file_name_filter = file_name_var.get().strip().lower()
            changes = self.get_history_entry_files(entry)

            if not changes:
                change_tree.insert(
                    "",
                    tk.END,
                    values=(
                        "-",
                        "Nenhum arquivo registrado",
                        "-",
                        "Backups antigos podem nao ter snapshot ou mudancas detalhadas",
                        "-",
                        "-"
                    )
                )
                return

            for change in changes:
                action = change.get("action", "-")

                if selected_action != "Todos" and action != selected_action:
                    continue

                file_name = change.get("name", "")
                archive_name = change.get("archive_name", "")

                if file_name_filter and not change_matches_history_search(change):
                    continue

                change_tree.insert(
                    "",
                    tk.END,
                    values=(
                        action,
                        file_name,
                        change.get("priority", "-"),
                        archive_name,
                        format_size(change.get("size_bytes")),
                        change.get("modified_at", "")
                    ),
                    tags=self.get_change_tag(action)
                )

            if not change_tree.get_children():
                change_tree.insert(
                    "",
                    tk.END,
                    values=("-", "Nenhum arquivo para este filtro", "-", "", "-", "-")
                )

        backup_tree.bind("<<TreeviewSelect>>", refresh_changes)
        action_combo.bind("<<ComboboxSelected>>", refresh_changes)
        file_name_var.trace_add(
            "write",
            lambda *args: (update_history_suggestions(), refresh_changes())
        )
        history_search_entry.bind("<Return>", lambda _event: apply_history_search())
        history_search_entry.bind("<Escape>", lambda _event: hide_history_suggestions())
        history_suggestion_box.bind("<ButtonRelease-1>", select_history_suggestion)
        history_suggestion_box.bind("<Double-Button-1>", select_history_suggestion)
        history_suggestion_box.bind("<Return>", select_history_suggestion)

        def open_history_filter_window():
            filter_window = tk.Toplevel(self.root)
            filter_window.title("Filtrar historico")
            filter_window.geometry("520x380")
            filter_window.minsize(500, 360)
            filter_window.configure(bg=BG_COLOR)
            filter_window.transient(self.root)
            self.prepare_window(filter_window)
            filter_window.grab_set()

            tk.Label(
                filter_window,
                text="Filtrar Historico",
                bg=BG_COLOR,
                fg=TITLE_COLOR,
                font=TITLE_FONT
            ).pack(pady=(18, 12))

            form = tk.Frame(filter_window, bg=BG_COLOR)
            form.pack(fill="x", padx=28)
            form.columnconfigure(1, weight=1)
            form.columnconfigure(3, weight=1)

            date_options = ["Todos"] + get_history_date_options()

            field_vars = {
                "timestamp_from": tk.StringVar(
                    value=history_filters["timestamp_from"] or "Todos"
                ),
                "timestamp_to": tk.StringVar(
                    value=history_filters["timestamp_to"] or "Todos"
                ),
                "user": tk.StringVar(value=history_filters["user"]),
                "backup_name": tk.StringVar(value=history_filters["backup_name"]),
                "backup_description": tk.StringVar(value=history_filters["backup_description"]),
                "trigger": tk.StringVar(value=history_filters["trigger"]),
            }

            def add_entry(label, key, row, column=0, columnspan=1):
                tk.Label(
                    form,
                    text=label,
                    bg=BG_COLOR,
                    fg=SUBTLE_TEXT,
                    font=("Arial", 10, "bold")
                ).grid(
                    row=row,
                    column=column,
                    sticky="w",
                    padx=(0 if column == 0 else 14, 0),
                    pady=(0, 4)
                )

                entry = tk.Entry(
                    form,
                    textvariable=field_vars[key],
                    font=("Arial", 10),
                    bg=LIGHT_BUTTON,
                    fg=TEXT_COLOR,
                    relief="flat"
                )
                entry.grid(
                    row=row,
                    column=column + 1,
                    columnspan=columnspan,
                    sticky="ew",
                    padx=(10, 0),
                    pady=(0, 8)
                )
                return entry

            def add_combo(label, key, row, values, column=0):
                tk.Label(
                    form,
                    text=label,
                    bg=BG_COLOR,
                    fg=SUBTLE_TEXT,
                    font=("Arial", 10, "bold")
                ).grid(
                    row=row,
                    column=column,
                    sticky="w",
                    padx=(0 if column == 0 else 14, 0),
                    pady=(0, 4)
                )

                combo = ttk.Combobox(
                    form,
                    textvariable=field_vars[key],
                    values=values,
                    state="readonly"
                )
                combo.grid(
                    row=row,
                    column=column + 1,
                    sticky="ew",
                    padx=(10, 0),
                    pady=(0, 8)
                )
                return combo

            add_entry("Nome", "backup_name", 0, columnspan=3)
            add_entry("Descricao", "backup_description", 1, columnspan=3)

            tk.Label(
                form,
                text="Tipo",
                bg=BG_COLOR,
                fg=SUBTLE_TEXT,
                font=("Arial", 10, "bold")
            ).grid(row=2, column=0, sticky="w", pady=(0, 4))

            trigger_combo = ttk.Combobox(
                form,
                textvariable=field_vars["trigger"],
                values=["Todos", "manual", "agendado", "sistema"],
                state="readonly"
            )
            trigger_combo.grid(
                row=2,
                column=1,
                columnspan=3,
                sticky="ew",
                padx=(10, 0),
                pady=(0, 8)
            )

            add_combo("Data inicial", "timestamp_from", 3, date_options)
            add_combo("Data final", "timestamp_to", 3, date_options, column=2)
            add_entry("Usuario", "user", 4, columnspan=3)

            buttons = tk.Frame(filter_window, bg=BG_COLOR)
            buttons.pack(pady=(10, 0))

            def apply_filters():
                selected_from = field_vars["timestamp_from"].get().strip()
                selected_to = field_vars["timestamp_to"].get().strip()
                from_date = parse_history_date(selected_from)
                to_date = parse_history_date(selected_to)

                if from_date and to_date and from_date.date() > to_date.date():
                    messagebox.showwarning(
                        "Periodo invalido",
                        "A data inicial nao pode ser maior que a data final.",
                        parent=filter_window
                    )
                    return

                for key, variable in field_vars.items():
                    value = variable.get().strip()

                    if key in ("timestamp_from", "timestamp_to"):
                        history_filters[key] = "" if value == "Todos" else value
                    else:
                        history_filters[key] = value

                refresh_backup_table()
                filter_window.destroy()

            def clear_filters():
                for key in history_filters:
                    history_filters[key] = "Todos" if key == "trigger" else ""

                refresh_backup_table()
                filter_window.destroy()

            self.create_dialog_button(buttons, "Aplicar", apply_filters).grid(
                row=0, column=0, padx=5
            )
            self.create_dialog_button(buttons, "Limpar", clear_filters).grid(
                row=0, column=1, padx=5
            )

        refresh_backup_table()

    def download_latest_backup(self):
        if not self.require_permission("download_backup"):
            return

        latest_entry = self.get_latest_visible_history_entry()

        if not latest_entry:
            messagebox.showinfo("Sem backup", "Nenhum backup disponivel para exportacao.")
            return

        self.export_history_entry(latest_entry, title_suffix="do ultimo backup")

    def get_latest_backup(self):
        return get_latest_backup_path(self.get_current_user_backup_destination())

    def get_latest_visible_full_backup_entry(self):
        history = self.get_visible_history()

        for entry in reversed(history):
            if entry.get("partial_backup"):
                continue
            return entry

        return None

    def choose_backup_export_destination(self, backup_path, export_mode_label):
        extension = os.path.splitext(backup_path)[1].lower()
        filetypes = [("Arquivo ZIP", "*.zip"), ("Todos os arquivos", "*.*")]
        defaultextension = ".zip"
        initial_name = os.path.splitext(os.path.basename(backup_path))[0] + ".zip"

        if extension == ".zip":
            initial_name = os.path.basename(backup_path)

        return filedialog.asksaveasfilename(
            title=f"Salvar copia {export_mode_label}",
            defaultextension=defaultextension,
            initialfile=initial_name,
            filetypes=filetypes
        )

    def export_history_entry(self, entry, title_suffix="do backup selecionado"):
        backup_path = entry.get("backup_path") or entry.get("snapshot_path", "")

        if not backup_path or not os.path.exists(backup_path):
            messagebox.showwarning(
                "Backup indisponivel",
                "O arquivo deste backup nao foi encontrado no disco.",
                parent=self.root
            )
            return False

        destination = self.choose_backup_export_destination(backup_path, title_suffix)

        if not destination:
            return False

        self.open_download_progress_window()

        def run_export():
            try:
                extension = os.path.splitext(backup_path)[1].lower()

                if extension == ".json":
                    export_result = export_snapshot_to_zip(
                        backup_path,
                        destination,
                        progress_callback=lambda processed, total, current_entry: (
                            self.enqueue_download_progress(
                                100 if total <= 0 else int((processed / total) * 100),
                                (
                                    "Gerando ZIP do backup..."
                                    if not current_entry
                                    else f"Compactando: {current_entry}"
                                )
                            )
                        ),
                        user_master_key=self.current_user.get("session_master_key")
                    )
                    warning_count = len(export_result.get("warnings", []))
                    warning_text = ""

                    if warning_count:
                        warning_text = (
                            "\n\nArquivos ignorados durante a exportacao: "
                            f"{warning_count}"
                        )

                    success_message = (
                        "ZIP gerado a partir do snapshot selecionado.\n\n"
                        f"Arquivo salvo em:\n{destination}\n\n"
                        f"Arquivos exportados: {export_result.get('files_exported', 0)}"
                        f"{warning_text}"
                    )
                else:
                    self.copy_file_with_progress(backup_path, destination)
                    success_message = f"Backup copiado para:\n{destination}"

                self.download_queue.put(("success", success_message))
            except Exception as error:
                self.download_queue.put(("error", str(error)))

        worker = threading.Thread(target=run_export, daemon=True)
        worker.start()
        self.root.after(120, self.process_download_events)

        return True

    def show_download_options_panel(self):
        if not self.require_permission("download_backup"):
            return

        history = self.get_visible_history()
        latest_entry = self.get_latest_visible_history_entry()
        latest_full_entry = self.get_latest_visible_full_backup_entry()

        _panel, shell_content = self.create_content_shell(
            "Baixar Backups",
            subtitle="Exporte o ultimo backup, um backup completo de recuperacao ou um backup especifico."
        )
        scroll_content = ScrollableFrame(shell_content, bg=HOME_PANEL_COLOR)
        scroll_content.grid(row=0, column=0, sticky="nsew")
        content = scroll_content.body
        content.columnconfigure(0, weight=1)
        content.rowconfigure(1, weight=1)

        options_box = FlowFrame(
            content,
            bg=PANEL_COLOR,
            min_item_width=250,
            hgap=8,
            vgap=8,
            max_columns=3,
            highlightbackground=BORDER_COLOR,
            highlightthickness=1,
            padx=18,
            pady=18
        )
        options_box.grid(row=0, column=0, sticky="ew", pady=(0, 14))

        def add_download_option(column, title, description, button_text, command, enabled=True):
            card = tk.Frame(
                options_box,
                bg=HOME_PANEL_COLOR,
                highlightbackground=BORDER_COLOR,
                highlightthickness=1,
                padx=16,
                pady=16
            )
            options_box.add(card)

            tk.Label(
                card,
                text=title,
                bg=HOME_PANEL_COLOR,
                fg=TITLE_COLOR,
                font=("Segoe UI", 12, "bold"),
                justify="left",
                anchor="w"
            ).pack(fill="x")

            description_label = tk.Label(
                card,
                text=description,
                bg=HOME_PANEL_COLOR,
                fg=SUBTLE_TEXT,
                font=("Segoe UI", 10),
                justify="left",
                anchor="w",
                wraplength=250
            )
            description_label.pack(fill="x", pady=(8, 14))

            button = self.create_dialog_button(card, button_text, command)
            if not enabled:
                button.config(state=tk.DISABLED, cursor="arrow")
            button.pack(anchor="w")

            def update_description_wrap(event=None):
                width = event.width if event is not None else card.winfo_width()
                description_label.configure(wraplength=max(width - 34, 160))

            card.bind("<Configure>", update_description_wrap, add="+")
            card.after_idle(update_description_wrap)
            return card

        download_cards = []

        download_cards.append(add_download_option(
            0,
            "Ultimo backup",
            "Exporta exatamente o backup mais recente visivel no historico, mesmo se ele for parcial por prioridade.",
            "Baixar ultimo",
            lambda: self.export_history_entry(latest_entry, "do ultimo backup"),
            enabled=latest_entry is not None
        ))
        download_cards.append(add_download_option(
            1,
            "Backup completo",
            "Exporta o backup completo mais recente para recuperacao de todos os arquivos, ignorando snapshots parciais.",
            "Baixar completo",
            lambda: self.export_history_entry(latest_full_entry, "do backup completo"),
            enabled=latest_full_entry is not None
        ))
        download_cards.append(add_download_option(
            2,
            "Backup especifico",
            "Selecione qualquer backup da lista abaixo para exportar exatamente a execucao desejada.",
            "Baixar selecionado",
            lambda: export_selected_backup(),
            enabled=bool(history)
        ))

        table_box = tk.Frame(
            content,
            bg=PANEL_COLOR,
            highlightbackground=BORDER_COLOR,
            highlightthickness=1,
            padx=14,
            pady=14
        )
        table_box.grid(row=1, column=0, sticky="nsew")
        table_box.columnconfigure(0, weight=1)
        table_box.rowconfigure(1, weight=1)

        tk.Label(
            table_box,
            text="Escolher backup especifico",
            bg=PANEL_COLOR,
            fg=SUBTLE_TEXT,
            font=("Arial", 10, "bold")
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        columns = ("timestamp", "user", "backup_name", "trigger", "total", "kind")
        table_frame = tk.Frame(table_box, bg=PANEL_COLOR)
        table_frame.grid(row=1, column=0, sticky="nsew")
        history_tree = self.create_scrollable_tree(table_frame, columns, height=12)
        self.configure_tree_columns(
            history_tree,
            {
                "timestamp": "Data",
                "user": "Usuario",
                "backup_name": "Backup",
                "trigger": "Tipo",
                "total": "Arquivos",
                "kind": "Escopo",
            },
            {
                "timestamp": {"width": 150, "minwidth": 130, "weight": 2},
                "user": {"width": 90, "minwidth": 70, "weight": 1},
                "backup_name": {"width": 220, "minwidth": 180, "weight": 3, "anchor": "w"},
                "trigger": {"width": 100, "minwidth": 85, "weight": 1},
                "total": {"width": 90, "minwidth": 75, "weight": 1},
                "kind": {"width": 110, "minwidth": 95, "weight": 1},
            }
        )

        indexed_history = list(reversed(history))

        for index, entry in enumerate(indexed_history):
            history_tree.insert(
                "",
                tk.END,
                iid=str(index),
                values=(
                    entry.get("timestamp", "-"),
                    entry.get("user", "sistema"),
                    entry.get("backup_name", "") or entry.get("backup_file", "-"),
                    entry.get("trigger", "-"),
                    entry.get("total_files", 0),
                    "Parcial" if entry.get("partial_backup") else "Completo",
                )
            )

        if history_tree.get_children():
            history_tree.selection_set(history_tree.get_children()[0])

        def get_selected_history_entry():
            selected = history_tree.selection()

            if not selected:
                return None

            return indexed_history[int(selected[0])]

        def export_selected_backup():
            selected_entry = get_selected_history_entry()

            if not selected_entry:
                messagebox.showwarning(
                    "Selecao vazia",
                    "Selecione um backup da lista para exportar.",
                    parent=self.root
                )
                return

            self.export_history_entry(selected_entry, "do backup selecionado")

        button_bar = tk.Frame(table_box, bg=PANEL_COLOR)
        button_bar.grid(row=2, column=0, sticky="e", pady=(10, 0))
        button_bar.columnconfigure(0, weight=1)

        selected_download_button = self.create_dialog_button(
            button_bar,
            "Baixar backup selecionado",
            export_selected_backup
        )
        selected_download_button.grid(row=0, column=0, sticky="ew")

    def open_user_manager(self):
        if not self.require_permission("manage_users"):
            return

        _panel, content = self.create_content_shell(
            "Gerenciar Usuarios",
            subtitle="Cadastre, altere e remova usuarios sem sair da tela principal."
        )
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)

        content_box = tk.Frame(
            content,
            bg=PANEL_COLOR,
            highlightbackground=BORDER_COLOR,
            highlightthickness=1,
            padx=18,
            pady=18
        )
        content_box.grid(row=0, column=0, sticky="nsew")

        columns = ("username", "name", "role")
        tree_frame = tk.Frame(content_box, bg=PANEL_COLOR)
        tree_frame.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 16))
        tree = self.create_scrollable_tree(tree_frame, columns, height=10)
        content_box.columnconfigure(0, weight=1)
        content_box.columnconfigure(1, weight=0)
        content_box.rowconfigure(0, weight=1)

        headings = {
            "username": "Usuario",
            "name": "Nome",
            "role": "Perfil"
        }

        self.configure_tree_columns(
            tree,
            headings,
            {
                "username": {
                    "width": 160,
                    "minwidth": 120,
                    "weight": 2,
                    "anchor": "w",
                },
                "name": {
                    "width": 220,
                    "minwidth": 160,
                    "weight": 3,
                    "anchor": "w",
                },
                "role": {"width": 150, "minwidth": 130, "weight": 1},
            }
        )

        form = tk.Frame(content_box, bg=PANEL_COLOR)
        form.grid(row=0, column=1, sticky="n")

        username_var = tk.StringVar()
        name_var = tk.StringVar()
        role_var = tk.StringVar(value="viewer")
        password_var = tk.StringVar()

        def add_field(label, variable, row, show=None):
            tk.Label(
                form,
                text=label,
                bg=PANEL_COLOR,
                fg=SUBTLE_TEXT,
                font=("Arial", 10, "bold")
            ).grid(row=row, column=0, sticky="w", pady=(0, 4))

            entry = tk.Entry(
                form,
                textvariable=variable,
                show=show,
                font=("Arial", 10),
                width=24
            )
            entry.grid(row=row + 1, column=0, sticky="ew", pady=(0, 10))
            return entry

        add_field("Usuario", username_var, 0)
        add_field("Nome", name_var, 2)

        tk.Label(
            form,
            text="Perfil",
            bg=PANEL_COLOR,
            fg=SUBTLE_TEXT,
            font=("Arial", 10, "bold")
        ).grid(row=4, column=0, sticky="w", pady=(0, 4))

        role_combo = ttk.Combobox(
            form,
            textvariable=role_var,
            values=get_role_options(),
            state="readonly",
            width=21
        )
        role_combo.grid(row=5, column=0, sticky="ew", pady=(0, 10))

        add_field("Senha", password_var, 6, show="*")

        buttons = tk.Frame(content_box, bg=PANEL_COLOR)
        buttons.grid(row=1, column=1, sticky="s")

        def refresh_users():
            for item in tree.get_children():
                tree.delete(item)

            for user in list_public_users():
                tree.insert(
                    "",
                    tk.END,
                    iid=user["username"],
                    values=(
                        user.get("username", ""),
                        user.get("name", ""),
                        get_role_label(user.get("role"))
                    )
                )

        def clear_form():
            username_var.set("")
            name_var.set("")
            role_var.set("viewer")
            password_var.set("")

            for selected_item in tree.selection():
                tree.selection_remove(selected_item)

        def fill_form(event=None):
            selected = tree.selection()

            if not selected:
                return

            username = selected[0]
            user = next(
                (
                    current_user
                    for current_user in list_public_users()
                    if current_user.get("username") == username
                ),
                None
            )

            if not user:
                return

            username_var.set(user.get("username", ""))
            name_var.set(user.get("name", ""))
            role_var.set(user.get("role", "viewer"))
            password_var.set("")

        def save_user():
            username = username_var.get()
            username_key = username.strip().lower()
            name_key = " ".join(name_var.get().strip().lower().split())
            selected = tree.selection()
            selected_username = selected[0] if selected else None
            users = list_public_users()
            existing_usernames = {
                user["username"]
                for user in users
            }

            if (
                (selected_username or username_key) == self.current_user.get("username")
                and role_var.get() != self.current_user.get("role")
            ):
                messagebox.showwarning(
                    "Operacao bloqueada",
                    "Voce nao pode alterar o perfil do usuario em uso.",
                    parent=self.root
                )
                return

            try:
                if selected_username:
                    update_user(
                        selected_username,
                        role=role_var.get(),
                        name=name_var.get(),
                        password=password_var.get() or None
                    )
                else:
                    if username_key in existing_usernames:
                        raise ValueError("Ja existe esse usuario cadastrado.")

                    if name_key and any(
                        " ".join(user.get("name", "").strip().lower().split()) == name_key
                        for user in users
                    ):
                        raise ValueError("Ja existe um usuario com esse nome.")

                    created_user = create_user(
                        username,
                        password_var.get(),
                        role_var.get(),
                        name=name_var.get()
                    )

                    if created_user.get("recovery_key"):
                        messagebox.showinfo(
                            "Chave de recuperacao",
                            (
                                "Guarde esta chave de recuperacao. "
                                "Ela nao sera exibida novamente.\n\n"
                                f"{created_user['recovery_key']}"
                            ),
                            parent=self.root
                        )
            except ValueError as error:
                messagebox.showwarning("Dados invalidos", str(error), parent=self.root)
                return

            refresh_users()
            clear_form()

        def remove_user():
            selected = tree.selection()

            if not selected:
                return

            username = selected[0]

            if username == self.current_user.get("username"):
                messagebox.showwarning(
                    "Operacao bloqueada",
                    "Voce nao pode remover o usuario em uso.",
                    parent=self.root
                )
                return

            confirmed = messagebox.askyesno(
                "Remover usuario",
                f"Remover o usuario '{username}'?",
                parent=self.root
            )

            if not confirmed:
                return

            try:
                delete_user(username)
            except ValueError as error:
                messagebox.showwarning("Operacao bloqueada", str(error), parent=self.root)
                return

            refresh_users()
            clear_form()

        tree.bind("<<TreeviewSelect>>", fill_form)

        self.create_dialog_button(buttons, "Salvar", save_user).grid(
            row=0, column=0, padx=4, pady=4
        )
        self.create_dialog_button(buttons, "Limpar", clear_form).grid(
            row=0, column=1, padx=4, pady=4
        )
        self.create_dialog_button(buttons, "Remover", remove_user).grid(
            row=1, column=0, columnspan=2, padx=4, pady=4, sticky="ew"
        )

        refresh_users()


def root_exists(root):
    if root is None:
        return False

    try:
        return bool(root.winfo_exists())
    except tk.TclError:
        return False


def clear_root_widgets(root):
    for widget in root.winfo_children():
        try:
            widget.destroy()
        except tk.TclError:
            pass


def start_gui(current_user=None):
    from interface.login import login_user

    global _background_root
    global _background_gui

    if (
        current_user is None
        and _background_gui is not None
        and root_exists(_background_root)
    ):
        _background_gui.show_window()
        _background_root.mainloop()

        if not _background_gui.logout_requested:
            return

        current_user = None
        clear_root_widgets(_background_root)
        _background_gui = None

    if not root_exists(_background_root):
        _background_root = tk.Tk()

    root = _background_root

    while True:
        if current_user is None:
            current_user = login_user(root=root)

        if current_user is None:
            try:
                root.withdraw()
            except tk.TclError:
                pass
            return

        clear_root_widgets(root)
        gui = BackupGUI(root, current_user)
        _background_gui = gui
        gui.show_window()
        root.mainloop()

        logout_requested = gui.logout_requested
        gui.is_closing = True

        if not logout_requested:
            return

        clear_root_widgets(root)
        _background_gui = None
        current_user = None
