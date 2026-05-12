ROLES = {
    "admin": {
        "manage_users",
        "manage_directories",
        "change_backup_destination",
        "run_backup",
        "schedule_backup",
        "view_files",
        "view_history",
        "download_backup",
        "restore_backup",
    },
    "operator": {
        "run_backup",
        "schedule_backup",
        "view_files",
        "view_history",
        "download_backup",
        "restore_backup",
    },
    "viewer": {
        "view_files",
        "view_history",
    },
}

ROLE_LABELS = {
    "admin": "Administrador",
    "operator": "Operador",
    "viewer": "Visualizador",
}


def can(user, permission):
    if not user:
        return False

    role = user.get("role")
    return permission in ROLES.get(role, set())


def get_role_label(role):
    return ROLE_LABELS.get(role, role)


def get_role_options():
    return list(ROLE_LABELS.keys())


def can_view_backup_entry(current_user, entry):
    if not current_user:
        return False

    current_username = current_user.get("username")
    current_role = current_user.get("role")
    current_company = current_user.get("company_id", "default")
    entry_company = entry.get("company_id", "default")
    entry_user = entry.get("user")
    entry_role = entry.get("user_role")

    if entry_company != current_company:
        return False

    if current_role == "admin":
        return True

    if current_role == "operator":
        return entry_user == current_username or entry_role == "viewer"

    if current_role == "viewer":
        return entry_user == current_username

    return False
