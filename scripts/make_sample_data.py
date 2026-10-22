"""Generate deterministic sample data for demos and tests.

    python scripts/make_sample_data.py

Writes to sample_data/:
  app.log              60 minutes of mixed JSON and plain-text logs with a database timeout spike at minute 40
  baseline.jtl         a healthy JMeter run
  current-good.jtl     a run within tolerance
  current-regressed.jtl  a run where POST /orders p95 has regressed
"""

from __future__ import annotations

import json
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "sample_data"


def make_logs(rng: random.Random) -> None:
    start = datetime(2026, 10, 20, 9, 0, 0)
    lines = []
    for minute in range(60):
        base = start + timedelta(minutes=minute)
        for _ in range(rng.randint(40, 60)):
            ts = base + timedelta(seconds=rng.uniform(0, 59.9))
            lines.append(
                (
                    ts,
                    json.dumps(
                        {
                            "ts": ts.strftime("%Y-%m-%dT%H:%M:%S+1100"),
                            "level": "INFO",
                            "service": "shop-api",
                            "msg": "request completed",
                            "method": "GET",
                            "path": "/orders",
                            "status": 200,
                            "duration_ms": round(rng.uniform(8, 60), 1),
                        }
                    ),
                )
            )
        # background noise: occasional validation errors
        if rng.random() < 0.4:
            ts = base + timedelta(seconds=rng.uniform(0, 59))
            lines.append(
                (
                    ts,
                    f"{ts:%Y-%m-%d %H:%M:%S},{rng.randint(100, 999)} ERROR [shop-api] "
                    f"Invalid quantity {rng.randint(1001, 5000)} for order {rng.randint(10000, 99999)}",
                )
            )
        # incident: DB connection pool exhausted between minutes 40 and 44
        if 40 <= minute <= 44:
            for _ in range(rng.randint(25, 40)):
                ts = base + timedelta(seconds=rng.uniform(0, 59))
                lines.append(
                    (
                        ts,
                        f"{ts:%Y-%m-%d %H:%M:%S},{rng.randint(100, 999)} ERROR [shop-api] "
                        f"Timeout acquiring DB connection from pool 'orders-db' after "
                        f"{rng.choice([3000, 5000])} ms (active={rng.randint(48, 50)}, max=50)",
                    )
                )
            for _ in range(rng.randint(3, 8)):
                ts = base + timedelta(seconds=rng.uniform(0, 59))
                lines.append(
                    (
                        ts,
                        f"{ts:%Y-%m-%d %H:%M:%S},{rng.randint(100, 999)} ERROR [payments] "
                        f"Upstream shop-api returned 503 for request {uuid.UUID(int=rng.getrandbits(128))}",
                    )
                )
    lines.sort(key=lambda x: x[0])
    (OUT / "app.log").write_text("\n".join(line for _, line in lines) + "\n")


def make_jtl(path: Path, rng: random.Random, post_p95_shift: float, seconds: int = 120) -> None:
    start_ms = 1_792_000_000_000
    rows = ["timeStamp,elapsed,label,responseCode,success,threadName"]
    t = start_ms
    end = start_ms + seconds * 1000
    while t < end:
        for label, base, spread in (("GET /orders", 35, 25), ("POST /orders", 60, 40)):
            elapsed = max(1, int(rng.gauss(base, spread / 3)))
            if label == "POST /orders" and rng.random() < 0.12:
                elapsed = int(elapsed + post_p95_shift + rng.uniform(80, 140))
            ok = rng.random() > 0.002
            code, success = (200, "true") if ok else (500, "false")
            rows.append(f"{t},{elapsed},{label},{code},{success},users 1-{rng.randint(1, 20)}")
        t += rng.randint(15, 30)
    path.write_text("\n".join(rows) + "\n")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    make_logs(random.Random(42))
    make_jtl(OUT / "baseline.jtl", random.Random(1), post_p95_shift=0)
    make_jtl(OUT / "current-good.jtl", random.Random(2), post_p95_shift=5)
    make_jtl(OUT / "current-regressed.jtl", random.Random(3), post_p95_shift=110)
    print(f"sample data written to {OUT}")


if __name__ == "__main__":
    main()
