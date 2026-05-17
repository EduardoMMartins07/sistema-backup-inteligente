import tkinter as tk
from tkinter import messagebox

from auth.permissions import ROLE_LABELS
from auth.users import authenticate
from auth.users import create_user
from auth.users import users_exist

BG_COLOR = "#283241"
PANEL_COLOR = "#1F2733"
TITLE_COLOR = "#FF990F"
LIGHT_BUTTON = "#D9D9D9"
TEXT_COLOR = "#101010"
SUBTLE_TEXT = "#E7EAF0"


class LoginWindow:
    def __init__(self, root=None):
        self.owns_root = root is None
        self.root = root if root is not None else tk.Tk()
        self.root.title("Login - Sistema de Backup Inteligente")
        self.root.geometry("520x500")
        self.root.minsize(480, 460)
        self.root.resizable(False, False)
        self.root.configure(bg=BG_COLOR)
        self.root.deiconify()
        self.user = None
        self.clear_window()
        self.root.protocol("WM_DELETE_WINDOW", self.cancel)

        self.username_var = tk.StringVar(master=self.root)
        self.password_var = tk.StringVar(master=self.root)
        self.name_var = tk.StringVar(master=self.root)
        self.confirm_password_var = tk.StringVar(master=self.root)

        if users_exist():
            self.build_login_form()
        else:
            self.build_initial_admin_form()

    def clear_window(self):
        for widget in self.root.winfo_children():
            widget.destroy()

    def create_shell(self):
        outer_frame = tk.Frame(
            self.root,
            bg=BG_COLOR,
            highlightbackground="#202020",
            highlightthickness=7
        )
        outer_frame.pack(fill="both", expand=True)

        panel = tk.Frame(outer_frame, bg=BG_COLOR)
        panel.place(relx=0.5, rely=0.5, anchor="center", width=370)
        return panel

    def create_title(self, text, subtitle):
        tk.Label(
            self.panel,
            text=text,
            bg=BG_COLOR,
            fg=TITLE_COLOR,
            font=("Arial Black", 25)
        ).pack(pady=(0, 8))

        tk.Label(
            self.panel,
            text=subtitle,
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=("Arial", 10),
            wraplength=340,
            justify="center"
        ).pack(pady=(0, 22))

    def create_form_frame(self):
        frame = tk.Frame(self.panel, bg=BG_COLOR)
        frame.pack(fill="x")
        frame.columnconfigure(0, weight=1)
        return frame

    def create_label(self, parent, text, row):
        tk.Label(
            parent,
            text=text,
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=("Arial", 10, "bold")
        ).grid(row=row, column=0, sticky="w", pady=(0, 4))

    def create_entry(self, parent, variable, row, show=None):
        entry = tk.Entry(
            parent,
            textvariable=variable,
            show=show,
            font=("Arial", 11),
            bg=LIGHT_BUTTON,
            fg=TEXT_COLOR,
            relief="flat",
            insertbackground=TEXT_COLOR
        )
        entry.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        return entry

    def create_primary_button(self, text, command):
        return tk.Button(
            self.panel,
            text=text,
            command=command,
            font=("Arial", 12, "bold"),
            bg=TITLE_COLOR,
            fg=TEXT_COLOR,
            activebackground=TITLE_COLOR,
            activeforeground=TEXT_COLOR,
            relief="flat",
            cursor="hand2",
            padx=18,
            pady=8
        )

    def create_footer(self, text):
        tk.Label(
            self.panel,
            text=text,
            bg=BG_COLOR,
            fg=SUBTLE_TEXT,
            font=("Arial", 9),
            wraplength=330,
            justify="center"
        ).pack(pady=(16, 0))

    def build_login_form(self):
        self.clear_window()
        self.panel = self.create_shell()
        self.create_title(
            "SMART BACKUP",
            "Entre com seu usuario para abrir o painel."
        )

        form = self.create_form_frame()
        self.create_label(form, "Usuario", 0)
        username_entry = self.create_entry(form, self.username_var, 1)
        self.create_label(form, "Senha", 2)
        password_entry = self.create_entry(form, self.password_var, 3, show="*")

        self.create_primary_button("Entrar", self.submit_login).pack(pady=(10, 0))
        self.create_footer("O acesso ao sistema depende do perfil de permissao.")

        username_entry.focus_set()
        self.root.bind("<Return>", lambda event: self.submit_login())

    def build_initial_admin_form(self):
        self.clear_window()
        self.root.geometry("540x560")
        self.panel = self.create_shell()
        self.create_title(
            "PRIMEIRO ACESSO",
            "Crie o administrador inicial para liberar o sistema."
        )

        form = self.create_form_frame()
        self.create_label(form, "Nome", 0)
        name_entry = self.create_entry(form, self.name_var, 1)
        self.create_label(form, "Usuario", 2)
        self.create_entry(form, self.username_var, 3)
        self.create_label(form, "Senha", 4)
        self.create_entry(form, self.password_var, 5, show="*")
        self.create_label(form, "Confirmar senha", 6)
        self.create_entry(form, self.confirm_password_var, 7, show="*")

        self.create_primary_button(
            "Criar administrador",
            self.submit_initial_admin
        ).pack(pady=(2, 0))
        self.create_footer("O administrador podera cadastrar operadores e visualizadores.")

        name_entry.focus_set()
        self.root.bind("<Return>", lambda event: self.submit_initial_admin())

    def submit_login(self):
        username = self.username_var.get()
        password = self.password_var.get()
        user = authenticate(username, password)

        if not user:
            messagebox.showerror(
                "Login invalido",
                "Usuario ou senha incorretos.",
                parent=self.root
            )
            return

        self.user = user
        self.close()

    def submit_initial_admin(self):
        password = self.password_var.get()
        confirm_password = self.confirm_password_var.get()

        if password != confirm_password:
            messagebox.showwarning(
                "Senhas diferentes",
                "A senha e a confirmacao precisam ser iguais.",
                parent=self.root
            )
            return

        try:
            user = create_user(
                self.username_var.get(),
                password,
                "admin",
                name=self.name_var.get()
            )
        except ValueError as error:
            messagebox.showwarning("Dados invalidos", str(error), parent=self.root)
            return

        message = f"Usuario administrador criado com perfil {ROLE_LABELS['admin']}."

        if user.get("recovery_key"):
            message += (
                "\n\nChave de recuperacao do usuario:\n"
                f"{user['recovery_key']}\n\n"
                "Guarde esta chave. Ela nao sera exibida novamente."
            )

        messagebox.showinfo("Administrador criado", message, parent=self.root)
        self.user = user
        self.close()

    def cancel(self):
        self.user = None
        self.close()

    def close(self):
        self.root.unbind("<Return>")

        if self.owns_root:
            self.root.destroy()
            return

        self.clear_window()
        self.root.quit()

    def run(self):
        self.root.mainloop()
        return self.user


def login_user(root=None):
    login_window = LoginWindow(root=root)
    return login_window.run()
