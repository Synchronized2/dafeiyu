"""Download the version-pinned animation archive without third-party dependencies."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent.parent


def expected_frames(root: Path) -> set[str]:
    frames = set()
    for name in ("pet-manifest.json", "pet-extra-manifest.json"):
        manifest = json.loads((root / "assets" / name).read_text(encoding="utf-8"))
        for clip in manifest["clips"].values():
            frames.update("assets/pet/" + frame for frame in clip["frames"])
    return frames


def validate_entries(archive: zipfile.ZipFile, expected: set[str]) -> list[zipfile.ZipInfo]:
    entries = []
    seen = set()
    for info in archive.infolist():
        path = PurePosixPath(info.filename)
        if (path.is_absolute() or ".." in path.parts or "\\" in info.filename
                or ":" in info.filename or stat.S_ISLNK(info.external_attr >> 16)):
            raise ValueError(f"Unsafe archive path: {info.filename}")
        if info.is_dir():
            continue
        if info.filename.startswith("assets/pet/"):
            if info.filename not in expected or info.filename in seen:
                raise ValueError(f"Unexpected or duplicate animation: {info.filename}")
            if info.file_size > 16 * 1024 * 1024:
                raise ValueError(f"Animation frame too large: {info.filename}")
            entries.append(info)
            seen.add(info.filename)
    if seen != expected:
        raise ValueError(f"Archive is missing {len(expected - seen)} required frames")
    return entries


def install(archive_path: Path, root: Path, expected_sha256: str) -> int:
    digest = sha256(archive_path)
    if digest != expected_sha256:
        raise ValueError("SHA-256 mismatch; the animation archive was not installed")
    with zipfile.ZipFile(archive_path) as archive:
        entries = validate_entries(archive, expected_frames(root))
        for info in entries:
            target = root.joinpath(*PurePosixPath(info.filename).parts)
            # Existing symlink/junction parents must not redirect writes.
            if not target.resolve().is_relative_to(root.resolve()):
                raise ValueError(f"Destination escapes repository: {info.filename}")
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(target.suffix + ".part")
            try:
                with archive.open(info) as source, temporary.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
    return len(entries)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="Install an already downloaded release asset ZIP")
    args = parser.parse_args()
    lock = json.loads((ROOT / "release-assets.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="dafeiyu-assets-") as temporary:
        path = args.archive
        if path is None:
            path = Path(temporary) / lock["filename"]
            print(f"Downloading {lock['url']}", flush=True)
            request = urllib.request.Request(lock["url"], headers={"User-Agent": "dafeiyu-assets/1.0"})
            downloaded = 0
            with urllib.request.urlopen(request, timeout=60) as source, path.open("wb") as destination:
                while block := source.read(1024 * 1024):
                    destination.write(block)
                    downloaded += len(block)
                    if downloaded % (32 * 1024 * 1024) == 0:
                        print(f"  {downloaded // (1024 * 1024)} MiB", flush=True)
            if path.stat().st_size != lock["size"]:
                raise ValueError("Download size mismatch")
        count = install(path, ROOT, lock["sha256"])
        print(f"Installed {count} animation frames. SHA-256 verified.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        raise SystemExit(f"Asset setup failed: {error}")
