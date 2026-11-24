"""Model catalog: remove TEA-800 and Gemini 2.x, add Gemini 3.x; GN7T placeholder cleanup.

Revision ID: 0010
Revises: 0009

0003 (the historical seed) still creates the old rows, so every database, new or existing, passes
through the same path: seed, then this migration removes them. Routes are not dropped: a removed
model's slot is filled by its replacement (Gemini 2.5 Pro → Gemini 3.8 Flash, Gemini 2.5 Flash →
Gemini 3.5 Flash-Lite); a removed model without a replacement just leaves the chain. Admin-chosen
priorities and parameters are kept. Downgrade is not supported: the removed rows are not restored.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

NS = uuid.UUID("6f1d3c52-6a8e-4f0b-9a57-2b3c9d0e7a11")  # same namespace as 0003, so ids are stable


def sid(name: str) -> uuid.UUID:
    return uuid.uuid5(NS, name)


#: New catalog entries. Prices are the standard per-1M-token rates from Google's pricing pages.
#: Gemini 3.8 Flash has an introductory rate ($0.75 / $3.75) until 31 Dec 2026; the standard rate is
#: recorded here and can be changed by a super-admin with PATCH /v1/admin/models/{id}.
NEW_MODELS = [
    ("gemini", "gemini-3.8-flash", "Gemini 3.8 Flash", ["reasoning", "text", "code", "long_context", "vision", "creative", "summarize"], 1.50, 7.50),
    ("gemini", "gemini-3.6-flash", "Gemini 3.6 Flash", ["reasoning", "text", "code", "long_context", "vision", "creative", "summarize"], 1.50, 7.50),
    ("gemini", "gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite", ["text", "summarize", "classify", "creative"], 0.30, 2.50),
]

#: Old model → replacement, used wherever a route pointed at the old model.
REPLACEMENTS = {
    ("gemini", "gemini-2.5-pro"): ("gemini", "gemini-3.8-flash"),
    ("gemini", "gemini-2.5-flash"): ("gemini", "gemini-3.5-flash-lite"),
}

#: Models removed outright. tea800 is the TEA-800 provider (all its models go with it).
#: gn7t-embed is a placeholder: GN7T's OpenAI-compatible API has no embeddings endpoint.
REMOVED_PROVIDERS = ("tea800",)
REMOVED_MODELS = (("gn7t", "gn7t-embed"),)

MAX_FALLBACKS = 3  # priorities 0..3, as enforced by the model_routes check constraint


def _model_id(conn, provider_key: str, name: str):
    return conn.execute(
        sa.text("SELECT m.id FROM models m JOIN model_providers p ON p.id = m.provider_id WHERE p.key = :p AND m.name = :n"),
        {"p": provider_key, "n": name},
    ).scalar()


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Add the new Gemini models (idempotent: re-running must not duplicate them).
    provider_ids = {k: i for k, i in conn.execute(sa.text("SELECT key, id FROM model_providers")).all()}
    for prov, name, label, caps, pin, pout in NEW_MODELS:
        conn.execute(
            sa.text(
                "INSERT INTO models (id, provider_id, name, label, capabilities, price_in_per_1m, price_out_per_1m, enabled) "
                "VALUES (:id, :p, :n, :l, :c, :pi, :po, true) ON CONFLICT (provider_id, name) DO NOTHING"
            ),
            {"id": sid(f"model:{prov}/{name}"), "p": provider_ids[prov], "n": name, "l": label, "c": caps, "pi": pin, "po": pout},
        )

    # 2. Work out which models go and what replaces them.
    removed_pairs = set(REMOVED_MODELS)
    for prov in REMOVED_PROVIDERS:
        for (name,) in conn.execute(
            sa.text("SELECT m.name FROM models m JOIN model_providers p ON p.id = m.provider_id WHERE p.key = :p"), {"p": prov}
        ).all():
            removed_pairs.add((prov, name))
    for old in REPLACEMENTS:
        removed_pairs.add(old)
    removed_ids = {i for i in (_model_id(conn, p, n) for p, n in removed_pairs) if i is not None}
    replacement_ids = {}
    for old, new in REPLACEMENTS.items():
        old_id = _model_id(conn, *old)
        if old_id is not None:
            replacement_ids[old_id] = _model_id(conn, *new)

    # 3. Rebuild every route chain that touched a removed or replaced model (all scopes).
    groups = conn.execute(
        sa.text(
            "SELECT DISTINCT scope, scope_id, capability FROM model_routes WHERE model_id = ANY(CAST(:ids AS uuid[]))"
        ),
        {"ids": [str(i) for i in removed_ids | set(replacement_ids)]},
    ).all()
    for scope, scope_id, capability in groups:
        rows = conn.execute(
            sa.text(
                "SELECT priority, model_id, params, updated_by FROM model_routes "
                "WHERE scope = :s AND scope_id IS NOT DISTINCT FROM CAST(:sid AS uuid) AND capability = :c ORDER BY priority"
            ),
            {"s": scope, "sid": scope_id, "c": capability},
        ).all()
        chain: list[tuple] = []
        seen: set = set()
        for _priority, model_id, params, updated_by in rows:
            if model_id in replacement_ids:
                model_id = replacement_ids[model_id]
            elif model_id in removed_ids:
                continue
            if model_id in seen:
                continue
            seen.add(model_id)
            chain.append((model_id, params, updated_by))
        conn.execute(
            sa.text("DELETE FROM model_routes WHERE scope = :s AND scope_id IS NOT DISTINCT FROM CAST(:sid AS uuid) AND capability = :c"),
            {"s": scope, "sid": scope_id, "c": capability},
        )
        for priority, (model_id, params, updated_by) in enumerate(chain[: MAX_FALLBACKS + 1]):
            conn.execute(
                sa.text(
                    "INSERT INTO model_routes (id, scope, scope_id, capability, priority, model_id, params, updated_by) "
                    "VALUES (:id, :s, :sid, :c, :prio, :m, CAST(:params AS jsonb), :ub)"
                ),
                {
                    "id": uuid.uuid4(),
                    "s": scope,
                    "sid": scope_id,
                    "c": capability,
                    "prio": priority,
                    "m": model_id,
                    "params": _json(params),
                    "ub": updated_by,
                },
            )

    # 4. Delete the removed models, then the TEA-800 provider (its credentials cascade with it).
    for model_id in removed_ids:
        conn.execute(sa.text("DELETE FROM models WHERE id = :id"), {"id": model_id})
    for prov in REMOVED_PROVIDERS:
        conn.execute(sa.text("DELETE FROM model_providers WHERE key = :p"), {"p": prov})


def _json(value) -> str:
    import json

    return json.dumps(value if value is not None else {})


def downgrade() -> None:
    raise NotImplementedError("0010 removes TEA-800 and Gemini 2.x rows and is not reversible; restore from a backup instead.")
