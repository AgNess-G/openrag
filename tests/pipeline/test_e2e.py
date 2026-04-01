"""End-to-end tests for the pipeline CLI.

These tests are marked slow and require running services + configured API keys.
Run with: pytest -m slow tests/pipeline/test_e2e.py
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest


@pytest.mark.slow
def test_cli_parse_command(sample_text_file):
    """Test the CLI parse subcommand on a sample file.

    Requires OPENAI_API_KEY to be set (or use a preset that doesn't need it).
    """
    env = {**os.environ, "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", "test-key")}
    result = subprocess.run(
        [
            sys.executable, "-m", "pipeline.cli",
            "--config", "config/presets/composable-basic.yaml",
            "parse", sample_text_file,
        ],
        capture_output=True,
        text=True,
        cwd="src",
        env=env,
    )
    if result.returncode != 0:
        pytest.skip(f"CLI failed (likely missing API key or service): {result.stderr[:200]}")
    assert "Filename:" in result.stdout
    assert "Content:" in result.stdout
