"""Plugin-Manager: Plugins ansehen, (de)aktivieren, installieren, entfernen und aktualisieren."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
    QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..plugins import manager
from ..plugins.model import FEATURES, PluginError
from ..plugins.registry import LoadedPlugin, discover
from ..settings import Profile
from .worker import Worker

COL_ON, COL_NAME, COL_VERSION, COL_ORIGIN, COL_STATUS = range(5)


def confirm_install(parent: QWidget, pending: manager.PendingInstall, title: str = "Plugin installieren") -> bool:
    """Zeigt, was sich ändert (neue Befehle hervorgehoben), und fragt nach."""
    p = pending.plugin
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    verb = "aktualisieren" if pending.is_update else "installieren"
    box.setText(f"„{p.name}“ {p.version} {verb}?")
    info = p.description or p.summary()
    if pending.changes.new_commands:
        box.setIcon(QMessageBox.Icon.Warning)
        info += ("\n\n⚠ Das Plugin führt beim Abgleich Befehle auf diesem Gerät aus. "
                 "Nur installieren, wenn du der Quelle vertraust.")
    else:
        box.setIcon(QMessageBox.Icon.Question)
    if pending.is_downgrade:
        info += f"\n\n⚠ Installiert ist bereits die neuere Version {pending.existing.version}."
    box.setInformativeText(info)
    box.setDetailedText(pending.changes.describe())
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    box.setDefaultButton(QMessageBox.StandardButton.No)
    return box.exec() == QMessageBox.StandardButton.Yes


class PluginDialog(QDialog):
    """Bearbeitet ``profile`` direkt und speichert es bei jeder Änderung."""

    def __init__(self, profile: Profile, parent=None, store=None):
        super().__init__(parent)
        self.profile = profile
        self.store = store
        self.changed = False
        self.worker: Worker | None = None
        self.updates: dict[str, manager.UpdateInfo] = {}
        self.setWindowTitle("Plugins")

        intro = QLabel("Plugins fügen Kategorien für weitere Programme hinzu oder schalten Funktionen wie "
                       "Verschlüsselung frei. Sie sind YAML-Dateien und enthalten keinen Programmcode.")
        intro.setWordWrap(True)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Aktiv", "Name", "Version", "Herkunft", "Status"])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        hdr = self.tree.header()
        hdr.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        for c in (COL_ON, COL_VERSION, COL_ORIGIN, COL_STATUS):
            hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemChanged.connect(self._toggled)
        self.tree.currentItemChanged.connect(self._show_details)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.tree)
        split.addWidget(self.details)
        split.setSizes([260, 160])

        self.btn_file = QPushButton("Aus Datei …")
        self.btn_url = QPushButton("Aus URL …")
        self.btn_store = QPushButton("Aus dem Speicher …")
        self.btn_store.setToolTip("Plugins übernehmen, die andere Geräte im Speicher abgelegt haben.")
        self.btn_store.setVisible(store is not None)
        self.btn_remove = QPushButton("Entfernen")
        self.btn_check = QPushButton("Nach Updates suchen")
        self.btn_update = QPushButton("Aktualisieren")
        self.btn_file.clicked.connect(self._install_file)
        self.btn_url.clicked.connect(self._install_url)
        self.btn_store.clicked.connect(self._from_store)
        self.btn_remove.clicked.connect(self._remove)
        self.btn_check.clicked.connect(self._check)
        self.btn_update.clicked.connect(self._update_selected)
        row = QHBoxLayout()
        for b in (self.btn_file, self.btn_url, self.btn_store, self.btn_remove):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(self.btn_check)
        row.addWidget(self.btn_update)

        self.status = QLabel()
        self.status.setStyleSheet("color: gray")
        self.status.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("Schließen")
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(intro)
        lay.addWidget(split, 1)
        lay.addLayout(row)
        lay.addWidget(self.status)
        lay.addWidget(buttons)
        self.resize(760, 560)
        self.reload()

    # ------------------------------------------------------------------ Liste
    def reload(self, select: str | None = None) -> None:
        cur = select or self.current_id()
        self.rows: dict[str, LoadedPlugin] = {}
        known = set(manager.known_updates()) | set(self.updates)
        self.tree.blockSignals(True)
        self.tree.clear()
        for lp in discover(self.profile):
            self.rows[lp.id] = lp
            it = QTreeWidgetItem()
            it.setData(COL_NAME, Qt.ItemDataRole.UserRole, lp.id)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(COL_ON, Qt.CheckState.Checked if lp.enabled else Qt.CheckState.Unchecked)
            it.setText(COL_NAME, lp.name)
            it.setText(COL_VERSION, lp.version)
            it.setText(COL_ORIGIN, "mitgeliefert" if lp.origin == "builtin" else "installiert")
            if lp.error:
                it.setText(COL_STATUS, "Fehler")
                it.setToolTip(COL_STATUS, lp.error)
            elif lp.id in known:
                it.setText(COL_STATUS, "Update verfügbar")
            else:
                it.setText(COL_STATUS, "aktiv" if lp.enabled else "aus")
            self.tree.addTopLevelItem(it)
            if lp.id == cur:
                self.tree.setCurrentItem(it)
        self.tree.blockSignals(False)
        if self.tree.currentItem() is None and self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        self._show_details()

    def current_id(self) -> str | None:
        it = self.tree.currentItem() if hasattr(self, "tree") else None
        return it.data(COL_NAME, Qt.ItemDataRole.UserRole) if it else None

    def item_for(self, plugin_id: str) -> QTreeWidgetItem | None:
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if it.data(COL_NAME, Qt.ItemDataRole.UserRole) == plugin_id:
                return it
        return None

    def _show_details(self, *_args) -> None:
        pid = self.current_id()
        lp = self.rows.get(pid) if pid else None
        busy = self.worker is not None and self.worker.isRunning()
        self.btn_remove.setEnabled(bool(lp and lp.removable) and not busy)
        self.btn_update.setEnabled(bool(pid and pid in self.updates) and not busy)
        if lp is None:
            self.details.setPlainText("")
            return
        lines = [f"{lp.name} ({lp.id}) – Version {lp.version}"]
        if lp.error:
            lines.append(f"⚠ {lp.error}")
        p = lp.plugin
        if p is not None:
            for label, value in (("Autor", p.author), ("Quelle", p.source), ("Webseite", p.homepage)):
                if value:
                    lines.append(f"{label}: {value}")
            if p.description:
                lines += ["", p.description]
            if p.is_feature:
                lines += ["", f"Schaltet frei: {FEATURES.get(p.feature, p.feature)}"]
            else:
                lines += ["", f"Inhalt: {p.summary()}", "Pfade:"] + [f"  {x}" for x in p.paths()]
                if p.commands():
                    lines += ["Befehle (werden beim Abgleich ausgeführt):"] + [f"  ! {c}" for c in p.commands()]
        if pid in self.updates:
            lines += ["", "Update:", self.updates[pid].pending.changes.describe()]
        lines += ["", f"Datei: {lp.path}"]
        self.details.setPlainText("\n".join(lines))

    def _toggled(self, it: QTreeWidgetItem, col: int) -> None:
        if col != COL_ON:
            return
        pid = it.data(COL_NAME, Qt.ItemDataRole.UserRole)
        on = it.checkState(COL_ON) == Qt.CheckState.Checked
        try:
            manager.set_enabled(pid, on, self.profile)
            self.changed = True
        except (PluginError, OSError) as exc:
            QMessageBox.warning(self, "Plugins", str(exc))
            on = not on
        # Zeile direkt anpassen – die Liste hier neu aufzubauen würde ``it`` mitten im Signal löschen
        lp = self.rows.get(pid)
        if lp is not None:
            lp.enabled = on
        self.tree.blockSignals(True)
        it.setCheckState(COL_ON, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        if it.text(COL_STATUS) in ("aktiv", "aus"):
            it.setText(COL_STATUS, "aktiv" if on else "aus")
        self.tree.blockSignals(False)

    # ------------------------------------------------------------------ Aktionen
    def _install_pending(self, pending: manager.PendingInstall) -> None:
        if not confirm_install(self, pending):
            return
        try:
            manager.install(pending, self.profile)
        except (PluginError, OSError) as exc:
            QMessageBox.warning(self, "Plugins", f"Installation fehlgeschlagen: {exc}")
            return
        self.updates.pop(pending.plugin.id, None)
        self.changed = True
        self.status.setText(f"„{pending.plugin.name}“ installiert und aktiviert.")
        self.reload(pending.plugin.id)

    def install_source(self, source: str) -> None:
        if manager.is_url(source):
            self._run(lambda _rep: manager.prepare_source(source, self.profile), self._install_pending,
                      f"Lade {source} …")
            return
        try:
            pending = manager.prepare_source(source, self.profile)
        except PluginError as exc:
            QMessageBox.warning(self, "Plugins", str(exc))
            return
        self._install_pending(pending)

    def _install_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Plugin installieren", "", "Yaleno-Plugin (*.yml *.yaml)")
        if path:
            self.install_source(path)

    def _install_url(self) -> None:
        url, ok = QInputDialog.getText(self, "Plugin aus URL", "Adresse der Plugin-Datei (https://…):")
        if ok and url.strip():
            self.install_source(url.strip())

    def _remove(self) -> None:
        pid = self.current_id()
        lp = self.rows.get(pid) if pid else None
        if lp is None:
            return
        ans = QMessageBox.question(self, "Plugin entfernen", f"„{lp.name}“ entfernen?\n\nBereits abgeglichene "
                                   "Dateien bleiben im Speicher und auf diesem Gerät erhalten.")
        if ans != QMessageBox.StandardButton.Yes:
            return
        try:
            manager.remove(lp.id, self.profile)
        except (PluginError, OSError) as exc:
            QMessageBox.warning(self, "Plugins", str(exc))
            return
        self.changed = True
        self.reload()

    def _check(self) -> None:
        def done(res: manager.UpdateCheck) -> None:
            self.updates = {u.id: u for u in res.updates}
            msg = (f"{len(res.updates)} Update(s) verfügbar." if res.updates
                   else f"Alle Plugins sind aktuell ({res.checked} geprüft).")
            if res.errors:
                msg += " Fehler: " + "; ".join(res.errors)
            self.status.setText(msg)
            self.reload()
        self._run(lambda _rep: manager.check_updates(self.profile), done, "Suche nach Updates …")

    def _update_selected(self) -> None:
        pid = self.current_id()
        info = self.updates.get(pid) if pid else None
        if info is None:
            return
        if not confirm_install(self, info.pending, "Plugin aktualisieren"):
            return
        try:
            manager.apply_update(info, self.profile)
        except (PluginError, OSError) as exc:
            QMessageBox.warning(self, "Plugins", f"Update fehlgeschlagen: {exc}")
            return
        self.updates.pop(pid, None)
        self.changed = True
        self.status.setText(f"„{info.current.name}“ auf {info.pending.plugin.version} aktualisiert.")
        self.reload(pid)

    def _from_store(self) -> None:
        if self.store is None:
            return
        from ..plugins import distribute
        try:
            offers = distribute.offers(self.store, self.profile)
        except Exception as exc:
            QMessageBox.warning(self, "Plugins", f"Speicher konnte nicht gelesen werden: {exc}")
            return
        if not offers:
            self.status.setText("Im Speicher liegen keine neuen Plugins.")
            return
        if offer_plugins(self, offers, self.profile):
            self.changed = True
        self.reload()

    # ------------------------------------------------------------------ Hintergrund
    def _run(self, fn, on_done, label: str) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        self.status.setText(label)
        for b in (self.btn_check, self.btn_url, self.btn_update):
            b.setEnabled(False)
        self.worker = Worker(fn, self)

        def finish() -> None:
            for b in (self.btn_check, self.btn_url):
                b.setEnabled(True)
            self._show_details()

        def ok(result) -> None:
            self.status.setText("")
            finish()
            on_done(result)

        def fail(msg: str) -> None:
            self.status.setText(f"Fehler: {msg}")
            finish()

        self.worker.succeeded.connect(ok)
        self.worker.failed.connect(fail)
        self.worker.start()

    def done(self, r: int) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.wait(30000)
        super().done(r)


def offer_plugins(parent: QWidget, offers, profile: Profile) -> bool:
    """Fragt je Plugin aus dem Speicher, ob es übernommen werden soll. True, wenn sich etwas geändert hat."""
    from ..plugins import distribute
    changed = False
    for offer in offers:
        if offer.enable_only:
            ans = QMessageBox.question(
                parent, "Plugin aus dem Speicher",
                f"Ein anderes Gerät nutzt „{offer.plugin.name}“. Hier aktivieren?")
            ok = ans == QMessageBox.StandardButton.Yes
        else:
            ok = confirm_install(parent, offer.pending, "Plugin aus dem Speicher übernehmen")
        try:
            if ok:
                distribute.accept(offer, profile)
                changed = True
            else:
                distribute.decline(offer)
        except (PluginError, OSError) as exc:
            QMessageBox.warning(parent, "Plugins", str(exc))
    return changed


# ---------------------------------------------------------------------- Einbindung in den Wizard
def refresh_catalog(state) -> None:
    """Katalog nach Plugin-Änderungen neu aufbauen; abhängige Daten verwerfen."""
    from ..catalog import catalog_for
    state.catalog = catalog_for(state.os_name)
    state.reset_run()


def open_plugin_dialog(parent: QWidget, state) -> bool:
    dlg = PluginDialog(state.profile, parent, store=state.store)
    dlg.exec()
    if dlg.changed:
        refresh_catalog(state)
    return dlg.changed


def offer_from_store(parent: QWidget, state) -> None:
    """Nach dem Verbinden: Plugins anderer Geräte zur Übernahme anbieten."""
    if state.store is None:
        return
    from ..plugins import distribute
    try:
        offers = distribute.offers(state.store, state.profile)
    except Exception:
        return  # Speicher ohne Plugins oder nicht lesbar – kein Grund, das Verbinden zu stören
    if offers and offer_plugins(parent, offers, state.profile):
        refresh_catalog(state)


def plugin_summary(state) -> str:
    n = len(state.catalog.plugins)
    from ..plugins.registry import active_plugins
    feats = sum(1 for p in active_plugins(state.profile) if p.is_feature)
    parts = []
    if n:
        parts.append(f"{n} Programm-Plugin{'s' if n != 1 else ''}")
    if feats:
        parts.append(f"{feats} Funktion{'en' if feats != 1 else ''}")
    text = ", ".join(parts) + " aktiv" if parts else "keine aktiv"
    if state.catalog.plugin_errors:
        text += " · ⚠ " + " ".join(state.catalog.plugin_errors)
    return text
