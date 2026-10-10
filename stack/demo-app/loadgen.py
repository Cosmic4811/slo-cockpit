"""loadgen: steady, realistic traffic for shop-api, so the SLIs always have data.

It sends LOADGEN_RPS requests per second (default 4): mostly browsing (/api/items),
some checkouts (/api/checkout) and a few homepage visits. One summary log line per minute.
"""

import json
import os
import random
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

TARGET = os.environ.get("TARGET_URL", "http://shop-api:8080").rstrip("/")
RPS = float(os.environ.get("LOADGEN_RPS", "4"))
MAX_IN_FLIGHT = 16  # if the API is very slow, skip requests instead of piling them up

ROUTES = [  # (weight, method, path, JSON body)
    (65, "GET", "/api/items", None),
    (30, "POST", "/api/checkout", b'{"quantity": 1}'),
    (5, "GET", "/", None),
]
WEIGHTS = [route[0] for route in ROUTES]

stats_lock = threading.Lock()
stats = {"sent": 0, "errors": 0, "skipped": 0}
slots = threading.BoundedSemaphore(MAX_IN_FLIGHT)


def log(msg, **fields):
    entry = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
             "level": "info", "service": "loadgen", "msg": msg, **fields}
    print(json.dumps(entry), flush=True)


def one_request():
    _weight, method, path, body = random.choices(ROUTES, weights=WEIGHTS)[0]
    req = urllib.request.Request(
        TARGET + path, data=body, method=method,
        headers={"Content-Type": "application/json", "User-Agent": "slo-cockpit-loadgen"})
    ok = True
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    except urllib.error.HTTPError as err:
        ok = err.code < 500
        err.close()
    except OSError:  # connection refused, timeout, DNS failure ...
        ok = False
    finally:
        slots.release()
    with stats_lock:
        stats["sent"] += 1
        stats["errors"] += 0 if ok else 1


def main():
    if RPS <= 0:
        log("LOADGEN_RPS must be greater than 0")
        sys.exit(1)
    log("starting", target=TARGET, rps=RPS)
    pool = ThreadPoolExecutor(max_workers=MAX_IN_FLIGHT)
    interval = 1.0 / RPS
    next_send = time.monotonic()
    next_report = next_send + 60
    while True:
        if slots.acquire(blocking=False):
            pool.submit(one_request)
        else:
            with stats_lock:
                stats["skipped"] += 1
        now = time.monotonic()
        next_send = max(next_send + interval, now - 1)  # never try to "catch up" a long pause
        if now >= next_report:
            with stats_lock:
                snapshot = dict(stats)
                stats.update(sent=0, errors=0, skipped=0)
            log("last minute", **snapshot)
            next_report = now + 60
        time.sleep(max(0.0, next_send - time.monotonic()))


if __name__ == "__main__":
    main()
