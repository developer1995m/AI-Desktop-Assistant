"""تست‌های ویجت تب‌های سند PDF."""

from pathlib import Path

from PySide6.QtWidgets import QPushButton

from app.services.pdf_service import PdfDocument
from app.ui.widgets.document_tabs import DocumentTabs


def make_document(name: str) -> PdfDocument:
    return PdfDocument(
        path=Path(name),
        name=name,
        page_count=1,
        pages_read=1,
        text="متن سند",
        truncated=False,
    )


def test_document_tabs_emits_activation_and_close(qt_app):
    widget = DocumentTabs()
    widget.set_documents([make_document("one.pdf"), make_document("two.pdf")], 1)
    activated = []
    closed = []
    widget.document_activated.connect(activated.append)
    widget.document_close_requested.connect(closed.append)

    widget.buttons[0].click()
    close_buttons = [
        button
        for button in widget.findChildren(QPushButton)
        if button.objectName() == "documentTabClose"
    ]
    close_buttons[1].click()

    assert activated == [0]
    assert closed == [1]
    assert [button.property("active") for button in widget.buttons] == [False, True]