"""Einstiegspunkt: ``python -m yaleno_wizard`` bzw. ``yaleno-wizard``.

    yaleno-wizard                    Wizard öffnen
    yaleno-wizard --background       Hintergrund-Abgleich mit Symbol im Infobereich
    yaleno-wizard --sync             einmal abgleichen (z. B. für cron/systemd-Timer), Exit-Code 0/1/2
    yaleno-wizard --config DATEI     andere Einstellungsdatei (YAML) verwenden
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="yaleno-wizard", description="Geräte über einen zentralen Speicher abgleichen.")
    parser.add_argument("--version", action="store_true", help="Version anzeigen")
    parser.add_argument("--config", metavar="DATEI", help="Einstellungsdatei (YAML)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--background", "--tray", action="store_true", help="Hintergrund-Abgleich im Infobereich")
    mode.add_argument("--sync", action="store_true", help="einmal ohne Oberfläche abgleichen")
    args, qt_args = parser.parse_known_args(sys.argv[1:] if argv is None else argv)

    if args.version:
        from yaleno_wizard import __version__
        print(__version__)
        return 0

    from yaleno_wizard import settings
    if args.config:
        settings.set_config_file(args.config)

    if args.sync:
        from yaleno_wizard.core.background import run_cli_sync
        return run_cli_sync()

    from PySide6.QtWidgets import QApplication

    from yaleno_wizard import APP_ID, APP_NAME

    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName(APP_ID)
    app.setApplicationDisplayName(APP_NAME)
    app.setDesktopFileName(APP_ID)
    if args.background:
        from yaleno_wizard.gui.tray import run_background
        return run_background(app)

    from yaleno_wizard.gui.wizard import YalenoWizard
    wizard = YalenoWizard()
    wizard.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
