#!/usr/bin/env python3
"""Prepare the stack to run on your own computer with Docker Desktop (no AWS needed).

Creates, only if they do not exist yet:
  stack/compose/secrets/grafana_admin_password   random password for Grafana's "admin" user
  stack/compose/secrets/shop_api_admin_token     random token used by: python scripts/chaos.py --local
  stack/compose/.env                             makes Docker Compose use the local Alertmanager config
These files are in .gitignore (never committed) and are left out of the bundle sent to AWS.
"""

import secrets
import string
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPOSE_DIR = ROOT / "stack" / "compose"
SECRETS_DIR = COMPOSE_DIR / "secrets"
ALPHABET = string.ascii_letters + string.digits


def random_secret(length: int) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def main() -> None:
    SECRETS_DIR.mkdir(exist_ok=True)
    for name, length in (("grafana_admin_password", 24), ("shop_api_admin_token", 40)):
        path = SECRETS_DIR / name
        if path.exists():
            print(f"kept     {path.relative_to(ROOT).as_posix()}")
        else:
            path.write_text(random_secret(length), encoding="utf-8", newline="\n")
            print(f"created  {path.relative_to(ROOT).as_posix()}")

    env_file = COMPOSE_DIR / ".env"
    env_file.write_text("ALERTMANAGER_CONFIG_FILE=alertmanager.local.yml\n", encoding="utf-8", newline="\n")
    print(f"wrote    {env_file.relative_to(ROOT).as_posix()}")

    password = (SECRETS_DIR / "grafana_admin_password").read_text(encoding="utf-8").strip()
    print(f"""
Next:
  cd stack/compose
  docker compose up -d --build --wait

Then open http://localhost:3000   user: admin   password: {password}
Stop it later with:  docker compose down      (add -v to also delete the stored data)""")


if __name__ == "__main__":
    main()
