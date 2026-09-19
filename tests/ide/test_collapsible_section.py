from PyQt6.QtWidgets import QLabel

from in_reach.ide.collapsible_section import CollapsibleSection


def test_starts_collapsed_by_default(qtbot) -> None:
    body = QLabel("body")
    section = CollapsibleSection("Title", body)
    qtbot.addWidget(section)
    section.show()

    assert section.expanded is False
    assert body.isVisible() is False


def test_starts_expanded_when_asked(qtbot) -> None:
    body = QLabel("body")
    section = CollapsibleSection("Title", body, collapsed=False)
    qtbot.addWidget(section)
    section.show()

    assert section.expanded is True
    assert body.isVisible() is True


def test_starts_collapsed_when_asked(qtbot) -> None:
    body = QLabel("body")
    section = CollapsibleSection("Title", body, collapsed=True)
    qtbot.addWidget(section)
    section.show()

    assert section.expanded is False
    assert body.isVisible() is False


def test_set_title_updates_the_header_text(qtbot) -> None:
    body = QLabel("body")
    section = CollapsibleSection("Title", body)
    qtbot.addWidget(section)

    section.set_title("Changes (3)")

    assert section._toggle.text() == "Changes (3)"


def test_toggling_the_header_shows_and_hides_the_body(qtbot) -> None:
    body = QLabel("body")
    section = CollapsibleSection("Title", body)
    qtbot.addWidget(section)
    section.show()

    section.set_expanded(False)
    assert body.isVisible() is False

    section.set_expanded(True)
    assert body.isVisible() is True
