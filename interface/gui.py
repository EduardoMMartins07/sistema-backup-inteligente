import csv
import json
import os
import queue
import shutil
import threading
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from backup.backup_manager import BackupCancelledError
from backup.backup_manager import get_latest_backup_path
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

    def __init__(self, root):
        self.root = root
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

        self.menu_frame = tk.Frame(self.outer_frame, bg=BG_COLOR)
        self.menu_frame.place(relx=0.5, rely=0.55, anchor="center")

        self.backup_button = self.create_menu_button(
            "Realizar Backup",
            self.perform_backup,
            bg=TITLE_COLOR
        )
        self.create_menu_button(
            "Agendar Backup",
            self.open_schedule_window,
            bg=TITLE_COLOR
        )
        self.create_menu_button(
            "Listar Arquivos",
            self.show_files_window,
            bg=LIGHT_BUTTON
        )
        self.create_menu_button(
            "Historico de Backups",
            self.show_history_window,
            bg=LIGHT_BUTTON
        )
        self.create_menu_button(
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

        manage_button = tk.Button(
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
        manage_button.pack(fill="x", pady=(0, 10))

        destination_button = tk.Button(
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
        destination_button.pack(fill="x")

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

    def open_schedule_window(self):
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
        dataset_path = os.path.join("dataset", "files_dataset.csv")

        if not os.path.exists(dataset_path):
            messagebox.showinfo(
                "Sem arquivos",
                "Nenhum arquivo foi listado ainda. Execute um backup primeiro."
            )
            return

        window = tk.Toplevel(self.root)
        window.title("Arquivos analisados")
        window.geometry("920x460")
        window.configure(bg=BG_COLOR)
        window.transient(self.root)

        tk.Label(
            window,
            text="Arquivos analisados",
            bg=BG_COLOR,
            fg=TITLE_COLOR,
            font=("Arial Black", 20)
        ).pack(pady=(18, 10))

        columns = (
            "name",
            "extension",
            "type",
            "size_kb",
            "days_since_modified",
            "important"
        )
        tree = ttk.Treeview(window, columns=columns, show="headings", height=15)
        tree.pack(fill="both", expand=True, padx=18, pady=(0, 18))

        headings = {
            "name": "Nome",
            "extension": "Extensao",
            "type": "Tipo",
            "size_kb": "Tamanho (KB)",
            "days_since_modified": "Dias sem alterar",
            "important": "Importante"
        }

        for key, title in headings.items():
            tree.heading(key, text=title)
            width = 120 if key != "name" else 270
            tree.column(key, width=width, anchor="center")

        with open(dataset_path, "r", encoding="utf-8", newline="") as file:
            reader = csv.DictReader(file)

            for row in reader:
                tree.insert(
                    "",
                    tk.END,
                    values=(
                        row.get("name", ""),
                        row.get("extension", ""),
                        row.get("type", ""),
                        self.format_float(row.get("size_kb", "0")),
                        row.get("days_since_modified", ""),
                        "Sim" if row.get("important") == "1" else "Nao"
                    )
                )

    def format_float(self, value):
        try:
            return f"{float(value):.2f}"
        except (TypeError, ValueError):
            return value

    def show_history_window(self):
        history = self.load_history()

        window = tk.Toplevel(self.root)
        window.title("Historico de backups")
        window.geometry("760x380")
        window.configure(bg=BG_COLOR)
        window.transient(self.root)

        tk.Label(
            window,
            text="Historico de Backups",
            bg=BG_COLOR,
            fg=TITLE_COLOR,
            font=("Arial Black", 20)
        ).pack(pady=(18, 10))

        listbox = tk.Listbox(
            window,
            width=95,
            height=14,
            font=("Arial", 11),
            bg=LIGHT_BUTTON,
            fg=TEXT_COLOR
        )
        listbox.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        if not history:
            listbox.insert(tk.END, "Nenhum backup registrado ate o momento.")
            return

        for entry in reversed(history):
            line = (
                f"{entry.get('timestamp', '-')}  |  "
                f"{entry.get('backup_file', '-')}  |  "
                f"{entry.get('total_files', 0)} arquivo(s)  |  "
                f"{entry.get('backup_folder', '-')}"
            )
            listbox.insert(tk.END, line)

    def download_latest_backup(self):
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


def start_gui():
    root = tk.Tk()
    BackupGUI(root)
    root.mainloop()
