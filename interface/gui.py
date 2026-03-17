import tkinter as tk
from tkinter import filedialog, messagebox
import json
import os

CONFIG_FILE = "../config/config.json"

class BackupGUI:

    def __init__(self, root):

        self.root = root
        self.root.title("Sistema de Backup Inteligente")
        self.root.geometry("500x400")

        self.directories = []

        self.load_config()

        self.label = tk.Label(
            root,
            text="Diretórios selecionados para backup",
            font=("Arial", 12)
        )
        self.label.pack(pady=10)

        self.listbox = tk.Listbox(root, width=60, height=10)
        self.listbox.pack()

        self.update_listbox()

        self.add_button = tk.Button(
            root,
            text="Adicionar pasta",
            command=self.add_directory
        )
        self.add_button.pack(pady=5)

        self.remove_button = tk.Button(
            root,
            text="Remover pasta",
            command=self.remove_directory
        )
        self.remove_button.pack(pady=5)

        self.save_button = tk.Button(
            root,
            text="Salvar configuração",
            command=self.save_config
        )
        self.save_button.pack(pady=10)

    def add_directory(self):

        folder = filedialog.askdirectory()

        if folder and folder not in self.directories:
            self.directories.append(folder)
            self.update_listbox()

    def remove_directory(self):

        selected = self.listbox.curselection()

        if selected:
            index = selected[0]
            self.directories.pop(index)
            self.update_listbox()

    def update_listbox(self):

        self.listbox.delete(0, tk.END)

        for directory in self.directories:
            self.listbox.insert(tk.END, directory)

    def save_config(self):

        data = {
            "directories": self.directories
        }

        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)

        with open(CONFIG_FILE, "w") as f:
            json.dump(data, f, indent=4)

        messagebox.showinfo("Sucesso", "Configuração salva!")

    def load_config(self):

        if os.path.exists(CONFIG_FILE):

            with open(CONFIG_FILE) as f:
                data = json.load(f)

                self.directories = data.get("directories", [])

def start_gui():

    root = tk.Tk()
    app = BackupGUI(root)
    root.mainloop()