#!/usr/bin/env python3
"""Burn error budget on purpose (fault injection), to demo the SLO alerts.

  python scripts/chaos.py outage  [--minutes 10]               every /api/ request fails (503)
  python scripts/chaos.py errors  [--rate 0.3] [--minutes 20]  30% of checkouts fail
  python scripts/chaos.py latency [--ms 600] [--rate 0.5] [--minutes 15]
  python scripts/chaos.py status
  python scripts/chaos.py stop

Add --local when the stack runs on your computer (Docker Desktop).
On AWS, keep "python scripts/tunnel.py" running in another terminal.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import tunnel  # helpers shared with scripts/tunnel.py (same folder)

ROOT = Path(__file__).resolve().parent.parent
LOCAL_TOKEN = ROOT / "stack" / "compose" / "secrets" / "shop_api_admin_token"
ADMIN_URL = "http://127.0.0.1:8080/admin/fault"


def admin_token(local: bool) -> str:
    if local:
        if not LOCAL_TOKEN.exists():
            tunnel.fail("No local token. Run: python scripts/local_setup.py")
        return LOCAL_TOKEN.read_text(encoding="utf-8").strip()
    outputs = tunnel.terraform_outputs()
    return tunnel.ssm_parameter(outputs, outputs["admin_token_parameter"])


def call(method: str, token: str, body: dict | None = None) -> dict:
    request = urllib.request.Request(
        ADMIN_URL, method=method, data=json.dumps(body).encode() if body else None,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as err:
        tunnel.fail(f"shop-api answered {err.code}: {err.read().decode(errors='replace')}")
    except OSError:
        tunnel.fail("Cannot reach shop-api on localhost:8080. On AWS: is 'python scripts/tunnel.py' "
                    "running? Locally: is the stack up ('docker compose ps' in stack/compose)?")
    return {}


def main() -> None:
    parser = argparse.ArgumentParser(description="Inject faults into shop-api")
    parser.add_argument("--local", action="store_true", help="the stack runs on this computer")
    sub = parser.add_subparsers(dest="command", required=True)
    outage = sub.add_parser("outage", help="every /api/ request fails")
    outage.add_argument("--minutes", type=float, default=10)
    errors = sub.add_parser("errors", help="a share of requests fail")
    errors.add_argument("--rate", type=float, default=0.3, help="0.3 = 30%% of requests fail")
    errors.add_argument("--route", default="/api/checkout", help="which requests (prefix, starts with /api/)")
    errors.add_argument("--minutes", type=float, default=20)
    latency = sub.add_parser("latency", help="a share of requests become slow")
    latency.add_argument("--ms", type=float, default=600, help="extra delay in milliseconds")
    latency.add_argument("--rate", type=float, default=0.5, help="0.5 = half of the requests")
    latency.add_argument("--minutes", type=float, default=15)
    sub.add_parser("status", help="show the current fault")
    sub.add_parser("stop", help="stop the current fault")
    args = parser.parse_args()

    token = admin_token(args.local)
    if args.command == "status":
        result = call("GET", token)
    elif args.command == "stop":
        result = call("DELETE", token)
    else:
        body = {"duration_seconds": int(args.minutes * 60)}
        if args.command == "outage":
            body.update(error_rate=1.0, route_prefix="/api/")
        elif args.command == "errors":
            body.update(error_rate=args.rate, route_prefix=args.route)
        else:
            body.update(latency_ms=args.ms, latency_rate=args.rate, route_prefix="/api/")
        result = call("POST", token, body)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
