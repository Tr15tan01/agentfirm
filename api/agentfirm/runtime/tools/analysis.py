"""`data.analyze`: a declarative analysis engine (pandas) for the BI agent.

The model chooses *operations*; this code computes every number. No generated code is
executed, so arithmetic can't be hallucinated and nothing can escape a sandbox. Each
result carries a plain-language `method` line so the report can show how a figure was made.

Operations (applied in order to the working table):
    profile | filter | derive | group | sort | limit | time_series | pct_change |
    forecast_linear | cohort_retention | weighted_score | sensitivity
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from agentfirm.agents.contracts import ErrorCode

from ..errors import StepError

MAX_ROWS = 50_000
MAX_OUT = 200
AGG = {"sum", "mean", "count", "nunique", "min", "max", "median"}
CMP = {"==", "!=", ">", ">=", "<", "<=", "in", "not_in", "contains", "is_null", "not_null", "between"}
ARITH = {"add": np.add, "sub": np.subtract, "mul": np.multiply, "div": np.divide}
FREQ = {"D": "D", "W": "W-MON", "M": "MS", "Q": "QS"}


class AnalysisError(StepError):
    def __init__(self, message: str) -> None:
        super().__init__(ErrorCode.INVALID_INPUT, message)


def _col(df: pd.DataFrame, name: str) -> pd.Series:
    if name not in df.columns:
        raise AnalysisError(f"Unknown column {name!r}; columns are {list(df.columns)}")
    return df[name]


def _operand(df: pd.DataFrame, v: Any) -> Any:
    return _col(df, v) if isinstance(v, str) else float(v)


def _json(v: Any) -> Any:
    if isinstance(v, float | np.floating):
        return None if math.isnan(v) or math.isinf(v) else round(float(v), 6)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, pd.Timestamp):
        return v.date().isoformat()
    if v is pd.NaT or (isinstance(v, float) and math.isnan(v)):
        return None
    return v


def _table(name: str, df: pd.DataFrame) -> dict[str, Any]:
    head = df.head(MAX_OUT)
    return {
        "name": name,
        "columns": [str(c) for c in head.columns],
        "rows": [[_json(v) for v in r] for r in head.itertuples(index=False, name=None)],
        "total_rows": len(df),
    }


def _dates(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce")


def run(rows: list[dict[str, Any]], operations: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(rows, list) or not rows:
        raise StepError(ErrorCode.MISSING_CONTEXT, "No data rows to analyse.")
    if len(rows) > MAX_ROWS:
        raise AnalysisError(f"At most {MAX_ROWS} rows can be analysed at once")
    df = pd.DataFrame(rows)
    tables: list[dict[str, Any]] = []
    values: dict[str, Any] = {}
    method: list[str] = []
    for n, op in enumerate(operations[:30]):
        kind = op.get("op")
        if kind == "profile":
            prof = [
                {
                    "column": c,
                    "dtype": str(df[c].dtype),
                    "nulls": int(df[c].isna().sum()),
                    "null_pct": round(float(df[c].isna().mean()), 4),
                    "distinct": int(df[c].nunique(dropna=True)),
                }
                for c in df.columns
            ]
            tables.append({"name": "profile", "columns": list(prof[0]), "rows": [list(p.values()) for p in prof], "total_rows": len(prof)})
            values["row_count"] = len(df)
            values["max_null_pct"] = max(p["null_pct"] for p in prof)
            values["null_pct"] = {p["column"]: p["null_pct"] for p in prof}
            method.append(f"profiled {len(df)} rows x {len(df.columns)} columns")
        elif kind == "filter":
            col, cmp, v = op.get("column"), op.get("cmp", "=="), op.get("value")
            if cmp not in CMP:
                raise AnalysisError(f"Unknown comparison {cmp!r}")
            s = _col(df, col)
            if cmp in ("in", "not_in"):
                mask = s.isin(v if isinstance(v, list) else [v])
                mask = ~mask if cmp == "not_in" else mask
            elif cmp == "contains":
                mask = s.astype(str).str.contains(str(v), case=False, regex=False)
            elif cmp == "is_null":
                mask = s.isna()
            elif cmp == "not_null":
                mask = s.notna()
            elif cmp == "between":
                lo, hi = v
                mask = (s >= lo) & (s <= hi)
            else:
                mask = {"==": s == v, "!=": s != v, ">": s > v, ">=": s >= v, "<": s < v, "<=": s <= v}[cmp]
            before = len(df)
            df = df[mask]
            method.append(f"kept rows where {col} {cmp} {v} ({len(df)} of {before})")
        elif kind == "derive":
            name, fn = op.get("name"), ARITH.get(op.get("fn", ""))
            if not name or fn is None:
                raise AnalysisError("derive needs `name` and `fn` in add|sub|mul|div")
            with np.errstate(divide="ignore", invalid="ignore"):
                df = df.assign(**{name: fn(_operand(df, op.get("left")), _operand(df, op.get("right")))})
            df[name] = df[name].replace([np.inf, -np.inf], np.nan)
            method.append(f"{name} = {op.get('left')} {op.get('fn')} {op.get('right')}")
        elif kind == "group":
            by = op.get("by") or []
            metrics = op.get("metrics") or []
            spec = {}
            for m in metrics:
                if m.get("agg") not in AGG:
                    raise AnalysisError(f"Unknown aggregation {m.get('agg')!r}")
                _col(df, m["column"])
                spec[m.get("as") or f"{m['agg']}_{m['column']}"] = (m["column"], m["agg"])
            for b in by:
                _col(df, b)
            if by:
                df = df.groupby(by, dropna=False).agg(**spec).reset_index()
            else:
                df = pd.DataFrame([{k: getattr(df[c], a)() for k, (c, a) in spec.items()}])
            method.append(f"aggregated {', '.join(f'{a}({c})' for c, a in spec.values())}" + (f" by {', '.join(by)}" if by else ""))
            if not by:
                values.update({k: _json(v) for k, v in df.iloc[0].items()})
        elif kind == "sort":
            df = df.sort_values(op["by"], ascending=not op.get("descending", True))
        elif kind == "limit":
            df = df.head(int(op.get("n", 10)))
        elif kind == "time_series":
            dcol, vcol, freq, agg = op["date_column"], op["value_column"], FREQ.get(op.get("freq", "M"), "MS"), op.get("agg", "sum")
            if agg not in AGG:
                raise AnalysisError(f"Unknown aggregation {agg!r}")
            ts = df.assign(_d=_dates(_col(df, dcol))).dropna(subset=["_d"]).set_index("_d")[vcol].resample(freq).agg(agg)
            df = ts.reset_index().rename(columns={"_d": "period", vcol: vcol})
            method.append(f"{agg} of {vcol} per {op.get('freq', 'M')} period")
        elif kind == "pct_change":
            col = op["column"]
            df = df.assign(**{f"{col}_pct_change": _col(df, col).pct_change()})
            last = df[f"{col}_pct_change"].dropna()
            if len(last):
                values[f"last_{col}_pct_change"] = _json(last.iloc[-1])
            method.append(f"period-over-period change of {col}")
        elif kind == "forecast_linear":
            vcol, periods = op["value_column"], max(1, min(int(op.get("periods", 3)), 24))
            y = pd.to_numeric(_col(df, vcol), errors="coerce").dropna().to_numpy()
            if len(y) < 6:
                raise StepError(ErrorCode.MISSING_CONTEXT, "At least 6 historical periods are needed for a forecast.")
            x = np.arange(len(y))
            slope, intercept = np.polyfit(x, y, 1)
            resid = y - (slope * x + intercept)
            sd = float(np.std(resid, ddof=2))
            fx_ = np.arange(len(y), len(y) + periods)
            pred = slope * fx_ + intercept
            # 80% prediction interval for OLS: ±1.2816·s·√(1 + 1/n + (x-x̄)²/Sxx)
            sxx = float(((x - x.mean()) ** 2).sum())
            half = 1.2816 * sd * np.sqrt(1 + 1 / len(y) + (fx_ - x.mean()) ** 2 / sxx)
            fc = pd.DataFrame({"step": fx_ - len(y) + 1, "forecast": pred, "low_80": pred - half, "high_80": pred + half})
            tables.append(_table("forecast", fc))
            values["forecast_total"] = _json(float(pred.sum()))
            values["trend_per_period"] = _json(float(slope))
            values["r_squared"] = _json(1 - float((resid**2).sum()) / float(((y - y.mean()) ** 2).sum()) if len(y) > 2 else None)
            method.append(f"ordinary least-squares linear trend on {len(y)} periods of {vcol}, 80% prediction interval")
        elif kind == "cohort_retention":
            cid, scol, acol = op["customer_column"], op["signup_column"], op.get("churn_column")
            d = df.assign(_s=_dates(_col(df, scol)))
            d = d.dropna(subset=["_s"])
            d["cohort"] = d["_s"].dt.to_period("M").astype(str)
            if acol:
                churn = _dates(_col(d, acol))
                months = ((churn.dt.year - d["_s"].dt.year) * 12 + (churn.dt.month - d["_s"].dt.month)).where(churn.notna(), 999)
            else:
                months = pd.Series(999, index=d.index)
            rows_ = []
            for cohort, g in d.groupby("cohort"):
                m = months.loc[g.index]
                rows_.append({"cohort": cohort, "customers": int(g[cid].nunique()), **{f"m{k}": round(float((m > k).mean()), 4) for k in (1, 3, 6)}})
            df = pd.DataFrame(rows_)
            method.append("monthly signup cohorts; share still active after 1, 3 and 6 months")
        elif kind in ("weighted_score", "sensitivity"):
            crit = op.get("criteria") or []
            label = op.get("label_column") or df.columns[0]
            if not crit:
                raise AnalysisError("criteria are required")

            def score(weights: list[float], df: pd.DataFrame = df, crit: list[dict[str, Any]] = crit) -> pd.Series:
                total = pd.Series(0.0, index=df.index)
                for c, w in zip(crit, weights, strict=True):
                    s = pd.to_numeric(_col(df, c["column"]), errors="coerce")
                    span = (s.max() - s.min()) or 1.0
                    norm = (s - s.min()) / span
                    total += w * (norm if c.get("higher_is_better", True) else 1 - norm)
                return total / sum(weights)

            base_w = [float(c.get("weight", 1)) for c in crit]
            base = score(base_w)
            if kind == "weighted_score":
                df = df.assign(score=base.round(4)).sort_values("score", ascending=False)
                method.append("min-max normalised criteria, weighted " + ", ".join(f"{c['column']}x{w:g}" for c, w in zip(crit, base_w, strict=True)))
            else:
                delta = float(op.get("delta", 0.2))
                leader = df.loc[base.idxmax(), label]
                flips = []
                for i in range(len(crit)):
                    for sign in (-1, 1):
                        w = list(base_w)
                        w[i] = max(0.0, w[i] * (1 + sign * delta))
                        top = df.loc[score(w).idxmax(), label]
                        if top != leader:
                            flips.append(f"{crit[i]['column']} {'+' if sign > 0 else '-'}{delta:.0%} → {top}")
                values["leader"] = _json(leader)
                values["leader_stable"] = not flips
                values["flips"] = flips
                method.append(f"re-ranked with each weight ±{delta:.0%}; leader {'unchanged' if not flips else 'changes in ' + str(len(flips)) + ' cases'}")
        else:
            raise AnalysisError(f"Unknown operation {kind!r} (step {n + 1})")
    tables.append(_table("result", df))
    if len(df) == 1:  # a single-row result (e.g. totals + derived ratios): every field is a named value
        values.update({str(k): _json(v) for k, v in df.iloc[0].items()})
    return {"tables": tables, "values": values, "row_count": len(df), "method": "; ".join(method) or "no operations"}
