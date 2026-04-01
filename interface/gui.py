import csv
import json
import os
import shutil
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from scanner.scanner import run_scanner

CONFIG_PATH = "config/config.json"
DATASET_PATH = "dataset/files_dataset.csv"
BACKUP_DIR = "backups"
HISTORY_PATH = "config/backup_history.json"
SCHEDULE_PATH = "config/backup_schedule.json"

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

        self.directories = []

        self.load_directories()
        self.build_layout()

    def build_layout(self):
        self.outer_frame = tk.Frame(
            self.root,
            bg=BG_COLOR,
            highlightbackground="#202020",
            highlightthickness=7
        )
        self.outer_frame.pack(fill="both", expand=True)

        title = tk.Label(
            self.outer_frame,
            text="MENU",
            bg=BG_COLOR,
            fg=TITLE_COLOR,
            font=("Arial Black", 30, "bold")
        )
        title.place(x=35, y=18)

        self.menu_frame = tk.Frame(self.outer_frame, bg=BG_COLOR)
        self.menu_frame.place(relx=0.5, rely=0.5, anchor="center", y=-20)

        self.create_menu_button(
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
        self.create_menu_button(
            "Retornar",
            self.root.destroy,
            bg=TITLE_COLOR
        )

        footer = tk.Label(
            self.outer_frame,
            text=self.build_footer_text(),
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=("Arial", 10)
        )
        footer.place(relx=0.5, rely=1.0, anchor="s", y=-18)
        self.footer_label = footer

        manage_button = tk.Button(
            self.outer_frame,
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
        manage_button.place(relx=1.0, x=-24, y=28, anchor="ne")

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

    def build_footer_text(self):
        total_dirs = len(self.directories)
        last_schedule = self.load_schedule()

        if last_schedule:
            schedule_text = (
                f"Agendamento salvo para {last_schedule['time']} "
                f"({last_schedule['frequency']})"
            )
        else:
            schedule_text = "Nenhum agendamento salvo"

        return f"{total_dirs} diretorio(s) monitorado(s)  |  {schedule_text}"

    def refresh_footer(self):
        self.footer_label.config(text=self.build_footer_text())

    def load_directories(self):
        if not os.path.exists(CONFIG_PATH):
            return

        with open(CONFIG_PATH, "r", encoding="utf-8") as file:
            try:
                data = json.load(file)
            except json.JSONDecodeError:
                return

        self.directories = data.get("directories", [])

    def save_directories(self):
        os.makedirs("config", exist_ok=True)

        with open(CONFIG_PATH, "w", encoding="utf-8") as file:
            json.dump({"directories": self.directories}, file, indent=4)

        self.refresh_footer()

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

        try:
            run_scanner()

            if not os.path.exists(DATASET_PATH):
                raise FileNotFoundError(
                    "O scanner foi executado, mas nenhum dataset foi gerado."
                )

            os.makedirs(BACKUP_DIR, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"backup_{timestamp}.csv"
            backup_path = os.path.join(BACKUP_DIR, backup_name)

            shutil.copy2(DATASET_PATH, backup_path)

            total_files = self.count_dataset_rows(DATASET_PATH)
            self.append_history(
                {
                    "timestamp": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                    "backup_file": backup_name,
                    "source_dataset": DATASET_PATH,
                    "total_files": total_files
                }
            )

            messagebox.showinfo(
                "Backup concluido",
                (
                    "Backup realizado com sucesso.\n\n"
                    f"Arquivo salvo em:\n{backup_path}\n\n"
                    f"Arquivos catalogados: {total_files}"
                )
            )
        except Exception as error:
            messagebox.showerror("Erro", str(error))

    def count_dataset_rows(self, path):
        with open(path, "r", encoding="utf-8", newline="") as file:
            reader = csv.reader(file)
            rows = list(reader)

        return max(len(rows) - 1, 0)

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
            text="O agendamento sera salvo para a proxima etapa do projeto.",
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
        if not os.path.exists(DATASET_PATH):
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

        with open(DATASET_PATH, "r", encoding="utf-8", newline="") as file:
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
                f"{entry.get('total_files', 0)} arquivo(s)"
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
            defaultextension=".csv",
            initialfile=os.path.basename(latest_backup),
            filetypes=[("Arquivo CSV", "*.csv"), ("Todos os arquivos", "*.*")]
        )

        if not destination:
            return

        shutil.copy2(latest_backup, destination)
        messagebox.showinfo(
            "Backup exportado",
            f"Ultimo backup copiado para:\n{destination}"
        )

    def get_latest_backup(self):
        if not os.path.exists(BACKUP_DIR):
            return None

        files = [
            os.path.join(BACKUP_DIR, name)
            for name in os.listdir(BACKUP_DIR)
            if name.lower().endswith(".csv")
        ]

        if not files:
            return None

        return max(files, key=os.path.getmtime)


def start_gui():
    root = tk.Tk()
    BackupGUI(root)
    root.mainloop()
