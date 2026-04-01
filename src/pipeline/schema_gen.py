"""Generate JSON Schema from PipelineConfig for editor autocomplete.

Usage:
    python -m pipeline.schema_gen
"""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.config import PipelineConfig


def generate_schema(output_path: str | Path = "config/pipeline.schema.json") -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    schema = PipelineConfig.model_json_schema()
    output.write_text(json.dumps(schema, indent=2) + "\n")
    return output


if __name__ == "__main__":
    path = generate_schema()
    print(f"Schema written to {path}")
