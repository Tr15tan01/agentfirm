"""Server-side latency quantiles from the API's own Prometheus histogram (excludes load-generator
and network effects). Usage: python server_quantiles.py <metrics URL> <token> [before.json]"""

from __future__ import annotations

import json
import sys
import urllib.request
from collections import defaultdict

from prometheus_client.parser import text_string_to_metric_families


def scrape(url: str, token: str) -> dict[tuple[str, str], dict[float, float]]:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    text = urllib.request.urlopen(req, timeout=10).read().decode()  # noqa: S310 - operator-provided URL
    out: dict[tuple[str, str], dict[float, float]] = defaultdict(dict)
    for fam in text_string_to_metric_families(text):
        if fam.name != "agentfirm_http_request_duration_seconds":
            continue
        for s in fam.samples:
            if s.name.endswith("_bucket"):
                out[(s.labels["method"], s.labels["route"])][float(s.labels["le"])] = s.value
    return out


def quantile(buckets: dict[float, float], q: float) -> float:
    items = sorted(buckets.items())
    total = items[-1][1]
    if total == 0:
        return 0.0
    rank, prev_le, prev_c = q * total, 0.0, 0.0
    for le, c in items:
        if c >= rank:
            if le == float("inf"):
                return prev_le
            return prev_le + (le - prev_le) * ((rank - prev_c) / max(c - prev_c, 1e-9))  # linear within bucket
        prev_le, prev_c = le, c
    return items[-1][0]


if __name__ == "__main__":
    url, token = sys.argv[1], sys.argv[2]
    now = scrape(url, token)
    if len(sys.argv) > 3:
        before = {tuple(k.split(" ", 1)): {float(le): v for le, v in b.items()} for k, b in json.load(open(sys.argv[3])).items()}
        now = {k: {le: c - before.get(k, {}).get(le, 0) for le, c in b.items()} for k, b in now.items()}
        print(f"{'route':48} {'n':>7} {'p50':>7} {'p95':>7} {'p99':>7}  (ms, server-side)")
        for (m, r), b in sorted(now.items(), key=lambda kv: -max(kv[1].values())):
            n = max(b.values())
            if n >= 20:
                print(f"{m + ' ' + r:48} {int(n):7} {quantile(b, .5) * 1000:7.0f} {quantile(b, .95) * 1000:7.0f} {quantile(b, .99) * 1000:7.0f}")
    else:
        json.dump({f"{m} {r}": b for (m, r), b in now.items()}, sys.stdout)
