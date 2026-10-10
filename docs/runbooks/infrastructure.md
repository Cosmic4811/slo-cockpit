# Runbook: infrastructure alerts

These alerts are about *causes* (a component, the server), so they open tickets instead of
paging. Open the tunnel first: `python scripts/tunnel.py`.

To run commands on the server, open a shell through Session Manager (no SSH):
`aws ssm start-session --target <instance_id> --profile slo --region <region>`
(`terraform output instance_id` prints the ID), then `cd /opt/slo-cockpit/compose`.

## TargetDown

Prometheus cannot scrape a component. Check it with `sudo docker compose ps`, read its logs
with `sudo docker compose logs --tail 50 <service>`, restart it with `sudo docker compose restart <service>`.

## HostMemoryPressure

Less than 10% RAM free and swap more than half used. Open **Server & stack** >
"Memory by component" to find the biggest user and restart it. If it keeps happening,
use a bigger server: `instance_type = "t3.small"` in `terraform.tfvars`, then `terraform apply`.

## HostDiskFillingUp

The disk is more than 85% full. Clean unused Docker data with `sudo docker system prune -f`,
or increase `root_volume_gb` in `terraform.tfvars` and run `terraform apply` (creates a new server).

## AlertDeliveryFailing

Alertmanager cannot publish to SNS, so alert e-mails are not arriving. Check:
1. Did you click "Confirm subscription" in the e-mail from AWS?
2. `sudo docker compose logs --tail 50 alertmanager` - look for `AccessDenied` or `credentials`.
3. `systemctl status imds-guard` - the firewall must allow Alertmanager (10.200.0.10).

## PrometheusRuleFailures

Some recording or alerting rules fail to evaluate, so SLO numbers may be missing.
Open `http://localhost:9090/rules` - the failing rule shows its error. Usually a typo in
`slos/slos.yaml`: fix it, run `python tools/slo_generator.py`, then `terraform apply`.
