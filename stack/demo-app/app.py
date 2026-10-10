"""shop-api: a tiny demo shop backend, instrumented for SLOs.

- RED metrics (Rate, Errors, Duration) for Prometheus at /metrics
- one structured JSON log line per request on stdout (collected by Grafana Alloy into Loki)
- a token-protected /admin/fault endpoint that scripts/chaos.py uses to burn error budget on demand
"""

import hmac
import json
import logging
import os
import random
import re
import sys
import threading
import time
import uuid
from datetime import datetime, timezone

from flask import Flask, Response, g, jsonify, request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from werkzeug.exceptions import HTTPException

SERVICE = "shop-api"

# ---------------------------------------------------------------- metrics (RED)
REQUESTS = Counter(
    "http_requests_total", "HTTP requests handled, by route and status code.",
    ["method", "route", "code"])
LATENCY = Histogram(
    "http_request_duration_seconds", "Time spent handling HTTP requests.",
    ["method", "route"],
    # 0.3 is the latency SLO threshold, so it must be one of the bucket boundaries.
    buckets=(0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0, 2.5, 5.0))
FAULT_ACTIVE = Gauge("demo_fault_active", "1 while a fault injection is running, else 0.")


# ---------------------------------------------------------------- JSON logging
class JsonFormatter(logging.Formatter):
    def format(self, record):
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "service": SERVICE,
            "msg": record.getMessage(),
        }
        entry.update(getattr(record, "fields", {}))
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry)


_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(JsonFormatter())
log = logging.getLogger(SERVICE)
log.setLevel(logging.INFO)
log.addHandler(_handler)
log.propagate = False


def log_event(level, msg, **fields):
    log.log(level, msg, extra={"fields": fields})


# ---------------------------------------------------------------- fault injection
class FaultInjector:
    """Holds the current fault (if any). Thread-safe: gunicorn serves requests on threads."""

    def __init__(self):
        self._lock = threading.Lock()
        self._fault = None

    def set(self, fault):
        with self._lock:
            self._fault = fault
        FAULT_ACTIVE.set(1)

    def clear(self):
        with self._lock:
            self._fault = None
        FAULT_ACTIVE.set(0)

    def current(self):
        with self._lock:
            fault = self._fault
        if fault and time.time() >= fault["until"]:
            self.clear()  # the fault expired on its own
            return None
        return fault

    def decide(self, path):
        """Return (extra_delay_seconds, should_fail) for a request to `path`."""
        fault = self.current()
        if not fault or not path.startswith(fault["route_prefix"]):
            return 0.0, False
        delay = fault["latency_ms"] / 1000 if random.random() < fault["latency_rate"] else 0.0
        return delay, random.random() < fault["error_rate"]


faults = FaultInjector()

# ---------------------------------------------------------------- app
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024  # reject request bodies over 16 KB

ADMIN_TOKEN = ""
_token_file = os.environ.get("ADMIN_TOKEN_FILE", "")
if _token_file and os.path.exists(_token_file):
    with open(_token_file, encoding="utf-8") as fh:
        ADMIN_TOKEN = fh.read().strip()

REQUEST_ID_OK = re.compile(r"^[A-Za-z0-9-]{1,64}$")
CATALOG = [
    {"id": 1, "name": "Coffee mug", "price": 12.5},
    {"id": 2, "name": "Sticker pack", "price": 4.0},
    {"id": 3, "name": "Hoodie", "price": 39.0},
]

# Create the SLI series at zero so dashboards show 0% errors instead of "No data".
for _method, _route, _codes in (("GET", "/api/items", ("200", "503")),
                                ("POST", "/api/checkout", ("200", "500", "503"))):
    for _code in _codes:
        REQUESTS.labels(_method, _route, _code)
    LATENCY.labels(_method, _route)


def route_label():
    # Use the route *template* (e.g. "/api/items"), never the raw path: raw paths would
    # create a new time series for every URL anyone types (a "cardinality explosion").
    return request.url_rule.rule if request.url_rule else "unmatched"


@app.before_request
def before():
    g.start = time.perf_counter()
    incoming = request.headers.get("X-Request-ID", "")
    g.request_id = incoming if REQUEST_ID_OK.match(incoming) else uuid.uuid4().hex[:16]
    delay, fail = faults.decide(request.path)
    if delay:
        time.sleep(delay)
    if fail:
        g.fault = True
        return jsonify(error="service unavailable (injected fault)"), 503
    return None


@app.after_request
def after(response):
    route = route_label()
    if route == "/metrics":
        return response
    elapsed = time.perf_counter() - g.get("start", time.perf_counter())
    code = str(response.status_code)
    REQUESTS.labels(request.method, route, code).inc()
    LATENCY.labels(request.method, route).observe(elapsed)
    response.headers["X-Request-ID"] = g.get("request_id", "-")
    response.headers["X-Content-Type-Options"] = "nosniff"
    if route != "/healthz":
        level = logging.ERROR if response.status_code >= 500 else (
            logging.WARNING if response.status_code >= 400 else logging.INFO)
        log_event(level, "request", method=request.method, route=route,
                  path=request.path[:200], status=response.status_code,
                  duration_ms=round(elapsed * 1000, 1), request_id=g.get("request_id"),
                  injected_fault=bool(g.get("fault")))
    return response


def simulate_work(low, high):
    time.sleep(random.uniform(low, high))
    if random.random() < 0.003:  # rare slow outlier, like a cold cache
        time.sleep(random.uniform(0.35, 0.6))


@app.get("/")
def index():
    return jsonify(service=SERVICE, status="ok", endpoints=["/api/items", "/api/checkout"])


@app.get("/healthz")
def healthz():
    return jsonify(status="ok")


@app.get("/api/items")
def items():
    simulate_work(0.01, 0.06)
    return jsonify(items=CATALOG)


@app.post("/api/checkout")
def checkout():
    simulate_work(0.06, 0.18)
    if random.random() < 0.002:  # the real world is never perfect: 0.2% payment timeouts
        log_event(logging.ERROR, "payment provider timed out", request_id=g.get("request_id"))
        return jsonify(error="payment provider timed out"), 500
    order = request.get_json(silent=True)
    quantity = order.get("quantity", 1) if isinstance(order, dict) else 1
    return jsonify(order_id=uuid.uuid4().hex[:12], quantity=quantity, status="confirmed")


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


# ---------------------------------------------------------------- admin API (fault injection)
def authorized():
    header = request.headers.get("Authorization", "")
    supplied = header[7:] if header.startswith("Bearer ") else ""
    # compare_digest takes the same time whether the first or the last character is wrong,
    # so an attacker cannot guess the token one character at a time from response times.
    return bool(ADMIN_TOKEN) and hmac.compare_digest(supplied.encode(), ADMIN_TOKEN.encode())


def number(body, key, default, low, high):
    value = body.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise ValueError(f"'{key}' must be a number between {low} and {high}")
    return float(value)


@app.route("/admin/fault", methods=["GET", "POST", "DELETE"])
def admin_fault():
    if not ADMIN_TOKEN:
        return jsonify(error="admin API disabled: no token configured"), 503
    if not authorized():
        return jsonify(error="unauthorized"), 401, {"WWW-Authenticate": "Bearer"}

    if request.method == "GET":
        fault = faults.current()
        if not fault:
            return jsonify(active=False)
        return jsonify(active=True, seconds_left=int(fault["until"] - time.time()),
                       **{k: v for k, v in fault.items() if k != "until"})

    if request.method == "DELETE":
        faults.clear()
        log_event(logging.WARNING, "fault injection stopped")
        return jsonify(active=False)

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="send a JSON object"), 400
    try:
        prefix = body.get("route_prefix", "/api/")
        if not isinstance(prefix, str) or not prefix.startswith("/api/") or len(prefix) > 64:
            raise ValueError("'route_prefix' must start with /api/")
        fault = {
            "route_prefix": prefix,
            "error_rate": number(body, "error_rate", 0.0, 0, 1),
            "latency_ms": number(body, "latency_ms", 0, 0, 5000),
            "latency_rate": number(body, "latency_rate", 0.0, 0, 1),
        }
        duration = number(body, "duration_seconds", 600, 10, 3600)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    fault["until"] = time.time() + duration
    faults.set(fault)
    log_event(logging.WARNING, "fault injection started", duration_seconds=int(duration),
              **{k: v for k, v in fault.items() if k != "until"})
    return jsonify(active=True, seconds_left=int(duration),
                   **{k: v for k, v in fault.items() if k != "until"})


@app.errorhandler(HTTPException)
def http_error(error):
    # Normal HTTP errors (404, 405, 413 ...) keep their status code, as JSON.
    return jsonify(error=error.name.lower()), error.code


@app.errorhandler(Exception)
def unexpected(_error):
    # A real bug: log the stack trace, but never show it to the caller.
    log.exception("unhandled error", extra={"fields": {"request_id": g.get("request_id")}})
    return jsonify(error="internal server error"), 500
