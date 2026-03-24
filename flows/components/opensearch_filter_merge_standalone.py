"""
Chat filter → OpenSearch request body merge (stdlib only).

Used by unit tests and kept in sync with the copy embedded in
``opensearch_multimodal.py`` for Langflow (no OpenRAG ``src`` imports).
"""

from __future__ import annotations

import copy
import json
from typing import Any


def _is_placeholder_term(term_obj: dict) -> bool:
    return any(v == "__IMPOSSIBLE_VALUE__" for v in term_obj.values())


def coerce_filter_clauses_from_filter_obj(filter_obj: dict | str | None) -> list[dict]:
    """Convert chat ``filter_expression`` JSON into OpenSearch filter clauses (term/terms).

    Format A — explicit filters:
        {"filter": [{"term": {...}}, {"terms": {...}}], "limit": ..., "score_threshold": ...}

    Format B — context-style keys (aligned with ``chat_service`` field mapping):
        data_sources → filename, document_types → mimetype, owners → owner,
        connector_types → connector_type.
    """
    if not filter_obj:
        return []

    if isinstance(filter_obj, str):
        try:
            filter_obj = json.loads(filter_obj)
        except json.JSONDecodeError:
            return []

    if not isinstance(filter_obj, dict):
        return []

    if "filter" in filter_obj:
        raw = filter_obj["filter"]
        if isinstance(raw, dict):
            raw = [raw]
        explicit_clauses: list[dict] = []
        for f in raw or []:
            if "term" in f and isinstance(f["term"], dict) and not _is_placeholder_term(f["term"]):
                explicit_clauses.append(f)
            elif "terms" in f and isinstance(f["terms"], dict):
                terms_map = f["terms"]
                if not terms_map:
                    continue
                field, vals = next(iter(terms_map.items()))
                if isinstance(vals, list) and len(vals) > 0:
                    explicit_clauses.append(f)
        return explicit_clauses

    field_mapping = {
        "data_sources": "filename",
        "document_types": "mimetype",
        "owners": "owner",
        "connector_types": "connector_type",
    }
    context_clauses: list[dict] = []
    for k, values in filter_obj.items():
        if not isinstance(values, list):
            continue
        field = field_mapping.get(k, k)
        if len(values) == 0:
            context_clauses.append({"term": {field: "__IMPOSSIBLE_VALUE__"}})
        elif len(values) == 1:
            if values[0] != "__IMPOSSIBLE_VALUE__":
                context_clauses.append({"term": {field: values[0]}})
        else:
            context_clauses.append({"terms": {field: values}})
    return context_clauses


def _append_to_bool_filter(bool_q: dict[str, Any], filter_clauses: list[dict]) -> None:
    existing = bool_q.get("filter")
    if existing is None:
        bool_q["filter"] = list(filter_clauses)
    elif isinstance(existing, list):
        bool_q["filter"] = [*existing, *filter_clauses]
    else:
        bool_q["filter"] = [existing, *filter_clauses]


def _inject_filter_into_top_level_knn(
    knn_payload: dict[str, Any], filter_clauses: list[dict]
) -> dict[str, Any]:
    """Add OpenSearch kNN ``filter`` to each vector field in a top-level ``knn`` block."""
    out = copy.deepcopy(knn_payload)
    scope = {"bool": {"filter": list(filter_clauses)}}
    for _field, spec in out.items():
        if not isinstance(spec, dict):
            continue
        existing = spec.get("filter")
        if existing is None:
            spec["filter"] = scope
        else:
            spec["filter"] = {"bool": {"must": [existing, scope]}}
    return out


def merge_filter_clauses_into_search_body(
    body: dict[str, Any], filter_clauses: list[dict]
) -> dict[str, Any]:
    """AND filter clauses into a search body. Does not mutate ``body``.

    - If there is no top-level ``query``, uses ``{"bool": {"filter": clauses}}`` — unless
      the body only has a top-level ``knn`` block (see below).
    - If ``query`` is already a ``bool`` query, appends to ``bool.filter`` (or wraps
      a single existing filter in a list).
    - Otherwise wraps the existing ``query`` as ``bool.must`` and sets ``bool.filter``.

    OpenSearch allows a **top-level** ``knn`` block (sibling of ``query``). Filters on
    ``query`` alone do not constrain that kNN execution; we inject the same clauses
    into each field's ``filter`` in the top-level ``knn`` map (see OpenSearch kNN docs).
    """
    if not filter_clauses:
        return copy.deepcopy(body)
    merged = copy.deepcopy(body)

    knn_block = merged.get("knn")
    if isinstance(knn_block, dict) and knn_block:
        merged["knn"] = _inject_filter_into_top_level_knn(knn_block, filter_clauses)

    q = merged.get("query")
    if q is None:
        # Avoid adding query={bool:filter} alone when kNN is already scoped above —
        # that combination can leave top-level kNN unscoped relative to the filter query.
        if isinstance(merged.get("knn"), dict) and merged["knn"]:
            return merged
        merged["query"] = {"bool": {"filter": filter_clauses}}
        return merged
    if isinstance(q, dict) and "bool" in q:
        _append_to_bool_filter(q["bool"], filter_clauses)
        return merged
    merged["query"] = {"bool": {"must": [q], "filter": filter_clauses}}
    return merged


def apply_chat_filter_limits_to_body(
    body: dict[str, Any], filter_obj: dict | None
) -> dict[str, Any]:
    """Apply ``limit`` / ``score_threshold`` from chat filter JSON when ``size`` / ``min_score`` are absent."""
    if not filter_obj:
        return copy.deepcopy(body)
    out = copy.deepcopy(body)
    if filter_obj.get("limit") is not None and "size" not in out:
        out["size"] = filter_obj["limit"]
    st = filter_obj.get("score_threshold")
    if isinstance(st, (int, float)) and st > 0 and "min_score" not in out:
        out["min_score"] = st
    return out


def _filter_expression_dict_for_limits(filter_expression: dict | str | None) -> dict | None:
    """Normalize ``filter_expression`` to a dict for :func:`apply_chat_filter_limits_to_body`, or ``None``."""
    if filter_expression is None:
        return None
    if isinstance(filter_expression, str):
        if not filter_expression.strip():
            return None
        try:
            parsed = json.loads(filter_expression)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    if isinstance(filter_expression, dict):
        return filter_expression
    return None


def apply_chat_filter_expression_to_search_body(
    raw_body: dict[str, Any],
    filter_expression: dict | str | None,
) -> dict[str, Any]:
    """Apply chat ``filter_expression`` to an OpenSearch request body (``raw_search`` pipeline).

    Order: coerce clauses → merge into ``query`` → apply ``limit`` / ``score_threshold``.
    Does not mutate ``raw_body``.
    """
    clauses = coerce_filter_clauses_from_filter_obj(filter_expression)
    merged = merge_filter_clauses_into_search_body(raw_body, clauses)
    limits_src = _filter_expression_dict_for_limits(filter_expression)
    return apply_chat_filter_limits_to_body(merged, limits_src)
