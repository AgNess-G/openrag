"""Tests for the component registry."""

from __future__ import annotations

import pytest

from pipeline.registry import ComponentRegistry


def test_register_and_get():
    reg = ComponentRegistry()

    class FakeParser:
        pass

    reg.register("fake", "parser", FakeParser)
    assert reg.get("fake", "parser") is FakeParser


def test_get_unknown_raises():
    reg = ComponentRegistry()
    with pytest.raises(KeyError, match="No parser registered with name 'missing'"):
        reg.get("missing", "parser")


def test_list_components():
    reg = ComponentRegistry()

    class A:
        pass

    class B:
        pass

    reg.register("a", "chunker", A)
    reg.register("b", "chunker", B)
    assert sorted(reg.list_components("chunker")) == ["a", "b"]


def test_has():
    reg = ComponentRegistry()

    class X:
        pass

    reg.register("x", "embedder", X)
    assert reg.has("x", "embedder")
    assert not reg.has("y", "embedder")


def test_invalid_stage_type():
    reg = ComponentRegistry()
    with pytest.raises(ValueError, match="Invalid stage_type"):
        reg.register("foo", "invalid_type", object)
