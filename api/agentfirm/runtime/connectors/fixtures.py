"""Fixture world: deterministic stand-ins for every external system, used when
AGENTFIRM_CONNECTOR_MODE=fixture (tests, evals, offline development). Production refuses
this mode. Every tool output produced from here carries `"fixture": True`, and the agents
say so in their results, so fixture data can never pass for a real system's answer.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any


def _h(s: str, mod: int) -> int:
    return int(hashlib.sha256(s.encode()).hexdigest(), 16) % mod


BILLING_REPO = {
    "README.md": "# billing-service\n\nHandles payment-provider webhooks, invoices and task listings.\n",
    "requirements.txt": "fastapi==0.110.0\nrequests==2.19.0\nhttpx==0.27.0\npypdf==3.0.0\n",
    "app/__init__.py": "",
    "app/webhooks.py": (
        "def handle_webhook(event: dict, store) -> str:\n"
        "    # Providers retry deliveries; every delivery is charged again.\n"
        '    store.charge(event["customer"], event["amount"])\n'
        '    return "ok"\n'
    ),
    "app/tasks.py": 'def list_tasks(db):\n    return db.query("SELECT * FROM tasks ORDER BY created_at DESC")\n',
    "app/auth.py": "def login(db, email, password):\n    user = db.get_user(email)\n    if user and user.check(password):\n        return user.token()\n    return None\n",
    "app/signup.py": 'def signup(db, payload: dict):\n    return db.create_user(payload["email"], payload["password"])\n',
    "app/dates.py": 'from datetime import datetime\n\ndef parse(value: str):\n    return datetime.strptime(value, "%d/%m/%Y")\n',
    "tests/test_webhooks.py": "def test_charges_once():\n    ...\n\ndef test_returns_ok():\n    ...\n",
    "tests/test_tasks.py": "def test_lists_tasks():\n    ...\n",
    "tests/test_dates.py": "def test_parse_iso():\n    ...\n",
}

ADVISORIES = {
    "requests==2.19.0": [{"id": "GHSA-x84v-xcm2-53pg", "summary": "Insufficiently protected credentials on redirect", "severity": "high", "fixed": "2.20.0"}],
    "pypdf==3.0.0": [{"id": "GHSA-4vvm-4w3v-6mr8", "summary": "Possible infinite loop on crafted PDF", "severity": "medium", "fixed": "3.9.0"}],
}


def _months(n: int, end: date = date(2026, 10, 1)) -> list[str]:
    out, y, m = [], end.year, end.month
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(out))


def default_datasets() -> dict[str, list[dict[str, Any]]]:
    months = _months(24)
    revenue = [{"month": m, "revenue": round(40_000 * (1.025**i) + (_h(m, 3000) - 1500), 2), "customers": 800 + 12 * i} for i, m in enumerate(months)]
    payments = []
    for i in range(150):
        mo = 7 + i % 3
        payments.append(
            {"payment_id": f"p{i:04d}", "customer_id": f"c{i % 60:03d}", "amount": float(20 + _h(f"pay{i}", 80)), "paid_at": f"2026-{mo:02d}-{1 + i % 28:02d}"}
        )
    customers = []
    for i in range(200):
        signup = date(2025, 11, 1) + timedelta(days=_h(f"s{i}", 330))
        churned = signup + timedelta(days=30 + _h(f"c{i}", 200)) if _h(f"ch{i}", 10) < 3 else None
        customers.append(
            {
                "customer_id": f"c{i:03d}",
                "signup_date": signup.isoformat(),
                "plan": ["starter", "team", "business"][_h(f"pl{i}", 3)],
                "status": "churned" if churned and churned < date(2026, 11, 1) else "active",
                "churned_at": churned.isoformat() if churned else None,
            }
        )
    campaigns = [
        {"campaign": "Autumn intake — Meta", "channel": "meta", "spend": 2400.0, "conversions": 48},
        {"campaign": "Brand search", "channel": "google", "spend": 900.0, "conversions": 45},
        {"campaign": "LinkedIn decision makers", "channel": "linkedin", "spend": 3100.0, "conversions": 52},
        {"campaign": "Retargeting", "channel": "meta", "spend": 650.0, "conversions": 26},
    ]
    funnel = [{"month": m, "visitors": 20_000 + _h(m + "v", 4000), "signups": 900 + _h(m + "s", 200)} for m in _months(11, date(2026, 11, 1))[:-1]]
    return {"revenue_monthly": revenue, "payments_q3": payments, "customers": customers, "campaigns": campaigns, "funnel_monthly": funnel}


@dataclass
class SandboxScript:
    unavailable: bool = False
    #: Number of failing tests every run reports (0 = derive a pass from the test files).
    fail_tests: int = 0
    runs: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class World:
    repository: str = "acme/billing-service"
    branches: dict[str, dict[str, str]] = field(default_factory=lambda: {"main": dict(BILLING_REPO)})
    protected: set[str] = field(default_factory=lambda: {"main"})
    pull_requests: list[dict[str, Any]] = field(default_factory=list)
    advisories: dict[str, list[dict[str, Any]]] = field(default_factory=lambda: dict(ADVISORIES))
    sandbox: SandboxScript = field(default_factory=SandboxScript)
    deployments: list[dict[str, Any]] = field(default_factory=list)
    datasets: dict[str, list[dict[str, Any]]] = field(default_factory=default_datasets)
    calendar_events: list[dict[str, Any]] = field(
        default_factory=lambda: [
            {"title": "Team stand-up", "start": "2026-11-23T09:00:00", "end": "2026-11-23T09:15:00"},
            {"title": "Customer call — Northwind", "start": "2026-11-24T14:00:00", "end": "2026-11-24T15:00:00"},
            {"title": "Planning", "start": "2026-11-26T10:00:00", "end": "2026-11-26T11:30:00"},
        ]
    )
    calendar_error: int | None = None
    created_events: list[dict[str, Any]] = field(default_factory=list)
    sent_emails: list[dict[str, Any]] = field(default_factory=list)
    published: list[dict[str, Any]] = field(default_factory=list)
    ad_campaigns: list[dict[str, Any]] = field(
        default_factory=lambda: [
            {
                "campaign": "Autumn intake — Meta",
                "channel": "meta",
                "spend": 2400.0,
                "impressions": 310_000,
                "clicks": 4100,
                "conversions": 48,
                "daily_budget": 60.0,
            },
            {
                "campaign": "LinkedIn decision makers",
                "channel": "linkedin",
                "spend": 3100.0,
                "impressions": 120_000,
                "clicks": 1300,
                "conversions": 52,
                "daily_budget": 90.0,
            },
            {"campaign": "Brand search", "channel": "google", "spend": 900.0, "impressions": 45_000, "clicks": 2900, "conversions": 45, "daily_budget": 30.0},
        ]
    )
    budget_changes: list[dict[str, Any]] = field(default_factory=list)
    automation_runs: list[dict[str, Any]] = field(default_factory=list)
    payments: list[dict[str, Any]] = field(default_factory=list)
    purchases: list[dict[str, Any]] = field(default_factory=list)
    jobs: list[dict[str, Any]] = field(
        default_factory=lambda: [
            {
                "title": "Senior Product Manager, Payments",
                "company": "Kontor Bank",
                "location": "Berlin (hybrid, 2 days remote)",
                "url": "https://jobs.example.com/kontor-spm",
                "salary": "€95-110k",
            },
            {
                "title": "Senior Product Manager — Growth",
                "company": "Lernwerk",
                "location": "Remote (EU) / Berlin",
                "url": "https://jobs.example.com/lernwerk-growth",
                "salary": "€90-105k",
            },
            {
                "title": "Lead PM, Developer Platform",
                "company": "Stackhaus",
                "location": "Berlin",
                "url": "https://jobs.example.com/stackhaus-lead",
                "salary": None,
            },
        ]
    )
    places: list[dict[str, Any]] = field(
        default_factory=lambda: [
            {
                "name": "Hafen Coworking",
                "kind": "coworking",
                "price": "€25/day",
                "distance": "0.6 km",
                "notes": "Quiet floor, bookable phone booths",
                "url": "https://places.example.com/hafen",
            },
            {
                "name": "Werkbank Studios",
                "kind": "coworking",
                "price": "€19/day",
                "distance": "1.4 km",
                "notes": "Community events, fewer meeting rooms",
                "url": "https://places.example.com/werkbank",
            },
            {
                "name": "Atelier 9",
                "kind": "coworking",
                "price": "€32/day",
                "distance": "0.3 km",
                "notes": "Premium, includes lunch",
                "url": "https://places.example.com/atelier9",
            },
            {
                "name": "ICE 597 Berlin → München, Fri 07:29",
                "kind": "train",
                "price": "€59.90",
                "distance": "4h 01m",
                "notes": "Saver fare, no refunds",
                "url": "https://places.example.com/ice597",
            },
            {
                "name": "ICE 1001 Berlin → München, Fri 09:04",
                "kind": "train",
                "price": "€79.90",
                "distance": "3h 58m",
                "notes": "Flex fare",
                "url": "https://places.example.com/ice1001",
            },
        ]
    )
    keywords_available: bool = True
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)


WORLD = World()


def reset() -> World:
    global WORLD
    WORLD = World()
    return WORLD


def keyword_metrics(keyword: str, locale: str) -> dict[str, Any]:
    return {"keyword": keyword, "locale": locale, "monthly_volume": 200 + _h(keyword + locale, 9800), "difficulty": 10 + _h(keyword, 80), "fixture": True}
