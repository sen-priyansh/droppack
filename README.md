# AppDrop

**AppDrop** is a clean, reliable Linux desktop utility that installs and manages AppImage and Debian (`.deb`) packages through drag-and-drop.

Targeted for Pop!_OS and compatible Ubuntu/Debian-based desktop distributions.

---

## Features

- **Drag and Drop Detection**: Drop one or multiple `.AppImage` or `.deb` packages onto the window.
- **Safe Metadata Extraction**: Format sniffing and metadata inspection without executing package binaries.
- **Identity & Update Recognition**: Distinguishes between new installations, updates, downgrades, and existing packages.
- **Managed AppImages**:
  - Installs AppImages into `~/.local/share/appdrop/apps/` (no root required).
  - Automatically creates and manages `.desktop` entries and application icons.
  - Updates preserve previous versions in `~/.local/share/appdrop/backups/`.
  - Instant rollback to the previous version with one click.
  - Clean uninstall removing desktop shortcuts and managed binaries.
- **APT Debian Package Integration**:
  - Installs and upgrades Debian packages via standard `apt-get` with dependency resolution.
  - Privilege escalation isolated via `pkexec` with explicit user confirmation.
  - Automatic silent downgrade prevention with prominent warnings.
  - Full post-installation package verification against system package database.
- **Application Registry & History**:
  - Persistent SQLite database at `~/.local/share/appdrop/registry.db`.
  - Complete timeline of installations, updates, rollbacks, and removals.
- **Installed Applications View**:
  - Searchable list of all installed packages with status and metadata.
  - Direct actions: View History, Rollback (AppImages), Uninstall.
- **Debian Packaging**:
  - Ships with standard Debian packaging (`debian/` and `scripts/build_deb.py`).

---

## Safety Guarantees

1. **No Execution for Inspection**: AppImages and `.deb` archives are never run or executed merely to inspect their metadata. AppImage metadata is parsed from the squashfs filesystem header or filename; `.deb` metadata is parsed using `dpkg-deb --info`.
2. **Strict Shell Safety**: Zero usage of `shell=True` in subprocess calls. All commands use fixed argument lists with `--` parameter separators to prevent argument injection.
3. **No Silent Downgrades**: System packages are checked against `dpkg-query` and `dpkg --compare-versions`. Downgrading an existing package requires explicit confirmation.
4. **Staging & Atomic Updates**: New AppImage versions are validated and staged in `~/.cache/appdrop/` before atomic move to prevent corruption on interruption.
5. **Path Traversal Protection**: Application names, icon paths, and desktop entries are strictly sanitized. Uninstallation refuses to delete any file outside managed directories.

---

## Directory Layout

AppDrop conforms to standard Linux XDG Base Directory specifications:

| Directory | Purpose |
|---|---|
| `~/.local/share/appdrop/apps/` | Managed AppImage executables |
| `~/.local/share/appdrop/backups/` | Previous AppImage versions for rollback |
| `~/.local/share/appdrop/registry.db` | Local SQLite registry database |
| `~/.local/share/appdrop/logs/` | Application log files |
| `~/.local/share/applications/` | User desktop entry files (`appdrop-*.desktop`) |
| `~/.local/share/icons/appdrop/` | Extracted application icons |
| `~/.cache/appdrop/` | Staging area for atomic operations |

---

## Installation & Usage

### Running from source

```bash
# Clone the repository
git clone https://github.com/appdrop/appdrop.git
cd appdrop

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies and editable package
pip install -e '.[dev]'

# Launch AppDrop
python3 -m appdrop
# or
appdrop
```

### Building the Debian package (.deb)

To build a standalone `.deb` package for Pop!_OS / Ubuntu / Debian:

```bash
python3 scripts/build_deb.py
```

The resulting package will be in `dist/appdrop_0.1.0_all.deb`.

To install it onto your system:

```bash
sudo apt install ./dist/appdrop_0.1.0_all.deb
```

---

## Running the Test Suite

AppDrop features a comprehensive automated test suite (142 unit and integration tests) covering format detection, identity matching, SQLite transactions, AppImage rollback, APT operations, GUI components, and security audits.

```bash
source .venv/bin/activate
pytest -v
```

All GUI tests run headlessly in offscreen mode (`QT_QPA_PLATFORM=offscreen`).
Package operations use mock command runners and temporary sandboxed directories, never performing destructive actions on the host system.
