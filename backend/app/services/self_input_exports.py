"""Export only reviewed narrative text; questions and internal citations stay out."""
from io import BytesIO

from docx import Document
from docx.shared import Inches, Pt
from odf import style, text
from odf.opendocument import OpenDocumentText

from app.services.self_input import plain_text

MIME = {"docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "odt": "application/vnd.oasis.opendocument.text", "txt": "text/plain; charset=utf-8"}


def export(title, version, extension):
    sections = [section for section in version["sections"] if section.get("included", True)]
    if extension == "txt":
        return plain_text(sections).encode("utf-8")
    stream = BytesIO()
    if extension == "docx":
        document = Document()
        document.sections[0].top_margin = document.sections[0].bottom_margin = Inches(0.75)
        document.styles["Normal"].font.name = "Calibri"
        document.styles["Normal"].font.size = Pt(11)
        document.add_heading(title, 0)
        document.add_paragraph(version["period"]["label"])
        for section in sections:
            blocks = [b for b in section["blocks"] if b["text"].strip()]
            if not blocks:
                continue
            document.add_heading(section["title"], 1)
            for block in blocks:
                document.add_paragraph(block["text"])
        document.save(stream)
    elif extension == "odt":
        document = OpenDocumentText()
        body = style.Style(name="SelfInputBody", family="paragraph")
        body.addElement(style.TextProperties(fontfamily="Calibri", fontsize="11pt"))
        document.styles.addElement(body)
        document.text.addElement(text.H(outlinelevel=1, text=title))
        document.text.addElement(text.P(stylename=body, text=version["period"]["label"]))
        for section in sections:
            blocks = [b for b in section["blocks"] if b["text"].strip()]
            if not blocks:
                continue
            document.text.addElement(text.H(outlinelevel=2, text=section["title"]))
            for block in blocks:
                document.text.addElement(text.P(stylename=body, text=block["text"]))
        document.save(stream)
    else:
        raise ValueError("Choose Word, ODT or plain text.")
    return stream.getvalue()
