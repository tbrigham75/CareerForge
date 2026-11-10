"""Resume source preservation and narrowly anchored document additions."""
import hashlib
import io
import re
from copy import deepcopy
from difflib import SequenceMatcher
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from odf import text, teletype
from odf.opendocument import load


def fingerprint(value):
    return hashlib.sha256(value.encode()).hexdigest()


def read_document(content: bytes, suffix: str):
    if len(content) > 25 * 1024 * 1024:
        raise ValueError("Resume exceeds 25 MB.")
    if suffix == ".pdf":
        from pypdf import PdfReader
        pdf = PdfReader(io.BytesIO(content))
        if pdf.is_encrypted or len(pdf.pages) > 50:
            raise ValueError("Choose an unencrypted resume with at most 50 pages.")
        result = [line.strip() for page in pdf.pages for line in (page.extract_text() or "").splitlines() if line.strip()]
        if not result:
            raise ValueError("This PDF has no readable text. Upload DOCX/ODT or a PDF with a text layer.")
        return result
    if suffix not in {".docx", ".odt"}:
        raise ValueError("Upload DOCX, ODT, or PDF.")
    with ZipFile(io.BytesIO(content)) as archive:
        if len(archive.infolist()) > 2000 or sum(i.file_size for i in archive.infolist()) > 50 * 1024 * 1024:
            raise ValueError("Resume package is too large.")
        if any("vbaproject" in n.lower() for n in archive.namelist()):
            raise ValueError("Macro-enabled documents are unsupported.")
    if suffix == ".docx":
        doc = Document(io.BytesIO(content))
        # Refuse layouts whose role boundaries cannot be safely located yet.
        if doc.tables or doc.element.xpath(".//w:txbxContent"):
            raise ValueError("For this release, use a resume with ordinary paragraphs rather than tables/text boxes, or upload its PDF for conversion.")
        return [p.text for p in doc.paragraphs]
    doc = load(io.BytesIO(content))
    return [teletype.extractText(p) for p in doc.getElementsByType(text.P)]


def append_bullets(source: Path, destination: Path, anchor: int, expected: str, bullets: list[str]):
    content = source.read_bytes()
    paragraphs = read_document(content, source.suffix)
    if anchor < 0 or anchor >= len(paragraphs) or paragraphs[anchor] != expected:
        raise ValueError("Resume placement changed. Confirm the insertion point again.")
    if source.suffix == ".docx":
        doc = Document(io.BytesIO(content))
        current = doc.paragraphs[anchor]._p
        for bullet in bullets:
            node = deepcopy(current)
            for child in list(node):
                if not child.tag.endswith("}pPr"):
                    node.remove(child)
            from docx.text.paragraph import Paragraph
            Paragraph(node, doc).add_run(bullet)
            current.addnext(node)
            current = node
        doc.save(destination)
    else:
        doc = load(io.BytesIO(content))
        current = doc.getElementsByType(text.P)[anchor]
        for bullet in bullets:
            node = text.P(text=bullet)
            style = current.getAttribute("stylename")
            if style:
                node.setAttribute("stylename", style)
            parent = current.parentNode
            parent.insertBefore(node, current.nextSibling)
            current = node
        doc.save(str(destination))


def normalize(value):
    return re.sub(r"\W+", " ", value.casefold()).strip()


def role_choices(paragraphs):
    """Extract source-backed current-role labels without an AI request."""
    current = re.compile(r"\b(present|current(?:ly)?|ongoing|to date)\b", re.I)
    year = re.compile(r"\b(?:19|20)\d{2}\b")
    headings = {'experience', 'work experience', 'professional experience', 'employment', 'employment history'}
    choices = []
    for index, paragraph in enumerate(paragraphs):
        value = paragraph.strip()
        if not current.search(value) or not year.search(value) or len(value) > 300:
            continue
        parts = [value]
        # A date-only line commonly follows employer and job-title lines.
        prefix = value[:year.search(value).start()].strip(' |–—-,:')
        if len(prefix.split()) < 2:
            for previous in reversed(paragraphs[max(0, index - 2):index]):
                previous = previous.strip()
                if not previous or previous.casefold() in headings or len(previous) > 160 or year.search(previous):
                    break
                parts.insert(0, previous)
        choices.append({'key': str(index), 'label': ' — '.join(parts)[:500], 'anchor': index, 'current': True})
    if choices:
        return choices
    # When dates are ambiguous, offer source text for explicit user selection.
    return [{'key': str(i), 'label': p.strip()[:500], 'anchor': i, 'current': False}
            for i, p in enumerate(paragraphs) if p.strip() and len(p.strip()) <= 300
            and p.strip().casefold() not in headings]


def similar(value, existing):
    normalized = normalize(value)
    return any(SequenceMatcher(None, normalized, normalize(other)).ratio() >= 0.85 for other in existing if normalize(other))


def validate_placement(paragraphs, anchor):
    """Reject insertion beneath a clearly ended employment date range."""
    date_range = re.compile(r"\b(?:19|20)\d{2}\s*[–—-]\s*((?:19|20)\d{2}|present|current|ongoing)\b", re.I)
    for paragraph in reversed(paragraphs[:anchor + 1]):
        match = date_range.search(paragraph)
        if match:
            if match.group(1).isdigit():
                raise ValueError("This insertion point belongs to a dated historical section. Choose a current role; historical sections are protected.")
            return
