"""Comandos administrativos.

Uso:
    python -m app.cli promover-gerente email@exemplo.com

O primeiro gerente é criado assim (RF-SEC03): a pessoa se cadastra normalmente pelo site
e depois é promovida por este comando, executado por quem tem acesso ao banco.
"""

import argparse
import sys

from app.core.database import SessionLocal
from app.models.usuario import PERFIL_GERENTE
from app.repositories import usuario_repository


def promover_gerente(email: str) -> int:
    with SessionLocal() as db, db.begin():
        usuario = usuario_repository.buscar_ativo_por_email(db, email)
        if not usuario:
            print(f"Nenhuma conta ativa com o e-mail {email}.", file=sys.stderr)
            return 1
        usuario.perfil = PERFIL_GERENTE
    print(f"{email} agora é gerente.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    comandos = parser.add_subparsers(dest="comando", required=True)
    promover = comandos.add_parser("promover-gerente", help="Promove uma conta existente a gerente")
    promover.add_argument("email")
    args = parser.parse_args()
    if args.comando == "promover-gerente":
        return promover_gerente(args.email)
    return 1


if __name__ == "__main__":
    sys.exit(main())
