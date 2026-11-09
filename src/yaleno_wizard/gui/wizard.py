"""Der Yaleno Wizard (QWizard mit allen Seiten)."""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWizard

from .. import APP_NAME, __version__
from .pages.categories import CategoriesPage
from .pages.connection import ConnectionPage
from .pages.files import FilesPage
from .pages.history import HistoryPage
from .pages.mode import ModePage
from .pages.progress import ProgressPage
from .pages.summary import SummaryPage
from .state import HistoryAction, Mode, WizardState

P_CONNECTION, P_MODE, P_HISTORY, P_CATEGORIES, P_FILES, P_SUMMARY, P_PROGRESS = range(7)


class YalenoWizard(QWizard):
    def __init__(self):
        super().__init__()
        self.state = WizardState()
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnLastPage, True)
        self.setOption(QWizard.WizardOption.HaveCustomButton1, True)
        self.setButtonText(QWizard.WizardButton.CustomButton1, "Neue Aktion")
        self.setButtonText(QWizard.WizardButton.NextButton, "Weiter >")
        self.setButtonText(QWizard.WizardButton.BackButton, "< Zurück")
        self.setButtonText(QWizard.WizardButton.FinishButton, "Fertig")
        self.setButtonText(QWizard.WizardButton.CancelButton, "Beenden")
        self.customButtonClicked.connect(self._restart)
        self.resize(900, 680)

        s = self.state
        self.summary = SummaryPage(s)
        self.progress = ProgressPage(s, self.summary)
        self.setPage(P_CONNECTION, ConnectionPage(s))
        self.setPage(P_MODE, ModePage(s))
        self.setPage(P_HISTORY, HistoryPage(s))
        self.setPage(P_CATEGORIES, CategoriesPage(s))
        self.setPage(P_FILES, FilesPage(s))
        self.setPage(P_SUMMARY, self.summary)
        self.setPage(P_PROGRESS, self.progress)
        self.setStartId(P_CONNECTION)

        self.progress.completeChanged.connect(self._update_custom_button)
        self.currentIdChanged.connect(lambda _id: self._update_custom_button())
        self._update_custom_button()

    def nextId(self) -> int:
        cur = self.currentId()
        if cur == P_MODE:
            return P_CATEGORIES if self.state.mode == Mode.SYNC else P_HISTORY
        if cur == P_HISTORY:
            return P_SUMMARY if self.state.history_action == HistoryAction.RESET else P_CATEGORIES
        if cur == P_PROGRESS:
            return -1
        return super().nextId()

    def _update_custom_button(self) -> None:
        btn = self.button(QWizard.WizardButton.CustomButton1)
        on_progress = self.currentId() == P_PROGRESS
        btn.setVisible(on_progress)
        btn.setEnabled(on_progress and not self.progress.running)

    def _restart(self) -> None:
        if self.progress.running:
            return
        # Verbindung bleibt bestehen; nach dem Neustart wird neu durchsucht und neu gelesen.
        self.state.reset_run()
        self.restart()
        if self.state.storage is not None:
            self.next()  # Verbindungsseite überspringen

    def _confirm_abort(self) -> bool:
        if not self.progress.running:
            return True
        ans = QMessageBox.question(self, "Abbrechen?", "Der Vorgang läuft noch. Wirklich abbrechen?")
        if ans != QMessageBox.StandardButton.Yes:
            return False
        self.progress.cancel()
        if self.progress.worker is not None:
            self.progress.worker.wait(30000)
        return True

    def reject(self) -> None:
        if self._confirm_abort():
            self.state.close_storage()
            super().reject()

    def accept(self) -> None:
        self.state.close_storage()
        super().accept()

    def closeEvent(self, event) -> None:
        if self._confirm_abort():
            self.state.close_storage()
            event.accept()
        else:
            event.ignore()
