from __future__ import annotations

import os
from pathlib import Path


def onedrive_root() -> Path | None:
    """Folder OneDrive lokal yang sudah tersinkron. Akun bisnis didahulukan."""
    for key in ("OneDriveCommercial", "OneDriveConsumer", "OneDrive"):
        raw = os.environ.get(key, "").strip()
        if raw and Path(raw).is_dir():
            return Path(raw)

    matches = sorted(path for path in Path.home().glob("OneDrive*") if path.is_dir())
    return matches[0] if matches else None


def resolve_dir(raw: str) -> Path:
    """Terima path lokal, path OneDrive, atau variable seperti %OneDrive%\\Finance."""
    value = raw.strip().strip('"')
    if value.lower().startswith(("http://", "https://")):
        raise ValueError(
            "Download folder harus folder OneDrive yang sudah tersinkron di komputer, bukan link web. "
            "Buka OneDrive di File Explorer, klik kanan foldernya, lalu copy path-nya."
        )
    return Path(os.path.expandvars(value)).expanduser().resolve()


if __name__ == "__main__":
    os.environ["ONEDRIVE_TEST"] = str(Path.home())
    assert resolve_dir("$ONEDRIVE_TEST") == Path.home().resolve()
    assert resolve_dir("~") == Path.home().resolve()
    try:
        resolve_dir("https://example-my.sharepoint.com/personal/x/Documents")
        raise AssertionError("URL harus ditolak")
    except ValueError:
        pass
    print("ok")
