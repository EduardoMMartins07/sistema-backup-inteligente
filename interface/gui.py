import tkinter as tk
from tkinter import filedialog, messagebox
import json
import os

CONFIG_PATH = "config/config.json"


class BackupGUI:

    def __init__(self, root):

        self.root = root
        self.root.title("Sistema de Backup Inteligente")
        self.root.geometry("500x400")

        self.directories = []

        # Título
        title = tk.Label(
            root,
            text="Diretórios para Backup",
            font=("Arial", 14)
        )
        title.pack(pady=10)

        # Lista de diretórios
        self.listbox = tk.Listbox(
            root,
            width=60,
            height=10
        )
        self.listbox.pack(pady=10)

        # Botões
        btn_frame = tk.Frame(root)
        btn_frame.pack(pady=10)

        add_btn = tk.Button(
            btn_frame,
            text="Adicionar Pasta",
            command=self.add_directory
        )
        add_btn.grid(row=0, column=0, padx=5)

        remove_btn = tk.Button(
            btn_frame,
            text="Remover",
            command=self.remove_directory
        )
        remove_btn.grid(row=0, column=1, padx=5)

        save_btn = tk.Button(
            btn_frame,
            text="Salvar",
            command=self.save_directories
        )
        save_btn.grid(row=0, column=2, padx=5)

        scan_btn = tk.Button(
            btn_frame,
            text="Executar Scan",
            command=self.run_scan
        )
        scan_btn.grid(row=0, column=3, padx=5)

        # carregar diretórios existentes
        self.load_directories()

    # -------------------------

    def add_directory(self):

        folder = filedialog.askdirectory()

        if folder and folder not in self.directories:

            self.directories.append(folder)

            self.listbox.insert(tk.END, folder)

    # -------------------------

    def remove_directory(self):

        selected = self.listbox.curselection()

        if not selected:
            return

        index = selected[0]

        self.listbox.delete(index)

        del self.directories[index]

    # -------------------------

    def save_directories(self):

        config = {
            "directories": self.directories
        }

        os.makedirs("config", exist_ok=True)

        with open(CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=4)

        messagebox.showinfo(
            "Sucesso",
            "Diretórios salvos com sucesso!"
        )

    # -------------------------

    def load_directories(self):

        if not os.path.exists(CONFIG_PATH):
            return

        with open(CONFIG_PATH, "r") as f:

            try:
                data = json.load(f)
            except:
                return

        dirs = data.get("directories", [])

        self.directories = dirs

        for d in dirs:
            self.listbox.insert(tk.END, d)

    # -------------------------

    def run_scan(self):

        try:

            from scanner.scanner import run_scanner

            run_scanner()

            messagebox.showinfo(
                "Scan",
                "Scanner executado com sucesso!"
            )

        except Exception as e:

            messagebox.showerror(
                "Erro",
                str(e)
            )


# -------------------------

def start_gui():

    root = tk.Tk()

    app = BackupGUI(root)

    root.mainloop()