"""
Generate minimal binary sample files for integration format tests.

Uses only Python stdlib — no external dependencies.
Run: python tests/data/create_samples.py

Files are committed to tests/data/samples/ so this script only needs to be
re-run when sample content needs to change.
"""
import io
import zipfile
from pathlib import Path

SAMPLES_DIR = Path(__file__).parent / "samples"
SAMPLES_DIR.mkdir(exist_ok=True)


def create_minimal_pdf(text: str) -> bytes:
    """Create a minimal valid PDF containing text with correct xref offsets."""
    content_stream = f"BT /F1 12 Tf 50 750 Td ({text}) Tj ET".encode("latin-1")

    header = b"%PDF-1.4\n"
    obj1 = b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    obj2 = b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    obj3 = (
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
        b" /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n"
    )
    obj4 = (
        b"4 0 obj\n<< /Length " + str(len(content_stream)).encode() + b" >>\n"
        b"stream\n" + content_stream + b"\nendstream\nendobj\n"
    )
    obj5 = b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"

    # Compute accurate byte offsets for each object
    off1 = len(header)
    off2 = off1 + len(obj1)
    off3 = off2 + len(obj2)
    off4 = off3 + len(obj3)
    off5 = off4 + len(obj4)
    xref_offset = off5 + len(obj5)

    xref = (
        b"xref\n0 6\n"
        b"0000000000 65535 f \n"
        + f"{off1:010d} 00000 n \n".encode()
        + f"{off2:010d} 00000 n \n".encode()
        + f"{off3:010d} 00000 n \n".encode()
        + f"{off4:010d} 00000 n \n".encode()
        + f"{off5:010d} 00000 n \n".encode()
        + f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode()
    )

    return header + obj1 + obj2 + obj3 + obj4 + obj5 + xref


def create_minimal_docx(text: str) -> bytes:
    """Create a minimal valid DOCX (ZIP+XML) containing text."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml"'
            ' ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '</Types>',
        )
        zf.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"'
            ' Target="word/document.xml"/>'
            '</Relationships>',
        )
        zf.writestr(
            "word/_rels/document.xml.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '</Relationships>',
        )
        zf.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body>'
            '<w:p><w:r><w:t>' + text + '</w:t></w:r></w:p>'
            '</w:body>'
            '</w:document>',
        )
    return buf.getvalue()


def create_minimal_xlsx(text: str) -> bytes:
    """Create a minimal valid XLSX (ZIP+XML) containing text in a cell."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml"'
            ' ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml"'
            ' ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/sharedStrings.xml"'
            ' ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
            '</Types>',
        )
        zf.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"'
            ' Target="xl/workbook.xml"/>'
            '</Relationships>',
        )
        zf.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"'
            ' Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings"'
            ' Target="sharedStrings.xml"/>'
            '</Relationships>',
        )
        zf.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
            ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets>'
            '</workbook>',
        )
        zf.writestr(
            "xl/worksheets/sheet1.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetData>'
            '<row r="1"><c r="A1" t="s"><v>0</v></c></row>'
            '</sheetData>'
            '</worksheet>',
        )
        zf.writestr(
            "xl/sharedStrings.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="1" uniqueCount="1">'
            f'<si><t>{text}</t></si>'
            '</sst>',
        )
    return buf.getvalue()


def create_minimal_pptx(title: str, body_lines: list[str]) -> bytes:
    """Create a minimal valid PPTX (ZIP+XML) with one slide containing a title and body text."""
    NS_PKG_CT   = "http://schemas.openxmlformats.org/package/2006/content-types"
    NS_PKG_REL  = "http://schemas.openxmlformats.org/package/2006/relationships"
    NS_OFF_REL  = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    NS_PML      = "http://schemas.openxmlformats.org/presentationml/2006/main"
    NS_DML      = "http://schemas.openxmlformats.org/drawingml/2006/main"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "[Content_Types].xml",
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<Types xmlns="{NS_PKG_CT}">'
            f'<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            f'<Default Extension="xml" ContentType="application/xml"/>'
            f'<Override PartName="/ppt/presentation.xml"'
            f' ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
            f'<Override PartName="/ppt/slides/slide1.xml"'
            f' ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
            f'<Override PartName="/ppt/slideLayouts/slideLayout1.xml"'
            f' ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>'
            f'</Types>',
        )
        zf.writestr(
            "_rels/.rels",
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<Relationships xmlns="{NS_PKG_REL}">'
            f'<Relationship Id="rId1" Type="{NS_OFF_REL}/officeDocument"'
            f' Target="ppt/presentation.xml"/>'
            f'</Relationships>',
        )
        zf.writestr(
            "ppt/_rels/presentation.xml.rels",
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<Relationships xmlns="{NS_PKG_REL}">'
            f'<Relationship Id="rId1" Type="{NS_OFF_REL}/slide"'
            f' Target="slides/slide1.xml"/>'
            f'</Relationships>',
        )
        # slide1 references its layout
        zf.writestr(
            "ppt/slides/_rels/slide1.xml.rels",
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<Relationships xmlns="{NS_PKG_REL}">'
            f'<Relationship Id="rId1" Type="{NS_OFF_REL}/slideLayout"'
            f' Target="../slideLayouts/slideLayout1.xml"/>'
            f'</Relationships>',
        )
        # minimal blank slide layout so parsers can resolve the reference
        zf.writestr(
            "ppt/slideLayouts/_rels/slideLayout1.xml.rels",
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<Relationships xmlns="{NS_PKG_REL}"/>'
        )
        zf.writestr(
            "ppt/slideLayouts/slideLayout1.xml",
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<p:sldLayout xmlns:p="{NS_PML}" xmlns:a="{NS_DML}" type="blank">'
            f'<p:cSld><p:spTree>'
            f'<p:grpSpPr>'
            f'<a:xfrm>'
            f'<a:off x="0" y="0"/><a:ext cx="9144000" cy="6858000"/>'
            f'<a:chOff x="0" y="0"/><a:chExt cx="9144000" cy="6858000"/>'
            f'</a:xfrm>'
            f'</p:grpSpPr>'
            f'</p:spTree></p:cSld>'
            f'</p:sldLayout>',
        )
        zf.writestr(
            "ppt/presentation.xml",
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<p:presentation xmlns:p="{NS_PML}"'
            f' xmlns:r="{NS_OFF_REL}">'
            f'<p:sldMasterIdLst/>'
            f'<p:sldSz cx="9144000" cy="6858000"/>'
            f'<p:notesSz cx="6858000" cy="9144000"/>'
            f'<p:sldIdLst><p:sldId id="256" r:id="rId1"/></p:sldIdLst>'
            f'</p:presentation>',
        )
        body_paragraphs = "".join(
            f'<a:p><a:r><a:t>{line}</a:t></a:r></a:p>'
            for line in body_lines
        )
        # Standard slide dimensions: 9144000 x 6858000 EMUs (10" x 7.5")
        # Title box: full width, top quarter
        # Body box: full width, remaining area
        zf.writestr(
            "ppt/slides/slide1.xml",
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<p:sld xmlns:p="{NS_PML}" xmlns:a="{NS_DML}">'
            f'<p:cSld><p:spTree>'
            f'<p:grpSpPr>'
            f'<a:xfrm>'
            f'<a:off x="0" y="0"/><a:ext cx="9144000" cy="6858000"/>'
            f'<a:chOff x="0" y="0"/><a:chExt cx="9144000" cy="6858000"/>'
            f'</a:xfrm>'
            f'</p:grpSpPr>'
            f'<p:sp>'
            f'<p:nvSpPr><p:cNvPr id="1" name="Title"/>'
            f'<p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>'
            f'<p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr>'
            f'<p:spPr>'
            f'<a:xfrm><a:off x="457200" y="274638"/><a:ext cx="8229600" cy="1143000"/></a:xfrm>'
            f'</p:spPr>'
            f'<p:txBody><a:bodyPr/><a:lstStyle/>'
            f'<a:p><a:r><a:t>{title}</a:t></a:r></a:p>'
            f'</p:txBody></p:sp>'
            f'<p:sp>'
            f'<p:nvSpPr><p:cNvPr id="2" name="Content"/>'
            f'<p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>'
            f'<p:nvPr><p:ph idx="1"/></p:nvPr></p:nvSpPr>'
            f'<p:spPr>'
            f'<a:xfrm><a:off x="457200" y="1600200"/><a:ext cx="8229600" cy="4525963"/></a:xfrm>'
            f'</p:spPr>'
            f'<p:txBody><a:bodyPr/><a:lstStyle/>'
            f'{body_paragraphs}'
            f'</p:txBody></p:sp>'
            f'</p:spTree></p:cSld>'
            f'</p:sld>',
        )
    return buf.getvalue()


def main():
    # --- Binary formats (require docling-serve) ---
    binary_formats = {
        "sample.pdf": create_minimal_pdf(
            "OpenRAG pdf format test document. This sample is used for integration testing."
        ),
        "sample.docx": create_minimal_docx(
            "OpenRAG docx format test document. This sample is used for integration testing."
        ),
        "sample.xlsx": create_minimal_xlsx(
            "OpenRAG xlsx format test document. This sample is used for integration testing."
        ),
        "sample.pptx": create_minimal_pptx(
            title="OpenRAG PPTX Format Test",
            body_lines=[
                "OpenRAG pptx format test document used for integration testing.",
                "This slide verifies that OpenRAG can ingest and index PPTX files.",
                "Key features: title extraction, body text parsing, multi-paragraph support.",
            ],
        ),
    }

    for filename, content in binary_formats.items():
        path = SAMPLES_DIR / filename
        path.write_bytes(content)
        print(f"Created {path} ({len(content)} bytes)")

    # --- Text formats (require docling-serve, committed as files for consistency) ---
    text_formats = {
        "sample.md": (
            "# OpenRAG Markdown Format Test\n\n"
            "OpenRAG markdown format content for integration testing.\n\n"
            "## About\n\n"
            "This is a **Markdown** sample document used to verify that OpenRAG can ingest "
            "and index Markdown files correctly.\n\n"
            "- Feature 1: Heading support\n"
            "- Feature 2: List support\n"
            "- Feature 3: Emphasis support\n\n"
            "> Markdown is a lightweight markup language for creating formatted text.\n"
        ),
        "sample.adoc": (
            "= OpenRAG AsciiDoc Format Test\n"
            ":author: OpenRAG Integration Tests\n"
            ":description: AsciiDoc sample for integration testing\n\n"
            "OpenRAG asciidoc format content for integration testing.\n\n"
            "== Introduction\n\n"
            "This is an *AsciiDoc* sample document used to verify that OpenRAG can ingest "
            "and index AsciiDoc files correctly.\n\n"
            "AsciiDoc is a human-readable, plain-text markup language for structured technical content.\n\n"
            "== Features\n\n"
            "* Heading support\n"
            "* List support\n"
            "* Attribute support\n"
        ),
        "sample.tex": (
            r"\documentclass{article}" + "\n"
            r"\title{OpenRAG \LaTeX\ Format Test}" + "\n"
            r"\author{OpenRAG Integration Tests}" + "\n"
            r"\begin{document}" + "\n"
            r"\maketitle" + "\n\n"
            "OpenRAG latex format content for integration testing.\n\n"
            r"\section{Introduction}" + "\n\n"
            "This is a \\LaTeX\\ sample document used to verify that OpenRAG can ingest "
            "and index \\LaTeX\\ files correctly.\n\n"
            "\\LaTeX\\ is a scientific document preparation system widely used in academia.\n\n"
            r"\section{Features}" + "\n\n"
            r"\begin{itemize}" + "\n"
            r"  \item Mathematical typesetting" + "\n"
            r"  \item Structured sections" + "\n"
            r"  \item Bibliography support" + "\n"
            r"\end{itemize}" + "\n\n"
            r"\end{document}" + "\n"
        ),
        "sample.html": (
            "<!DOCTYPE html>\n"
            "<html lang=\"en\">\n"
            "<head>\n"
            "  <meta charset=\"UTF-8\">\n"
            "  <title>OpenRAG HTML Format Test</title>\n"
            "</head>\n"
            "<body>\n"
            "  <h1>OpenRAG HTML Format Test</h1>\n"
            "  <p>OpenRAG html format content for integration testing.</p>\n"
            "  <h2>About</h2>\n"
            "  <p>This is an <strong>HTML</strong> sample document used to verify that OpenRAG\n"
            "  can ingest and index HTML files correctly.</p>\n"
            "  <ul>\n"
            "    <li>Heading support</li>\n"
            "    <li>Paragraph support</li>\n"
            "    <li>List support</li>\n"
            "  </ul>\n"
            "</body>\n"
            "</html>\n"
        ),
        "sample.xhtml": (
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
            "<!DOCTYPE html PUBLIC \"-//W3C//DTD XHTML 1.0 Strict//EN\"\n"
            "  \"http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd\">\n"
            "<html xmlns=\"http://www.w3.org/1999/xhtml\" lang=\"en\" xml:lang=\"en\">\n"
            "<head>\n"
            "  <meta charset=\"UTF-8\" />\n"
            "  <title>OpenRAG XHTML Format Test</title>\n"
            "</head>\n"
            "<body>\n"
            "  <h1>OpenRAG XHTML Format Test</h1>\n"
            "  <p>OpenRAG xhtml format content for integration testing.</p>\n"
            "  <h2>About</h2>\n"
            "  <p>This is an <strong>XHTML</strong> sample document used to verify that OpenRAG\n"
            "  can ingest and index XHTML files correctly.</p>\n"
            "  <p>XHTML is a stricter, XML-based version of HTML.</p>\n"
            "</body>\n"
            "</html>\n"
        ),
        "sample.csv": (
            "format,category,description,searchable_content\n"
            "OpenRAG csv format,Integration Test,CSV sample for testing,openrag csv format content for integration testing\n"
            "Comma-Separated Values,Data Format,Tabular data format,structured data storage\n"
            "Column 1,Column 2,Column 3,Column 4\n"
            "Value A,Value B,Value C,Value D\n"
            "Row 2 A,Row 2 B,Row 2 C,Row 2 D\n"
        ),
    }

    for filename, content in text_formats.items():
        path = SAMPLES_DIR / filename
        path.write_text(content, encoding="utf-8")
        print(f"Created {path} ({len(content.encode())} bytes)")

    print(f"\nAll sample files written to {SAMPLES_DIR}")


if __name__ == "__main__":
    main()
