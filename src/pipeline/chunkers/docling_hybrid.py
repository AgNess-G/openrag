"""Hybrid chunker: Docling structure awareness + recursive splitting."""

from __future__ import annotations

from langchain_text_splitters import RecursiveCharacterTextSplitter

from pipeline.types import Chunk, ParsedDocument


class DoclingHybridChunker:
    """Split by docling pages/tables first, then recursively split large page chunks."""

    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ) -> None:
        self._chunk_size = chunk_size
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", " ", ""],
        )

    async def chunk(self, doc: ParsedDocument) -> list[Chunk]:
        chunks: list[Chunk] = []
        idx = 0

        if doc.pages:
            for page_data in doc.pages:
                text = page_data.get("text", "")
                page_no = page_data.get("page")
                if not text.strip():
                    continue
                if len(text) > self._chunk_size:
                    for sub in self._splitter.split_text(text):
                        chunks.append(Chunk(
                            text=sub, index=idx, source=doc.filename,
                            page=page_no, chunk_type="text",
                        ))
                        idx += 1
                else:
                    chunks.append(Chunk(
                        text=text, index=idx, source=doc.filename,
                        page=page_no, chunk_type="text",
                    ))
                    idx += 1

        if doc.tables:
            for table_data in doc.tables:
                text = table_data.get("text", "")
                if text.strip():
                    chunks.append(Chunk(
                        text=text, index=idx, source=doc.filename,
                        page=table_data.get("page"), chunk_type="table",
                    ))
                    idx += 1

        if not chunks and doc.content:
            for sub in self._splitter.split_text(doc.content):
                chunks.append(Chunk(
                    text=sub, index=idx, source=doc.filename,
                    chunk_type="text",
                ))
                idx += 1

        return chunks
