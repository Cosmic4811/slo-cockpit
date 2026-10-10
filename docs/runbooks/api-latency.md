# Runbook: api-latency

**SLO:** 99% of `/api/*` requests are answered in under 300 ms over 30 days.
**Error budget:** 1% = 432 "bad minutes" per 30 days.

## What the alert means

| Alert | Severity | Meaning |
|---|---|---|
| `ErrorBudgetBurnFast` | page | Too many slow requests: 14.4x (1h) or 6x (6h) the sustainable rate. |
| `ErrorBudgetBurnSlow` | ticket | Latency has been slightly too high for a day or more. |

## First 5 minutes

1. `python scripts/tunnel.py`, then **Service health (RED)** > "Duration: API latency percentiles".
   Is p95/p99 above the dashed 300 ms line? On every route or only one?
2. `python scripts/chaos.py status`: a `latency` drill adds delay on purpose.
3. **Server & stack** dashboard: is the CPU pinned, or is the server swapping heavily?
   A server that is out of memory (heavy swapping) gets slow.

## Mitigate

- Drill: `python scripts/chaos.py stop`.
- Out of memory: check "Memory by component" and restart the biggest container, or move to a
  `t3.small` (`instance_type = "t3.small"` in `terraform.tfvars`, then `terraform apply`).
