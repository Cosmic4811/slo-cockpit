# Runbook: synthetic-availability

**SLO:** 99.9% of black-box probes of `GET /api/items` succeed over 30 days.
**Error budget:** 0.1% = 43.2 "bad minutes" per 30 days.

This SLO is measured from the *outside* by blackbox_exporter, every 15 seconds, like a user
would. It catches problems the app cannot report itself (the app is down, hung, or unreachable).

## First 5 minutes

1. `python scripts/tunnel.py`, then **Service health (RED)** > "Black-box probes OK".
2. Prometheus > Status > Targets (`http://localhost:9090/targets`): is `shop-api` down?
   Then the app is not running at all - check `docker compose ps` on the server.
3. If only the probes fail but the app's own metrics look fine, the problem is between the
   two (network, DNS inside Docker) - check the `blackbox` container logs in Grafana Explore:
   `{service="blackbox"}`.

## Mitigate

- Restart `shop-api` (see the checkout runbook), or `python scripts/chaos.py stop` if it is a drill.
