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
            font=("Arial Black", 30, "bold")
        )
        title.pack(side="left", anchor="nw")

        self.utility_frame = tk.Frame(self.header_frame, bg=BG_COLOR)
        self.utility_frame.pack(side="right", anchor="ne")

        tk.Label(
            self.utility_frame,
            text=self.build_user_label(),
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=("Arial", 10),
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
            font=("Arial", 10),
            justify="center",
            wraplength=720
        )
        footer.place(relx=0.5, rely=1.0, anchor="s", y=-18)
        self.footer_label = footer

        self.manage_button = tk.Button(
            self.utility_frame,
            text="Gerenciar diretorios",
            command=self.open_directory_manager,
            font=("Arial", 11, "bold"),
            bg=PANEL_COLOR,
            fg="white",
            activebackground=PANEL_COLOR,
            activeforeground="white",
            relief="flat",
            cursor="hand2",
            padx=12,
            pady=6
        )
        self.manage_button.pack(fill="x", pady=(0, 10))

        self.destination_button = tk.Button(
            self.utility_frame,
            text="Diretorio padrao de backup",
            command=self.choose_backup_destination,
            font=("Arial", 11, "bold"),
            bg=PANEL_COLOR,
            fg="white",
            activebackground=PANEL_COLOR,
            activeforeground="white",
            relief="flat",
            cursor="hand2",
            padx=12,
            pady=6
        )
        self.destination_button.pack(fill="x", pady=(0, 10))

        if can(self.current_user, "manage_users"):
            users_button = tk.Button(
                self.utility_frame,
                text="Gerenciar usuarios",
                command=self.open_user_manager,
                font=("Arial", 11, "bold"),
                bg=PANEL_COLOR,
                fg="white",
                activebackground=PANEL_COLOR,
                activeforeground="white",
                relief="flat",
                cursor="hand2",
                padx=12,
                pady=6
            )
            users_button.pack(fill="x")

        logout_button = tk.Button(
            self.utility_frame,
            text="Sair da conta",
            command=self.logout,
            font=("Arial", 11, "bold"),
            bg=LIGHT_BUTTON,
            fg=TEXT_COLOR,
            activebackground=LIGHT_BUTTON,
            activeforeground=TEXT_COLOR,
            relief="flat",
            cursor="hand2",
            padx=12,
            pady=6
        )
        logout_button.pack(fill="x", pady=(10, 0))

        self.apply_permissions()

    def create_menu_button(self, text, command, bg):
        button = tk.Button(
            self.menu_frame,
            text=text,
            command=command,
            font=("Arial", 15),
            bg=bg,
            fg=TEXT_COLOR,
            activebackground=bg,
            activeforeground=TEXT_COLOR,
            relief="flat",
            cursor="hand2",
            width=22,
            pady=4
        )
        button.pack(pady=8)
        return button

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
        window.configure(bg=BG_COLOR)
        window.transient(self.root)

        tk.Label(
            window,
            text="Diretorios para backup",
            bg=BG_COLOR,
            fg=TITLE_COLOR,
            font=("Arial Black", 20)
        ).pack(pady=(20, 12))

        listbox = tk.Listbox(
            window,
            width=85,
            height=12,
            font=("Arial", 11),
            bg=LIGHT_BUTTON,
            fg=TEXT_COLOR,
            selectbackground=TITLE_COLOR,
            selectforeground=TEXT_COLOR
        )
        listbox.pack(padx=20, pady=10, fill="both", expand=True)

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
        return tk.Button(
            parent,
            text=text,
            command=command,
            font=("Arial", 11, "bold"),
            bg=TITLE_COLOR,
            fg=TEXT_COLOR,
            activebackground=TITLE_COLOR,
            activeforeground=TEXT_COLOR,
            relief="flat",
            cursor="hand2",
            padx=14,
            pady=7
        )

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
        window.configure(bg=BG_COLOR)
        window.transient(self.root)
        window.grab_set()
        window.resizable(False, False)

        result = {"value": None}

        tk.Label(
            window,
            text="Identificar Backup",
            bg=BG_COLOR,
            fg=TITLE_COLOR,
            font=("Arial Black", 20)
        ).pack(pady=(22, 14))

        form = tk.Frame(window, bg=BG_COLOR)
        form.pack(fill="x", padx=34)

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
        description_text.pack(fill="x", pady=(0, 16))

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
        tk.Button(
            buttons,
            text="Cancelar",
            command=cancel,
            font=("Arial", 11, "bold"),
            bg=LIGHT_BUTTON,
            fg=TEXT_COLOR,
            activebackground=LIGHT_BUTTON,
            activeforeground=TEXT_COLOR,
            relief="flat",
            cursor="hand2",
            padx=14,
            pady=7
        ).grid(row=0, column=1, padx=6)

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
        self.progress_window.configure(bg=BG_COLOR)
        self.progress_window.transient(self.root)
        self.progress_window.grab_set()
        self.progress_window.resizable(False, False)
        self.progress_window.protocol("WM_DELETE_WINDOW", lambda: None)

        tk.Label(
            self.progress_window,
            text="Realizando backup",
            bg=BG_COLOR,
            fg=TITLE_COLOR,
            font=("Arial Black", 20)
        ).pack(pady=(22, 14))

        self.progress_label = tk.Label(
            self.progress_window,
            text="Preparando...",
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=("Arial", 11)
        )
        self.progress_label.pack(pady=(0, 12))

        self.progress_bar = ttk.Progressbar(
            self.progress_window,
            orient="horizontal",
            mode="determinate",
            length=320,
            maximum=100
        )
        self.progress_bar.pack(pady=(0, 10))
        self.progress_bar["value"] = 0

        self.cancel_button = tk.Button(
            self.progress_window,
            text="Cancelar",
            command=self.request_backup_cancel,
            font=("Arial", 10, "bold"),
            bg=LIGHT_BUTTON,
            fg=TEXT_COLOR,
            activebackground=LIGHT_BUTTON,
            activeforeground=TEXT_COLOR,
            relief="flat",
            cursor="hand2",
            padx=18,
            pady=6
        )
        self.cancel_button.pack(pady=(4, 0))

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
        window.configure(bg=BG_COLOR)
        window.transient(self.root)

        tk.Label(
            window,
            text="Agendar Backup",
            bg=BG_COLOR,
            fg=TITLE_COLOR,
            font=("Arial Black", 20)
        ).pack(pady=(18, 18))

        form = tk.Frame(window, bg=BG_COLOR)
        form.pack(pady=4)

        tk.Label(
            form,
            text="Horario (HH:MM)",
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=("Arial", 11)
        ).grid(row=0, column=0, sticky="w", pady=6)

        time_var = tk.StringVar(value=self.load_schedule().get("time", "09:00"))
        time_entry = tk.Entry(form, textvariable=time_var, font=("Arial", 11), width=18)
        time_entry.grid(row=0, column=1, padx=10, pady=6)

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
            width=15
        )
        frequency_combo.grid(row=1, column=1, padx=10, pady=6)

        info = tk.Label(
            window,
            text="O backup sera executado automaticamente no horario escolhido.",
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=("Arial", 10)
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

        tk.Label(
            window,
            text="Arquivos analisados",
            bg=BG_COLOR,
            fg=TITLE_COLOR,
            font=("Arial Black", 20)
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
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=15)
        tree.grid(row=0, column=0, sticky="nsew")

        vertical_scrollbar = ttk.Scrollbar(
            table_frame,
            orient="vertical",
            command=tree.yview
        )
        vertical_scrollbar.grid(row=0, column=1, sticky="ns")

        horizontal_scrollbar = ttk.Scrollbar(
            table_frame,
            orient="horizontal",
            command=tree.xview
        )
        horizontal_scrollbar.grid(row=1, column=0, sticky="ew")

        tree.configure(
            yscrollcommand=vertical_scrollbar.set,
            xscrollcommand=horizontal_scrollbar.set
        )

        for key, title in headings.items():
            tree.heading(key, text=title)
            width = 150

            if key == "name":
                width = 280
            elif key == "added_to_backup_at":
                width = 180

            tree.column(key, width=width, minwidth=90, anchor="center", stretch=True)

        tree.column("name", anchor="w")

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

            if not value:
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
            filter_window.geometry("420x430")
            filter_window.configure(bg=BG_COLOR)
            filter_window.transient(window)
            filter_window.grab_set()
            filter_window.resizable(False, False)

            tk.Label(
                filter_window,
                text="Filtrar Arquivos",
                bg=BG_COLOR,
                fg=TITLE_COLOR,
                font=("Arial Black", 18)
            ).pack(pady=(18, 12))

            form = tk.Frame(filter_window, bg=BG_COLOR)
            form.pack(fill="x", padx=28)

            field_vars = {
                "name": tk.StringVar(value=filter_state["name"]),
                "extension": tk.StringVar(value=filter_state["extension"]),
                "added_from": tk.StringVar(value=filter_state["added_from"]),
                "added_to": tk.StringVar(value=filter_state["added_to"]),
                "size_kb": tk.StringVar(value=filter_state["size_kb"]),
                "days_since_modified": tk.StringVar(value=filter_state["days_since_modified"]),
                "important": tk.StringVar(value=filter_state["important"]),
            }

            def add_entry(label, key, row):
                tk.Label(
                    form,
                    text=label,
                    bg=BG_COLOR,
                    fg=SUBTLE_TEXT,
                    font=("Arial", 10, "bold")
                ).grid(row=row, column=0, sticky="w", pady=(0, 4))

                entry = tk.Entry(
                    form,
                    textvariable=field_vars[key],
                    font=("Arial", 10),
                    bg=LIGHT_BUTTON,
                    fg=TEXT_COLOR,
                    relief="flat"
                )
                entry.grid(row=row, column=1, sticky="ew", padx=(10, 0), pady=(0, 8))

            form.columnconfigure(1, weight=1)
            add_entry("Nome", "name", 0)
            add_entry("Extensao", "extension", 1)
            add_entry("Data inicial", "added_from", 2)
            add_entry("Data final", "added_to", 3)
            add_entry("Tamanho (KB)", "size_kb", 4)
            add_entry("Dias sem alterar", "days_since_modified", 5)

            tk.Label(
                form,
                text="Importante",
                bg=BG_COLOR,
                fg=SUBTLE_TEXT,
                font=("Arial", 10, "bold")
            ).grid(row=6, column=0, sticky="w", pady=(0, 4))

            important_combo = ttk.Combobox(
                form,
                textvariable=field_vars["important"],
                values=["Todos", "Sim", "Nao"],
                state="readonly"
            )
            important_combo.grid(row=6, column=1, sticky="ew", padx=(10, 0), pady=(0, 8))

            buttons = tk.Frame(filter_window, bg=BG_COLOR)
            buttons.pack(pady=(10, 0))

            def apply_filters():
                from_date = parse_date(field_vars["added_from"].get())
                to_date = parse_date(field_vars["added_to"].get())

                if field_vars["added_from"].get().strip() and from_date is None:
                    messagebox.showwarning(
                        "Data invalida",
                        "Informe a data inicial no formato DD/MM/AAAA.",
                        parent=filter_window
                    )
                    return

                if field_vars["added_to"].get().strip() and to_date is None:
                    messagebox.showwarning(
                        "Data invalida",
                        "Informe a data final no formato DD/MM/AAAA.",
                        parent=filter_window
                    )
                    return

                for key, variable in field_vars.items():
                    filter_state[key] = variable.get().strip()

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

        window = tk.Toplevel(self.root)
        window.title("Recuperar arquivos e versoes")
        window.geometry("1220x650")
        window.minsize(980, 520)
        window.configure(bg=BG_COLOR)
        window.transient(self.root)

        tk.Label(
            window,
            text="Recuperar Arquivos e Versoes",
            bg=BG_COLOR,
            fg=TITLE_COLOR,
            font=("Arial Black", 20)
        ).pack(pady=(18, 10))

        content = tk.Frame(window, bg=BG_COLOR)
        content.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        content.columnconfigure(0, weight=1)
        content.columnconfigure(1, weight=2)
        content.rowconfigure(1, weight=1)

        tk.Label(
            content,
            text="Backups",
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=("Arial", 10, "bold")
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))

        recoverable_summary = tk.StringVar(value="Arquivos recuperaveis")
        tk.Label(
            content,
            textvariable=recoverable_summary,
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=("Arial", 10, "bold")
        ).grid(row=0, column=1, sticky="w", pady=(0, 6))

        backup_frame = tk.Frame(content, bg=BG_COLOR)
        backup_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 14))
        backup_frame.columnconfigure(0, weight=1)
        backup_frame.rowconfigure(0, weight=1)

        backup_columns = (
            "timestamp",
            "user",
            "backup_name",
            "trigger",
            "changed",
            "deleted"
        )
        backup_tree = ttk.Treeview(
            backup_frame,
            columns=backup_columns,
            show="headings",
            selectmode="browse"
        )
        backup_tree.grid(row=0, column=0, sticky="nsew")

        backup_scrollbar = ttk.Scrollbar(
            backup_frame,
            orient="vertical",
            command=backup_tree.yview
        )
        backup_scrollbar.grid(row=0, column=1, sticky="ns")
        backup_tree.configure(yscrollcommand=backup_scrollbar.set)

        backup_headings = {
            "timestamp": "Data",
            "user": "Usuario",
            "backup_name": "Backup",
            "trigger": "Tipo",
            "changed": "Alterados",
            "deleted": "Excluidos"
        }

        for key, title in backup_headings.items():
            backup_tree.heading(key, text=title)
            backup_tree.column(key, width=100, anchor="center")

        backup_tree.column("timestamp", width=135)
        backup_tree.column("backup_name", width=170, anchor="w")

        file_frame = tk.Frame(content, bg=BG_COLOR)
        file_frame.grid(row=1, column=1, sticky="nsew")
        file_frame.columnconfigure(0, weight=1)
        file_frame.rowconfigure(0, weight=1)

        file_columns = (
            "action",
            "name",
            "archive_name",
            "source_path",
            "size",
            "modified_at"
        )
        file_tree = ttk.Treeview(
            file_frame,
            columns=file_columns,
            show="headings",
            selectmode="extended"
        )
        file_tree.grid(row=0, column=0, sticky="nsew")

        file_vertical_scrollbar = ttk.Scrollbar(
            file_frame,
            orient="vertical",
            command=file_tree.yview
        )
        file_vertical_scrollbar.grid(row=0, column=1, sticky="ns")

        file_horizontal_scrollbar = ttk.Scrollbar(
            file_frame,
            orient="horizontal",
            command=file_tree.xview
        )
        file_horizontal_scrollbar.grid(row=1, column=0, sticky="ew")

        file_tree.configure(
            yscrollcommand=file_vertical_scrollbar.set,
            xscrollcommand=file_horizontal_scrollbar.set
        )

        file_headings = {
            "action": "Acao",
            "name": "Arquivo",
            "archive_name": "Caminho no backup",
            "source_path": "Local original",
            "size": "Tamanho",
            "modified_at": "Modificado em"
        }

        for key, title in file_headings.items():
            file_tree.heading(key, text=title)
            file_tree.column(key, width=130, anchor="center")

        file_tree.column("name", width=180, anchor="w")
        file_tree.column("archive_name", width=250, anchor="w")
        file_tree.column("source_path", width=330, anchor="w")

        button_bar = tk.Frame(content, bg=BG_COLOR)
        button_bar.grid(row=2, column=1, sticky="ew", pady=(10, 0))

        def refresh_backups():
            for item in backup_tree.get_children():
                backup_tree.delete(item)

            for list_index, (_, entry) in enumerate(indexed_history):
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

            if indexed_history:
                backup_tree.selection_set("0")
                refresh_recoverable_files()

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
            recoverable_summary.set(
                f"Arquivos recuperaveis: {len(current_recoverable_changes)}"
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

            for index, change in enumerate(current_recoverable_changes):
                file_tree.insert(
                    "",
                    tk.END,
                    iid=str(index),
                    values=(
                        change.get("action", ""),
                        change.get("name", ""),
                        change.get("archive_name", ""),
                        change.get("source_path", ""),
                        self.format_size_bytes(change.get("size_bytes")),
                        change.get("modified_at", "")
                    )
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
        ).pack(side="left")

        backup_tree.bind("<<TreeviewSelect>>", refresh_recoverable_files)
        refresh_backups()

    def show_history_window(self):
        if not self.require_permission("view_history"):
            return

        history = self.get_visible_history()

        window = tk.Toplevel(self.root)
        window.title("Historico de backups")
        window.geometry("1260x680")
        window.minsize(980, 520)
        window.configure(bg=BG_COLOR)
        window.transient(self.root)

        tk.Label(
            window,
            text="Historico de Backups",
            bg=BG_COLOR,
            fg=TITLE_COLOR,
            font=("Arial Black", 20)
        ).pack(pady=(18, 10))

        content = tk.Frame(window, bg=BG_COLOR)
        content.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        content.columnconfigure(0, weight=1)
        content.columnconfigure(1, weight=2)
        content.rowconfigure(1, weight=1)

        history_top_bar = tk.Frame(content, bg=BG_COLOR)
        history_top_bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        history_filter_summary = tk.StringVar(value="Filtros: todos os backups")
        tk.Label(
            history_top_bar,
            textvariable=history_filter_summary,
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=("Arial", 10)
        ).pack(side="left")

        history_filters = {
            "timestamp_from": "",
            "timestamp_to": "",
            "user": "",
            "backup_name": "",
            "backup_description": "",
            "trigger": "Todos",
            "total_files": "",
            "changes": "",
        }

        self.create_dialog_button(
            history_top_bar,
            "Filtrar",
            lambda: open_history_filter_window()
        ).pack(side="right")

        filter_frame = tk.Frame(content, bg=BG_COLOR)
        filter_frame.grid(row=0, column=1, sticky="ew", pady=(0, 6))

        tk.Label(
            filter_frame,
            text="Arquivos do backup selecionado",
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=("Arial", 10, "bold")
        ).pack(side="left")

        action_var = tk.StringVar(value="Todos")
        action_combo = ttk.Combobox(
            filter_frame,
            textvariable=action_var,
            values=["Todos", "adicionado", "alterado", "excluido"],
            state="readonly",
            width=14
        )
        action_combo.pack(side="right")

        tk.Label(
            filter_frame,
            text="Filtro:",
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=("Arial", 10)
        ).pack(side="right", padx=(0, 6))

        backup_columns = (
            "timestamp",
            "user",
            "backup_name",
            "description",
            "trigger",
            "total",
            "changes"
        )
        backup_tree = ttk.Treeview(
            content,
            columns=backup_columns,
            show="headings",
            height=15
        )
        backup_tree.grid(row=1, column=0, sticky="nsew", padx=(0, 14))

        backup_headings = {
            "timestamp": "Data",
            "user": "Usuario",
            "backup_name": "Nome",
            "description": "Descricao",
            "trigger": "Tipo",
            "total": "Arquivos",
            "changes": "Mudancas"
        }

        for key, title in backup_headings.items():
            backup_tree.heading(key, text=title)
            backup_tree.column(key, width=110, anchor="center")

        backup_tree.column("timestamp", width=135)
        backup_tree.column("description", width=170, anchor="w")

        change_columns = ("action", "name", "archive_name", "size", "modified_at")
        change_tree = ttk.Treeview(
            content,
            columns=change_columns,
            show="headings",
            height=15
        )
        change_tree.grid(row=1, column=1, sticky="nsew")

        change_headings = {
            "action": "Acao",
            "name": "Arquivo",
            "archive_name": "Caminho no backup",
            "size": "Tamanho",
            "modified_at": "Modificado em"
        }

        for key, title in change_headings.items():
            change_tree.heading(key, text=title)
            width = 260 if key == "archive_name" else 120
            change_tree.column(key, width=width, anchor="center")

        change_tree.column("name", width=180, anchor="w")
        change_tree.column("archive_name", width=300, anchor="w")

        if not history:
            backup_tree.insert(
                "",
                tk.END,
                values=("Nenhum backup visivel", "-", "-", "-")
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

            if not value:
                return None

            for date_format in ("%d/%m/%Y", "%d/%m/%Y %H:%M:%S"):
                try:
                    return datetime.strptime(value, date_format)
                except ValueError:
                    pass

            return None

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
                "total_files": entry.get("total_files", 0),
                "changes": len(entry.get("file_changes", [])),
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

            return True

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

            if history_filters["timestamp_from"] or history_filters["timestamp_to"]:
                active_filters.append("Periodo")

            for key, label in (
                ("user", "Usuario"),
                ("backup_name", "Nome"),
                ("backup_description", "Descricao"),
                ("total_files", "Arquivos"),
                ("changes", "Mudancas"),
            ):
                if history_filters[key].strip():
                    active_filters.append(label)

            if history_filters["trigger"] != "Todos":
                active_filters.append("Tipo")

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

                change_tree.insert(
                    "",
                    tk.END,
                    values=(
                        action,
                        change.get("name", ""),
                        change.get("archive_name", ""),
                        format_size(change.get("size_bytes")),
                        change.get("modified_at", "")
                    )
                )

            if not change_tree.get_children():
                change_tree.insert(
                    "",
                    tk.END,
                    values=("-", "Nenhum arquivo para este filtro", "", "-", "-")
                )

        backup_tree.bind("<<TreeviewSelect>>", refresh_changes)
        action_combo.bind("<<ComboboxSelected>>", refresh_changes)

        def open_history_filter_window():
            filter_window = tk.Toplevel(window)
            filter_window.title("Filtrar historico")
            filter_window.geometry("460x470")
            filter_window.configure(bg=BG_COLOR)
            filter_window.transient(window)
            filter_window.grab_set()
            filter_window.resizable(False, False)

            tk.Label(
                filter_window,
                text="Filtrar Historico",
                bg=BG_COLOR,
                fg=TITLE_COLOR,
                font=("Arial Black", 18)
            ).pack(pady=(18, 12))

            form = tk.Frame(filter_window, bg=BG_COLOR)
            form.pack(fill="x", padx=28)
            form.columnconfigure(1, weight=1)

            field_vars = {
                "timestamp_from": tk.StringVar(value=history_filters["timestamp_from"]),
                "timestamp_to": tk.StringVar(value=history_filters["timestamp_to"]),
                "user": tk.StringVar(value=history_filters["user"]),
                "backup_name": tk.StringVar(value=history_filters["backup_name"]),
                "backup_description": tk.StringVar(value=history_filters["backup_description"]),
                "trigger": tk.StringVar(value=history_filters["trigger"]),
                "total_files": tk.StringVar(value=history_filters["total_files"]),
                "changes": tk.StringVar(value=history_filters["changes"]),
            }

            def add_entry(label, key, row):
                tk.Label(
                    form,
                    text=label,
                    bg=BG_COLOR,
                    fg=SUBTLE_TEXT,
                    font=("Arial", 10, "bold")
                ).grid(row=row, column=0, sticky="w", pady=(0, 4))

                entry = tk.Entry(
                    form,
                    textvariable=field_vars[key],
                    font=("Arial", 10),
                    bg=LIGHT_BUTTON,
                    fg=TEXT_COLOR,
                    relief="flat"
                )
                entry.grid(row=row, column=1, sticky="ew", padx=(10, 0), pady=(0, 8))

            add_entry("Data inicial", "timestamp_from", 0)
            add_entry("Data final", "timestamp_to", 1)
            add_entry("Usuario", "user", 2)
            add_entry("Nome", "backup_name", 3)
            add_entry("Descricao", "backup_description", 4)

            tk.Label(
                form,
                text="Tipo",
                bg=BG_COLOR,
                fg=SUBTLE_TEXT,
                font=("Arial", 10, "bold")
            ).grid(row=5, column=0, sticky="w", pady=(0, 4))

            trigger_combo = ttk.Combobox(
                form,
                textvariable=field_vars["trigger"],
                values=["Todos", "manual", "agendado", "sistema"],
                state="readonly"
            )
            trigger_combo.grid(row=5, column=1, sticky="ew", padx=(10, 0), pady=(0, 8))

            add_entry("Arquivos", "total_files", 6)
            add_entry("Mudancas", "changes", 7)

            buttons = tk.Frame(filter_window, bg=BG_COLOR)
            buttons.pack(pady=(10, 0))

            def apply_filters():
                from_date = parse_history_date(field_vars["timestamp_from"].get())
                to_date = parse_history_date(field_vars["timestamp_to"].get())

                if field_vars["timestamp_from"].get().strip() and from_date is None:
                    messagebox.showwarning(
                        "Data invalida",
                        "Informe a data inicial no formato DD/MM/AAAA.",
                        parent=filter_window
                    )
                    return

                if field_vars["timestamp_to"].get().strip() and to_date is None:
                    messagebox.showwarning(
                        "Data invalida",
                        "Informe a data final no formato DD/MM/AAAA.",
                        parent=filter_window
                    )
                    return

                for key, variable in field_vars.items():
                    history_filters[key] = variable.get().strip()

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
        window.configure(bg=BG_COLOR)
        window.transient(self.root)

        tk.Label(
            window,
            text="Gerenciar Usuarios",
            bg=BG_COLOR,
            fg=TITLE_COLOR,
            font=("Arial Black", 20)
        ).pack(pady=(18, 10))

        content = tk.Frame(window, bg=BG_COLOR)
        content.pack(fill="both", expand=True, padx=18, pady=(0, 18))

        columns = ("username", "name", "role")
        tree = ttk.Treeview(content, columns=columns, show="headings", height=10)
        tree.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 16))
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)

        headings = {
            "username": "Usuario",
            "name": "Nome",
            "role": "Perfil"
        }

        for key, title in headings.items():
            tree.heading(key, text=title)
            tree.column(key, width=130, anchor="center")

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
