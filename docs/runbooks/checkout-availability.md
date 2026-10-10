# Runbook: checkout-availability

**SLO:** 99.5% of `POST /api/checkout` requests succeed (no 5xx) over 30 days.
**Error budget:** 0.5% = 216 "bad minutes" per 30 days.

## What the alert means

| Alert | Severity | Meaning |
|---|---|---|
| `ErrorBudgetBurnFast` | page | Budget burning at 14.4x (1h) or 6x (6h). At this pace it is gone in about 2-5 days. Act now. |
| `ErrorBudgetBurnSlow` | ticket | Budget burning at 3x (1d) or 1x (3d). Not urgent, but it will run out. Fix this week. |

## First 5 minutes

1. Open the tunnel: `python scripts/tunnel.py`, then the **SLO Cockpit** dashboard
   (`http://localhost:3000/d/slo-cockpit?var-slo=checkout-availability`).
2. Is a fault injection running? Look for red shaded areas on the graphs, or run
   `python scripts/chaos.py status`. If it is a drill, `python scripts/chaos.py stop` ends it.
3. Open **Service health (RED)**: are the errors only on `/api/checkout`, or on every route?
4. In the **Error logs** panel (or Grafana Explore > Loki), run:
   `{service="shop-api"} | json | level="error"` and read the `msg` field.

## Mitigate

- Every route failing: check that the `shop-api` container is healthy
  (`sudo docker compose -f /opt/slo-cockpit/compose/docker-compose.yml ps` in an SSM session).
  Restart it with `... restart shop-api`.
- A planned maintenance or a drill: create a **silence** in Alertmanager
  (`http://localhost:9093` > New Silence > matcher `slo="checkout-availability"`) so nobody gets paged for it.

## Afterwards

Write down what happened, how much budget it used (the "Bad minutes" panel) and one
thing that would prevent it next time. That is a postmortem.
