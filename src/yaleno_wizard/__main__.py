"""Einstiegspunkt: ``python -m yaleno_wizard`` bzw. ``yaleno-wizard``.

    yaleno-wizard                    Wizard öffnen
    yaleno-wizard --background       Hintergrund-Abgleich mit Symbol im Infobereich
    yaleno-wizard --sync             einmal abgleichen (z. B. für cron/systemd-Timer), Exit-Code 0/1/2
    yaleno-wizard --config DATEI     andere Einstellungsdatei (YAML) verwenden
    yaleno-wizard --install          ins Startmenü eintragen (Linux; Windows nutzt den Installer)
    yaleno-wizard --uninstall        Eintrag wieder entfernen
    yaleno-wizard encryption …       Verschlüsselung (status, enable, unlock … – siehe encryption --help)
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["encryption"]:
        from yaleno_wizard.encryption_cli import main as encryption_main
        return encryption_main(argv[1:])

    parser = argparse.ArgumentParser(prog="yaleno-wizard", description="Geräte über einen zentralen Speicher abgleichen.")
    parser.add_argument("--version", action="store_true", help="Version anzeigen")
    parser.add_argument("--config", metavar="DATEI", help="Einstellungsdatei (YAML)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--background", "--tray", action="store_true", help="Hintergrund-Abgleich im Infobereich")
    mode.add_argument("--sync", action="store_true", help="einmal ohne Oberfläche abgleichen")
    mode.add_argument("--install", action="store_true", help="ins Startmenü eintragen (mit Logo)")
    mode.add_argument("--uninstall", action="store_true", help="Startmenü-Eintrag und Programm entfernen")
    args, qt_args = parser.parse_known_args(argv)

    if args.version:
        from yaleno_wizard import __version__
        print(__version__)
        return 0

    from yaleno_wizard import settings
    if args.config:
        settings.set_config_file(args.config)

    if args.install or args.uninstall:
        from yaleno_wizard import install
        return install.main(uninstall=args.uninstall)

    if args.sync:
        from yaleno_wizard.core.background import run_cli_sync
        return run_cli_sync()

    from PySide6.QtWidgets import QApplication

    from yaleno_wizard import APP_ID, APP_NAME

    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName(APP_ID)
    app.setApplicationDisplayName(APP_NAME)
    app.setDesktopFileName(APP_ID)  # verknüpft Fenster mit dem Startmenü-Eintrag (Symbol in der Taskleiste)
    from yaleno_wizard.assets import app_icon
    app.setWindowIcon(app_icon())
    if args.background:
        from yaleno_wizard.gui.tray import run_background
        return run_background(app)

    from yaleno_wizard.gui.app_lock_dialog import ensure_app_unlocked
    if not ensure_app_unlocked():
        return 0
    from yaleno_wizard.gui.wizard import YalenoWizard
    wizard = YalenoWizard()
    wizard.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
