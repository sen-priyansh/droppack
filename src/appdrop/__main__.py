"""Entry point for ``python -m appdrop``."""

import sys


def main() -> int:
    """Launch the AppDrop application."""
    from appdrop.config import setup_logging

    setup_logging()

    from PySide6.QtWidgets import QApplication

    from appdrop.gui.main_window import MainWindow
    from appdrop.service import AppService

    app = QApplication(sys.argv)
    app.setApplicationName("AppDrop")
    app.setApplicationVersion("0.1.0")

    service = AppService()
    window = MainWindow(service=service)
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
