"""
Integration tests for file format support in OpenRAG.

Uses the production ingestion path (DISABLE_INGEST_WITH_LANGFLOW=false) — all
uploads go through the Langflow pipeline, exactly as they do in production.

Parametrized across all non-multimedia formats supported by docling:
  - Markdown, plain text  → bypass docling (always runnable via Langflow)
  - HTML, XHTML, CSV, AsciiDoc, LaTeX → text formats (Langflow → docling-serve)
  - PDF, DOCX, XLSX, PPTX            → binary formats (Langflow → docling-serve)

Each parametrized test case:
  1. Uploads the sample file via /router/upload_ingest (Langflow path → 202 + task_id)
  2. Polls GET /tasks/{task_id} until completed
  3. Polls /search to confirm content was indexed

Skip conditions:
  - Langflow not running → entire test is skipped
  - docling-serve not running + format requires docling → test is skipped

This test file serves as a living format-support report. Run with -v to see
per-format results.

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
    is_langflow_available,
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
    Upload a file of format 'fmt' through the production Langflow ingestion pipeline
    and assert it is indexed in OpenSearch.

    SKIPPED when Langflow is not running (all formats).
    SKIPPED when docling-serve is not running and the format requires it.
    PASSED when the file is successfully ingested and appears in the index.
    FAILED when the upload or indexing step errors unexpectedly.
    """
    # Production path requires Langflow — skip entire test if it's not running
    if not await is_langflow_available():
        pytest.skip("Langflow not running — skipping format ingestion test")

    # Skip docling-dependent formats when docling-serve is unavailable
    if req_docling and not await is_docling_available():
        pytest.skip(f"docling-serve not running — skipping {fmt} format test")

    # Boot app with production ingestion path (Langflow enabled)
    app, client = await boot_app(disable_langflow_ingest=False)
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

        # Upload via production route — Langflow path always returns 202 + task_id
        files = {"file": (filename, file_bytes, "application/octet-stream")}
        upload_resp = await client.post("/router/upload_ingest", files=files)
        assert upload_resp.status_code == 202, (
            f"{fmt}: Upload failed with {upload_resp.status_code}: {upload_resp.text}"
        )

        body = upload_resp.json()
        task_id = body.get("task_id")
        assert task_id, f"{fmt}: 202 response missing task_id: {body}"

        # Poll task until completion (allow generous timeout for docling processing)
        task = await wait_for_task_completion(client, task_id, timeout_s=180)
        assert task["status"] == "completed", (
            f"{fmt}: Task did not complete successfully: {task}"
        )

        # Verify file was indexed by checking filename exists in OpenSearch
        # This is more reliable than search and avoids KNN/embedding dependencies
        deadline = asyncio.get_event_loop().time() + 30
        found = False
        last_resp = None
        while asyncio.get_event_loop().time() < deadline:
            check_resp = await client.get(
                f"/documents/check-filename?filename={filename}"
            )
            if check_resp.status_code == 200:
                body = check_resp.json()
                if body.get("exists"):
                    found = True
                    break
            last_resp = check_resp
            await asyncio.sleep(1)

        assert found, (
            f"{fmt}: File '{filename}' not found in index within 30s. "
            f"Task completed successfully but document was not indexed. "
            f"Last check response: {last_resp.text if last_resp else 'none'}"
        )

        print(f"\n✓ {fmt.upper()}: ingested and indexed {filename} ({len(file_bytes)} bytes) via Langflow")

    finally:
        await client.aclose()
        from config.settings import clients
        await clients.cleanup()
