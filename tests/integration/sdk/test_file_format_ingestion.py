"""
SDK-based file format ingestion tests.

Tests against the real running OpenRAG stack (OPENRAG_URL env var,
default http://localhost:3000).  Because these tests talk to the actual
deployed service, Langflow's OpenSearch component is already configured
and pointing at the same index that the API reads — no boot_app / clean
index mismatch.

The ground truth for "was the document indexed?" is
``result.successful_files > 0`` returned by
``client.documents.ingest(wait=True)``.  The SDK polls the task until it
reaches a terminal state and returns the task summary, including the count
of files that were actually committed to the index.

Parametrized across all non-multimedia formats:
  - Markdown, plain text  → bypass docling
  - HTML, XHTML, CSV, AsciiDoc, LaTeX → sent to docling-serve
  - PDF, DOCX, XLSX, PPTX            → binary, docling-serve required

Skip conditions:
  - OpenRAG not reachable → ALL formats skipped
  - docling-serve not running + format requires it → that format skipped

Results are never hard-raised — the pytest_terminal_summary hook in
conftest.py prints a formatted report after all tests finish.
Priority formats (pdf, docx, html) are flagged prominently in failures.

Binary sample files must exist in tests/data/samples/ — generate them with:
    python tests/data/create_samples.py
"""
import io
from pathlib import Path

import pytest

from tests.integration.core.helpers import is_docling_available

# ---------------------------------------------------------------------------
# Format table
# ---------------------------------------------------------------------------

SAMPLES_DIR = Path(__file__).parent.parent.parent / "data" / "samples"

_FORMAT_CASES = [
    # (fmt, ext, content_or_path, requires_docling)
    ("markdown", ".md",   SAMPLES_DIR / "sample.md",   False),
    (
        "text",
        ".txt",
        "OpenRAG text format content for integration testing. Plain text document.",
        False,
    ),
    ("html",     ".html",  SAMPLES_DIR / "sample.html",  True),
    ("xhtml",    ".xhtml", SAMPLES_DIR / "sample.xhtml", True),
    ("csv",      ".csv",   SAMPLES_DIR / "sample.csv",   True),
    ("asciidoc", ".adoc",  SAMPLES_DIR / "sample.adoc",  True),
    ("latex",    ".tex",   SAMPLES_DIR / "sample.tex",   True),
    ("pdf",      ".pdf",   SAMPLES_DIR / "sample.pdf",   True),
    ("docx",     ".docx",  SAMPLES_DIR / "sample.docx",  True),
    ("xlsx",     ".xlsx",  SAMPLES_DIR / "sample.xlsx",  True),
    ("pptx",     ".pptx",  SAMPLES_DIR / "sample.pptx",  True),
]

_PRIORITY_FORMATS = {"pdf", "docx", "html"}

def _fmt_ids():
    return [c[0] for c in _FORMAT_CASES]


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("fmt,ext,content,req_docling", _FORMAT_CASES, ids=_fmt_ids())
async def test_ingest_format(fmt, ext, content, req_docling, ingestion_report, client):
    """
    Ingest a sample file of format 'fmt' via the SDK and verify it was indexed.

    Uses ``client.documents.ingest(wait=True)`` which polls the task until
    completion and returns the final task summary including ``successful_files``.
    ``successful_files > 0`` means at least one chunk reached the OpenSearch index.

    The test never raises — results are recorded in ``ingestion_report`` and
    reported by pytest_terminal_summary at the end of the session.
    """
    # ------------------------------------------------------------------
    # Infrastructure availability checks
    # ------------------------------------------------------------------
    if req_docling and not await is_docling_available():
        ingestion_report[fmt] = {
            "status": "SKIPPED",
            "reason": "docling-serve not running",
        }
        pytest.skip(f"docling-serve not running — skipping {fmt}")

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
    # Step 2 — Ingest via SDK (upload + poll until terminal state)
    # ------------------------------------------------------------------
    try:
        result = await client.documents.ingest(
            file=io.BytesIO(file_bytes),
            filename=filename,
            wait=True,
        )
    except Exception as exc:
        _record_failure(ingestion_report, fmt, "ingest", exc)
        return

    # ------------------------------------------------------------------
    # Step 3 — Verify: successful_files > 0 means chunks hit the index
    # ------------------------------------------------------------------
    successful = getattr(result, "successful_files", None)
    status     = getattr(result, "status", "unknown")

    if not successful:
        reason = (
            f"task status='{status}', successful_files={successful} — "
            f"document not indexed.  Check Langflow / docling-serve logs."
        )
        _record_failure(ingestion_report, fmt, "index verification", reason)
        # Best-effort cleanup even on failure
        await _cleanup(client, filename)
        return

    # ------------------------------------------------------------------
    # All steps passed
    # ------------------------------------------------------------------
    ingestion_report[fmt] = {"status": "PASSED"}
    _print_result(fmt, passed=True, detail=f"{filename} ({len(file_bytes)} bytes)")

    await _cleanup(client, filename)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _cleanup(client, filename: str) -> None:
    """Delete the ingested document (best-effort — never raises)."""
    try:
        await client.documents.delete(filename)
    except Exception:
        pass
    # For .txt files, the server renames to .md before indexing
    if filename.endswith(".txt"):
        try:
            await client.documents.delete(filename[:-4] + ".md")
        except Exception:
            pass


def _record_failure(report: dict, fmt: str, step: str, exc) -> None:
    reason = f"[{step}] {exc}"
    report[fmt] = {"status": "FAILED", "reason": reason}
    _print_result(fmt, passed=False, detail=reason)


def _print_result(fmt: str, *, passed: bool, detail: str = "") -> None:
    symbol = "✓" if passed else "✗"
    tag    = " [PRIORITY]" if fmt in _PRIORITY_FORMATS else ""
    label  = "PASSED" if passed else "FAILED"
    print(f"\n{symbol} {fmt.upper()}{tag}: {label} — {detail}")
