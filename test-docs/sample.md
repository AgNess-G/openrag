# OpenRAG Pipeline Test Document

## Introduction

This is a **markdown** document used for testing the composable pipeline's ability
to handle structured text formats.

## Features

- Modular architecture with pluggable components
- YAML-based configuration with schema validation
- Support for multiple embedding providers
- Ray-based distributed processing

## Configuration Table

| Setting | Default | Description |
|---------|---------|-------------|
| chunk_size | 1000 | Maximum characters per chunk |
| chunk_overlap | 200 | Overlap between adjacent chunks |
| batch_size | 100 | Embedding API batch size |
| concurrency | 4 | Parallel file processing limit |

## Code Example

```python
from pipeline.config import PipelineConfigManager

mgr = PipelineConfigManager("config/pipeline.yaml")
config = mgr.load()
```

## Conclusion

The composable pipeline provides a flexible and scalable approach to document
ingestion for RAG applications.
