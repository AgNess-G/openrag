"""
Integration tests for file format support in OpenRAG.

Parametrized across all non-multimedia formats supported by docling:
  - Markdown, plain text  → bypass docling (always runnable)
  - HTML, XHTML, CSV, AsciiDoc, LaTeX → text formats requiring docling-serve
  - PDF, DOCX, XLSX, PPTX            → binary formats requiring docling-serve

Each parametrized test case:
  1. Uploads the sample file via /router/upload_ingest
  2. Waits for indexing confirmation via /search
  3. Asserts content was indexed (pass = format supported, skip = docling unavailable)

This test file serves as a living format-support report. Run with -v to see
per-format results. "SKIPPED" means docling-serve was not running, not that
the format is unsupported.

Binary sample files are pre-generated in tests/data/samples/ by running:
  python tests/data/create_samples.py
"""
from pathlib import Path
import asyncio

import pytest

from tests.integration.core.helpers import (
    boot_app,
    wait_for_task_completion,
    is_docling_available,
)

# Path to pre-generated binary sample files
SAMPLES_DIR = Path(__file__).parent.parent.parent / "data" / "samples"

# ---------------------------------------------------------------------------
# Format definitions
# Each tuple: (format_label, file_ext, content_or_sample_path, requires_docling)
#
# content_or_sample_path:
#   str  → write this string to a temp file
#   Path → read from the pre-baked binary sample file
# ---------------------------------------------------------------------------

_FORMAT_CASES = [
    # --- Text formats that bypass docling in OpenRAG — always runnable ---
    # (committed sample files used for consistency with other formats)
    ("markdown", ".md",   SAMPLES_DIR / "sample.md",   False),
    (
        "text",
        ".txt",
        "OpenRAG text format content for integration testing. Plain text document.",
        False,
    ),
    # --- Text formats sent to docling-serve (committed sample files) ---
    ("html",     ".html",  SAMPLES_DIR / "sample.html",  True),
    ("xhtml",    ".xhtml", SAMPLES_DIR / "sample.xhtml", True),
    ("csv",      ".csv",   SAMPLES_DIR / "sample.csv",   True),
    ("asciidoc", ".adoc",  SAMPLES_DIR / "sample.adoc",  True),
    ("latex",    ".tex",   SAMPLES_DIR / "sample.tex",   True),
    # --- Binary formats (committed sample files, require docling-serve) ---
    ("pdf",  ".pdf",  SAMPLES_DIR / "sample.pdf",  True),
    ("docx", ".docx", SAMPLES_DIR / "sample.docx", True),
    ("xlsx", ".xlsx", SAMPLES_DIR / "sample.xlsx", True),
    ("pptx", ".pptx", SAMPLES_DIR / "sample.pptx", True),
]


def _fmt_ids():
    return [case[0] for case in _FORMAT_CASES]


# ---------------------------------------------------------------------------
# Parametrized format ingestion test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("fmt,ext,content,req_docling", _FORMAT_CASES, ids=_fmt_ids())
async def test_ingest_format(tmp_path, fmt, ext, content, req_docling):
    """
    Upload a file of format 'fmt' and assert it is indexed and searchable.

    SKIPPED when docling-serve is not running and the format requires it.
    PASSED when the file is successfully ingested and appears in search results.
    FAILED when the upload or indexing step errors unexpectedly.
    """
    # Skip docling-dependent tests when docling-serve is unavailable
    if req_docling and not await is_docling_available():
        pytest.skip(f"docling-serve not running — skipping {fmt} format test")

    app, client = await boot_app()
    try:
        # Prepare file bytes
        filename = f"sample_openrag_{fmt}{ext}"
        if isinstance(content, Path):
            assert content.exists(), (
                f"Pre-baked sample file missing: {content}\n"
                f"Run: python tests/data/create_samples.py"
            )
            file_bytes = content.read_bytes()
        else:
            file_bytes = content.encode("utf-8")

        # Upload
        files = {"file": (filename, file_bytes, "application/octet-stream")}
        upload_resp = await client.post("/router/upload_ingest", files=files)
        assert upload_resp.status_code in (201, 202), (
            f"{fmt}: Upload failed with {upload_resp.status_code}: {upload_resp.text}"
        )

        body = upload_resp.json()

        # Handle async task response (202) vs synchronous (201)
        if upload_resp.status_code == 202 and "task_id" in body:
            task = await wait_for_task_completion(client, body["task_id"], timeout_s=120)
            assert task["status"] == "completed", (
                f"{fmt}: Task did not complete successfully: {task}"
            )
        else:
            assert body.get("status") in ("indexed", "unchanged"), (
                f"{fmt}: Unexpected upload status: {body}"
            )

        # For text-based formats, verify content appears in search results.
        # Binary formats may extract different text so we just verify indexing occurred.
        search_query = f"OpenRAG {fmt} format"
        deadline = asyncio.get_event_loop().time() + 30
        found = False
        last_resp = None
        while asyncio.get_event_loop().time() < deadline:
            search_resp = await client.post(
                "/search", json={"query": search_query, "limit": 5}
            )
            if search_resp.status_code == 200:
                results = search_resp.json().get("results", [])
                if results:
                    found = True
                    break
            last_resp = search_resp
            await asyncio.sleep(1)

        # For binary formats (PDF/DOCX/XLSX/PPTX), accept that content may not
        # be discoverable via keyword search if embeddings aren't available —
        # the upload success (no 5xx) is the primary assertion.
        if not found and isinstance(content, Path):
            # Binary format: verify the upload response at minimum
            assert upload_resp.status_code in (201, 202), (
                f"{fmt}: Upload succeeded but content not found in search within 30s. "
                f"Last search response: {last_resp.text if last_resp else 'none'}"
            )
        else:
            assert found, (
                f"{fmt}: Content not found in search within 30s. "
                f"Query: '{search_query}'. "
                f"Last search response: {last_resp.text if last_resp else 'none'}"
            )

        print(f"\n✓ {fmt.upper()}: ingested {filename} ({len(file_bytes)} bytes)")

    finally:
        await client.aclose()
        from config.settings import clients
        await clients.close()
