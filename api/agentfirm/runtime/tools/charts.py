"""`chart.render`: server-side SVG charts for reports (bar and line).

Follows the platform chart rules: one y-axis, recessive grid, thin marks (bars with 4px
rounded data-ends on a zero baseline, 2px lines, ≥8px markers), fixed categorical order
(never cycled; >8 series is refused), a legend whenever there are ≥2 series, text in text
ink (never the series colour), and a <title>/<desc> plus a data table for accessibility.
"""

from __future__ import annotations

import html
import math
from typing import Any

from agentfirm.agents.contracts import ErrorCode

from ..errors import StepError

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SURFACE, INK, INK_2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e7e6e2"
W, H, L, R, T, B = 720, 360, 64, 24, 56, 56


def _nice(v: float) -> float:
    if v <= 0:
        return 1.0
    exp = 10 ** math.floor(math.log10(v))
    return next(m * exp for m in (1, 2, 2.5, 5, 10) if m * exp >= v)


def _fmt(v: float) -> str:
    a = abs(v)
    if a >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if a >= 1_000:
        return f"{v / 1_000:.1f}k"
    return f"{v:g}" if a >= 1 or v == 0 else f"{v:.2f}"


def render(spec: dict[str, Any]) -> str:
    kind = spec.get("type", "bar")
    x = [str(v) for v in spec.get("x") or []]
    series = spec.get("series") or []
    if kind not in ("bar", "line") or not x or not series:
        raise StepError(ErrorCode.INVALID_INPUT, "chart.render needs type bar|line, x labels and at least one series")
    if len(series) > len(SERIES):
        raise StepError(ErrorCode.INVALID_INPUT, f"At most {len(SERIES)} series per chart; group the rest into 'Other' or use small multiples")
    for s in series:
        if len(s.get("values") or []) != len(x):
            raise StepError(ErrorCode.INVALID_INPUT, f"Series {s.get('name')!r} must have one value per x label")
    vals = [float(v) for s in series for v in s["values"] if v is not None]
    lo = min(0.0, min(vals)) if kind == "bar" else min(vals)
    top = max(vals) if max(vals) > 0 else 1.0
    if kind == "line" and lo > 0 and lo >= top * 0.5:  # line charts may start above zero when the data sit high
        lo = math.floor(lo / _nice((top - lo) / 5)) * _nice((top - lo) / 5)
    elif kind == "line":
        lo = min(0.0, lo)
    step = _nice((top - lo) / 5)
    hi = lo + step * math.ceil((top - lo) / step)
    ticks = round((hi - lo) / step)
    span = (hi - lo) or 1.0
    pw, ph = W - L - R, H - T - B
    ys = lambda v: T + ph - (float(v) - lo) / span * ph  # noqa: E731
    title = html.escape(spec.get("title") or "Chart")
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-labelledby="t d" font-family="Inter, system-ui, sans-serif">',
        f'<title id="t">{title}</title><desc id="d">{html.escape(spec.get("description") or "")}</desc>',
        f'<rect width="{W}" height="{H}" fill="{SURFACE}"/>',
        f'<text x="{L}" y="24" font-size="15" font-weight="600" fill="{INK}">{title}</text>',
    ]
    for i in range(ticks + 1):  # recessive grid + y ticks
        v = lo + step * i
        y = ys(v)
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{y:.1f}" y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>')
        out.append(f'<text x="{L - 8}" y="{y + 4:.1f}" font-size="11" text-anchor="end" fill="{INK_2}">{_fmt(v)}</text>')
    if spec.get("y_label"):
        out.append(
            f'<text x="14" y="{T + ph / 2:.0f}" font-size="11" fill="{INK_2}" transform="rotate(-90 14 {T + ph / 2:.0f})" text-anchor="middle">{html.escape(spec["y_label"])}</text>'
        )
    band = pw / len(x)
    step = max(1, math.ceil(len(x) / 12))
    for i, lab in enumerate(x):
        if i % step == 0:
            out.append(
                f'<text x="{L + band * (i + 0.5):.1f}" y="{H - B + 18}" font-size="11" text-anchor="middle" fill="{INK_2}">{html.escape(lab[:14])}</text>'
            )
    zero = ys(0 if lo <= 0 <= hi else lo)
    if kind == "bar":
        n = len(series)
        bw = max(2.0, min(28.0, (band * 0.7 - 2 * (n - 1)) / n))
        group = n * bw + 2 * (n - 1)
        for si, s in enumerate(series):
            for i, v in enumerate(s["values"]):
                if v is None:
                    continue
                x0 = L + band * i + (band - group) / 2 + si * (bw + 2)
                y0 = ys(v)
                top, h = min(y0, zero), abs(zero - y0)
                r = min(4.0, bw / 2, h)
                # rounded data-end only (square at the baseline)
                if float(v) >= 0:
                    d = f"M{x0:.1f},{zero:.1f} V{top + r:.1f} Q{x0:.1f},{top:.1f} {x0 + r:.1f},{top:.1f} H{x0 + bw - r:.1f} Q{x0 + bw:.1f},{top:.1f} {x0 + bw:.1f},{top + r:.1f} V{zero:.1f} Z"
                else:
                    d = f"M{x0:.1f},{zero:.1f} V{zero + h - r:.1f} Q{x0:.1f},{zero + h:.1f} {x0 + r:.1f},{zero + h:.1f} H{x0 + bw - r:.1f} Q{x0 + bw:.1f},{zero + h:.1f} {x0 + bw:.1f},{zero + h - r:.1f} V{zero:.1f} Z"
                out.append(f'<path d="{d}" fill="{SERIES[si]}"><title>{html.escape(s.get("name", ""))} · {html.escape(x[i])}: {_fmt(float(v))}</title></path>')
    else:
        for si, s in enumerate(series):
            pts = [(L + band * (i + 0.5), ys(v)) for i, v in enumerate(s["values"]) if v is not None]
            out.append(
                f'<polyline points="{" ".join(f"{a:.1f},{b:.1f}" for a, b in pts)}" fill="none" stroke="{SERIES[si]}" stroke-width="2" stroke-linejoin="round"/>'
            )
            for (a, b), v in zip(pts, [v for v in s["values"] if v is not None], strict=True):
                out.append(
                    f'<circle cx="{a:.1f}" cy="{b:.1f}" r="4" fill="{SERIES[si]}" stroke="{SURFACE}" stroke-width="2"><title>{html.escape(s.get("name", ""))}: {_fmt(float(v))}</title></circle>'
                )
    out.append(f'<line x1="{L}" x2="{W - R}" y1="{zero:.1f}" y2="{zero:.1f}" stroke="{INK_2}" stroke-width="1"/>')
    if len(series) >= 2:
        lx = L
        for si, s in enumerate(series):
            name = html.escape(str(s.get("name", f"Series {si + 1}"))[:28])
            out.append(
                f'<rect x="{lx}" y="34" width="10" height="10" rx="2" fill="{SERIES[si]}"/><text x="{lx + 14}" y="43" font-size="11" fill="{INK_2}">{name}</text>'
            )
            lx += 24 + 7 * len(name)
    out.append("</svg>")
    return "".join(out)


def table_markdown(spec: dict[str, Any]) -> str:
    """Accessible companion table for the chart (identity never rests on colour alone)."""
    head = "| " + " | ".join(["", *[str(s.get("name", "")) for s in spec["series"]]]) + " |"
    sep = "|" + "---|" * (len(spec["series"]) + 1)
    rows = [
        "| " + " | ".join([str(lab), *[_fmt(float(s["values"][i])) if s["values"][i] is not None else "—" for s in spec["series"]]]) + " |"
        for i, lab in enumerate(spec["x"])
    ]
    return "\n".join([head, sep, *rows])
