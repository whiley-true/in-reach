"""The Kanban board itself, shown as an editor tab (PROMPT.md: "when clicked it should load the
default board in the editor view ... the board should function like a simple Trello: add column,
rename, delete; add card, title, description, label (edit, delete, make labels); mark as done").

:class:`KanbanBoardView` renders one board from a :class:`~in_reach.app.kanban_db.KanbanStore` as a
row of :class:`_ColumnWidget`\\ s, each holding a drag-and-drop :class:`_CardList` of cards. The view
never keeps state of its own beyond what it's currently showing -- every edit goes straight to the
store, which notifies its listeners, and the view rebuilds itself from that (so the sidebar panel, a
second view of the same board in a split pane, and this one all stay in step for free).

Cards are painted by a delegate (:class:`_CardDelegate`) rather than being real child widgets: Qt's
own item drag-and-drop between two list widgets loses ``setItemWidget()`` widgets on a move, but
plain item data survives it, and the view re-renders from the store right after a drop anyway.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QEvent, QModelIndex, QPoint, QRect, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QColor,
    QFont,
    QFontMetrics,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPalette,
    QPen,
    QPixmap,
    QResizeEvent,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QScrollArea,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from in_reach.app.kanban_db import BoardData, Card, ColumnData, KanbanStore, Label
from in_reach.ide.kanban_dialogs import CardDialog, LabelsDialog

_ROLE_ID = int(Qt.ItemDataRole.UserRole)
_ROLE_DONE = _ROLE_ID + 1
#: ``["#rrggbb|name", ...]`` -- plain strings, since only plain data survives a drag between lists.
_ROLE_LABELS = _ROLE_ID + 2

COLUMN_WIDTH = 280
_PAD = 8
_CHECK = 14
_ITEM_GAP = 6

_HEADER_CHIP_STYLE = (
    "QLabel#kanbanBoardTitle { background-color: rgba(0, 0, 0, 140); color: white; font-weight: bold;"
    " border-radius: 5px; padding: 4px 10px; }"
)
_COLUMN_STYLE = (
    "QFrame#kanbanColumn { background-color: palette(window); border: 1px solid palette(mid);"
    " border-radius: 6px; }"
)
_FLAT_BUTTON_STYLE = (
    "QToolButton { border: none; background: transparent; padding: 2px 6px; }"
    "QToolButton::menu-indicator { image: none; width: 0px; }"
    "QToolButton:hover { background-color: palette(midlight); }"
)
_TOOLBAR_BUTTON_STYLE = (
    "QToolButton { background-color: rgba(0, 0, 0, 140); color: white; border: none; border-radius: 5px;"
    " padding: 4px 10px; }"
    "QToolButton:hover { background-color: rgba(0, 0, 0, 200); }"
)


def _encode_labels(labels: list[Label]) -> list[str]:
    return [f"{label.color}|{label.name}" for label in labels]


def _decode_labels(raw) -> list[tuple[str, str]]:
    out = []
    for entry in raw or []:
        color, _, name = str(entry).partition("|")
        out.append((color, name))
    return out


class _CardDelegate(QStyledItemDelegate):
    """Paints one card: an optional row of coloured label chips, then a tick box and the (word-
    wrapped) title -- struck through and dimmed once the card is done."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        #: The list's own viewport width -- a QListView doesn't reliably hand a delegate's
        #: ``sizeHint`` a useful ``option.rect``, so the owning list tells us instead.
        self.available_width = 0

    @staticmethod
    def _chip_font(font: QFont) -> QFont:
        chip = QFont(font)
        chip.setPointSizeF(max(6.0, font.pointSizeF() * 0.8))
        return chip

    def _layout_card(self, width: int, font: QFont, labels: list[tuple[str, str]], title: str):
        """``(chips, check_rect, title_rect, height)``, all relative to the card's own top-left."""
        fm = QFontMetrics(font)
        chip_fm = QFontMetrics(self._chip_font(font))
        chip_h = chip_fm.height() + 2
        y = _PAD
        chips: list[tuple[QRect, str, str]] = []
        x = _PAD
        for color, name in labels:
            chip_w = max(26, chip_fm.horizontalAdvance(name) + 12)
            if x + chip_w > width - _PAD:
                break  # no room for more -- the rest just aren't drawn on the card face
            chips.append((QRect(x, y, chip_w, chip_h), color, name))
            x += chip_w + 4
        if labels:
            y += chip_h + 4
        text_left = _PAD + _CHECK + 6
        text_w = max(20, width - text_left - _PAD)
        text_h = fm.boundingRect(QRect(0, 0, text_w, 10_000), int(Qt.TextFlag.TextWordWrap), title).height()
        title_rect = QRect(text_left, y, text_w, max(text_h, fm.height()))
        check_rect = QRect(_PAD, y + (fm.height() - _CHECK) // 2, _CHECK, _CHECK)
        height = y + max(title_rect.height(), _CHECK) + _PAD
        return chips, check_rect, title_rect, height

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        width = self.available_width or option.rect.width() or 240
        labels = _decode_labels(index.data(_ROLE_LABELS))
        _chips, _check, _title, height = self._layout_card(
            width - 4, option.font, labels, str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        )
        return QSize(width, height + _ITEM_GAP)

    def check_rect(self, item_rect: QRect, font: QFont, labels: list[tuple[str, str]], title: str) -> QRect:
        """Where the tick box sits for an item drawn into ``item_rect`` -- in the list's own
        viewport coordinates, for hit-testing a click on it."""
        card = item_rect.adjusted(2, _ITEM_GAP // 2, -2, -_ITEM_GAP // 2)
        _chips, check, _title, _height = self._layout_card(card.width(), font, labels, title)
        return check.translated(card.topLeft())

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        title = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        done = bool(index.data(_ROLE_DONE))
        labels = _decode_labels(index.data(_ROLE_LABELS))
        palette = option.palette
        card = option.rect.adjusted(2, _ITEM_GAP // 2, -2, -_ITEM_GAP // 2)
        chips, check, title_rect, _height = self._layout_card(card.width(), option.font, labels, title)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.setPen(QPen(palette.color(QPalette.ColorRole.Highlight if selected else QPalette.ColorRole.Mid)))
        painter.setBrush(palette.color(QPalette.ColorRole.Base))
        painter.drawRoundedRect(QRectF(card), 5, 5)
        painter.translate(card.topLeft())

        for rect, color, name in chips:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(QRectF(rect), 3, 3)
            if name:
                painter.setFont(self._chip_font(option.font))
                painter.setPen(QColor("black"))
                painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), name)

        text_color = palette.color(
            QPalette.ColorGroup.Disabled if done else QPalette.ColorGroup.Active, QPalette.ColorRole.Text
        )
        painter.setPen(QPen(palette.color(QPalette.ColorRole.Mid), 1.2))
        painter.setBrush(palette.color(QPalette.ColorRole.Highlight) if done else Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(check), 3, 3)
        if done:
            painter.setPen(QPen(palette.color(QPalette.ColorRole.HighlightedText), 1.8))
            painter.drawLine(check.left() + 3, check.center().y(), check.center().x() - 1, check.bottom() - 3)
            painter.drawLine(check.center().x() - 1, check.bottom() - 3, check.right() - 3, check.top() + 3)

        font = QFont(option.font)
        font.setStrikeOut(done)
        painter.setFont(font)
        painter.setPen(text_color)
        painter.drawText(title_rect, int(Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignTop), title)
        painter.restore()


class _CardList(QListWidget):
    """One column's cards -- drag a card within it or onto another column's list to move it."""

    #: Emitted after a drop landed on this list (whichever list the card came from).
    order_changed = pyqtSignal()
    #: Emitted with a card id when its tick box was clicked.
    done_toggled = pyqtSignal(int)
    #: Emitted with a card id when it was double-clicked (or Enter pressed on it).
    edit_requested = pyqtSignal(int)
    #: Emitted with a card id and the global position of a right-click on it.
    context_requested = pyqtSignal(int, QPoint)

    def __init__(self, column_id: int) -> None:
        super().__init__()
        self.column_id = column_id
        self.card_delegate = _CardDelegate(self)
        self.setItemDelegate(self.card_delegate)
        self.setFrameShape(QFrame.Shape.NoFrame)
        # Not a "background: transparent" stylesheet -- that also rewrites the palette the delegate
        # reads its card/text colours from, leaving black-on-black cards.
        self.viewport().setAutoFillBackground(False)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        self.itemDoubleClicked.connect(lambda item: self.edit_requested.emit(item.data(_ROLE_ID)))
        self.card_delegate.available_width = self.viewport().width()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.card_delegate.available_width = self.viewport().width()
        self.scheduleDelayedItemsLayout()

    def card_ids(self) -> list[int]:
        return [self.item(i).data(_ROLE_ID) for i in range(self.count())]

    def add_card_item(self, card: Card, labels: list[Label]) -> QListWidgetItem:
        item = QListWidgetItem(card.title)
        item.setData(_ROLE_ID, card.id)
        item.setData(_ROLE_DONE, card.done)
        item.setData(_ROLE_LABELS, _encode_labels(labels))
        item.setToolTip(card.description.strip()[:300] if card.description.strip() else "")
        self.addItem(item)
        return item

    def _item_parts(self, item: QListWidgetItem) -> tuple[list[tuple[str, str]], str]:
        return _decode_labels(item.data(_ROLE_LABELS)), item.text()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.position().toPoint())
            if item is not None:
                labels, title = self._item_parts(item)
                check = self.card_delegate.check_rect(self.visualItemRect(item), self.font(), labels, title)
                if check.adjusted(-3, -3, 3, 3).contains(event.position().toPoint()):
                    self.done_toggled.emit(item.data(_ROLE_ID))
                    return  # a tick-box click is never the start of a drag
        super().mousePressEvent(event)

    def dropEvent(self, event) -> None:  # noqa: ANN001 -- QDropEvent
        super().dropEvent(event)
        self.order_changed.emit()

    def _on_context_menu(self, pos: QPoint) -> None:
        item = self.itemAt(pos)
        if item is not None:
            self.context_requested.emit(item.data(_ROLE_ID), self.viewport().mapToGlobal(pos))


class _AddCardEdit(QLineEdit):
    """The inline "add a card" box: Enter adds and stays open for the next one, Escape (or clicking
    away while empty) closes it."""

    closed = pyqtSignal()

    def keyPressEvent(self, event) -> None:  # noqa: ANN001 -- QKeyEvent
        if event.key() == Qt.Key.Key_Escape:
            self.clear()
            self.hide()
            self.closed.emit()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: ANN001 -- QFocusEvent
        super().focusOutEvent(event)
        if not self.text().strip():
            self.hide()
            self.closed.emit()


class _ColumnWidget(QFrame):
    """One column: a header (name, card count, a menu), its :class:`_CardList`, and an "Add a card"
    footer."""

    rename_requested = pyqtSignal(int)
    delete_requested = pyqtSignal(int)
    move_requested = pyqtSignal(int, int)  # column id, direction (-1 / +1)
    add_card_requested = pyqtSignal(int, str)

    def __init__(self, data: ColumnData, labels_by_id: dict[int, Label], *, can_move_left: bool, can_move_right: bool) -> None:
        super().__init__()
        self.column_id = data.column.id
        self.setObjectName("kanbanColumn")
        self.setStyleSheet(_COLUMN_STYLE)
        self.setFixedWidth(COLUMN_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        header = QHBoxLayout()
        header.setContentsMargins(4, 0, 0, 0)
        self.title_label = QLabel(data.column.name)
        self.title_label.setStyleSheet("QLabel { font-weight: bold; border: none; }")
        header.addWidget(self.title_label, 1)
        self.count_label = QLabel(str(len(data.cards)))
        self.count_label.setEnabled(False)
        self.count_label.setStyleSheet("QLabel { border: none; }")
        header.addWidget(self.count_label)
        self.menu_button = QToolButton()
        self.menu_button.setText("...")
        self.menu_button.setToolTip("Column actions")
        self.menu_button.setStyleSheet(_FLAT_BUTTON_STYLE)
        self.menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.menu_button)
        self.rename_action = menu.addAction("Rename...", lambda: self.rename_requested.emit(self.column_id))
        self.move_left_action = menu.addAction("Move Left", lambda: self.move_requested.emit(self.column_id, -1))
        self.move_right_action = menu.addAction("Move Right", lambda: self.move_requested.emit(self.column_id, 1))
        self.move_left_action.setEnabled(can_move_left)
        self.move_right_action.setEnabled(can_move_right)
        menu.addSeparator()
        self.delete_action = menu.addAction("Delete Column...", lambda: self.delete_requested.emit(self.column_id))
        self.menu_button.setMenu(menu)
        header.addWidget(self.menu_button)
        layout.addLayout(header)

        self.card_list = _CardList(self.column_id)
        for card in data.cards:
            self.card_list.add_card_item(card, [labels_by_id[i] for i in card.label_ids if i in labels_by_id])
        layout.addWidget(self.card_list, 1)

        self.add_card_edit = _AddCardEdit()
        self.add_card_edit.setPlaceholderText("Enter a title for this card...")
        self.add_card_edit.returnPressed.connect(self._submit_add_card)
        self.add_card_edit.closed.connect(self._sync_add_button)
        self.add_card_edit.hide()
        layout.addWidget(self.add_card_edit)
        self.add_card_button = QToolButton()
        self.add_card_button.setText("+ Add a card")
        self.add_card_button.setStyleSheet(_FLAT_BUTTON_STYLE + "QToolButton { text-align: left; }")
        self.add_card_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.add_card_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_card_button.clicked.connect(self.open_add_card_editor)
        layout.addWidget(self.add_card_button)

    def open_add_card_editor(self) -> None:
        self.add_card_button.hide()
        self.add_card_edit.show()
        self.add_card_edit.setFocus()

    def _sync_add_button(self) -> None:
        self.add_card_button.setVisible(not self.add_card_edit.isVisibleTo(self))

    def _submit_add_card(self) -> None:
        title = self.add_card_edit.text().strip()
        if title:
            self.add_card_edit.clear()
            self.add_card_requested.emit(self.column_id, title)


class _BoardCanvas(QWidget):
    """Paints the board's background (a solid colour, or a custom image scaled to cover) behind
    everything else, which is all transparent on top of it."""

    def __init__(self) -> None:
        super().__init__()
        self._color: QColor | None = None
        self._image: QPixmap | None = None
        self._scaled: QPixmap | None = None

    def set_background(self, color: str | None, image_path: Path | None) -> None:
        self._color = QColor(color) if color else None
        self._image = QPixmap(str(image_path)) if image_path is not None else None
        if self._image is not None and self._image.isNull():
            self._image = None
        self._scaled = None
        self.update()

    @property
    def has_image(self) -> bool:
        return self._image is not None

    @property
    def color(self) -> QColor | None:
        return self._color

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._color or self.palette().color(QPalette.ColorRole.Base))
        if self._image is not None:
            if self._scaled is None or self._scaled.size() != self.size():
                cover = self._image.scaled(
                    self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation
                )
                x = (cover.width() - self.width()) // 2
                y = (cover.height() - self.height()) // 2
                self._scaled = cover.copy(x, y, self.width(), self.height())
            painter.drawPixmap(0, 0, self._scaled)
        painter.end()


class KanbanBoardView(QWidget):
    """One board, as a tab (see :meth:`in_reach.ide.tabs.TabPane.open_kanban_board`)."""

    def __init__(self, store: KanbanStore, board_id: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.board_id = board_id
        self._adding_column_id: int | None = None
        self._persist_pending = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._canvas = _BoardCanvas()
        outer.addWidget(self._canvas)
        canvas_layout = QVBoxLayout(self._canvas)
        canvas_layout.setContentsMargins(12, 10, 12, 0)
        canvas_layout.setSpacing(8)

        toolbar = QHBoxLayout()
        self.title_label = QLabel()
        self.title_label.setObjectName("kanbanBoardTitle")
        self.title_label.setStyleSheet(_HEADER_CHIP_STYLE)
        toolbar.addWidget(self.title_label)
        toolbar.addStretch(1)
        self.add_column_button = QToolButton()
        self.add_column_button.setText("+ Add Column")
        self.add_column_button.setStyleSheet(_TOOLBAR_BUTTON_STYLE)
        self.add_column_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_column_button.clicked.connect(self.add_column)
        toolbar.addWidget(self.add_column_button)
        self.labels_button = QToolButton()
        self.labels_button.setText("Labels")
        self.labels_button.setStyleSheet(_TOOLBAR_BUTTON_STYLE)
        self.labels_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.labels_button.clicked.connect(self.open_labels_dialog)
        toolbar.addWidget(self.labels_button)
        canvas_layout.addLayout(toolbar)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; }")
        self._scroll.viewport().setAutoFillBackground(False)
        canvas_layout.addWidget(self._scroll, 1)

        self.columns: list[_ColumnWidget] = []
        self._missing_label = QLabel("This board no longer exists.")
        self._missing_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._missing_label.hide()
        canvas_layout.addWidget(self._missing_label)

        self.store.add_listener(self._on_store_changed)
        self.reload()

    # -- rendering --------------------------------------------------------------------------------

    def _on_store_changed(self) -> None:
        self.reload()

    def reload(self) -> None:
        """Rebuilds the whole board from the store, keeping the horizontal scroll position and any
        open "add a card" box."""
        data = self.store.load_board(self.board_id)
        if data is None:
            self._scroll.hide()
            self._missing_label.show()
            self.title_label.setText("(deleted board)")
            self.add_column_button.setEnabled(False)
            self.labels_button.setEnabled(False)
            return
        self._scroll.show()
        self._missing_label.hide()
        self.add_column_button.setEnabled(True)
        self.labels_button.setEnabled(True)
        self._render(data)

    def _render(self, data: BoardData) -> None:
        self.title_label.setText(data.board.name)
        self._canvas.set_background(data.board.background_color, self.store.resolve_background_image(data.board))

        scroll_value = self._scroll.horizontalScrollBar().value()
        labels_by_id = {label.id: label for label in data.labels}

        content = QWidget()
        content.setAutoFillBackground(False)
        row = QHBoxLayout(content)
        row.setContentsMargins(0, 0, 0, 12)
        row.setSpacing(10)
        self.columns = []
        last = len(data.columns) - 1
        for index, column_data in enumerate(data.columns):
            widget = _ColumnWidget(
                column_data, labels_by_id, can_move_left=index > 0, can_move_right=index < last
            )
            widget.rename_requested.connect(self.rename_column)
            widget.delete_requested.connect(self.delete_column)
            widget.move_requested.connect(self.move_column)
            widget.add_card_requested.connect(self._on_add_card)
            widget.card_list.order_changed.connect(self._schedule_persist_order)
            widget.card_list.done_toggled.connect(self.toggle_done)
            widget.card_list.edit_requested.connect(self.edit_card)
            widget.card_list.context_requested.connect(self._show_card_menu)
            row.addWidget(widget)
            self.columns.append(widget)
        if not data.columns:
            hint = QLabel("No columns yet -- click \"+ Add Column\" to make one.")
            hint.setStyleSheet(_HEADER_CHIP_STYLE.replace("#kanbanBoardTitle", ""))
            row.addWidget(hint, 0, Qt.AlignmentFlag.AlignTop)
        row.addStretch(1)

        old = self._scroll.takeWidget()
        self._scroll.setWidget(content)
        content.setAutoFillBackground(False)  # QScrollArea.setWidget() turns it back on
        if old is not None:
            old.deleteLater()
        self._scroll.horizontalScrollBar().setValue(scroll_value)

        if self._adding_column_id is not None:
            column = self.column_widget(self._adding_column_id)
            if column is not None:
                column.open_add_card_editor()

    def column_widget(self, column_id: int) -> _ColumnWidget | None:
        return next((c for c in self.columns if c.column_id == column_id), None)

    def sync_board_name(self) -> str:
        """The board's current name, for the owning tab's title."""
        board = self.store.get_board(self.board_id)
        return board.name if board else "(deleted board)"

    # -- test seams -------------------------------------------------------------------------------

    def _ask_text(self, title: str, label: str, default: str = "") -> str | None:
        text, ok = QInputDialog.getText(self, title, label, text=default)
        return text.strip() if ok and text.strip() else None

    def _confirm(self, text: str) -> bool:
        result = QMessageBox.question(
            self, "in-reach", text, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        return result == QMessageBox.StandardButton.Yes

    def _run_dialog(self, dialog) -> None:  # noqa: ANN001 -- QDialog
        dialog.exec()

    # -- columns ----------------------------------------------------------------------------------

    def add_column(self) -> None:
        name = self._ask_text("Add Column", "Column name")
        if name:
            self.store.add_column(self.board_id, name)

    def rename_column(self, column_id: int) -> None:
        current = next((c.column.name for c in self._current_columns() if c.column.id == column_id), "")
        name = self._ask_text("Rename Column", "Column name", current)
        if name:
            self.store.rename_column(column_id, name)

    def delete_column(self, column_id: int) -> None:
        column = next((c for c in self._current_columns() if c.column.id == column_id), None)
        if column is None:
            return
        count = len(column.cards)
        detail = f" and its {count} card{'s' if count != 1 else ''}" if count else ""
        if self._confirm(f"Delete the column {column.column.name!r}{detail}? This can't be undone."):
            self.store.delete_column(column_id)

    def move_column(self, column_id: int, direction: int) -> None:
        columns = [c.column for c in self._current_columns()]
        index = next((i for i, c in enumerate(columns) if c.id == column_id), None)
        if index is not None:
            self.store.move_column(column_id, index + direction)

    def _current_columns(self) -> list[ColumnData]:
        data = self.store.load_board(self.board_id)
        return data.columns if data else []

    # -- cards ------------------------------------------------------------------------------------

    def _on_add_card(self, column_id: int, title: str) -> None:
        self._adding_column_id = column_id
        self.store.add_card(column_id, title)

    def add_card(self, column_id: int, title: str) -> None:
        self._adding_column_id = None
        self.store.add_card(column_id, title)

    def toggle_done(self, card_id: int) -> None:
        card = self.store.get_card(card_id)
        if card is not None:
            self.store.set_card_done(card_id, not card.done)

    def edit_card(self, card_id: int) -> None:
        if self.store.get_card(card_id) is None:
            return
        self._run_dialog(CardDialog(self.store, card_id, self))

    def delete_card(self, card_id: int) -> None:
        card = self.store.get_card(card_id)
        if card is not None and self._confirm(f"Delete the card {card.title!r}? This can't be undone."):
            self.store.delete_card(card_id)

    def move_card_to(self, card_id: int, column_id: int) -> None:
        self.store.move_card(card_id, column_id)

    def _show_card_menu(self, card_id: int, global_pos: QPoint) -> None:
        card = self.store.get_card(card_id)
        if card is None:
            return
        menu = self.build_card_menu(card_id)
        menu.exec(global_pos)

    def build_card_menu(self, card_id: int) -> QMenu:
        """The right-click menu for ``card_id`` -- separate from :meth:`_show_card_menu` (which
        only pops it up) so it can be inspected without a modal ``exec``."""
        card = self.store.get_card(card_id)
        menu = QMenu(self)
        menu.addAction("Edit...", lambda: self.edit_card(card_id))
        done_text = "Mark as Not Done" if card and card.done else "Mark as Done"
        menu.addAction(done_text, lambda: self.toggle_done(card_id))
        move_menu = menu.addMenu("Move to")
        for column in self._current_columns():
            action = QAction(column.column.name, move_menu)
            action.setEnabled(card is not None and column.column.id != card.column_id)
            action.triggered.connect(lambda _checked=False, c=column.column.id: self.move_card_to(card_id, c))
            move_menu.addAction(action)
        menu.addSeparator()
        menu.addAction("Delete...", lambda: self.delete_card(card_id))
        return menu

    # -- drag and drop ----------------------------------------------------------------------------

    def _schedule_persist_order(self) -> None:
        """A card was just dropped -- persist the resulting order from a fresh event-loop turn
        rather than from inside the drop handler itself: persisting notifies the store's listeners,
        this view among them, which rebuilds (and so destroys) the very list widget the drag was
        started from, not something to do while Qt is still unwinding that drag."""
        if not self._persist_pending:
            self._persist_pending = True
            QTimer.singleShot(0, self.persist_order)

    def persist_order(self) -> None:
        """Writes every column's current card order (as the lists now show it) back to the store."""
        self._persist_pending = False
        with self.store.batch():
            for column in self.columns:
                self.store.set_column_cards(column.column_id, column.card_list.card_ids())

    # -- labels -----------------------------------------------------------------------------------

    def open_labels_dialog(self) -> None:
        self._run_dialog(LabelsDialog(self.store, self.board_id, self))

    # -- lifecycle --------------------------------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: ANN001 -- QCloseEvent
        self.store.remove_listener(self._on_store_changed)
        super().closeEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            self._canvas.update()
