#!/usr/bin/env python3
"""Dashboards as code: builds the Grafana dashboard JSON files from compact Python.

Usage (works from any folder):
  python tools/dashboards.py           write stack/compose/grafana/dashboards/*.json
  python tools/dashboards.py --check   only check that the JSON files are up to date (used by CI)

Grafana loads the JSON files at start-up (see grafana/provisioning/dashboards/dashboards.yml).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "stack" / "compose" / "grafana" / "dashboards"
PROM = {"type": "prometheus", "uid": "prometheus"}
LOKI = {"type": "loki", "uid": "loki"}


# ------------------------------------------------------------------ building blocks
def steps(*pairs) -> dict:
    """steps(("green", None), ("red", 0.9)) -> Grafana thresholds (None = minus infinity)."""
    return {"mode": "absolute", "steps": [{"color": c, "value": v} for c, v in pairs]}


def q(expr: str, legend: str = "", instant: bool = False, table: bool = False) -> dict:
    """One Prometheus query."""
    target = {"datasource": PROM, "expr": expr, "legendFormat": legend or "__auto",
              "range": not instant, "instant": instant}
    if table:
        target["format"] = "table"
    return target


def panel(kind: str, title: str, queries: list, unit: str = "none", *, description: str = "",
          thresholds: dict | None = None, options: dict | None = None, custom: dict | None = None,
          extra_defaults: dict | None = None, datasource: dict = PROM, **extra) -> dict:
    defaults = {"unit": unit, "thresholds": thresholds or steps(("green", None))}
    defaults["color"] = {"mode": "thresholds"} if thresholds else {"mode": "palette-classic"}
    if custom:
        defaults["custom"] = custom
    defaults.update(extra_defaults or {})
    for index, target in enumerate(queries):
        target["refId"] = chr(ord("A") + index)
    return {"type": kind, "title": title, "description": description, "datasource": datasource,
            "targets": queries, "fieldConfig": {"defaults": defaults, "overrides": []},
            "options": options or {}, **extra}


REDUCE_LAST = {"values": False, "calcs": ["lastNotNull"], "fields": ""}


def stat(title, queries, unit, *, thresholds=None, decimals=None, description="", color=None):
    extra = {} if decimals is None else {"decimals": decimals}
    if color:
        extra["color"] = {"mode": "fixed", "fixedColor": color}
    return panel("stat", title, queries, unit, description=description, thresholds=thresholds,
                 extra_defaults=extra,
                 options={"reduceOptions": REDUCE_LAST, "colorMode": "value", "graphMode": "none",
                          "textMode": "value_and_name" if len(queries) > 1 else "value",
                          "justifyMode": "center", "orientation": "auto", "wideLayout": True})


def bargauge(title, queries, unit, *, thresholds, low, high, description=""):
    return panel("bargauge", title, queries, unit, description=description, thresholds=thresholds,
                 extra_defaults={"min": low, "max": high, "decimals": 1},
                 options={"reduceOptions": REDUCE_LAST, "orientation": "horizontal",
                          "displayMode": "gradient", "valueMode": "color", "showUnfilled": True})


def timeseries(title, queries, unit, *, thresholds=None, description="", low=None, high=None):
    custom = {"lineWidth": 2, "fillOpacity": 10, "showPoints": "never", "spanNulls": False,
              "thresholdsStyle": {"mode": "dashed" if thresholds else "off"}}
    extra = {k: v for k, v in (("min", low), ("max", high)) if v is not None}
    result = panel("timeseries", title, queries, unit, description=description, custom=custom,
                   thresholds=thresholds, extra_defaults=extra,
                   options={"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
                            "tooltip": {"mode": "multi", "sort": "desc"}})
    result["fieldConfig"]["defaults"]["color"] = {"mode": "palette-classic"}
    return result


def table(title, queries, *, hide=(), rename=None, description="", no_value="None"):
    organize = {"excludeByName": {name: True for name in ("Time", "__name__", *hide)},
                "renameByName": rename or {}}
    return panel("table", title, queries, description=description,
                 extra_defaults={"noValue": no_value},
                 options={"showHeader": True, "cellHeight": "sm"},
                 transformations=[{"id": "organize", "options": organize}])


def logs(title, expr, description=""):
    return {"type": "logs", "title": title, "description": description, "datasource": LOKI,
            "targets": [{"refId": "A", "datasource": LOKI, "expr": expr, "queryType": "range"}],
            "options": {"showTime": True, "wrapLogMessage": True, "sortOrder": "Descending",
                        "enableLogDetails": True, "dedupStrategy": "none"}}


def text(title, markdown):
    return {"type": "text", "title": title, "options": {"mode": "markdown", "content": markdown}}


def place(rows: list[list[tuple[dict, int, int]]]) -> list[dict]:
    """Lay panels out on Grafana's 24-column grid, row by row: [(panel, width, height), ...]."""
    panels, y = [], 0
    for row in rows:
        x = 0
        for item, width, height in row:
            item["id"] = len(panels) + 1
            item["gridPos"] = {"x": x, "y": y, "w": width, "h": height}
            panels.append(item)
            x += width
        if x > 24:
            raise ValueError(f"row starting with '{row[0][0]['title']}' is wider than 24 columns")
        y += max(height for _item, _width, height in row)
    return panels


def dashboard(uid, title, rows, *, description="", variables=(), annotations=(),
              time_from="now-3h", refresh="30s") -> dict:
    return {
        "uid": uid, "title": title, "description": description, "tags": ["slo-cockpit"],
        "editable": False, "graphTooltip": 1, "schemaVersion": 41, "version": 1,
        "time": {"from": time_from, "to": "now"}, "refresh": refresh, "timezone": "browser",
        "templating": {"list": list(variables)},
        "annotations": {"list": [
            {"builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"}, "enable": True,
             "hide": True, "iconColor": "rgba(0, 211, 255, 1)", "name": "Annotations & Alerts",
             "type": "dashboard"},
            *annotations]},
        "panels": place(rows),
    }


def query_variable(name, label, query, hide=0):
    return {"type": "query", "name": name, "label": label, "datasource": PROM, "query": query,
            "definition": query, "refresh": 2, "sort": 1, "includeAll": False, "multi": False,
            "hide": hide, "current": {}, "options": []}


FAULT_ANNOTATION = {
    "name": "Fault injection", "datasource": PROM, "enable": True, "iconColor": "red",
    "expr": "max(demo_fault_active) > 0", "step": "30s", "titleFormat": "Fault injection running",
}

# Burn-rate colours: 1x = spending exactly the budget; 6x / 14.4x = the paging thresholds.
BURN = steps(("green", None), ("yellow", 1), ("orange", 6), ("red", 14.4))
BUDGET = steps(("red", None), ("orange", 0), ("yellow", 0.25), ("green", 0.5))
SEL = 'slo="$slo"'


# ------------------------------------------------------------------ 1. SLO cockpit
def slo_cockpit() -> dict:
    burn = "slo:sli_error:ratio_rate{w}{{{sel}}} / on(slo, service) slo:error_budget:ratio{{{sel}}}"
    intro = text("How to read this dashboard", (
        "**Error budget** = how much failure the SLO allows per 30 days (e.g. 99.5% leaves 0.5%, "
        "about 216 *bad minutes*). **Burn rate** = how fast it is being spent: **1x** uses exactly "
        "the whole budget in 30 days, **14.4x** would use it all in about 2 days and **pages** someone. "
        "Red shaded areas mark fault injections from `scripts/chaos.py`."))
    return dashboard(
        "slo-cockpit", "SLO Cockpit",
        description="Error budgets and burn rates for every SLO defined in slos/slos.yaml",
        variables=[
            query_variable("slo", "SLO", "label_values(slo:objective:ratio, slo)"),
            query_variable("service", "Service", 'label_values(slo:objective:ratio{slo="$slo"}, service)', hide=2),
        ],
        annotations=[FAULT_ANNOTATION],
        rows=[
            [(intro, 24, 3)],
            [(bargauge("Error budget remaining - all SLOs", [q("slo:error_budget_remaining:ratio", "{{slo}}")],
                       "percentunit", thresholds=BUDGET, low=0, high=1,
                       description="Share of this period's error budget still unspent."), 12, 7),
             (bargauge("Burn rate over the last hour - all SLOs",
                       [q("slo:sli_error:ratio_rate1h / on(slo, service) slo:error_budget:ratio", "{{slo}}")],
                       "suffix:x", thresholds=BURN, low=0, high=20,
                       description="1x = on budget. 14.4x sustained for 1h pages."), 12, 7)],
            [(table("Firing alerts", [q('ALERTS{alertstate="firing"}', instant=True, table=True)],
                    hide=("alertstate", "Value"), no_value="No alerts firing",
                    description="Alerts Prometheus is currently firing (they go to Alertmanager, then e-mail)."), 24, 5)],
            [(stat("Objective", [q(f"slo:objective:ratio{{{SEL}}}")], "percentunit",
                   decimals=2, color="blue"), 4, 5),
             (stat("Availability this period", [q(f"1 - slo:sli_error:ratio_period{{{SEL}}}")], "percentunit",
                   decimals=3, color="blue",
                   description="Average SLI over the period so far (since the stack started if younger)."), 5, 5),
             (stat("Error budget remaining", [q(f"slo:error_budget_remaining:ratio{{{SEL}}}")],
                   "percentunit", decimals=1, thresholds=BUDGET), 5, 5),
             (stat("Bad minutes", [q(f"slo:error_budget_consumed:minutes{{{SEL}}}", "used"),
                                   q(f"slo:error_budget:minutes{{{SEL}}}", "allowed")],
                   "m", decimals=1, color="purple",
                   description="1 bad minute = 1 minute at 100% errors (or 2 minutes at 50%, ...)."), 5, 5),
             (stat("Burn rate now", [q(burn.format(w="5m", sel=SEL), "5m"), q(burn.format(w="1h", sel=SEL), "1h")],
                   "suffix:x", decimals=1, thresholds=BURN), 5, 5)],
            [(timeseries("Burn rate ($slo)",
                         [q(burn.format(w=w, sel=SEL), f"{w} window") for w in ("5m", "1h", "6h")],
                         "suffix:x", thresholds=BURN, low=0,
                         description="Dashed lines: 1x (on budget), 6x and 14.4x (paging thresholds)."), 12, 8),
             (timeseries("Error budget remaining ($slo)",
                         [q(f"slo:error_budget_remaining:ratio{{{SEL}}}", "remaining")], "percentunit",
                         high=1), 12, 8)],
            [(timeseries("SLI error ratio vs. error budget ($slo)",
                         [q(f"slo:sli_error:ratio_rate5m{{{SEL}}}", "error ratio (5m)"),
                          q(f"slo:sli_error:ratio_rate1h{{{SEL}}}", "error ratio (1h)"),
                          q(f"slo:error_budget:ratio{{{SEL}}}", "allowed (budget)")],
                         "percentunit", low=0), 12, 8),
             (logs("Error logs ($service)", '{service="$service"} | json | level="error"',
                   description="Structured JSON logs collected by Alloy and stored in Loki."), 12, 8)],
        ],
    )


# ------------------------------------------------------------------ 2. service health (RED)
def service_red() -> dict:
    job = 'job="shop-api"'
    api = f'{job}, route=~"/api/.+"'
    return dashboard(
        "service-red", "Service health (RED)", time_from="now-1h",
        description="Rate, Errors, Duration for shop-api, plus black-box probes and logs",
        annotations=[FAULT_ANNOTATION],
        rows=[
            [(stat("Requests / second", [q(f'sum(rate(http_requests_total{{{job}, route!="/healthz"}}[5m]))')],
                   "reqps", decimals=1, color="blue"), 6, 4),
             (stat("Errors (5xx)", [q(f'sum(rate(http_requests_total{{{job}, code=~"5.."}}[5m])) '
                                      f'/ sum(rate(http_requests_total{{{job}}}[5m]))')],
                   "percentunit", decimals=2, thresholds=steps(("green", None), ("orange", 0.005), ("red", 0.05))), 6, 4),
             (stat("p95 latency (API)", [q(f"histogram_quantile(0.95, sum by (le) "
                                           f"(rate(http_request_duration_seconds_bucket{{{api}}}[5m])))")],
                   "s", decimals=3, thresholds=steps(("green", None), ("orange", 0.3), ("red", 1))), 6, 4),
             (stat("Black-box probes OK (5m)", [q('avg(avg_over_time(probe_success{job="blackbox-http"}[5m]))')],
                   "percentunit", decimals=1, thresholds=steps(("red", None), ("orange", 0.99), ("green", 0.999))), 6, 4)],
            [(timeseries("Rate: requests / second by route",
                         [q(f'sum by (route) (rate(http_requests_total{{{job}, route!="/healthz"}}[1m]))', "{{route}}")],
                         "reqps", low=0), 12, 8),
             (timeseries("Errors: 5xx responses / second",
                         [q(f'sum by (route, code) (rate(http_requests_total{{{job}, code=~"5.."}}[1m]))',
                            "{{route}} {{code}}")], "reqps", low=0), 12, 8)],
            [(timeseries("Duration: API latency percentiles",
                         [q(f"histogram_quantile({p}, sum by (le) (rate(http_request_duration_seconds_bucket{{{api}}}[1m])))",
                            f"p{int(p * 100)}") for p in (0.5, 0.95, 0.99)],
                         "s", low=0, thresholds=steps(("green", None), ("red", 0.3)),
                         description="Dashed line: the 300 ms latency SLO threshold."), 12, 8),
             (timeseries("Black-box probe: duration",
                         [q('probe_duration_seconds{job="blackbox-http"}', "{{instance}}")], "s", low=0), 12, 8)],
            [(logs("shop-api logs", '{service="shop-api"}'), 24, 10)],
        ],
    )


# ------------------------------------------------------------------ 3. server + stack
def host() -> dict:
    root_fs = 'mountpoint="/"'
    return dashboard(
        "host", "Server & stack", refresh="1m",
        description="The EC2 server (node_exporter) and the monitoring stack itself",
        rows=[
            [(stat("CPU busy", [q('1 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m]))')], "percentunit",
                   decimals=1, thresholds=steps(("green", None), ("orange", 0.2), ("red", 0.8)),
                   description="A t3.micro can use 20% CPU all the time for free; above that it spends CPU credits."), 4, 4),
             (stat("Memory used", [q("1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes")],
                   "percentunit", decimals=1, thresholds=steps(("green", None), ("orange", 0.8), ("red", 0.9))), 4, 4),
             (stat("Swap used", [q("node_memory_SwapTotal_bytes - node_memory_SwapFree_bytes")], "bytes",
                   decimals=0, thresholds=steps(("green", None), ("orange", 512 * 1024 ** 2), ("red", 1536 * 1024 ** 2))), 4, 4),
             (stat("Disk used", [q(f"1 - node_filesystem_avail_bytes{{{root_fs}}} / node_filesystem_size_bytes{{{root_fs}}}")],
                   "percentunit", decimals=1, thresholds=steps(("green", None), ("orange", 0.7), ("red", 0.85))), 4, 4),
             (stat("Active time series", [q("prometheus_tsdb_head_series")], "short", decimals=0, color="purple",
                   description="Cardinality: every unique metric + label combination is one series held in memory."), 4, 4),
             (stat("Scrape targets up", [q("count(up == 1)", "up"), q("count(up)", "total")], "short",
                   decimals=0, color="blue"), 4, 4)],
            [(timeseries("Memory by component (RSS)", [q("process_resident_memory_bytes", "{{job}}")], "bytes", low=0,
                         description="How the 1 GB of RAM is shared between the containers."), 12, 8),
             (timeseries("Server memory", [
                 q("node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes", "used"),
                 q("node_memory_MemAvailable_bytes", "available"),
                 q("node_memory_SwapTotal_bytes - node_memory_SwapFree_bytes", "swap used")], "bytes", low=0), 12, 8)],
            [(timeseries("CPU by mode", [q('sum by (mode) (rate(node_cpu_seconds_total{mode!="idle"}[1m])) '
                                          '/ scalar(count(node_cpu_seconds_total{mode="idle"}))', "{{mode}}")],
                         "percentunit", low=0), 12, 8),
             (timeseries("Logs received by Loki", [q("sum(rate(loki_distributor_lines_received_total[5m]))", "lines / s")],
                         "short", low=0), 12, 8)],
            [(table("Scrape targets", [q("up", instant=True, table=True)], rename={"Value": "up (1 = OK)"}), 12, 8),
             (table("Top 10 metrics by number of series (cardinality)",
                    [q('topk(10, count by (__name__) ({__name__=~".+"}))', instant=True, table=True)],
                    rename={"__name__": "metric", "Value": "series"}), 12, 8)],
        ],
    )


def build() -> dict[Path, str]:
    boards = {"slo-cockpit.json": slo_cockpit(), "service-red.json": service_red(), "host.json": host()}
    return {OUT_DIR / name: json.dumps(board, indent=2) + "\n" for name, board in boards.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Grafana dashboards")
    parser.add_argument("--check", action="store_true", help="exit 1 if the JSON files are out of date")
    args = parser.parse_args(argv)
    outputs = build()
    if args.check:
        stale = [p for p, text in outputs.items() if not p.exists() or p.read_text(encoding="utf-8") != text]
        for path in stale:
            print(f"OUT OF DATE: {path.relative_to(ROOT).as_posix()}", file=sys.stderr)
        if stale:
            print("Run:  python tools/dashboards.py", file=sys.stderr)
            return 1
        print("Dashboards are up to date.")
        return 0
    for path, text_ in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text_, encoding="utf-8", newline="\n")
        print(f"wrote {path.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
