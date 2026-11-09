"""Einstiegspunkt: ``python -m yaleno_wizard`` bzw. ``yaleno-wizard``."""

from __future__ import annotations

import sys


def main() -> int:
    if "--version" in sys.argv:
        from yaleno_wizard import __version__
        print(__version__)
        return 0

    from PySide6.QtWidgets import QApplication

    from yaleno_wizard import APP_ID, APP_NAME
    from yaleno_wizard.gui.wizard import YalenoWizard

    app = QApplication(sys.argv)
    app.setApplicationName(APP_ID)
    app.setApplicationDisplayName(APP_NAME)
    app.setDesktopFileName(APP_ID)
    wizard = YalenoWizard()
    wizard.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
