"""Entry point for ``python -m appdrop``."""

import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    """Launch the AppDrop application."""
    if argv is None:
        argv = sys.argv[1:]

    # Handle quick flags
    if "--version" in argv or "-v" in argv:
        import appdrop
        print(f"AppDrop {appdrop.__version__}")
        return 0

    if "--help" in argv or "-h" in argv:
        print("Usage: appdrop [OPTIONS] [FILE...]")
        print("\nInstall and manage AppImage and Debian packages via drag-and-drop.")
        print("\nArguments:")
        print("  FILE...        Optional .AppImage or .deb file(s) to open directly")
        print("\nOptions:")
        print("  -v, --version  Show application version")
        print("  -h, --help     Show this help message")
        return 0

    from appdrop.config import setup_logging

    setup_logging()

    # Collect initial file paths from CLI
    initial_files: list[Path] = []
    for arg in argv:
        if not arg.startswith("-"):
            p = Path(arg).resolve()
            if p.is_file():
                initial_files.append(p)

    from PySide6.QtWidgets import QApplication

    from appdrop.gui.main_window import MainWindow
    from appdrop.service import AppService

    app = QApplication(sys.argv[:1])
    app.setApplicationName("AppDrop")
    app.setApplicationVersion("0.1.0")

    service = AppService()
    window = MainWindow(service=service, initial_files=initial_files)
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
