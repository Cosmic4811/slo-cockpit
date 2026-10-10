#!/usr/bin/env python3
"""Project checker: finds missing, misnamed or mistyped files before they cause trouble.

Run it from the project folder at the end of each part:
  python scripts/check_project.py 4      checks everything up to the end of Part 4
  python scripts/check_project.py        checks the whole project (Part 7)

It compares every file you created with the guide's copy (ignoring spaces at line ends
and your GitHub username), so a missing line or a bad paste is found at once.
"""

import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Fingerprint of every file as it appears in the guide, by the part that creates it.
GUIDE_FILES = [
    (2, "2.2", ".vscode/settings.json", "fd022b98490e17f7"),
    (2, "2.2", ".gitattributes", "adf9f6ce6fc27da9"),
    (2, "2.2", ".editorconfig", "3e1fc03bb2b3cc6a"),
    (2, "2.2", ".gitignore", "d109e457adb22e19"),
    (2, "2.3", "stack/demo-app/requirements.txt", "3d7cc36828b480a9"),
    (2, "2.3", "stack/demo-app/app.py", "acd4b8f4ebd6d592"),
    (2, "2.4", "stack/demo-app/loadgen.py", "4c2cb03c7eccf28e"),
    (2, "2.4", "stack/demo-app/Dockerfile", "aa986c42feb0d2f0"),
    (2, "2.4", "stack/demo-app/.dockerignore", "2e47fd7e37607894"),
    (3, "3.2", "slos/slos.yaml", "4712038a765fd910"),
    (3, "3.3", "tools/requirements.txt", "b68ef5d2c3ac74e8"),
    (3, "3.3", "tools/slo_generator.py", "f0ca0bb7e3db2c7d"),
    (3, "3.4", "tests/sli-recording.test.yml", "1e48137e10658319"),
    (4, "4.1", "stack/compose/prometheus/prometheus.yml", "db8ab9aeaa0d0668"),
    (4, "4.1", "stack/compose/prometheus/rules/infra-alerts.rules.yml", "6a9c25915c91eff2"),
    (4, "4.2", "stack/compose/alertmanager/alertmanager.local.yml", "7e198584702b08ff"),
    (4, "4.2", "stack/compose/alertmanager/templates/sns.tmpl", "222f021307e3df0f"),
    (4, "4.3", "stack/compose/blackbox/blackbox.yml", "75bc0cec05530961"),
    (4, "4.3", "stack/compose/loki/loki.yml", "e6171f90bb503e73"),
    (4, "4.3", "stack/compose/alloy/config.alloy", "4c16721dbe42b2b1"),
    (4, "4.4", "stack/compose/grafana/provisioning/datasources/datasources.yml", "15a914d9c63f8d08"),
    (4, "4.4", "stack/compose/grafana/provisioning/dashboards/dashboards.yml", "d52b59e435638c15"),
    (4, "4.4", "tools/dashboards.py", "b1f5b5840200fcba"),
    (4, "4.5", "stack/compose/docker-compose.yml", "56b5f669c4e72d50"),
    (4, "4.6", "scripts/local_setup.py", "b54048f6d8d67196"),
    (4, "4.6", "scripts/tunnel.py", "cf5222827dfa34e2"),
    (4, "4.6", "scripts/chaos.py", "a95b44717fafe413"),
    (6, "6.1", "stack/ansible/ansible.cfg", "c68a5d0e7713cdee"),
    (6, "6.1", "stack/ansible/site.yml", "a9ce25249a5418d1"),
    (6, "6.1", "stack/ansible/roles/base/tasks/main.yml", "64654d65b7c34f9d"),
    (6, "6.1", "stack/ansible/roles/base/handlers/main.yml", "1dffbaea0db96af0"),
    (6, "6.2", "stack/ansible/roles/docker/tasks/main.yml", "c59159bb3d22b72f"),
    (6, "6.2", "stack/ansible/roles/docker/handlers/main.yml", "8a8b1c05377d9391"),
    (6, "6.3", "stack/ansible/roles/stack/tasks/main.yml", "981d5539e41ffaa7"),
    (6, "6.3", "stack/ansible/roles/stack/templates/alertmanager.yml.j2", "1d6b7aa0b17d7afe"),
    (6, "6.4", "terraform/versions.tf", "38876bb388104162"),
    (6, "6.4", "terraform/variables.tf", "66f4d12c6557bcd7"),
    (6, "6.4", "terraform/data.tf", "a3ca04b7aa485308"),
    (6, "6.5", "terraform/storage.tf", "5a319868899dfabd"),
    (6, "6.5", "terraform/iam.tf", "beafe144c4f32efc"),
    (6, "6.5", "terraform/alerts.tf", "fd91f6535f158487"),
    (6, "6.5", "terraform/secrets.tf", "2d8d2953521e2b6e"),
    (6, "6.6", "terraform/compute.tf", "f6c868bc6d3b6758"),
    (6, "6.6", "terraform/outputs.tf", "a33daf6b192b76a5"),
    (6, "6.6", "terraform/user_data.sh.tftpl", "b0c29171f026ff0d"),
    (6, "6.6", "terraform/files/slo-deploy.sh", "befb5e024be91c18"),
    (6, "6.7", "terraform/tests/security.tftest.hcl", "26ddaaddd0591943"),
    (6, "6.7", "terraform/terraform.tfvars.example", "3cfbb505fbfa9712"),
    (7, "7.1", "README.md", "62dbcb15d82a1106"),
    (7, "7.1", "docs/runbooks/checkout-availability.md", "ee0334b90f3e1ca4"),
    (7, "7.1", "docs/runbooks/api-latency.md", "0f1ef17ccd7c9c46"),
    (7, "7.1", "docs/runbooks/synthetic-availability.md", "5afe4df321530be8"),
    (7, "7.1", "docs/runbooks/infrastructure.md", "86ea815afb187501"),
    (7, "7.2", ".github/workflows/validate.yml", "b16be6d269c74c0d"),
    (7, "7.2", ".github/dependabot.yml", "efe2c3253d96a20f"),
    (7, "7.2", ".trivyignore", "ed964462c6451649"),
]

# Files written by a command instead of by hand: (part, file, command that writes it).
GENERATED = [
    (3, "stack/compose/prometheus/rules/slo-recording.rules.yml", "python tools/slo_generator.py"),
    (3, "stack/compose/prometheus/rules/slo-alerts.rules.yml", "python tools/slo_generator.py"),
    (3, "tests/slo-alerts.test.yml", "python tools/slo_generator.py"),
    (4, "stack/compose/grafana/dashboards/slo-cockpit.json", "python tools/dashboards.py"),
    (4, "stack/compose/grafana/dashboards/service-red.json", "python tools/dashboards.py"),
    (4, "stack/compose/grafana/dashboards/host.json", "python tools/dashboards.py"),
]
EMPTY_FILES = [
    (4, "stack/compose/grafana/provisioning/plugins/.gitkeep"),
    (4, "stack/compose/grafana/provisioning/alerting/.gitkeep"),
]
# Written in two halves, so a "replace in all files" of the placeholder cannot change this script.
PLACEHOLDER = "YOUR_GITHUB" + "_USER"
USERNAME_FILES = ["slos/slos.yaml", "stack/compose/prometheus/rules/infra-alerts.rules.yml"]
USERNAME_IN_URL = re.compile(r"github\.com/[A-Za-z0-9_-]+/slo-cockpit")


def fingerprint(raw: bytes) -> str:
    """The same fingerprint the guide's copy has, whatever your editor did to spaces and line ends."""
    text = raw.decode("utf-8-sig").replace("\r\n", "\n")
    text = USERNAME_IN_URL.sub("github.com/" + PLACEHOLDER + "/slo-cockpit", text)
    lines = [line.rstrip() for line in text.split("\n")]
    return hashlib.sha256("\n".join(lines).strip("\n").encode("utf-8")).hexdigest()[:16]


def find(relative: str):
    """Return (path, problem). Spots a folder or file whose name differs only in capitals."""
    here = ROOT
    for part in relative.split("/"):
        exact = here / part
        names = {p.name: p for p in here.iterdir()} if here.is_dir() else {}
        if part in names:
            here = exact
            continue
        twins = [name for name in names if name.lower() == part.lower()]
        if twins:
            return None, f"WRONG NAME: '{twins[0]}' must be spelled '{part}' (capitals matter on the server)"
        return None, "MISSING: create it (the step is shown below)"
    return here, None


def main() -> int:
    try:
        upto = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    except ValueError:
        upto = 0
    if not 1 <= upto <= 7:
        print("Give the number of the part you just finished, from 1 to 7. Example: python scripts/check_project.py 4")
        return 2

    problems = []

    def report(name, message, step=""):
        problems.append(f"  {name}\n      {message}" + (f"\n      See step {step} in the guide." if step else ""))

    for part, step, name, expected in GUIDE_FILES:
        if part > upto:
            continue
        path, problem = find(name)
        if problem:
            report(name, problem, step)
            continue
        raw = path.read_bytes()
        if b"\r\n" in raw:
            report(name, "WINDOWS LINE ENDINGS: open it in VS Code, click 'CRLF' at the bottom right, "
                         "choose 'LF', then save (Ctrl+S).", step)
        if fingerprint(raw) != expected:
            if not raw.strip():
                report(name, "EMPTY: paste the code into it and save (Ctrl+S).", step)
            else:
                report(name, "DIFFERENT FROM THE GUIDE: select everything in the file (Ctrl+A), delete it, "
                             "click Copy on the guide's code block, paste and save.", step)

    for part, name in EMPTY_FILES:
        if part <= upto:
            _path, problem = find(name)
            if problem:
                report(name, problem + " (an empty file)", "4.4")

    for name in USERNAME_FILES:
        path, problem = find(name)
        if not problem and PLACEHOLDER.encode() in path.read_bytes():
            report(name, f"YOUR VALUE: replace {PLACEHOLDER} with your GitHub username (Ctrl+H in VS Code).")

    for part, name, command in GENERATED:
        if part <= upto:
            _path, problem = find(name)
            if problem:
                report(name, f"MISSING: run  {command}  (it writes this file for you).")
    if upto >= 3 and not any("MISSING" in p and "tools/" in p for p in problems):
        for tool in ("tools/slo_generator.py", "tools/dashboards.py")[: 1 if upto == 3 else 2]:
            result = subprocess.run([sys.executable, tool, "--check"], cwd=ROOT, capture_output=True, text=True)
            if result.returncode != 0:
                first = (result.stderr or result.stdout).strip().splitlines()
                report(tool, f"OUT OF DATE: run  python {tool}  again. ({first[0] if first else 'no details'})")

    if upto >= 6:
        tfvars, problem = find("terraform/terraform.tfvars")
        if problem:
            report("terraform/terraform.tfvars", "MISSING: copy it from terraform.tfvars.example.", "6.7")
        elif b"you@example.com" in tfvars.read_bytes():
            report("terraform/terraform.tfvars", "YOUR VALUE: put your own e-mail address in alert_email.", "6.7")

    if problems:
        print(f"Found {len(problems)} problem(s) in Parts 1 to {upto}:\n")
        print("\n".join(problems))
        print("\nFix them, save, and run this check again.")
        return 1
    print(f"All checks passed for Parts 1 to {upto}. You can move on.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
