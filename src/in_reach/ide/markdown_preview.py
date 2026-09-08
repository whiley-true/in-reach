"""A read-only, rendered preview for ``.md`` files (PROMPT.md: "please make .md be preview when
opened") -- opened in place of :class:`~in_reach.ide.editor.TextEditorWidget` for any file whose
suffix is ``.md`` (see :meth:`~in_reach.ide.tabs.TabPane.open_file`), rather than as a raw-text
editor tab. Uses Qt's own built-in Markdown-to-rich-text conversion (``QTextDocument.setMarkdown``,
wrapped by :class:`QTextBrowser`) rather than a hand-rolled renderer -- correct GitHub-flavored-ish
Markdown rendering (headings, lists, code spans, links, ...) with zero new dependencies.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QTextBrowser, QWidget


class MarkdownPreviewWidget(QTextBrowser):
    """One Markdown-preview tab's content. Never editable -- there's no source view to switch
    back to here, just the rendered document -- so it never participates in dirty-tracking, the
    italic-tab-text treatment, or Save/Save As (see :meth:`~in_reach.ide.tabs.TabPane._save_tab`'s
    own guard)."""

    def __init__(self, parent: QWidget | None = None, *, path: Path | None = None) -> None:
        super().__init__(parent)
        self.path = path
        self.setReadOnly(True)
        self.setOpenExternalLinks(True)
