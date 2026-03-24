"""
Unit tests for merging chat knowledge filters into OpenSearch raw search bodies.

These specify behavior for ``utils.opensearch_filter_merge`` before the Langflow
OpenSearch component calls into it from ``raw_search``.
"""

from __future__ import annotations

import copy
import json

import pytest

from utils.opensearch_filter_merge import (
    apply_chat_filter_expression_to_search_body,
    apply_chat_filter_limits_to_body,
    coerce_filter_clauses_from_filter_obj,
    merge_filter_clauses_into_search_body,
)

TERM_DOC = {"term": {"filename": "a.pdf"}}
TERM_OWNER = {"term": {"owner": "u1"}}


class TestCoerceFilterClausesFromFilterObj:
    def test_none_returns_empty(self):
        assert coerce_filter_clauses_from_filter_obj(None) == []

    def test_invalid_json_string_returns_empty(self):
        assert coerce_filter_clauses_from_filter_obj("{not json") == []

    def test_explicit_filter_term_and_terms(self):
        obj = {
            "filter": [
                {"term": {"filename": "x.pdf"}},
                {"terms": {"owner": ["a", "b"]}},
            ],
            "limit": 10,
        }
        assert coerce_filter_clauses_from_filter_obj(obj) == [
            {"term": {"filename": "x.pdf"}},
            {"terms": {"owner": ["a", "b"]}},
        ]

    def test_explicit_skips_placeholder_term(self):
        obj = {
            "filter": [
                {"term": {"filename": "__IMPOSSIBLE_VALUE__"}},
                {"term": {"mimetype": "application/pdf"}},
            ],
        }
        assert coerce_filter_clauses_from_filter_obj(obj) == [
            {"term": {"mimetype": "application/pdf"}},
        ]

    def test_explicit_terms_empty_dict_skipped(self):
        """Empty ``terms`` map must not crash on ``next(iter(...))``."""
        obj = {"filter": [{"terms": {}}]}
        assert coerce_filter_clauses_from_filter_obj(obj) == []

    def test_explicit_single_dict_filter_wrapped(self):
        obj = {"filter": {"term": {"connector_type": "upload"}}}
        assert coerce_filter_clauses_from_filter_obj(obj) == [
            {"term": {"connector_type": "upload"}},
        ]

    def test_context_data_sources_and_document_types(self):
        obj = {
            "data_sources": ["a.pdf", "b.pdf"],
            "document_types": ["application/pdf"],
        }
        assert coerce_filter_clauses_from_filter_obj(obj) == [
            {"terms": {"filename": ["a.pdf", "b.pdf"]}},
            {"term": {"mimetype": "application/pdf"}},
        ]

    def test_connector_types_maps_to_connector_type(self):
        obj = {"connector_types": ["upload", "s3"]}
        assert coerce_filter_clauses_from_filter_obj(obj) == [
            {"terms": {"connector_type": ["upload", "s3"]}},
        ]

    def test_empty_selection_list_is_impossible_term(self):
        obj = {"data_sources": []}
        assert coerce_filter_clauses_from_filter_obj(obj) == [
            {"term": {"filename": "__IMPOSSIBLE_VALUE__"}},
        ]

    def test_json_string_input(self):
        s = '{"data_sources": ["doc.pdf"]}'
        assert coerce_filter_clauses_from_filter_obj(s) == [{"term": {"filename": "doc.pdf"}}]

    def test_non_object_json_returns_empty(self):
        assert coerce_filter_clauses_from_filter_obj("[1,2]") == []


class TestMergeFilterClausesIntoSearchBody:
    def test_empty_clauses_returns_deep_copy(self):
        body = {"query": {"match_all": {}}, "size": 5}
        out = merge_filter_clauses_into_search_body(body, [])
        assert out == body
        assert out is not body
        out["size"] = 99
        assert body["size"] == 5

    def test_no_query_key_adds_bool_filter(self):
        body: dict = {"size": 10}
        out = merge_filter_clauses_into_search_body(body, [TERM_DOC])
        assert out == {
            "size": 10,
            "query": {"bool": {"filter": [TERM_DOC]}},
        }

    def test_bool_without_filter_sets_filter(self):
        body = {
            "query": {
                "bool": {
                    "must": [{"match": {"text": "hello"}}],
                }
            }
        }
        out = merge_filter_clauses_into_search_body(body, [TERM_DOC])
        assert out["query"]["bool"]["must"] == [{"match": {"text": "hello"}}]
        assert out["query"]["bool"]["filter"] == [TERM_DOC]

    def test_bool_with_should_only_adds_filter(self):
        body = {
            "query": {
                "bool": {
                    "should": [{"match": {"text": "x"}}],
                    "minimum_should_match": 1,
                }
            }
        }
        out = merge_filter_clauses_into_search_body(body, [TERM_DOC])
        assert out["query"]["bool"]["filter"] == [TERM_DOC]
        assert out["query"]["bool"]["should"] == [{"match": {"text": "x"}}]

    def test_bool_with_filter_list_extends(self):
        body = {
            "query": {
                "bool": {
                    "filter": [{"term": {"connector_type": "upload"}}],
                    "must": [{"match_all": {}}],
                }
            }
        }
        out = merge_filter_clauses_into_search_body(body, [TERM_DOC])
        assert out["query"]["bool"]["filter"] == [
            {"term": {"connector_type": "upload"}},
            TERM_DOC,
        ]

    def test_bool_with_single_filter_becomes_list(self):
        body = {
            "query": {
                "bool": {
                    "filter": {"term": {"mimetype": "application/pdf"}},
                }
            }
        }
        out = merge_filter_clauses_into_search_body(body, [TERM_DOC])
        assert out["query"]["bool"]["filter"] == [
            {"term": {"mimetype": "application/pdf"}},
            TERM_DOC,
        ]

    def test_non_bool_query_wrapped_in_must(self):
        body = {"query": {"match": {"text": "q"}}}
        out = merge_filter_clauses_into_search_body(body, [TERM_DOC, TERM_OWNER])
        assert out["query"] == {
            "bool": {
                "must": [{"match": {"text": "q"}}],
                "filter": [TERM_DOC, TERM_OWNER],
            }
        }

    def test_original_body_not_mutated(self):
        body = {"query": {"match_all": {}}}
        original = copy.deepcopy(body)
        merge_filter_clauses_into_search_body(body, [TERM_DOC])
        assert body == original

    def test_top_level_knn_gets_per_field_filter_not_bare_query_filter(self):
        """Top-level ``knn`` must be scoped via each field's ``filter``, not only ``query``."""
        scope = {"bool": {"filter": [TERM_DOC]}}
        body = {
            "size": 5,
            "knn": {
                "chunk_embedding_x": {
                    "vector": [0.1, 0.2],
                    "k": 10,
                }
            },
        }
        out = merge_filter_clauses_into_search_body(body, [TERM_DOC])
        assert "query" not in out
        assert out["knn"]["chunk_embedding_x"]["filter"] == scope
        assert out["size"] == 5

    def test_top_level_knn_with_existing_query_injects_knn_and_merges_query(self):
        scope = {"bool": {"filter": [TERM_DOC]}}
        body = {
            "knn": {"field_a": {"vector": [1.0], "k": 5}},
            "query": {"match": {"text": "hello"}},
        }
        out = merge_filter_clauses_into_search_body(body, [TERM_DOC])
        assert out["knn"]["field_a"]["filter"] == scope
        assert out["query"] == {
            "bool": {
                "must": [{"match": {"text": "hello"}}],
                "filter": [TERM_DOC],
            }
        }

    def test_top_level_knn_preserves_existing_field_filter(self):
        scope = {"bool": {"filter": [TERM_DOC]}}
        body = {
            "knn": {
                "vec": {
                    "vector": [0.0],
                    "k": 3,
                    "filter": {"term": {"owner": "x"}},
                }
            },
        }
        out = merge_filter_clauses_into_search_body(body, [TERM_DOC])
        assert out["knn"]["vec"]["filter"] == {
            "bool": {
                "must": [
                    {"term": {"owner": "x"}},
                    scope,
                ]
            }
        }


class TestApplyChatFilterLimitsToBody:
    def test_none_filter_returns_deep_copy(self):
        body = {"query": {"match_all": {}}}
        out = apply_chat_filter_limits_to_body(body, None)
        assert out == body
        assert out is not body

    def test_sets_size_from_limit_when_missing(self):
        body = {"query": {"match_all": {}}}
        out = apply_chat_filter_limits_to_body(
            body, {"limit": 25, "filter": [], "score_threshold": 0}
        )
        assert out["size"] == 25

    def test_respects_existing_size(self):
        body = {"query": {"match_all": {}}, "size": 100}
        out = apply_chat_filter_limits_to_body(body, {"limit": 25})
        assert out["size"] == 100

    def test_sets_min_score_when_positive_and_missing(self):
        body = {"query": {"match_all": {}}}
        out = apply_chat_filter_limits_to_body(body, {"score_threshold": 1.5})
        assert out["min_score"] == 1.5

    def test_skips_min_score_when_zero(self):
        body = {"query": {"match_all": {}}}
        out = apply_chat_filter_limits_to_body(body, {"score_threshold": 0})
        assert "min_score" not in out

    def test_respects_existing_min_score(self):
        body = {"query": {"match_all": {}}, "min_score": 2.0}
        out = apply_chat_filter_limits_to_body(body, {"score_threshold": 1.5})
        assert out["min_score"] == 2.0

    def test_empty_filter_object_like_no_limits(self):
        """Chat may send `{}` when no filter — treat as no-op for limits."""
        body = {"query": {"match_all": {}}}
        out = apply_chat_filter_limits_to_body(body, {})
        assert out == body
        assert out is not body
        assert "size" not in out and "min_score" not in out

    def test_negative_score_threshold_skipped(self):
        body = {"query": {"match_all": {}}}
        out = apply_chat_filter_limits_to_body(body, {"score_threshold": -0.5})
        assert "min_score" not in out

    def test_limit_zero_applied_when_missing_size(self):
        """PEP 440 / API may use 0; we only skip when key is absent."""
        body = {"query": {"match_all": {}}}
        out = apply_chat_filter_limits_to_body(body, {"limit": 0})
        assert out["size"] == 0


class TestApplyChatFilterExpressionToSearchBody:
    """Single entry point for the Langflow ``raw_search`` path (utils-only contract)."""

    def test_end_to_end_context_filter_limit_and_score_dict_and_json_string(self):
        raw = {"query": {"match_all": {}}}
        filt: dict = {
            "data_sources": ["x.pdf"],
            "limit": 7,
            "score_threshold": 1.2,
        }
        expected_term = {"term": {"filename": "x.pdf"}}
        out = apply_chat_filter_expression_to_search_body(raw, filt)
        assert out["query"]["bool"]["filter"] == [expected_term]
        assert out["size"] == 7
        assert out["min_score"] == 1.2

        out_str = apply_chat_filter_expression_to_search_body(raw, json.dumps(filt))
        assert out_str == out

    def test_none_returns_deep_copy_without_filters(self):
        raw = {"query": {"match_all": {}}, "size": 10}
        out = apply_chat_filter_expression_to_search_body(raw, None)
        assert out == raw
        assert out is not raw


class TestMergeThenApplyIntegration:
    """Order used in raw_search: merge filters, then apply limit/score."""

    def test_merge_preserves_aggs_and_source(self):
        body = {
            "query": {"match": {"text": "x"}},
            "aggs": {"by_owner": {"terms": {"field": "owner.keyword"}}},
            "_source": ["text", "filename"],
            "size": 50,
        }
        out = merge_filter_clauses_into_search_body(body, [TERM_DOC])
        assert out["aggs"] == body["aggs"]
        assert out["_source"] == body["_source"]
        assert out["size"] == 50
        assert "bool" in out["query"]

    def test_chained_merge_then_apply(self):
        body = {"query": {"match_all": {}}}
        merged = merge_filter_clauses_into_search_body(body, [TERM_DOC])
        final = apply_chat_filter_limits_to_body(merged, {"limit": 5, "score_threshold": 1.2})
        assert final["query"]["bool"]["filter"] == [TERM_DOC]
        assert final["size"] == 5
        assert final["min_score"] == 1.2


@pytest.mark.parametrize(
    "clauses,expected_query",
    [
        (
            [TERM_DOC],
            {"bool": {"must": [{"match": {"text": "x"}}], "filter": [TERM_DOC]}},
        ),
        ([], {"match": {"text": "x"}}),
    ],
)
def test_merge_parametrized(clauses, expected_query):
    body = {"query": {"match": {"text": "x"}}}
    out = merge_filter_clauses_into_search_body(body, clauses)
    assert out["query"] == expected_query
