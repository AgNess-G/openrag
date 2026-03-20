"""
Conftest for core integration tests.

Provides a session-scoped ingestion_report fixture that accumulates per-format
results from test_file_format_ingestion.py, and a pytest_terminal_summary hook
that prints a formatted report after all tests finish.
"""
import pytest

# Module-level dict — shared across the session via the fixture below.
# Keys are format labels (e.g. "pdf", "docx"). Values are dicts with:
#   status: "PASSED" | "FAILED" | "SKIPPED"
#   reason: human-readable failure / skip reason (omitted for PASSED)
_INGESTION_RESULTS: dict = {}

# Formats to highlight prominently in the report
PRIORITY_FORMATS = {"pdf", "docx", "html"}


@pytest.fixture(scope="session")
def ingestion_report() -> dict:
    """Session-scoped fixture giving tests a shared dict to record ingestion results."""
    return _INGESTION_RESULTS


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Append the file-format ingestion report to pytest's terminal output."""
    if not _INGESTION_RESULTS:
        return

    tw = terminalreporter

    passed  = {f: r for f, r in _INGESTION_RESULTS.items() if r["status"] == "PASSED"}
    failed  = {f: r for f, r in _INGESTION_RESULTS.items() if r["status"] == "FAILED"}
    skipped = {f: r for f, r in _INGESTION_RESULTS.items() if r["status"] == "SKIPPED"}

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
            tag = "  [PRIORITY]" if fmt in PRIORITY_FORMATS else ""
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
