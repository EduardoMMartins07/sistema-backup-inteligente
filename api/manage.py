import argparse
import os
import sys

from api.config import get_settings, is_truthy, validate_environment
from api.database import connect, init_db
from api.services import create_company, create_user, users_count


def command_migrate(_args):
    init_db()
    print("Migrations aplicadas com sucesso.")
    return 0


def command_check_env(args):
    settings = get_settings()
    strict = (
        args.strict
        or settings.environment == "production"
        or is_truthy(os.environ.get("SMARTBACKUP_REQUIRE_ENV"))
    )
    missing = validate_environment(strict=False, settings=settings)

    if missing:
        print("Variaveis ausentes: " + ", ".join(missing))
        if strict:
            return 1
        print("Aviso: ambiente local permitido; configure antes do deploy.")
        return 0

    print("Ambiente configurado.")
    return 0


def command_seed(args):
    settings = get_settings()

    if settings.environment == "production" and not args.force:
        print("Seed bloqueado em producao. Use --force se tiver certeza.")
        return 1

    admin_password = settings.seed_admin_password
    operator_password = settings.seed_operator_password or admin_password
    viewer_password = settings.seed_viewer_password or admin_password

    if not admin_password:
        print("Configure SEED_ADMIN_PASSWORD antes de executar o seed.")
        return 1

    db = connect()

    try:
        if users_count(db) > 0 and not args.force:
            print("Seed ignorado: ja existem usuarios. Use --force para continuar.")
            return 0

        company = create_company(db, "Empresa Demo", company_id="company_demo")
        create_user(
            db,
            company["id"],
            "Admin Demo",
            "admin@demo.com",
            admin_password,
            "ADMIN_EMPRESA",
        )
        create_user(
            db,
            company["id"],
            "Operador Demo",
            "operador@demo.com",
            operator_password,
            "OPERADOR",
        )
        create_user(
            db,
            company["id"],
            "Viewer Demo",
            "viewer@demo.com",
            viewer_password,
            "VIEWER",
        )
        db.commit()
        print("Seed demo criado: Empresa Demo, admin, operador e viewer.")
        return 0
    except Exception as error:
        db.rollback()
        print(f"Falha no seed: {error}")
        return 1
    finally:
        db.close()


def build_parser():
    parser = argparse.ArgumentParser(description="Gerenciamento da API Smart Backup.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    migrate_parser = subparsers.add_parser("migrate", help="Aplica migrations.")
    migrate_parser.set_defaults(func=command_migrate)

    check_env_parser = subparsers.add_parser("check-env", help="Valida ambiente.")
    check_env_parser.add_argument("--strict", action="store_true")
    check_env_parser.set_defaults(func=command_check_env)

    seed_parser = subparsers.add_parser("seed", help="Cria dados demo opcionais.")
    seed_parser.add_argument("--force", action="store_true")
    seed_parser.set_defaults(func=command_seed)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
