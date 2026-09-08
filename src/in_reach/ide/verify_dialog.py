"""The popout window behind the Welcome tab's "Verify Now" button.

Walks :data:`in_reach.app.system_verify.STEPS` one entry at a time, showing how many are left and
what each one resolved to, writing every answer straight back to the project's ``.env`` as it goes.
Steps that resolve on their own advance by themselves on a short timer, so the run visibly cycles
rather than sitting on a single progress bar; a step that needs the user -- pick one of several
detected Steam accounts, or point at a folder that couldn't be found anywhere expected -- stops the
run and shows the matching control, with that step's help tip above it.

The stepping itself lives in :meth:`VerifyDialog.process_next_step`, driven by a timer only for
pacing: a caller (or a test) can drive the entire run by calling it in a loop instead, without an
event loop or a real ``.env`` full of real install paths behind it.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from in_reach.app import system_verify
from in_reach.app.system_verify import STEPS, Outcome, StepResult, VerifyRun, VerifyStep

# Long enough that a run of self-resolving steps reads as a checklist ticking over rather than as
# one instantaneous jump, short enough that twelve of them don't feel like waiting.
_STEP_DELAY_MS = 180

_TICK = "✓"
_CROSS = "✗"


class VerifyDialog(QDialog):
    """Runs the twelve-step system check, prompting only where a step can't resolve itself."""

    #: Emitted once the run reaches the end, so the Welcome tab can re-read the ``.env`` and
    #: re-tick its checklist without waiting for the dialog to be dismissed.
    run_finished = pyqtSignal()

    def __init__(
        self,
        project_dir: Path,
        parent: QWidget | None = None,
        *,
        run: VerifyRun | None = None,
    ) -> None:
        """
        Args:
            project_dir: The project's ``.in-reach`` folder.
            parent: Owning widget.
            run: Injectable :class:`~in_reach.app.system_verify.VerifyRun`, for testing -- one
                built against a fake home folder/``shutil.which`` instead of this machine.
        """
        super().__init__(parent)
        self._run = run or VerifyRun(project_dir)
        self._index = 0
        self._pending: StepResult | None = None

        self.setWindowTitle("Verify System Settings")
        self.setModal(True)
        self.setMinimumWidth(520)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.process_next_step)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        self.progress_label = QLabel()
        layout.addWidget(self.progress_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, len(STEPS))
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)

        self.step_label = QLabel()
        step_font = self.step_label.font()
        step_font.setBold(True)
        self.step_label.setFont(step_font)
        layout.addWidget(self.step_label)

        self.detail_label = QLabel()
        self.detail_label.setWordWrap(True)
        layout.addWidget(self.detail_label)

        self.hint_label = QLabel()
        self.hint_label.setWordWrap(True)
        self.hint_label.hide()
        layout.addWidget(self.hint_label)

        self.choice_combo = QComboBox()
        self.choice_combo.hide()
        layout.addWidget(self.choice_combo)

        self.results_list = QListWidget()
        self.results_list.setMinimumHeight(160)
        layout.addWidget(self.results_list, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch(1)

        self.use_button = self._button("Use This", self._accept_choice)
        self.manual_button = self._button("Set Manually...", self.set_manually)
        self.skip_button = self._button("Skip", self.skip_step)
        self.close_button = self._button("Cancel", self.reject)
        for button in (self.use_button, self.manual_button, self.skip_button, self.close_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)

        self._show_prompt_controls(None)
        self._update_progress()

    def _button(self, text: str, slot) -> QPushButton:  # noqa: ANN001 -- bound method/callable
        button = QPushButton(text)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(slot)
        return button

    # -- running -------------------------------------------------------------------------------

    def start(self) -> None:
        """Begins the run. Deliberately not called from ``__init__`` -- a caller that only wants to
        drive :meth:`process_next_step` itself (a test) then never has a timer running behind it."""
        self._run.record_windows_user()
        self._index = 0
        self.results_list.clear()
        self._schedule_next()

    def _schedule_next(self) -> None:
        self._timer.start(_STEP_DELAY_MS)

    def process_next_step(self) -> None:
        """Checks the next step, accepting it outright if it resolved and stopping for input if not.

        Every call either advances past one step or leaves the run parked on one waiting for the
        user -- so calling this repeatedly drives the whole checklist, which is exactly what the
        pacing timer does.
        """
        self._pending = None
        if self._index >= len(STEPS):
            self._finish()
            return

        step = STEPS[self._index]
        self.step_label.setText(f"{step.label}")
        result = self._run.check(step)

        if result.outcome == Outcome.FOUND:
            self._run.accept(step, result.value)
            self._complete_step(step, result.detail, verified=True)
            return

        self._pending = result
        self.detail_label.setText(result.detail)
        self._show_prompt_controls(result)
        self._update_progress()

    def pending_result(self) -> StepResult | None:
        """The step the run is currently parked on, or ``None`` while it's still cycling."""
        return self._pending

    def _complete_step(self, step: VerifyStep, detail: str, *, verified: bool) -> None:
        self.results_list.addItem(f"{_TICK if verified else _CROSS}  {step.label} -- {detail}")
        self.results_list.scrollToBottom()
        self.detail_label.setText(detail)
        self._index += 1
        self._update_progress()
        self._show_prompt_controls(None)
        self._schedule_next()

    def _finish(self) -> None:
        self._timer.stop()
        self._show_prompt_controls(None)
        verified = sum(1 for is_set in system_verify.verified_keys(self._run.project_dir).values() if is_set)
        self.step_label.setText("Verification complete")
        self.detail_label.setText(f"{verified} of {len(STEPS)} steps verified.")
        self.progress_label.setText(f"Step {len(STEPS)} of {len(STEPS)}")
        self.progress.setValue(len(STEPS))
        self.close_button.setText("Done")
        self.run_finished.emit()

    def _update_progress(self) -> None:
        shown = min(self._index + 1, len(STEPS))
        self.progress_label.setText(f"Step {shown} of {len(STEPS)}")
        self.progress.setValue(self._index)

    def _show_prompt_controls(self, result: StepResult | None) -> None:
        """Shows only the controls the parked step actually offers -- a chooser for several
        candidates, a browse/skip pair for none at all, and nothing at all while the run is
        cycling through steps that resolve themselves."""
        is_choice = result is not None and result.outcome == Outcome.CHOICE
        is_missing = result is not None and result.outcome == Outcome.MISSING

        self.choice_combo.setVisible(is_choice)
        self.use_button.setVisible(is_choice)
        self.manual_button.setVisible(is_missing)
        self.skip_button.setVisible(is_choice or is_missing)

        hint = result.step.hint if result is not None else ""
        self.hint_label.setText(hint)
        self.hint_label.setVisible(bool(hint))

        self.choice_combo.clear()
        if is_choice:
            for choice in result.choices:
                self.choice_combo.addItem(choice.label, choice.value)

    # -- answering a parked step ----------------------------------------------------------------

    def _accept_choice(self) -> None:
        result = self._pending
        value = self.choice_combo.currentData()
        if result is None or not value:
            return
        self._run.accept(result.step, value)
        self._complete_step(result.step, value, verified=True)

    def set_manually(self) -> None:
        """Asks the user to point at whatever this step couldn't find, then accepts that answer.

        A Steam account is picked as its folder under ``userdata`` and stored as that folder's
        name -- the account id -- rather than as a path, since that's what the rest of the
        checklist derives from it.
        """
        result = self._pending
        if result is None:
            return

        if result.step.manual == system_verify.MANUAL_FILE:
            chosen = self.ask_file(result.suggestion)
        else:
            chosen = self.ask_directory(result.suggestion)
        if not chosen:
            return

        value = Path(chosen).name if result.step.manual == system_verify.MANUAL_STEAM_ACCOUNT else chosen
        self._run.accept(result.step, value)
        self._complete_step(result.step, value, verified=True)

    def skip_step(self) -> None:
        """Leaves this step unverified (its ``.env`` key untouched) and moves on."""
        result = self._pending
        if result is None:
            return
        self._complete_step(result.step, "Skipped", verified=False)

    # -- native pickers, kept as their own methods purely as a test seam (see tabs.py's
    # _ask_save_path for the same pattern) -------------------------------------------------------

    def ask_directory(self, start_at: str) -> str:
        return QFileDialog.getExistingDirectory(self, "Select folder", start_at)

    def ask_file(self, start_at: str) -> str:
        chosen, _selected_filter = QFileDialog.getOpenFileName(self, "Select file", start_at)
        return chosen
