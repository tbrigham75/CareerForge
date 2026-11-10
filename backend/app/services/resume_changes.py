"""Validated resume edits and deterministic previews shared by saving and review."""
from copy import deepcopy
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from docx import Document
from docx.text.paragraph import Paragraph
from odf import text, teletype
from odf.opendocument import load

from app.services.resumes import read_document, normalize, validate_placement


def section_bounds(paragraphs, anchor):
    start = anchor
    for index in range(anchor, -1, -1):
        if re.search(r'\b(?:19|20)\d{2}\b', paragraphs[index]):
            start = index
            break
    end = len(paragraphs)
    headings = {'education', 'certifications', 'skills', 'professional development', 'references', 'technical skills'}
    for index in range(start + 1, len(paragraphs)):
        value = paragraphs[index].strip()
        if value.casefold() in headings or re.search(r'\b(?:19|20)\d{2}\s*[–—-]', value):
            end = index
            break
    return start, end


def validate_changes(paragraphs, changes, start, end, protected):
    if not 0 <= start < end <= len(paragraphs):
        raise ValueError('Confirm current-role boundaries.')
    validate_placement(paragraphs, start)
    touched = set()
    for change in changes:
        kind = change.get('kind', 'add')
        targets = change.get('targets', [])
        value = change.get('text', '')
        if kind not in {'add', 'replace', 'combine', 'remove'} or not isinstance(targets, list):
            raise ValueError('Invalid change type.')
        if (kind == 'add' and targets) or (kind in {'replace', 'remove'} and len(targets) != 1) or (kind == 'combine' and len(targets) < 2):
            raise ValueError('Invalid change targets.')
        if len(set(targets)) != len(targets):
            raise ValueError('Repeated change target.')
        for index in targets:
            if type(index) is not int or not start < index < end or index in protected or index in touched:
                raise ValueError('A change touches protected content or overlaps another change.')
            validate_placement(paragraphs, index)
            touched.add(index)
        if kind != 'remove' and (not value.strip() or len(value) > 1500 or re.search(r'\[[^\]]+\]', value)):
            raise ValueError('Resolve empty wording or placeholders.')
        if kind == 'remove' and value.strip():
            raise ValueError('Removal cannot contain replacement text.')
    return changes


def preview(paragraphs, changes, anchor):
    replacements, removed, additions = {}, set(), []
    for change in changes:
        targets = sorted(change.get('targets', []))
        if change['kind'] == 'add':
            additions.append(change['text'])
        else:
            removed.update(targets)
            if change['kind'] != 'remove':
                replacements[targets[0]] = change['text']
    result = []
    for index, paragraph in enumerate(paragraphs):
        if index in replacements:
            result.append(replacements[index])
        elif index not in removed:
            result.append(paragraph)
        if index == anchor:
            result.extend(additions)
    return result


def write_changes(source, destination, paragraphs, changes, anchor):
    if read_document(source.read_bytes(), source.suffix) != paragraphs:
        raise ValueError('Document changed since review. Regenerate the proposal.')
    if source.suffix == '.docx':
        doc = Document(source)
        nodes = [p._p for p in doc.paragraphs]
    else:
        doc = load(str(source))
        nodes = doc.getElementsByType(text.P)
    def replace(index, value):
        node = nodes[index]
        if source.suffix == '.docx':
            paragraph = Paragraph(node, doc)
            properties = deepcopy(paragraph.runs[0]._r.rPr) if paragraph.runs and paragraph.runs[0]._r.rPr is not None else None
            paragraph.clear()
            run = paragraph.add_run(value)
            if properties is not None:
                run._r.insert(0, properties)
        else:
            for child in list(node.childNodes):
                node.removeChild(child)
            node.addText(value)
    current = nodes[anchor]
    for change in changes:
        targets = sorted(change.get('targets', []))
        if change['kind'] == 'add':
            node = deepcopy(nodes[anchor])
            if source.suffix == '.docx':
                paragraph = Paragraph(node, doc)
                paragraph.clear()
                paragraph.add_run(change['text'])
                current.addnext(node)
            else:
                for child in list(node.childNodes):
                    node.removeChild(child)
                node.addText(change['text'])
                current.parentNode.insertBefore(node, current.nextSibling)
            current = node
        else:
            if change['kind'] != 'remove':
                replace(targets[0], change['text'])
                targets = targets[1:]
            for index in targets:
                node = nodes[index]
                if source.suffix == '.docx':
                    node.getparent().remove(node)
                else:
                    node.parentNode.removeChild(node)
    doc.save(str(destination))
    if read_document(destination.read_bytes(), destination.suffix) != preview(paragraphs, changes, anchor):
        destination.unlink(missing_ok=True)
        raise ValueError('Saved document did not match the approved preview.')


def renderer():
    return shutil.which('soffice.com') or next((str(p) for p in [Path('C:/Program Files/LibreOffice/program/soffice.com'), Path('C:/Program Files (x86)/LibreOffice/program/soffice.com')] if p.is_file()), None)


def render_pdf(source, destination):
    executable = renderer()
    if not executable:
        raise ValueError('Install local LibreOffice to enable paginated preview. Content preview remains available.')
    with tempfile.TemporaryDirectory(prefix='resume-render-') as scratch:
        root = Path(scratch)
        subprocess.run([executable, '-env:UserInstallation=' + (root / 'profile').as_uri(), '--headless', '--convert-to', 'pdf', '--outdir', str(root), str(source.resolve())], check=True, timeout=60, capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        pdf = root / (source.stem + '.pdf')
        if not pdf.is_file():
            raise ValueError('Local rendering did not produce a preview.')
        shutil.copyfile(pdf, destination)
