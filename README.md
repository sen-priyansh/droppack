# AppDrop

Drag-and-drop installer and manager for AppImage and Debian packages on
Pop!_OS and compatible Ubuntu/Debian-based distributions.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
python -m appdrop
```

## Running tests

```bash
source .venv/bin/activate
pytest -v
```

## Requirements

- Python 3.10+
- PySide6
- `dpkg-deb` (provided by dpkg)
- `unsquashfs` (provided by squashfs-tools, optional for AppImage metadata)
- `pkexec` (for privileged .deb installation)
