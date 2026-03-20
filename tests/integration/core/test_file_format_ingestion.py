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
  3. Polls /documents/check-filename to confirm content was indexed

Results are never hard-failed — every format records PASSED / FAILED / SKIPPED in
the shared ``ingestion_report`` fixture.  A formatted summary table is printed by
the pytest_terminal_summary hook defined in conftest.py.

Priority formats (pdf, docx, html) are highlighted in the report.

Skip conditions:
  - Langflow not running → format recorded as SKIPPED, test skipped
  - docling-serve not running + format requires docling → SKIPPED

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

# Formats whose failures are highlighted in the final report
_PRIORITY_FORMATS = {"pdf", "docx", "html"}


def _fmt_ids():
    return [case[0] for case in _FORMAT_CASES]


# ---------------------------------------------------------------------------
# Parametrized format ingestion test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("fmt,ext,content,req_docling", _FORMAT_CASES, ids=_fmt_ids())
async def test_ingest_format(tmp_path, fmt, ext, content, req_docling, ingestion_report):
    """
    Upload a file of format 'fmt' through the production Langflow ingestion pipeline
    and assert it is indexed in OpenSearch.

    Results are recorded in ``ingestion_report`` without raising — the test itself
    always exits cleanly so that all formats run.  Consult the ingestion report
    printed at the end of the session for pass / fail details.

    SKIPPED when Langflow is not running (all formats).
    SKIPPED when docling-serve is not running and the format requires it.
    """
    # --- Infrastructure checks — record SKIPPED and let pytest skip normally ---
    if not await is_langflow_available():
        ingestion_report[fmt] = {
            "status": "SKIPPED",
            "reason": "Langflow not running",
        }
        pytest.skip("Langflow not running — skipping format ingestion test")

    if req_docling and not await is_docling_available():
        ingestion_report[fmt] = {
            "status": "SKIPPED",
            "reason": "docling-serve not running",
        }
        pytest.skip(f"docling-serve not running — skipping {fmt} format test")

    # Boot app with production ingestion path (Langflow enabled)
    app, client = await boot_app(disable_langflow_ingest=False)
    try:
        filename = f"sample_openrag_{fmt}{ext}"

        # ------------------------------------------------------------------
        # Step 1 — Prepare file bytes
        # ------------------------------------------------------------------
        try:
            if isinstance(content, Path):
                if not content.exists():
                    raise FileNotFoundError(
                        f"Pre-baked sample file missing: {content}  "
                        f"Run: python tests/data/create_samples.py"
                    )
                file_bytes = content.read_bytes()
            else:
                file_bytes = content.encode("utf-8")
        except Exception as exc:
            _record_failure(ingestion_report, fmt, "file preparation", exc)
            return

        # ------------------------------------------------------------------
        # Step 2 — Upload via production route
        # ------------------------------------------------------------------
        try:
            files = {"file": (filename, file_bytes, "application/octet-stream")}
            upload_resp = await client.post("/router/upload_ingest", files=files)
            if upload_resp.status_code != 202:
                raise AssertionError(
                    f"Upload returned {upload_resp.status_code}: {upload_resp.text}"
                )
            body = upload_resp.json()
            task_id = body.get("task_id")
            if not task_id:
                raise AssertionError(f"202 response missing task_id: {body}")
        except Exception as exc:
            _record_failure(ingestion_report, fmt, "upload", exc)
            return

        # ------------------------------------------------------------------
        # Step 3 — Poll task until completion
        # ------------------------------------------------------------------
        try:
            task = await wait_for_task_completion(client, task_id, timeout_s=180)
            if task["status"] != "completed":
                raise AssertionError(
                    f"Task ended with status '{task['status']}': {task}"
                )
        except Exception as exc:
            _record_failure(ingestion_report, fmt, "task completion", exc)
            return

        # ------------------------------------------------------------------
        # Step 4 — Confirm file appears in the index (30 s window)
        # ------------------------------------------------------------------
        deadline = asyncio.get_event_loop().time() + 30
        found = False
        last_resp = None
        while asyncio.get_event_loop().time() < deadline:
            check_resp = await client.get(
                f"/documents/check-filename?filename={filename}"
            )
            if check_resp.status_code == 200 and check_resp.json().get("exists"):
                found = True
                break
            last_resp = check_resp
            await asyncio.sleep(1)

        if not found:
            reason = (
                f"'{filename}' not found in index within 30 s — task completed but "
                f"document was not indexed. "
                f"Last check: {last_resp.text if last_resp else 'none'}"
            )
            _record_failure(ingestion_report, fmt, "index verification", reason)
            return

        # ------------------------------------------------------------------
        # All steps passed
        # ------------------------------------------------------------------
        ingestion_report[fmt] = {"status": "PASSED"}
        _print_result(fmt, passed=True, detail=f"{filename} ({len(file_bytes)} bytes)")

    finally:
        await client.aclose()
        from config.settings import clients
        await clients.cleanup()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _record_failure(report: dict, fmt: str, step: str, exc) -> None:
    """Store a FAILED entry and print an inline notice (no exception raised)."""
    reason = f"[{step}] {exc}"
    report[fmt] = {"status": "FAILED", "reason": reason}
    _print_result(fmt, passed=False, detail=reason)


def _print_result(fmt: str, *, passed: bool, detail: str = "") -> None:
    symbol = "✓" if passed else "✗"
    priority = " [PRIORITY]" if fmt in _PRIORITY_FORMATS else ""
    status = "PASSED" if passed else "FAILED"
    print(f"\n{symbol} {fmt.upper()}{priority}: {status} — {detail}")
