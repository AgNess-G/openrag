"""
Shared fixtures and setup for OpenRAG SDK integration tests.

All tests in this directory require a running OpenRAG instance.
Set OPENRAG_URL (default: http://localhost:3000) before running.
"""

import os
import uuid
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

# ---------------------------------------------------------------------------
# File-format ingestion report (used by test_file_format_ingestion.py)
# ---------------------------------------------------------------------------

# Module-level dict populated by the format ingestion tests.
# Keys: format label ("pdf", "docx", …)
# Values: {"status": "PASSED"|"FAILED"|"SKIPPED", "reason": "…"}
_FORMAT_INGESTION_RESULTS: dict = {}

# Formats highlighted in the summary
_FORMAT_PRIORITY = {"pdf", "docx", "html"}


@pytest.fixture(scope="session")
def ingestion_report() -> dict:
    """Session-scoped dict for recording per-format ingestion results."""
    return _FORMAT_INGESTION_RESULTS


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Print the file-format ingestion report at the end of the session."""
    if not _FORMAT_INGESTION_RESULTS:
        return

    tw = terminalreporter
    passed  = {f: r for f, r in _FORMAT_INGESTION_RESULTS.items() if r["status"] == "PASSED"}
    failed  = {f: r for f, r in _FORMAT_INGESTION_RESULTS.items() if r["status"] == "FAILED"}
    skipped = {f: r for f, r in _FORMAT_INGESTION_RESULTS.items() if r["status"] == "SKIPPED"}

    tw.write_sep("=", "FILE FORMAT INGESTION REPORT")

    if passed:
        tw.write_line(
            f"\n  PASSED  ({len(passed)}):  {', '.join(sorted(passed))}",
            green=True,
        )

    if failed:
        tw.write_line(
            f"\n  FAILED  ({len(failed)}):  {', '.join(sorted(failed))}",
            red=True,
        )
        for fmt in sorted(failed):
            tag = "  [PRIORITY]" if fmt in _FORMAT_PRIORITY else ""
            tw.write_line(
                f"    {fmt}{tag}: {failed[fmt].get('reason', 'unknown')}",
                red=True,
            )

    if skipped:
        tw.write_line(
            f"\n  SKIPPED ({len(skipped)}):  {', '.join(sorted(skipped))}",
            yellow=True,
        )
        for fmt in sorted(skipped):
            tw.write_line(
                f"    {fmt}: {skipped[fmt].get('reason', 'unknown')}",
                yellow=True,
            )

    tw.write_sep(
        "-",
        f"Ingestion totals — passed: {len(passed)}, "
        f"failed: {len(failed)}, skipped: {len(skipped)}",
    )

_cached_api_key: str | None = None
_base_url = os.environ.get("OPENRAG_URL", "http://localhost:3000")
_onboarding_done = False


@pytest_asyncio.fixture(scope="session", autouse=True)
async def require_openrag():
    """Skip the entire test session if OpenRAG is not reachable."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as ac:
            r = await ac.get(f"{_base_url}/api/health")
            if r.status_code != 200:
                pytest.skip(f"OpenRAG not reachable at {_base_url} (status {r.status_code})")
    except Exception:
        pytest.skip(f"OpenRAG not reachable at {_base_url}")


@pytest_asyncio.fixture(scope="session", autouse=True)
async def ensure_onboarding(require_openrag):
    """Ensure the OpenRAG instance is onboarded before running tests.

    Uses httpx.AsyncClient so the async event loop is never blocked,
    even on a slow or unreachable server.
    """
    global _onboarding_done
    if _onboarding_done:
        return

    onboarding_payload = {
        "llm_provider": "openai",
        "embedding_provider": "openai",
        "embedding_model": "text-embedding-3-small",
        "llm_model": "gpt-4o-mini",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as ac:
            response = await ac.post(
                f"{_base_url}/api/onboarding",
                json=onboarding_payload,
            )
        if response.status_code in (200, 204):
            print("[SDK Tests] Onboarding completed successfully")
        else:
            print(f"[SDK Tests] Onboarding returned {response.status_code}: {response.text[:200]}")
    except Exception as e:
        print(f"[SDK Tests] Onboarding request failed: {e}")

    _onboarding_done = True


async def _fetch_api_key() -> str:
    """Fetch or create a test API key from the running instance (async, cached)."""
    global _cached_api_key
    if _cached_api_key is not None:
        return _cached_api_key

    async with httpx.AsyncClient(timeout=30.0) as ac:
        response = await ac.post(
            f"{_base_url}/api/keys",
            json={"name": "SDK Integration Test"},
        )

    if response.status_code == 401:
        pytest.skip("Cannot create API key — authentication required")

    assert response.status_code == 200, f"Failed to create API key: {response.text}"
    _cached_api_key = response.json()["api_key"]
    return _cached_api_key


@pytest_asyncio.fixture
async def client():
    """OpenRAG client authenticated with a valid test API key."""
    from openrag_sdk import OpenRAGClient

    api_key = await _fetch_api_key()
    c = OpenRAGClient(api_key=api_key, base_url=_base_url)
    yield c
    await c.close()


@pytest.fixture
def base_url() -> str:
    """The base URL of the running OpenRAG instance."""
    return _base_url


@pytest.fixture
def test_file(tmp_path) -> Path:
    """A uniquely-named markdown file ready for ingestion."""
    file_path = tmp_path / f"sdk_test_doc_{uuid.uuid4().hex[:8]}.md"
    file_path.write_text(
        f"# SDK Integration Test Document\n\n"
        f"ID: {uuid.uuid4()}\n\n"
        "This document tests the OpenRAG Python SDK.\n\n"
        "It contains unique content about purple elephants dancing.\n"
    )
    return file_path
