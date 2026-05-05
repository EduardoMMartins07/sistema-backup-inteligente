import csv
import json
import os
import queue
import re
import shutil
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
from backup.backup_manager import inspect_restore_changes
from backup.backup_manager import restore_recoverable_changes
from backup.backup_manager import run_backup_job

CONFIG_PATH = "config/config.json"
BACKUP_DIR = "backups"
HISTORY_PATH = "config/backup_history.json"
SCHEDULE_PATH = "config/backup_schedule.json"
ICON_PATH = os.path.join("assets", "nuvem.png")

BG_COLOR = "#283241"
PANEL_COLOR = "#1F2733"
TITLE_COLOR = "#FF990F"
LIGHT_BUTTON = "#D9D9D9"
TEXT_COLOR = "#101010"
SUBTLE_TEXT = "#E7EAF0"
BORDER_COLOR = "#3A4657"
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


class BackupGUI:

    def __init__(self, root, current_user):
        self.root = root
        self.current_user = current_user
        self.root.title("Sistema de Backup Inteligente")
        self.root.geometry("820x520")
        self.root.minsize(760, 500)
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
        self.backup_button = None
        self.schedule_button = None
        self.files_button = None
        self.history_button = None
        self.download_button = None
        self.restore_button = None
        self.manage_button = None
        self.destination_button = None
        self.logout_requested = False
        self.pending_backup_name = ""
        self.pending_backup_description = ""
        self.cancel_backup_requested = threading.Event()

        self.configure_window_icon()
        self.configure_widget_styles()
        self.load_directories()
        self.build_layout()

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
            background=LIGHT_BUTTON,
            troughcolor=PANEL_COLOR,
            bordercolor=BORDER_COLOR,
            arrowcolor=TEXT_COLOR,
            relief="flat",
            width=14
        )
        style.configure(
            "Horizontal.TScrollbar",
            background=LIGHT_BUTTON,
            troughcolor=PANEL_COLOR,
            bordercolor=BORDER_COLOR,
            arrowcolor=TEXT_COLOR,
            relief="flat",
            width=14
        )
        style.map(
            "Vertical.TScrollbar",
            background=[("active", TITLE_COLOR)]
        )
        style.map(
            "Horizontal.TScrollbar",
            background=[("active", TITLE_COLOR)]
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

    def build_layout(self):
        self.outer_frame = tk.Frame(
            self.root,
            bg=BG_COLOR,
            highlightbackground="#202020",
            highlightthickness=7
        )
        self.outer_frame.pack(fill="both", expand=True)

        self.header_frame = tk.Frame(self.outer_frame, bg=BG_COLOR)
        self.header_frame.pack(fill="x", padx=34, pady=(20, 0))

        title = tk.Label(
            self.header_frame,
            text="MENU",
            bg=BG_COLOR,
            fg=TITLE_COLOR,
            font=MENU_TITLE_FONT
        )
        title.pack(side="left", anchor="nw")

        self.utility_frame = tk.Frame(self.header_frame, bg=BG_COLOR)
        self.utility_frame.pack(side="right", anchor="ne")

        tk.Label(
            self.utility_frame,
            text=self.build_user_label(),
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=BODY_FONT,
            justify="right"
        ).pack(fill="x", pady=(0, 8))

        self.menu_frame = tk.Frame(self.outer_frame, bg=BG_COLOR)
        self.menu_frame.place(relx=0.5, rely=0.55, anchor="center")

        self.backup_button = self.create_menu_button(
            "Realizar Backup",
            self.perform_backup,
            bg=TITLE_COLOR
        )
        self.schedule_button = self.create_menu_button(
            "Agendar Backup",
            self.open_schedule_window,
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
            "Baixar ultimo backup",
            self.download_latest_backup,
            bg=LIGHT_BUTTON
        )

        footer = tk.Label(
            self.outer_frame,
            text=self.build_footer_text(),
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=("Segoe UI", 9),
            justify="center",
            wraplength=720
        )
        footer.place(relx=0.5, rely=1.0, anchor="s", y=-18)
        self.footer_label = footer

        self.manage_button = tk.Button(
            self.utility_frame,
            text="Gerenciar diretorios",
            command=self.open_directory_manager,
            font=BUTTON_FONT,
            bg=PANEL_COLOR,
            fg="white",
            activebackground=PANEL_COLOR,
            activeforeground="white",
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground="#101722",
            highlightcolor="#101722",
            cursor="hand2",
            padx=10,
            pady=5
        )
        self.manage_button.pack(fill="x", pady=(0, 10))
        self.apply_button_feedback(self.manage_button)

        self.destination_button = tk.Button(
            self.utility_frame,
            text="Diretorio padrao de backup",
            command=self.choose_backup_destination,
            font=BUTTON_FONT,
            bg=PANEL_COLOR,
            fg="white",
            activebackground=PANEL_COLOR,
            activeforeground="white",
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground="#101722",
            highlightcolor="#101722",
            cursor="hand2",
            padx=10,
            pady=5
        )
        self.destination_button.pack(fill="x", pady=(0, 10))
        self.apply_button_feedback(self.destination_button)

        if can(self.current_user, "manage_users"):
            users_button = tk.Button(
                self.utility_frame,
                text="Gerenciar usuarios",
                command=self.open_user_manager,
                font=BUTTON_FONT,
                bg=PANEL_COLOR,
                fg="white",
                activebackground=PANEL_COLOR,
                activeforeground="white",
                relief="flat",
                bd=0,
                highlightthickness=1,
                highlightbackground="#101722",
                highlightcolor="#101722",
                cursor="hand2",
                padx=10,
                pady=5
            )
            users_button.pack(fill="x")
            self.apply_button_feedback(users_button)

        logout_button = tk.Button(
            self.utility_frame,
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
            pady=5
        )
        logout_button.pack(fill="x", pady=(10, 0))
        self.apply_button_feedback(logout_button)

        self.apply_permissions()

    def create_menu_button(self, text, command, bg):
        button = tk.Button(
            self.menu_frame,
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
            width=20,
            pady=5
        )
        button.pack(pady=7)
        self.apply_button_feedback(button)
        return button

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

    def logout(self):
        if self.backup_in_progress:
            messagebox.showwarning(
                "Backup em andamento",
                "Aguarde o backup terminar ou cancele a operacao antes de sair."
            )
            return

        self.logout_requested = True
        self.root.destroy()

    def build_footer_text(self):
        latest_backup = self.get_latest_history_entry()
        backup_destination = self.get_backup_destination()

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

    def load_directories(self):
        data = self.load_config()
        self.directories = data.get("directories", [])
        self.backup_destination = data.get("backup_destination", BACKUP_DIR)

    def save_directories(self):
        data = self.load_config()
        data["directories"] = self.directories
        data["backup_destination"] = self.backup_destination
        self.save_config(data)
        self.refresh_footer()

    def load_config(self):
        if not os.path.exists(CONFIG_PATH):
            return {}

        with open(CONFIG_PATH, "r", encoding="utf-8") as file:
            try:
                data = json.load(file)
            except json.JSONDecodeError:
                return {}

        if isinstance(data, dict):
            return data

        return {}

    def save_config(self, data):
        os.makedirs("config", exist_ok=True)

        with open(CONFIG_PATH, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=4, ensure_ascii=False)

    def get_backup_destination(self):
        return self.backup_destination or BACKUP_DIR

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

        window = tk.Toplevel(self.root)
        window.title("Gerenciar diretorios")
        window.geometry("700x420")
        window.minsize(560, 360)
        window.configure(bg=BG_COLOR)
        window.transient(self.root)
        self.prepare_window(window)

        tk.Label(
            window,
            text="Diretorios para backup",
            bg=BG_COLOR,
            fg=TITLE_COLOR,
            font=TITLE_FONT
        ).pack(pady=(20, 12))

        list_frame = tk.Frame(window, bg=BG_COLOR)
        list_frame.pack(padx=20, pady=10, fill="both", expand=True)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        listbox = tk.Listbox(
            list_frame,
            height=12,
            font=TABLE_FONT,
            bg=LIGHT_BUTTON,
            fg=TEXT_COLOR,
            selectbackground=TITLE_COLOR,
            selectforeground=TEXT_COLOR
        )
        listbox.grid(row=0, column=0, sticky="nsew")

        list_vertical_scrollbar = ttk.Scrollbar(
            list_frame,
            orient="vertical",
            command=listbox.yview
        )
        list_vertical_scrollbar.grid(row=0, column=1, sticky="ns")

        list_horizontal_scrollbar = ttk.Scrollbar(
            list_frame,
            orient="horizontal",
            command=listbox.xview
        )
        list_horizontal_scrollbar.grid(row=1, column=0, sticky="ew")

        listbox.configure(
            yscrollcommand=list_vertical_scrollbar.set,
            xscrollcommand=list_horizontal_scrollbar.set
        )

        for directory in self.directories:
            listbox.insert(tk.END, directory)

        buttons = tk.Frame(window, bg=BG_COLOR)
        buttons.pack(pady=(0, 20))

        def add_directory():
            folder = filedialog.askdirectory(parent=window)

            if folder and folder not in self.directories:
                self.directories.append(folder)
                listbox.insert(tk.END, folder)

        def remove_directory():
            selected = listbox.curselection()

            if not selected:
                return

            index = selected[0]
            listbox.delete(index)
            del self.directories[index]

        def save_and_close():
            self.save_directories()
            messagebox.showinfo(
                "Sucesso",
                "Diretorios salvos com sucesso!",
                parent=window
            )
            window.destroy()

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
        self.apply_button_feedback(button)
        return button

    def prepare_window(self, window):
        self.configure_child_icon(window)
        self.fade_in_window(window)

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
        height=15
    ):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        tree = ttk.Treeview(
            parent,
            columns=columns,
            show="headings",
            selectmode=selectmode,
            height=height
        )
        tree.grid(row=0, column=0, sticky="nsew")

        vertical_scrollbar = ttk.Scrollbar(
            parent,
            orient="vertical",
            command=tree.yview
        )
        vertical_scrollbar.grid(row=0, column=1, sticky="ns")

        horizontal_scrollbar = ttk.Scrollbar(
            parent,
            orient="horizontal",
            command=tree.xview
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

    def get_change_tag(self, action):
        normalized_action = str(action).strip().lower()

        if normalized_action in ("excluido", "excluído"):
            return ("change_deleted",)

        if normalized_action == "alterado":
            return ("change_modified",)

        if normalized_action == "adicionado":
            return ("change_added",)

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

        self.backup_in_progress = True
        self.cancel_backup_requested.clear()
        self.open_progress_window()
        self.set_backup_button_state(tk.DISABLED)

        worker = threading.Thread(target=self.run_backup_in_background, daemon=True)
        worker.start()
        self.root.after(120, self.process_backup_events)

    def run_backup_in_background(self):
        try:
            result = run_backup_job(
                directories=self.directories,
                backup_destination=self.get_backup_destination(),
                trigger="manual",
                username=self.current_user.get("username"),
                user_role=self.current_user.get("role"),
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

        if should_continue and self.backup_in_progress:
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
        self.set_backup_button_state(tk.NORMAL)
        self.close_progress_window()
        self.refresh_footer()

        warning_count = len(result.get("warnings", []))
        warning_text = ""

        if warning_count:
            warning_text = (
                f"\n\nArquivos ignorados por erro durante a copia: {warning_count}"
            )

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
        self.set_backup_button_state(tk.NORMAL)
        self.close_progress_window()
        messagebox.showerror("Erro", error_message)

    def finish_backup_cancelled(self, message):
        self.backup_in_progress = False
        self.cancel_backup_requested.clear()
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
        window.geometry("420x260")
        window.minsize(390, 260)
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

        tk.Label(
            form,
            text="Horario (HH:MM)",
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=("Arial", 11)
        ).grid(row=0, column=0, sticky="w", pady=6)

        time_var = tk.StringVar(value=self.load_schedule().get("time", "09:00"))
        time_entry = tk.Entry(form, textvariable=time_var, font=("Arial", 11))
        time_entry.grid(row=0, column=1, sticky="ew", padx=(10, 0), pady=6)

        tk.Label(
            form,
            text="Frequencia",
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=("Arial", 11)
        ).grid(row=1, column=0, sticky="w", pady=6)

        frequency_var = tk.StringVar(
            value=self.load_schedule().get("frequency", "Diariamente")
        )
        frequency_combo = ttk.Combobox(
            form,
            textvariable=frequency_var,
            values=["Diariamente", "Semanalmente", "Mensalmente"],
            state="readonly",
        )
        frequency_combo.grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=6)

        info = tk.Label(
            window,
            text="O backup sera executado automaticamente no horario escolhido.",
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=("Arial", 10),
            wraplength=340,
            justify="center"
        )
        info.pack(pady=(12, 14))

        def save_schedule():
            value = time_var.get().strip()

            if not self.is_valid_time(value):
                messagebox.showwarning(
                    "Horario invalido",
                    "Informe o horario no formato HH:MM.",
                    parent=window
                )
                return

            payload = {
                "time": value,
                "frequency": frequency_var.get(),
                "updated_at": datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            }

            os.makedirs("config", exist_ok=True)

            with open(SCHEDULE_PATH, "w", encoding="utf-8") as file:
                json.dump(payload, file, indent=4, ensure_ascii=False)

            self.refresh_footer()
            messagebox.showinfo(
                "Agendamento salvo",
                "Horario salvo com sucesso.",
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

        dataset_path = os.path.join("dataset", "files_dataset.csv")

        if not os.path.exists(dataset_path):
            messagebox.showinfo(
                "Sem arquivos",
                "Nenhum arquivo foi listado ainda. Execute um backup primeiro."
            )
            return

        window = tk.Toplevel(self.root)
        window.title("Arquivos analisados")
        window.geometry("1040x540")
        window.minsize(840, 420)
        window.configure(bg=BG_COLOR)
        window.transient(self.root)
        self.prepare_window(window)

        tk.Label(
            window,
            text="Arquivos analisados",
            bg=BG_COLOR,
            fg=TITLE_COLOR,
            font=TITLE_FONT
        ).pack(pady=(18, 10))

        content = tk.Frame(window, bg=BG_COLOR)
        content.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        content.columnconfigure(0, weight=1)
        content.rowconfigure(1, weight=1)

        columns = (
            "name",
            "extension",
            "added_to_backup_at",
            "size_kb",
            "days_since_modified",
            "important"
        )
        headings = {
            "name": "Nome",
            "extension": "Extensao",
            "added_to_backup_at": "Adicionado ao backup",
            "size_kb": "Tamanho (KB)",
            "days_since_modified": "Dias sem alterar",
            "important": "Importante"
        }

        top_bar = tk.Frame(content, bg=BG_COLOR)
        top_bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        filter_summary_var = tk.StringVar(value="Filtros: todos os arquivos")
        tk.Label(
            top_bar,
            textvariable=filter_summary_var,
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=("Arial", 10)
        ).pack(side="left")

        filter_state = {
            "name": "",
            "extension": "",
            "added_from": "",
            "added_to": "",
            "size_kb": "",
            "days_since_modified": "",
            "important": "Todos",
        }

        self.create_dialog_button(
            top_bar,
            "Filtrar",
            lambda: open_filter_window()
        ).pack(side="right")

        table_frame = tk.Frame(content, bg=BG_COLOR)
        table_frame.grid(row=1, column=0, sticky="nsew")

        tree = self.create_scrollable_tree(table_frame, columns, height=15)
        self.configure_tree_columns(
            tree,
            headings,
            {
                "name": {
                    "width": 300,
                    "minwidth": 220,
                    "weight": 4,
                    "anchor": "w",
                },
                "extension": {"width": 100, "minwidth": 80, "weight": 1},
                "added_to_backup_at": {
                    "width": 180,
                    "minwidth": 150,
                    "weight": 2,
                },
                "size_kb": {"width": 120, "minwidth": 95, "weight": 1},
                "days_since_modified": {
                    "width": 140,
                    "minwidth": 120,
                    "weight": 1,
                },
                "important": {"width": 110, "minwidth": 90, "weight": 1},
            }
        )

        rows = []

        with open(dataset_path, "r", encoding="utf-8", newline="") as file:
            reader = csv.DictReader(file)

            for row in reader:
                added_to_backup_at = (
                    row.get("added_to_backup_at")
                    or row.get("created_at")
                    or "-"
                )
                important = "Sim" if row.get("important") == "1" else "Nao"
                row_values = {
                    "name": row.get("name", ""),
                    "extension": row.get("extension", ""),
                    "added_to_backup_at": added_to_backup_at,
                    "size_kb": self.format_float(row.get("size_kb", "0")),
                    "days_since_modified": row.get("days_since_modified", ""),
                    "important": important
                }
                rows.append(row_values)

        def parse_date(value):
            value = value.strip()

            if not value or value == "Todos":
                return None

            for date_format in ("%d/%m/%Y", "%d/%m/%Y %H:%M:%S"):
                try:
                    return datetime.strptime(value, date_format)
                except ValueError:
                    pass

            return None

        def parse_row_date(value):
            if not value or value == "-":
                return None

            for date_format in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
                try:
                    return datetime.strptime(value, date_format)
                except ValueError:
                    pass

            return None

        def get_file_date_options():
            dated_options = {}

            for row_values in rows:
                row_date = parse_row_date(row_values["added_to_backup_at"])

                if row_date:
                    dated_options[row_date.date()] = row_date.strftime("%d/%m/%Y")

            return [
                dated_options[key]
                for key in sorted(dated_options.keys(), reverse=True)
            ]

        def matches_filters(row_values):
            text_filters = {
                "name": filter_state["name"],
                "extension": filter_state["extension"],
                "size_kb": filter_state["size_kb"],
                "days_since_modified": filter_state["days_since_modified"],
            }

            for key, filter_value in text_filters.items():
                filter_value = filter_value.strip().lower()

                if filter_value and filter_value not in str(row_values[key]).lower():
                    return False

            if (
                filter_state["important"] != "Todos"
                and row_values["important"] != filter_state["important"]
            ):
                return False

            row_date = parse_row_date(row_values["added_to_backup_at"])
            from_date = parse_date(filter_state["added_from"])
            to_date = parse_date(filter_state["added_to"])

            if from_date and (row_date is None or row_date < from_date):
                return False

            if to_date and (row_date is None or row_date.date() > to_date.date()):
                return False

            return True

        def refresh_table(*args):
            for item in tree.get_children():
                tree.delete(item)

            for row_values in rows:
                if not matches_filters(row_values):
                    continue

                tree.insert(
                    "",
                    tk.END,
                    values=(
                        row_values["name"],
                        row_values["extension"],
                        row_values["added_to_backup_at"],
                        row_values["size_kb"],
                        row_values["days_since_modified"],
                        row_values["important"]
                    )
                )

            active_filters = []

            for key in ("name", "extension", "size_kb", "days_since_modified"):
                if filter_state[key].strip():
                    active_filters.append(headings[key])

            if filter_state["important"] != "Todos":
                active_filters.append("Importante")

            if filter_state["added_from"] or filter_state["added_to"]:
                active_filters.append("Periodo")

            if active_filters:
                filter_summary_var.set(f"Filtros: {', '.join(active_filters)}")
            else:
                filter_summary_var.set("Filtros: todos os arquivos")

        def open_filter_window():
            filter_window = tk.Toplevel(window)
            filter_window.title("Filtrar arquivos")
            filter_window.geometry("540x390")
            filter_window.minsize(520, 370)
            filter_window.configure(bg=BG_COLOR)
            filter_window.transient(window)
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

            date_options = ["Todos"] + get_file_date_options()

            field_vars = {
                "name": tk.StringVar(value=filter_state["name"]),
                "extension": tk.StringVar(value=filter_state["extension"]),
                "added_from": tk.StringVar(
                    value=filter_state["added_from"] or "Todos"
                ),
                "added_to": tk.StringVar(
                    value=filter_state["added_to"] or "Todos"
                ),
                "size_kb": tk.StringVar(value=filter_state["size_kb"]),
                "days_since_modified": tk.StringVar(value=filter_state["days_since_modified"]),
                "important": tk.StringVar(value=filter_state["important"]),
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
            add_entry("Extensao", "extension", 1, columnspan=3)

            tk.Label(
                form,
                text="Importante",
                bg=BG_COLOR,
                fg=SUBTLE_TEXT,
                font=("Arial", 10, "bold")
            ).grid(row=2, column=0, sticky="w", pady=(0, 4))

            important_combo = ttk.Combobox(
                form,
                textvariable=field_vars["important"],
                values=["Todos", "Sim", "Nao"],
                state="readonly"
            )
            important_combo.grid(
                row=2,
                column=1,
                columnspan=3,
                sticky="ew",
                padx=(10, 0),
                pady=(0, 8)
            )

            add_combo("Data inicial", "added_from", 3, date_options)
            add_combo("Data final", "added_to", 3, date_options, column=2)
            add_entry("Tamanho (KB)", "size_kb", 4)
            add_entry(
                "Dias sem alterar",
                "days_since_modified",
                4,
                column=2
            )

            buttons = tk.Frame(filter_window, bg=BG_COLOR)
            buttons.pack(pady=(10, 0))

            def apply_filters():
                from_date = parse_date(field_vars["added_from"].get())
                to_date = parse_date(field_vars["added_to"].get())

                if from_date and to_date and from_date.date() > to_date.date():
                    messagebox.showwarning(
                        "Periodo invalido",
                        "A data inicial nao pode ser maior que a data final.",
                        parent=filter_window
                    )
                    return

                for key, variable in field_vars.items():
                    value = variable.get().strip()

                    if key in ("added_from", "added_to"):
                        filter_state[key] = "" if value == "Todos" else value
                    else:
                        filter_state[key] = value

                refresh_table()
                filter_window.destroy()

            def clear_filters():
                for key in filter_state:
                    filter_state[key] = "Todos" if key == "important" else ""

                refresh_table()
                filter_window.destroy()

            self.create_dialog_button(buttons, "Aplicar", apply_filters).grid(
                row=0, column=0, padx=5
            )
            self.create_dialog_button(buttons, "Limpar", clear_filters).grid(
                row=0, column=1, padx=5
            )

        refresh_table()

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

    def show_restore_window(self):
        if not self.require_permission("restore_backup"):
            return

        history = [
            (index, entry)
            for index, entry in enumerate(self.load_history())
            if can_view_backup_entry(self.current_user, entry)
        ]

        if not history:
            messagebox.showinfo(
                "Sem backups",
                "Nenhum backup disponivel para recuperacao."
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

        window = tk.Toplevel(self.root)
        window.title("Recuperar arquivos e versoes")
        window.geometry("1240x700")
        window.minsize(900, 540)
        window.configure(bg=BG_COLOR)
        window.transient(self.root)
        self.prepare_window(window)

        tk.Label(
            window,
            text="Recuperar Arquivos e Versoes",
            bg=BG_COLOR,
            fg=TITLE_COLOR,
            font=TITLE_FONT
        ).pack(pady=(18, 10))

        content = tk.Frame(window, bg=BG_COLOR)
        content.pack(fill="both", expand=True, padx=18, pady=(0, 18))

        search_bar = tk.Frame(content, bg=BG_COLOR)
        search_bar.columnconfigure(1, weight=1)

        search_var = tk.StringVar()

        tk.Label(
            search_bar,
            text="Buscar arquivo",
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=("Arial", 10, "bold")
        ).grid(row=0, column=0, sticky="w", padx=(0, 10))

        search_entry = tk.Entry(
            search_bar,
            textvariable=search_var,
            font=TABLE_FONT,
            bg=LIGHT_BUTTON,
            fg=TEXT_COLOR,
            relief="flat"
        )
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

        self.create_dialog_button(
            search_bar,
            "Buscar",
            lambda: apply_restore_search()
        ).grid(row=0, column=2, padx=(10, 0))

        def clear_file_search():
            search_var.set("")
            hide_restore_suggestions()
            refresh_backups()

        self.create_dialog_button(
            search_bar,
            "Limpar",
            clear_file_search
        ).grid(row=0, column=3, padx=(8, 0))

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
                row=1,
                column=1,
                columnspan=3,
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

        backup_label = tk.Label(
            content,
            text="Backups",
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=("Arial", 10, "bold")
        )

        recoverable_summary = tk.StringVar(value="Arquivos recuperaveis")
        recoverable_label = tk.Label(
            content,
            textvariable=recoverable_summary,
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=("Arial", 10, "bold")
        )

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
                button_bar.grid(row=5, column=0, sticky="e", pady=(10, 0))

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
            filter_window = tk.Toplevel(window)
            filter_window.title("Filtrar arquivos recuperaveis")
            filter_window.geometry("560x390")
            filter_window.minsize(540, 370)
            filter_window.configure(bg=BG_COLOR)
            filter_window.transient(window)
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
                    target_overrides=target_overrides
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

        self.create_dialog_button(
            button_bar,
            "Recuperar selecionados",
            restore_selected_files
        ).pack(side="left", padx=(0, 8))

        self.create_dialog_button(
            button_bar,
            "Recuperar pasta do item",
            restore_selected_folder
        ).pack(side="left", padx=(0, 8))

        self.create_dialog_button(
            button_bar,
            "Filtrar arquivos",
            lambda: open_restore_filter_window()
        ).pack(side="left")

        backup_tree.bind("<<TreeviewSelect>>", refresh_recoverable_files)
        refresh_backups()

    def show_history_window(self):
        if not self.require_permission("view_history"):
            return

        history = self.get_visible_history()

        window = tk.Toplevel(self.root)
        window.title("Historico de backups")
        window.geometry("1280x720")
        window.minsize(900, 540)
        window.configure(bg=BG_COLOR)
        window.transient(self.root)
        self.prepare_window(window)

        tk.Label(
            window,
            text="Historico de Backups",
            bg=BG_COLOR,
            fg=TITLE_COLOR,
            font=TITLE_FONT
        ).pack(pady=(18, 10))

        content = tk.Frame(window, bg=BG_COLOR)
        content.pack(fill="both", expand=True, padx=18, pady=(0, 18))

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
            values=["Todos", "adicionado", "alterado", "excluido"],
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
            "backup_name",
            "description",
            "trigger",
            "total",
            "changes"
        )
        backup_frame = tk.Frame(content, bg=BG_COLOR)
        backup_tree = self.create_scrollable_tree(
            backup_frame,
            backup_columns,
            height=15
        )

        backup_headings = {
            "timestamp": "Data",
            "user": "Usuario",
            "backup_name": "Nome",
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
                "backup_name": {
                    "width": 150,
                    "minwidth": 120,
                    "weight": 2,
                    "anchor": "w",
                },
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

        change_columns = ("action", "name", "archive_name", "size", "modified_at")
        change_frame = tk.Frame(content, bg=BG_COLOR)
        change_tree = self.create_scrollable_tree(
            change_frame,
            change_columns,
            height=15
        )

        change_headings = {
            "action": "Acao",
            "name": "Arquivo",
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
                    "width": 220,
                    "minwidth": 170,
                    "weight": 3,
                    "anchor": "w",
                },
                "archive_name": {
                    "width": 330,
                    "minwidth": 250,
                    "weight": 5,
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
                values=("Nenhum backup visivel", "-", "-", "-", "-", "-", "-")
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
                for change in entry.get("file_changes", [])
            )

        def get_history_search_suggestions():
            search_text = file_name_var.get().strip().lower()

            if not search_text:
                return []

            suggestions = []
            seen = set()

            for entry in history:
                for change in entry.get("file_changes", []):
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

        indexed_history = []

        def refresh_backup_table():
            nonlocal indexed_history

            for item in backup_tree.get_children():
                backup_tree.delete(item)

            indexed_history = [
                entry for entry in reversed(history)
                if entry_matches_history_filters(entry)
            ]

            for index, entry in enumerate(indexed_history):
                backup_tree.insert(
                    "",
                    tk.END,
                    iid=str(index),
                    values=(
                        entry.get("timestamp", "-"),
                        entry.get("user", "sistema"),
                        entry.get("backup_name", "") or entry.get("backup_file", "-"),
                        entry.get("backup_description", ""),
                        entry.get("trigger", "-"),
                        entry.get("total_files", 0),
                        len(entry.get("file_changes", []))
                    )
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

            if indexed_history:
                backup_tree.selection_set("0")
                refresh_changes()
            else:
                change_tree.insert(
                    "",
                    tk.END,
                    values=("-", "Nenhum backup para este filtro", "", "-", "-")
                )

        def refresh_changes(event=None):
            for item in change_tree.get_children():
                change_tree.delete(item)

            selected = backup_tree.selection()

            if not selected:
                return

            entry = indexed_history[int(selected[0])]
            selected_action = action_var.get()
            file_name_filter = file_name_var.get().strip().lower()
            changes = entry.get("file_changes", [])

            if not changes:
                change_tree.insert(
                    "",
                    tk.END,
                    values=(
                        "-",
                        "Nenhuma mudanca registrada",
                        "Backups antigos podem nao ter esse detalhe",
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
                    values=("-", "Nenhum arquivo para este filtro", "", "-", "-")
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
            filter_window = tk.Toplevel(window)
            filter_window.title("Filtrar historico")
            filter_window.geometry("520x380")
            filter_window.minsize(500, 360)
            filter_window.configure(bg=BG_COLOR)
            filter_window.transient(window)
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

        latest_backup = self.get_latest_backup()

        if not latest_backup:
            messagebox.showinfo(
                "Sem backup",
                "Nenhum backup disponivel para exportacao."
            )
            return

        destination = filedialog.asksaveasfilename(
            title="Salvar copia do ultimo backup",
            defaultextension=".zip",
            initialfile=os.path.basename(latest_backup),
            filetypes=[("Arquivo ZIP", "*.zip"), ("Todos os arquivos", "*.*")]
        )

        if not destination:
            return

        shutil.copy2(latest_backup, destination)
        messagebox.showinfo(
            "Backup exportado",
            f"Ultimo backup copiado para:\n{destination}"
        )

    def get_latest_backup(self):
        return get_latest_backup_path(self.get_backup_destination())

    def open_user_manager(self):
        if not self.require_permission("manage_users"):
            return

        window = tk.Toplevel(self.root)
        window.title("Gerenciar usuarios")
        window.geometry("820x470")
        window.minsize(760, 440)
        window.configure(bg=BG_COLOR)
        window.transient(self.root)
        self.prepare_window(window)

        tk.Label(
            window,
            text="Gerenciar Usuarios",
            bg=BG_COLOR,
            fg=TITLE_COLOR,
            font=TITLE_FONT
        ).pack(pady=(18, 10))

        content = tk.Frame(window, bg=BG_COLOR)
        content.pack(fill="both", expand=True, padx=18, pady=(0, 18))

        columns = ("username", "name", "role")
        tree_frame = tk.Frame(content, bg=BG_COLOR)
        tree_frame.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 16))
        tree = self.create_scrollable_tree(tree_frame, columns, height=10)
        content.columnconfigure(0, weight=1)
        content.columnconfigure(1, weight=0)
        content.rowconfigure(0, weight=1)

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

        form = tk.Frame(content, bg=BG_COLOR)
        form.grid(row=0, column=1, sticky="n")

        username_var = tk.StringVar()
        name_var = tk.StringVar()
        role_var = tk.StringVar(value="viewer")
        password_var = tk.StringVar()

        def add_field(label, variable, row, show=None):
            tk.Label(
                form,
                text=label,
                bg=BG_COLOR,
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
            bg=BG_COLOR,
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

        buttons = tk.Frame(content, bg=BG_COLOR)
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

            if (
                username_key == self.current_user.get("username")
                and role_var.get() != self.current_user.get("role")
            ):
                messagebox.showwarning(
                    "Operacao bloqueada",
                    "Voce nao pode alterar o perfil do usuario em uso.",
                    parent=window
                )
                return

            try:
                if username_key in [user["username"] for user in list_public_users()]:
                    update_user(
                        username,
                        role=role_var.get(),
                        name=name_var.get(),
                        password=password_var.get() or None
                    )
                else:
                    create_user(
                        username,
                        password_var.get(),
                        role_var.get(),
                        name=name_var.get()
                    )
            except ValueError as error:
                messagebox.showwarning("Dados invalidos", str(error), parent=window)
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
                    parent=window
                )
                return

            confirmed = messagebox.askyesno(
                "Remover usuario",
                f"Remover o usuario '{username}'?",
                parent=window
            )

            if not confirmed:
                return

            try:
                delete_user(username)
            except ValueError as error:
                messagebox.showwarning("Operacao bloqueada", str(error), parent=window)
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


def start_gui(current_user=None):
    from interface.login import login_user

    while True:
        if current_user is None:
            current_user = login_user()

        if current_user is None:
            return

        root = tk.Tk()
        gui = BackupGUI(root, current_user)
        root.mainloop()

        if not gui.logout_requested:
            return

        current_user = None
