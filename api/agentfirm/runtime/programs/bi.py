"""BI & Automation agent program (manifest: agents/manifests/bi.yaml).

Integrity rules enforced in code:
* every figure is computed by `data.analyze` (declarative operations, no generated code);
* interpretation numbers are checked against the computed values; a finding quoting a
  number that wasn't computed is downgraded to an assumption;
* forecasts and model-estimated inputs are labelled `estimate`; computed facts cite the
  dataset/query they came from;
* bad data (key columns > 20% empty) stops the analysis and asks the user;
* automations and payments run only after an approval showing the exact targets/amount.
"""

from __future__ import annotations

import csv
import io
import re
from typing import Any

from pydantic import BaseModel, Field

from agentfirm.agents.contracts import AgentResult, ArtifactRef, Citation, Claim, ErrorCode, HandoffRequest

from ..context import ExecutionContext
from ..errors import StepError
from ..gateway import simulated
from .base import NUMBER, approval_state, art_ref, fixture_note, wants

SYSTEM = (
    "You are AgentFirm's BI & Automation agent. You never do arithmetic yourself: you choose data.analyze "
    "operations and interpret their results. Separate computed facts, estimates and assumptions."
)
NULL_LIMIT = 0.2
KPI_LIBRARY: dict[str, dict[str, Any]] = {
    "revenue": {"dataset": "revenue_monthly", "label": "Monthly revenue", "x": "month", "y": "revenue", "ops": [{"op": "pct_change", "column": "revenue"}]},
    "active_customers": {
        "dataset": "customers",
        "label": "Active customers",
        "ops": [
            {"op": "filter", "column": "status", "cmp": "==", "value": "active"},
            {"op": "group", "by": [], "metrics": [{"column": "customer_id", "agg": "nunique", "as": "active_customers"}]},
        ],
    },
    "activation": {
        "dataset": "funnel_monthly",
        "label": "Activation (signups ÷ visitors)",
        "x": "month",
        "y": "activation_rate",
        "ops": [{"op": "derive", "name": "activation_rate", "fn": "div", "left": "signups", "right": "visitors"}],
    },
    "retention": {
        "dataset": "customers",
        "label": "Retention by signup cohort",
        "x": "cohort",
        "y": "m3",
        "ops": [{"op": "cohort_retention", "customer_column": "customer_id", "signup_column": "signup_date", "churn_column": "churned_at"}],
    },
    "churn": {
        "dataset": "customers",
        "label": "Churned customers",
        "ops": [
            {"op": "filter", "column": "status", "cmp": "==", "value": "churned"},
            {"op": "group", "by": [], "metrics": [{"column": "customer_id", "agg": "nunique", "as": "churned_customers"}]},
        ],
    },
}


class Question(BaseModel):
    metric: str
    period: str = ""
    kind: str = Field(default="descriptive", pattern="^(descriptive|diagnostic|forecast)$")


class Pick(BaseModel):
    dataset: str
    key_columns: list[str] = Field(default_factory=list)
    reason: str = ""


class Op(BaseModel):
    model_config = {"extra": "allow"}
    op: str


class AnalysisPlan(BaseModel):
    operations: list[Op]
    explanation: str = ""


class Finding(BaseModel):
    text: str
    kind: str = Field(pattern="^(computed|estimate|assumption)$")


class Interpretation(BaseModel):
    answer: str
    findings: list[Finding]
    caveats: list[str] = Field(default_factory=list)


class KpiChoice(BaseModel):
    kpis: list[str]


class OptionRow(BaseModel):
    model_config = {"extra": "allow"}
    option: str


class Criterion(BaseModel):
    column: str
    weight: float = Field(gt=0)
    higher_is_better: bool = True
    description: str = ""


class Scoring(BaseModel):
    criteria: list[Criterion]
    rows: list[OptionRow]
    basis: str = "estimated"


class AutomationSpec(BaseModel):
    trigger: str
    dataset: str = ""
    condition: dict[str, Any] = Field(default_factory=dict)
    #: Optional derived column the condition uses, e.g. {"op": "derive", "name": "cpa", "fn": "div", "left": "spend", "right": "conversions"}.
    derive: dict[str, Any] | None = None
    action: str
    description: str
    payment: dict[str, Any] | None = None


# ── helpers ──────────────────────────────────────────────────────────────────



_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}(?:\.[A-Za-z_][A-Za-z0-9_]{0,62})?$")


def select_all(dataset: str) -> str:
    """Security review F-01: dataset names come from a model's output. Only plain (optionally
    schema-qualified) identifiers are accepted, and each part is quoted, so a name can never
    carry SQL (the GN7T read-only guard is a second layer, not the first)."""
    if not isinstance(dataset, str) or not _IDENT.match(dataset):
        raise StepError(ErrorCode.UPSTREAM_DATA_INVALID, f"'{str(dataset)[:60]}' is not a valid dataset name.")
    quoted = ".".join(f'"{part}"' for part in dataset.split("."))
    return "SELECT * FROM " + quoted  # nosec B608 - validated identifier, quoted

def _num(v: str) -> float | None:
    try:
        return float(v.replace(",", "")) if v.strip() else None
    except ValueError:
        return None


def parse_csv(text: str) -> list[dict[str, Any]]:
    rows = list(csv.DictReader(io.StringIO(text.strip())))
    return [{k.strip(): (_num(v) if _num(v) is not None else (v.strip() or None)) for k, v in r.items() if k} for r in rows]


def computed_numbers(result: dict[str, Any]) -> set[float]:
    vals: set[float] = set()

    def add(v: Any) -> None:
        if isinstance(v, int | float) and not isinstance(v, bool):
            for x in (v, v * 100):
                vals.update({round(x, 0), round(x, 1), round(x, 2)})

    for v in (result.get("values") or {}).values():
        add(v)
    for t in result.get("tables", []):
        for r in t["rows"]:
            for v in r:
                add(v)
    return vals


def unsupported_numbers(text: str, computed: set[float], user_text: str) -> list[str]:
    supplied = {
        round(float(x.rstrip("%kmbnx ").replace(",", "")), 2)
        for x in NUMBER.findall(user_text)
        if x.rstrip("%kmbnx ").replace(",", "").replace(".", "").isdigit()
    }
    out = []
    for raw in NUMBER.findall(text):
        core = raw.strip().rstrip("%kmbnxKMBNX ").replace(",", "")
        try:
            v = float(core)
        except ValueError:
            continue
        if v.is_integer() and 1900 <= v <= 2100:  # years
            continue
        if not any(abs(v - c) <= max(0.01, abs(c) * 0.005) for c in computed | supplied):
            out.append(raw.strip())
    return out


async def _analyze(ctx: ExecutionContext, rows: list[dict[str, Any]], operations: list[dict[str, Any]]) -> dict[str, Any]:
    return await ctx.tool("data.analyze", rows=rows, operations=operations)


def _source(d: dict[str, Any]) -> dict[str, str]:
    src = d.get("source") or {}
    return {"source_id": src.get("id", "data"), "title": src.get("title", "Workspace data"), "url": src.get("url")}


def _chart_spec(table: dict[str, Any], title: str, y_hint: str | None = None) -> dict[str, Any] | None:
    cols, rows = table["columns"], table["rows"][:36]
    if len(rows) < 2 or len(cols) < 2:
        return None
    numeric = [i for i, c in enumerate(cols) if i > 0 and all(isinstance(r[i], int | float) or r[i] is None for r in rows)]
    if y_hint and y_hint in cols:
        numeric = [cols.index(y_hint)]
    if not numeric:
        return None
    series = [{"name": cols[i], "values": [r[i] for r in rows]} for i in numeric[:3]]
    return {"type": "line" if len(rows) > 6 else "bar", "title": title, "x": [str(r[0]) for r in rows], "series": series}


# ── analysis (also forecasts) ────────────────────────────────────────────────


async def objective(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    q = await ctx.structured(
        "objective",
        "classify",
        Question,
        system=SYSTEM + " Restate the metric, period and whether this is descriptive, diagnostic or a forecast.",
        user=ctx.objective,
        sim={"objective": ctx.objective},
    )
    return {"question": q.model_dump()}


async def inventory(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    if ctx.parameters.get("files") or ctx.parameters.get("datasets"):
        ids = ctx.parameters.get("files") or ctx.parameters.get("datasets")
        docs = (await ctx.tool("docs.parse", document_ids=ids))["documents"]
        for doc in docs:
            rows = parse_csv(doc["text"])
            if rows:
                return {
                    "rows": rows,
                    "columns": list(rows[0]),
                    "source": {"id": f"kb:{doc['document_id']}", "title": doc["title"], "url": f"kb://{doc['document_id']}"},
                }
        raise StepError(ErrorCode.UPSTREAM_DATA_INVALID, "The attached files contain no table I can read (CSV with a header row).")
    catalog = (await ctx.tool("gn7t.query", list_datasets=True))["datasets"]
    if not catalog:
        raise StepError(ErrorCode.MISSING_CONTEXT, "No datasets are available. Connect GN7T or attach a CSV.")
    pick = await ctx.structured(
        "pick",
        "classify",
        Pick,
        system=SYSTEM + " Pick the one dataset that answers the question, and the columns the answer depends on.",
        user=f"Question: {d.get('question')}\nDatasets: {[{'name': c['name'], 'columns': c['columns']} for c in catalog]}",
        sim={"objective": ctx.objective, "catalog": catalog},
    )
    names = {c["name"] for c in catalog}
    if pick.dataset not in names:
        raise StepError(ErrorCode.MISSING_CONTEXT, f"None of the available datasets ({', '.join(sorted(names))}) covers this question.")
    out = await ctx.tool("gn7t.query", query=select_all(pick.dataset), max_rows=10_000)
    return {
        "rows": out["rows"],
        "columns": out["columns"],
        "key_columns": pick.key_columns,
        "fixture:inventory": bool(out.get("fixture")),
        "source": {"id": f"gn7t:{pick.dataset}", "title": f"GN7T dataset {pick.dataset}", "url": f"gn7t://{pick.dataset}"},
    }


async def quality(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    prof = await _analyze(ctx, d["rows"], [{"op": "profile"}])
    nulls = prof["values"]["null_pct"]
    keys = [k for k in d.get("key_columns") or [] if k in nulls] or [
        c for c in nulls if re.search(r"date|month|_at$|amount|revenue", c) and not c.endswith("churned_at")
    ]
    bad = {k: nulls[k] for k in keys if nulls[k] > NULL_LIMIT}
    if bad:
        detail = ", ".join(f"{k} is {v:.0%} empty" for k, v in bad.items())
        raise StepError(
            ErrorCode.UPSTREAM_DATA_INVALID,
            f"The data isn't good enough to answer reliably: {detail}. Can you fix or backfill it, or tell me to exclude those rows?",
        )
    return {"profile": {"rows": prof["values"]["row_count"], "null_pct": nulls}}


async def analyse(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    q = d.get("question", {})
    sample = d["rows"][:5]
    prompt = f"Question: {q}\nColumns: {d['columns']}\nSample rows: {sample}"
    error = ""
    for attempt in range(2):
        plan = await ctx.structured(
            "analyse",
            "reasoning",
            AnalysisPlan,
            system=SYSTEM
            + " Choose data.analyze operations (profile, filter, derive, group, sort, limit, time_series, pct_change, forecast_linear, cohort_retention).",
            user=prompt + (f"\nPrevious attempt failed: {error}" if error else ""),
            sim={"objective": ctx.objective, "columns": d["columns"], "question": q},
        )
        ops = [o.model_dump() for o in plan.operations]
        try:
            res = await _analyze(ctx, d["rows"], ops)
            return {"result": res, "operations": ops}
        except StepError as exc:
            if exc.code != ErrorCode.INVALID_INPUT or attempt == 1:
                raise
            error = exc.message
    raise AssertionError("unreachable")


async def visualise(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    tables = d.get("result", {}).get("tables", [])
    t = next((t for t in tables if t["name"] == "forecast"), None) or (tables[-1] if tables else None)
    spec = _chart_spec(t, d.get("question", {}).get("metric", "Result").capitalize()) if t else None
    if spec is None:
        return {"charts": []}
    out = await ctx.tool("chart.render", spec=spec)
    return {"charts": [{"artifact": art_ref(out), "table": out["table"]}]}


async def interpret(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    res = d["result"]
    if res.get("row_count", 0) == 0:
        return {
            "interpretation": {
                "answer": "There is no data for the period or segment you asked about, so I can't give a figure. "
                "Check that the data has been loaded for that period.",
                "findings": [],
                "caveats": [f"Operations returned no rows ({res.get('method')})."],
            }
        }
    i = await ctx.structured(
        "interpret",
        "reasoning",
        Interpretation,
        system=SYSTEM + " Interpret only the computed values. kind=computed for values in the result, estimate for forecasts, assumption otherwise.",
        user=f"Question: {d.get('question')}\nMethod: {res['method']}\nValues: {res['values']}\nTables: {[{'name': t['name'], 'columns': t['columns'], 'rows': t['rows'][:24]} for t in res['tables']]}",
        sim={"question": d.get("question"), "result": res},
    )
    nums = computed_numbers(res)
    findings = []
    for f in i.findings:
        bad = unsupported_numbers(f.text, nums, ctx.objective)
        if bad and f.kind == "computed":
            await ctx.log("warn", f"Finding quotes figures that weren't computed ({', '.join(bad)}); labelled as an assumption")
            findings.append({"text": f.text, "kind": "assumption"})
        else:
            findings.append(f.model_dump())
    if unsupported_numbers(i.answer, nums, ctx.objective):
        i.caveats.append("The headline contains a figure that wasn't computed directly; rely on the findings table.")
    return {"interpretation": {"answer": i.answer, "findings": findings, "caveats": i.caveats}}


def _fmt(v: Any) -> str:
    """Readable numbers for reports: thousands separators, no scientific notation."""
    if v is None:
        return "—"
    if isinstance(v, bool) or not isinstance(v, int | float):
        return str(v)
    if isinstance(v, int) or float(v).is_integer():
        return f"{v:,.0f}"
    if abs(v) >= 100:
        return f"{v:,.2f}"
    if abs(v) >= 1:
        return f"{v:,.3f}".rstrip("0").rstrip(".")
    return f"{v:.4f}".rstrip("0").rstrip(".")


def _tables_md(res: dict[str, Any]) -> str:
    out = []
    for t in res.get("tables", []):
        if t["name"] == "profile":
            continue
        head = "| " + " | ".join(t["columns"]) + " |\n|" + "---|" * len(t["columns"])
        body = "\n".join("| " + " | ".join(_fmt(v) for v in r) + " |" for r in t["rows"][:24])
        more = f"\n\n_{t['total_rows'] - 24} more rows in data_tables.csv_" if t["total_rows"] > 24 else ""
        out.append(f"**{t['name'].capitalize()}**\n\n{head}\n{body}{more}")
    return "\n\n".join(out)


async def deliver_analysis(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    i, res = d.get("interpretation", {}), d.get("result", {})
    findings = "\n".join(f"- {f['text']} _({f['kind']})_" for f in i.get("findings", []))
    charts = "\n\n".join(f"Chart: {c['artifact']['name']}\n\n{c['table']}" for c in d.get("charts", []))
    md = (
        f"# {d.get('question', {}).get('metric', 'Analysis').capitalize()}\n\n**Answer.** {i.get('answer', '')}\n\n## Findings\n{findings or '—'}\n\n"
        f"## How this was computed\nSource: {_source(d)['title']}. Method: {res.get('method', '')}.\n\n{_tables_md(res)}"
        + (f"\n\n## Charts\n{charts}" if charts else "")
        + ("\n\n## Caveats\n" + "\n".join(f"- {c}" for c in i["caveats"]) if i.get("caveats") else "")
    )
    arts = [art_ref(await ctx.tool("artifact.write", name="business_report.md", content=md, deliverable="business_report"))]
    result_table = next((t for t in reversed(res.get("tables", [])) if t["name"] != "profile"), None)
    if result_table:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(result_table["columns"])
        w.writerows(result_table["rows"])
        arts.append(art_ref(await ctx.tool("artifact.write", name="data_tables.csv", content=buf.getvalue(), deliverable="data_tables")))
    return {"report_md": md, "artifacts": [*(c["artifact"] for c in d.get("charts", [])), *arts]}


# ── KPI report ───────────────────────────────────────────────────────────────


async def define(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    k = await ctx.structured(
        "define",
        "reasoning",
        KpiChoice,
        system=SYSTEM + f" Choose the KPIs for this report from: {list(KPI_LIBRARY)}.",
        user=ctx.objective,
        sim={"objective": ctx.objective},
    )
    return {"kpis": [x for x in k.kpis if x in KPI_LIBRARY][:6] or ["revenue", "active_customers"]}


async def compute(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    catalog = {c["name"] for c in (await ctx.tool("gn7t.query", list_datasets=True))["datasets"]}
    fixture = False
    for k in d.get("kpis", []):
        spec = KPI_LIBRARY[k]
        if spec["dataset"] not in catalog:
            out[k] = {"label": spec["label"], "unavailable": f"dataset {spec['dataset']} is not available"}
            continue
        q = await ctx.tool("gn7t.query", query=select_all(spec["dataset"]), max_rows=10_000)
        fixture = fixture or bool(q.get("fixture"))
        res = await _analyze(ctx, q["rows"], spec["ops"])
        out[k] = {"label": spec["label"], "result": res, "dataset": spec["dataset"]}
    return {"kpi_results": out, "fixture:compute": fixture}


async def visualise_kpis(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    charts = []
    for k, v in d.get("kpi_results", {}).items():
        spec_def = KPI_LIBRARY[k]
        if "result" not in v or "x" not in spec_def:
            continue
        t = v["result"]["tables"][-1]
        cols = t["columns"]
        if spec_def["x"] in cols and spec_def["y"] in cols:
            xi, yi = cols.index(spec_def["x"]), cols.index(spec_def["y"])
            rows = t["rows"][-12:]
            spec = {
                "type": "line" if len(rows) > 6 else "bar",
                "title": spec_def["label"],
                "x": [str(r[xi]) for r in rows],
                "series": [{"name": spec_def["label"], "values": [r[yi] for r in rows]}],
            }
            out = await ctx.tool("chart.render", spec=spec)
            charts.append({"kpi": k, "artifact": art_ref(out), "table": out["table"]})
    return {"charts": charts}


def _kpi_md(d: dict[str, Any]) -> str:
    lines = ["# KPI report", ""]
    for k, v in d.get("kpi_results", {}).items():
        if "unavailable" in v:
            lines.append(f"## {v['label']}\n\nNot available: {v['unavailable']}.\n")
            continue
        res = v["result"]
        vals = ", ".join(f"{a}: {_fmt(b)}" for a, b in res["values"].items() if not isinstance(b, dict | list))
        chart = next((c for c in d.get("charts", []) if c["kpi"] == k), None)
        lines.append(
            f"## {v['label']}\n\n{vals or ''}\n\n_Source: GN7T `{v['dataset']}` · {res['method']}_"
            + (f"\n\nChart: {chart['artifact']['name']}\n\n{chart['table']}" if chart else "")
            + "\n"
        )
    return "\n".join(lines)


async def deliver_kpis(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    md = _kpi_md(d)
    out = await ctx.tool("artifact.write", name="kpi_dashboard.md", content=md, deliverable="kpi_dashboard")
    return {"report_md": md, "artifacts": [*(c["artifact"] for c in d.get("charts", [])), art_ref(out)]}


def cadence_from_text(text: str) -> str | None:
    t = text.lower()
    tm = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b(?! ?(?:%|€|days|weeks))", t) if re.search(r"\bat \d", t) else None
    hh, mm = 8, 0
    if tm:
        hh, mm = int(tm.group(1)) % 24, int(tm.group(2) or 0)
        if tm.group(3) == "pm" and hh < 12:
            hh += 12
    at = f"@{hh:02d}:{mm:02d}"
    for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun"):
        if re.search(rf"\b(?:every |on )?{day}[a-z]*day[s]?\b", t):
            return f"weekly:{day}{at}"
    if re.search(r"\b(daily|every day|each day)\b", t):
        return f"daily{at}"
    if re.search(r"\b(weekly|every week)\b", t):
        return f"weekly:mon{at}"
    if re.search(r"\b(monthly|every month)\b", t):
        return f"monthly:1{at}"
    return None


async def schedule(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    cadence = ctx.parameters.get("schedule") or (
        cadence_from_text(ctx.objective) if wants(ctx.objective, r"\bschedule\b", r"\bevery\b", r"\bweekly\b", r"\bdaily\b", r"\bmonthly\b") else None
    )
    if not cadence:
        return {"schedule": None}
    out = await ctx.tool("report.schedule", cadence=cadence, timezone=ctx.parameters.get("timezone") or "UTC", title=ctx.objective[:200])
    return {"schedule": out}


# ── opportunity scoring ──────────────────────────────────────────────────────


async def criteria(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    s = await ctx.structured(
        "criteria",
        "reasoning",
        Scoring,
        system=SYSTEM
        + " List the options and weighted criteria. Give each option a value per criterion; values you can't source are estimates (basis=estimated).",
        user=ctx.objective,
        sim={"objective": ctx.objective},
    )
    if len(s.rows) < 2:
        raise StepError(ErrorCode.MISSING_CONTEXT, "Which options should I compare? List at least two.")
    rows = [r.model_dump() for r in s.rows]
    for c in s.criteria:
        if any(not isinstance(r.get(c.column), int | float) for r in rows):
            raise StepError(ErrorCode.UPSTREAM_DATA_INVALID, f"Missing values for criterion {c.column}")
    return {"scoring": {"criteria": [c.model_dump() for c in s.criteria], "rows": rows, "basis": s.basis}}


async def evidence(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    if not wants(ctx.objective, r"\bmarket", r"\bcountr", r"\bexpan", r"\bcompetit", r"\bsegment"):
        return {"handoffs": []}
    h = await ctx.tool(
        "agents.delegate",
        to_agent="research",
        objective=f"Find cited evidence for the scoring inputs: {ctx.objective[:300]}",
        reason="Replace estimated inputs with sourced figures",
        blocking=False,
    )
    return {"handoffs": [h["handoff"]]}


async def score(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    sc = d["scoring"]
    res = await _analyze(ctx, sc["rows"], [{"op": "weighted_score", "label_column": "option", "criteria": sc["criteria"]}])
    return {"scores": res}


async def sensitivity(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    sc = d["scoring"]
    res = await _analyze(ctx, sc["rows"], [{"op": "sensitivity", "label_column": "option", "criteria": sc["criteria"], "delta": 0.2}])
    return {"sensitivity": res["values"]}


async def deliver_opportunity(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    sc, sens = d["scoring"], d.get("sensitivity", {})
    t = d["scores"]["tables"][-1]
    crit = "\n".join(
        f"- **{c['column']}** x {c['weight']:g} ({'higher' if c['higher_is_better'] else 'lower'} is better) {c.get('description', '')}" for c in sc["criteria"]
    )
    stable = (
        "The leader stays the same when any weight moves ±20%."
        if sens.get("leader_stable")
        else "The ranking is sensitive: " + "; ".join(sens.get("flips", []))
    )
    md = (
        f"# Opportunity matrix\n\n**Leader: {sens.get('leader')}.** {stable}\n\n## Criteria\n{crit}\n\n"
        + _tables_md({"tables": [t]})
        + f"\n\n_Inputs are **{sc['basis']}**; scores are min-max normalised and weighted by data.analyze._"
    )
    out = await ctx.tool("artifact.write", name="opportunity_matrix.md", content=md, deliverable="opportunity_matrix")
    return {"report_md": md, "artifacts": [art_ref(out)]}


# ── automation ───────────────────────────────────────────────────────────────


async def design(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    s = await ctx.structured(
        "design",
        "reasoning",
        AutomationSpec,
        system=SYSTEM
        + " Specify the automation: trigger, dataset, condition {column, cmp, value} or derived metric, action; for a payment fill payment {payee, amount, currency, reference}.",
        user=ctx.objective,
        sim={"objective": ctx.objective},
    )
    return {"spec": s.model_dump()}


async def dry_run(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    spec = d["spec"]
    if spec.get("payment"):
        p = spec["payment"]
        if not p.get("payee") or not isinstance(p.get("amount"), int | float) or p["amount"] <= 0:
            raise StepError(ErrorCode.MISSING_CONTEXT, "Who should be paid, and how much exactly?")
        return {"dry_run": {"targets": [p], "method": "validated payee and amount"}}
    if not spec.get("dataset"):
        return {"dry_run": {"targets": [], "method": "no data condition"}}
    q = await ctx.tool("gn7t.query", query=select_all(spec["dataset"]), max_rows=10_000)
    ops = [*([spec["derive"]] if spec.get("derive") else []), {"op": "filter", **spec["condition"]}]
    res = await _analyze(ctx, q["rows"], ops)
    t = res["tables"][-1]
    targets = [dict(zip(t["columns"], r, strict=False)) for r in t["rows"]]
    return {"dry_run": {"targets": targets, "method": res["method"]}, "fixture:dry_run": bool(q.get("fixture"))}


async def execute(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    if approval_state(d) != "approved":
        return {"executed": None}
    spec = d["spec"]
    if spec.get("payment"):
        out = await ctx.tool("payments.execute", **spec["payment"])
    else:
        out = await ctx.tool("automation.run", action=spec["action"], description=spec["description"], targets=d["dry_run"]["targets"])
    return {"executed": out, "fixture:execute": bool(out.get("fixture"))}


async def monitor(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    spec, dr = d["spec"], d.get("dry_run", {})
    targets = "\n".join(f"- {t}" for t in dr.get("targets", [])[:50]) or "- none"
    recurring = spec["trigger"].lower() not in ("now", "once", "")
    md = (
        f"# Automation spec\n\n- Trigger: **{spec['trigger']}**\n- Action: {spec['description']}\n- Dry run: {dr.get('method', '')}\n\n## Affected now\n{targets}\n\n"
        f"## Result\n{d.get('executed') or ('Not executed (' + approval_state(d) + ')')}\n"
        + (
            "\n_Recurring runs: each future run will ask for approval again. Standing approvals for recurring automations arrive with the admin console (Phase 6)._"
            if recurring
            else ""
        )
    )
    out = await ctx.tool("artifact.write", name="automation_spec.md", content=md, deliverable="automation_spec")
    return {"report_md": md, "artifacts": [art_ref(out)]}


# ── Program ──────────────────────────────────────────────────────────────────


class BIProgram:
    key = "bi"
    handlers = {
        "analysis": {
            "objective": objective,
            "inventory": inventory,
            "quality": quality,
            "analyse": analyse,
            "visualise": visualise,
            "interpret": interpret,
            "deliver": deliver_analysis,
        },
        "kpi_report": {"define": define, "compute": compute, "visualise": visualise_kpis, "deliver": deliver_kpis, "schedule": schedule},
        "opportunity": {"criteria": criteria, "evidence": evidence, "score": score, "sensitivity": sensitivity, "deliver": deliver_opportunity},
        "automation": {"design": design, "dry_run": dry_run, "execute": execute, "monitor": monitor},
    }

    def approval_scope(self, ctx: ExecutionContext, step: str, data: dict[str, Any]) -> list[str] | None:
        spec = data.get("spec") or {}
        if spec.get("payment"):
            return ["payments.execute"]
        return ["automation.run"] if (data.get("dry_run") or {}).get("targets") else []

    def approval_facts(self, ctx: ExecutionContext, step: str, data: dict[str, Any]) -> dict[str, Any]:
        """Facts a standing approval's conditions can check (ADR 0006)."""
        spec, dr = data.get("spec") or {}, data.get("dry_run") or {}
        if spec.get("payment"):
            p = spec["payment"]
            return {"amount": p.get("amount"), "currency": p.get("currency", "EUR"), "payee": p.get("payee")}
        return {"target_count": len(dr.get("targets", []))} if dr else {}

    def approval_preview(self, ctx: ExecutionContext, step: str, data: dict[str, Any]) -> str | None:
        spec, dr = data.get("spec") or {}, data.get("dry_run") or {}
        if spec.get("payment"):
            p = spec["payment"]
            return f"Pay: {p.get('currency', 'EUR')} {p['amount']:,.2f}\nTo: {p['payee']}\nReference: {p.get('reference') or '—'}"
        rows = "\n".join(f"- {t}" for t in dr.get("targets", [])[:25])
        return f"{spec.get('description', '')}\n\nAffected now ({len(dr.get('targets', []))}), from a dry run ({dr.get('method', '')}):\n{rows}"

    def finalize(self, ctx: ExecutionContext, data: dict[str, Any]) -> AgentResult:
        claims: list[Claim] = []
        src = _source(data)
        cite = Citation(source_id=src["source_id"], title=src["title"], url=src["url"], excerpt=(data.get("result") or {}).get("method", "")[:300] or None)
        for f in (data.get("interpretation") or {}).get("findings", []):
            if f["kind"] == "computed":
                claims.append(Claim(text=f["text"], status="verified", citations=[cite]))
            else:
                claims.append(Claim(text=f["text"], status="estimate" if f["kind"] == "estimate" else "assumption"))
        if any(t["name"] == "forecast" for t in (data.get("result") or {}).get("tables", [])) and not any(c.status == "estimate" for c in claims):
            claims.append(
                Claim(
                    text=f"Forecast: {(data['result']['values'] or {}).get('forecast_total')} over the forecast horizon (linear trend, 80% interval in the report)",
                    status="estimate",
                )
            )
        if data.get("scoring"):
            basis = data["scoring"]["basis"]
            for r in data["scoring"]["rows"]:
                claims.append(
                    Claim(
                        text=f"Inputs for {r['option']}: " + ", ".join(f"{k}={v}" for k, v in r.items() if k != "option"),
                        status="estimate" if basis != "sourced" else "assumption",
                    )
                )
        parts = []
        if data.get("interpretation"):
            parts.append(f"**{data['interpretation']['answer']}**")
        if data.get("report_md"):
            parts.append(data["report_md"])
        if data.get("schedule"):
            s = data["schedule"]
            parts.append(f"Scheduled: `{s['cadence']}` ({s['timezone']}), next run {s['next_run_at']}.")
        if data.get("spec") and approval_state(data) == "rejected":
            parts.append(f"The automation was **not** run: the approver rejected it ({data.get('approval_note:approval') or 'no note'}).")
        artifacts = [ArtifactRef(id=a["id"], name=a["name"], kind=a["kind"]) for a in data.get("artifacts", [])]
        handoffs = [HandoffRequest(**h) for h in data.get("handoffs", [])]
        return AgentResult(
            execution_id=ctx.execution_id,
            status="completed",
            summary="\n\n".join(parts) + fixture_note(data) or "Nothing produced.",
            claims=claims,
            artifacts=artifacts,
            handoffs=handoffs,
        )


# ── Simulator builders (offline/dev only) ────────────────────────────────────


def _o(req) -> str:  # type: ignore[no-untyped-def]
    return req.sim_context.get("objective", "").lower()


@simulated.register("bi.objective")
def _sim_objective(req):  # type: ignore[no-untyped-def]
    o = _o(req)
    kind = "forecast" if re.search(r"forecast|predict|next \w+ quarters?|will we need", o) else "diagnostic" if o.startswith("why") else "descriptive"
    return {"metric": req.sim_context["objective"].rstrip("?."), "period": "", "kind": kind}


@simulated.register("bi.pick")
def _sim_pick(req):  # type: ignore[no-untyped-def]
    o, names = _o(req), {c["name"] for c in req.sim_context["catalog"]}
    rules = [
        (r"conversion|visitor|signup rate|activation", "funnel_monthly", ["month"]),
        (r"payment|per customer|q3", "payments_q3", ["amount", "paid_at"]),
        (r"retention|cohort|churn|active customers|customers", "customers", ["signup_date"]),
        (r"cpa|campaign", "campaigns", ["spend"]),
        (r"revenue|mrr|q1", "revenue_monthly", ["month", "revenue"]),
    ]
    for pat, ds, keys in rules:
        if re.search(pat, o) and ds in names:
            return {"dataset": ds, "key_columns": keys, "reason": "matches the question"}
    return {"dataset": sorted(names)[0], "key_columns": [], "reason": "closest available"}


@simulated.register("bi.analyse")
def _sim_analyse(req):  # type: ignore[no-untyped-def]
    o, cols = _o(req), req.sim_context["columns"]
    if "revenue" in cols and re.search(r"forecast|next|q1|predict", o):
        return {"operations": [{"op": "forecast_linear", "value_column": "revenue", "periods": 3}], "explanation": "linear trend forecast"}
    if "amount" in cols and "customer_id" in cols:
        return {
            "operations": [
                {
                    "op": "group",
                    "by": [],
                    "metrics": [{"column": "amount", "agg": "sum", "as": "revenue"}, {"column": "customer_id", "agg": "nunique", "as": "customers"}],
                },
                {"op": "derive", "name": "revenue_per_customer", "fn": "div", "left": "revenue", "right": "customers"},
            ]
        }
    if "signups" in cols:
        month = "2026-12" if "december" in o else None
        ops = [{"op": "derive", "name": "conversion_rate", "fn": "div", "left": "signups", "right": "visitors"}]
        return {"operations": ([{"op": "filter", "column": "month", "cmp": "==", "value": month}] if month else []) + ops}
    if "signup_date" in cols and re.search(r"retention|cohort", o):
        return {"operations": [{"op": "cohort_retention", "customer_column": "customer_id", "signup_column": "signup_date", "churn_column": "churned_at"}]}
    if "status" in cols:
        if "why" in o or "churn" in o:
            return {"operations": [{"op": "group", "by": ["plan", "status"], "metrics": [{"column": "customer_id", "agg": "nunique", "as": "customers"}]}]}
        return {
            "operations": [
                {"op": "filter", "column": "status", "cmp": "==", "value": "active"},
                {"op": "group", "by": [], "metrics": [{"column": "customer_id", "agg": "nunique", "as": "active_customers"}]},
            ]
        }
    if "revenue" in cols:
        return {"operations": [{"op": "pct_change", "column": "revenue"}]}
    return {"operations": [{"op": "profile"}]}


@simulated.register("bi.interpret")
def _sim_interpret(req):  # type: ignore[no-untyped-def]
    res = req.sim_context["result"]
    v = res.get("values", {})
    findings = []
    for k, val in v.items():
        if isinstance(val, int | float) and not isinstance(val, bool):
            kind = "estimate" if k in ("forecast_total", "trend_per_period") else "computed"
            findings.append({"text": f"{k.replace('_', ' ')}: {val:,.2f}" if isinstance(val, float) else f"{k.replace('_', ' ')}: {val}", "kind": kind})
    if not findings and res["tables"]:
        t = res["tables"][-1]
        findings.append({"text": f"{t['total_rows']} rows in the result table ({t['name']}).", "kind": "computed"})
    findings.append({"text": "Seasonality is likely to lift growth by 12% in spring.", "kind": "computed"})  # exercised by the number check
    answer = findings[0]["text"] if findings else "See the tables."
    return {"answer": answer, "findings": findings, "caveats": ["Linear trend ignores seasonality."] if "forecast_total" in v else []}


@simulated.register("bi.define")
def _sim_define(req):  # type: ignore[no-untyped-def]
    o = _o(req)
    picks = [
        k
        for k, words in {"activation": "activation", "retention": "retention", "revenue": "revenue", "churn": "churn", "active_customers": "active"}.items()
        if words in o
    ]
    return {"kpis": picks or ["revenue", "active_customers", "retention"]}


@simulated.register("bi.criteria")
def _sim_criteria(req):  # type: ignore[no-untyped-def]
    o = _o(req)
    names = ["Germany", "France", "Spain"] if re.search(r"countr", o) else [f"Segment {c}" for c in "ABCDE"][: (5 if "five" in o else 3)]
    rows = [{"option": n, "market_size": 10 + (i * 7) % 23, "margin": 20 + (i * 5) % 17, "entry_cost": 3 + (i * 4) % 9} for i, n in enumerate(names)]
    return {
        "criteria": [
            {"column": "market_size", "weight": 2, "higher_is_better": True, "description": "addressable demand"},
            {"column": "margin", "weight": 1.5, "higher_is_better": True, "description": "expected gross margin %"},
            {"column": "entry_cost", "weight": 1, "higher_is_better": False, "description": "€k to enter"},
        ],
        "rows": rows,
        "basis": "estimated",
    }


@simulated.register("bi.design")
def _sim_design(req):  # type: ignore[no-untyped-def]
    o = req.sim_context["objective"]
    if re.search(r"\bpay\b|invoice|supplier", o, re.I):
        m = re.search(r"€\s?([\d,]+(?:\.\d+)?)", o)
        return {
            "trigger": "now",
            "action": "payment",
            "description": "Pay the outstanding supplier invoice",
            "payment": {
                "payee": "Supplier (outstanding invoice)",
                "amount": float(m.group(1).replace(",", "")) if m else 0.0,
                "currency": "EUR",
                "reference": "Outstanding invoice",
            },
        }
    m = re.search(r"cpa (?:above|over|>) ?€?\s?(\d+)", o, re.I)
    trig = "every Monday 08:00" if re.search(r"every monday", o, re.I) else "now"
    return {
        "trigger": trig,
        "dataset": "campaigns",
        "condition": {"column": "cpa", "cmp": ">", "value": float(m.group(1)) if m else 40.0},
        "derive": {"op": "derive", "name": "cpa", "fn": "div", "left": "spend", "right": "conversions"},
        "action": "pause_campaigns",
        "description": "Pause campaigns whose cost per acquisition is above the threshold",
    }
