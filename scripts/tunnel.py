#!/usr/bin/env python3
"""Open private tunnels to the cockpit on AWS through SSM Session Manager (no open ports needed).

  python scripts/tunnel.py              Grafana, Prometheus, Alertmanager and shop-api on localhost
  python scripts/tunnel.py --password   print the Grafana admin password and exit

Keep this window open while you use the dashboards. Press Ctrl+C to close the tunnels.
Needs: AWS CLI v2, the Session Manager plugin, and a finished "terraform apply".
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TF_DIR = ROOT / "terraform"
PORTS = [  # (port on the server and on your computer, name, what to open)
    (3000, "Grafana", "http://localhost:3000/d/slo-cockpit"),
    (9090, "Prometheus", "http://localhost:9090/alerts"),
    (9093, "Alertmanager", "http://localhost:9093"),
    (8080, "shop-api", "used by scripts/chaos.py"),
]


def fail(message: str) -> None:
    print(f"\nERROR: {message}", file=sys.stderr)
    sys.exit(1)


def terraform_outputs() -> dict:
    """Read the values Terraform printed at the end of 'terraform apply'."""
    terraform = shutil.which("terraform") or fail("'terraform' is not installed or not on PATH.")
    result = subprocess.run([terraform, f"-chdir={TF_DIR}", "output", "-json"],
                            capture_output=True, text=True)
    if result.returncode != 0:
        fail(f"'terraform output' failed:\n{result.stderr.strip()}")
    outputs = {key: item["value"] for key, item in json.loads(result.stdout or "{}").items()}
    if "instance_id" not in outputs:
        fail("Terraform has no outputs yet. Run 'terraform apply' in the terraform folder first.")
    return outputs


def aws_args(outputs: dict) -> list[str]:
    """The AWS CLI program plus the region/profile Terraform used."""
    aws = shutil.which("aws") or fail("The AWS CLI ('aws') is not installed or not on PATH.")
    args = [aws, "--region", outputs["aws_region"]]
    if outputs.get("aws_profile"):
        args += ["--profile", outputs["aws_profile"]]
    return args


def aws_text(outputs: dict, *command: str) -> str:
    result = subprocess.run([*aws_args(outputs), *command, "--output", "text"],
                            capture_output=True, text=True)
    if result.returncode != 0:
        fail(f"AWS CLI error:\n{result.stderr.strip()}\n"
             "If it mentions expired credentials, run:  aws login --profile slo-login")
    return result.stdout.strip()


def ssm_parameter(outputs: dict, name: str) -> str:
    return aws_text(outputs, "ssm", "get-parameter", "--name", name, "--with-decryption",
                    "--query", "Parameter.Value")


def wait_for_ssm(outputs: dict) -> None:
    instance = outputs["instance_id"]
    print(f"Waiting for server {instance} to connect to Session Manager", end="", flush=True)
    for _ in range(60):  # up to 10 minutes
        status = aws_text(outputs, "ssm", "describe-instance-information",
                          "--filters", f"Key=InstanceIds,Values={instance}",
                          "--query", "InstanceInformationList[0].PingStatus")
        if status == "Online":
            print(" online.")
            return
        print(".", end="", flush=True)
        time.sleep(10)
    fail("The server never came online in Session Manager. See 'Troubleshooting' in the guide.")


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex(("127.0.0.1", port)) != 0


def open_tunnel(outputs: dict, port: int) -> subprocess.Popen:
    parameters = json.dumps({"portNumber": [str(port)], "localPortNumber": [str(port)]})
    return subprocess.Popen(
        [*aws_args(outputs), "ssm", "start-session", "--target", outputs["instance_id"],
         "--document-name", "AWS-StartPortForwardingSession", "--parameters", parameters],
        stdout=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
        # Own process group (macOS/Linux), so stop_tunnel() can also end the plugin it starts.
        start_new_session=(sys.platform != "win32"))


def stop_tunnel(process: subprocess.Popen) -> None:
    """Close one tunnel. 'aws' starts a separate session-manager-plugin process that keeps the
    port open, so stopping only 'aws' would leave the port busy: end the whole process tree."""
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True)
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


def grafana_ready() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:3000/api/health", timeout=5) as response:
            return response.status == 200
    except OSError:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Open SSM tunnels to the SLO cockpit")
    parser.add_argument("--password", action="store_true", help="print the Grafana admin password and exit")
    args = parser.parse_args()

    outputs = terraform_outputs()
    if args.password:
        print(ssm_parameter(outputs, outputs["grafana_password_parameter"]))
        return

    if not shutil.which("session-manager-plugin"):
        fail("The Session Manager plugin is not installed (or this terminal was opened before "
             "installing it - open a new one). See step 1 of the guide.")
    busy = [port for port, _name, _url in PORTS if not port_is_free(port)]
    if busy:
        fail(f"Port(s) {busy} are already in use on this computer. Usually one of these:\n"
             "  - A tunnel left over from an earlier run. Close it:\n"
             "      Windows:      Stop-Process -Name session-manager-plugin\n"
             "      macOS/Linux:  pkill -f session-manager-plugin\n"
             "  - The local Docker stack. Stop it: 'docker compose down' in stack/compose.\n"
             "Then run this script again.")

    wait_for_ssm(outputs)
    tunnels = {port: open_tunnel(outputs, port) for port, _name, _url in PORTS}
    try:
        print("Waiting for Grafana (the first boot takes about 5 minutes)", end="", flush=True)
        deadline = time.time() + 900
        while not grafana_ready():
            if time.time() > deadline:
                fail("Grafana did not answer within 15 minutes. See 'Troubleshooting' in the guide.")
            print(".", end="", flush=True)
            time.sleep(10)
        print(" ready!\n")
        for port, name, url in PORTS:
            print(f"  {name:<13} {url}")
        print("\n  Grafana login: admin / password:  python scripts/tunnel.py --password")
        print("  Press Ctrl+C to close the tunnels.\n")
        while True:  # re-open a tunnel if AWS closes it (e.g. after 20 idle minutes)
            time.sleep(5)
            for port, process in tunnels.items():
                if process.poll() is not None:
                    print(f"Tunnel for port {port} closed - reopening.")
                    stop_tunnel(process)  # make sure its plugin has let go of the port
                    tunnels[port] = open_tunnel(outputs, port)
    except KeyboardInterrupt:
        print("\nClosing tunnels...")
    finally:
        for process in tunnels.values():
            stop_tunnel(process)


if __name__ == "__main__":
    main()
