"""Build clean Windows portable and animation ZIPs from verified local inputs."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent.parent


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()



def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--asset-root", type=Path, default=ROOT / "assets/pet")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    runtime = args.runtime_root.resolve()
    for name in ("python.exe", "pythonw.exe", "python312._pth", "LICENSE.txt"):
        if not (runtime / name).is_file():
            raise ValueError(f"Missing portable runtime file: {name}")
    for name in ("PySide6", "PIL", "shiboken6"):
        if not (runtime / "Lib/site-packages" / name).is_dir():
            raise ValueError(f"Missing runtime dependency: {name}")
    expected = set()
    for name in ("pet-manifest.json", "pet-extra-manifest.json"):
        manifest = json.loads((ROOT / "assets" / name).read_text(encoding="utf-8"))
        for clip in manifest["clips"].values():
            expected.update(clip["frames"])
    missing = [name for name in expected if not (args.asset_root / name).is_file()]
    if missing:
        raise ValueError(f"Missing {len(missing)} animation frames, e.g. {missing[:3]}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    asset_zip = args.output_dir / f"Dafeiyu-v{version}-assets.zip"
    portable_zip = args.output_dir / f"Codex-Dafeiyu-v{version}-Windows-x64.zip"
    # Stream from the original inputs. Copying 25k frames into a temporary
    # directory adds substantial filesystem overhead on Windows.
    sources = {}
    for path in ROOT.iterdir():
        if path.is_file() and (path.suffix in {".py", ".pyw", ".cmd", ".md", ".json", ".txt"}
                               or path.name in {"LICENSE", "VERSION"}):
            if path.name not in {"BUNDLE.json", "release-assets.json"}:
                sources[path.name] = path
    for folder in ("runtime", "codex_tests", "scripts", "docs"):
        for path in (ROOT / folder).rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}:
                sources[path.relative_to(ROOT).as_posix()] = path
    media = {}
    for path in (ROOT / "assets").rglob("*"):
        if path.is_file() and "pet" not in path.relative_to(ROOT / "assets").parts:
            media[path.relative_to(ROOT).as_posix()] = path
    for frame in sorted(expected):
        media["assets/pet/" + frame] = args.asset_root / frame
    with zipfile.ZipFile(asset_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.write(ROOT / "ASSET_LICENSE.md", "ASSET_LICENSE.md")
        for index, (name, path) in enumerate(sorted(media.items())):
            archive.write(path, name)
            if index and index % 5000 == 0:
                print("ASSETS_PACKED", index, flush=True)
    with zipfile.ZipFile(asset_zip) as archive:
        if archive.testzip():
            raise RuntimeError("Asset archive CRC check failed")
    lock = dict(version=version, filename=asset_zip.name,
                url=f"https://github.com/Synchronized2/dafeiyu/releases/download/v{version}/{asset_zip.name}",
                size=asset_zip.stat().st_size, sha256=digest(asset_zip), frames=len(expected))
    (ROOT / "release-assets.json").write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    sources["release-assets.json"] = ROOT / "release-assets.json"
    sources.update(media)
    print(f"ASSETS_READY {asset_zip.name} {lock['size']} bytes, {len(expected)} frames", flush=True)
    for path in runtime.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}:
            sources[".windows-runtime/" + path.relative_to(runtime).as_posix()] = path
    bundle = {}
    with zipfile.ZipFile(portable_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for index, (name, path) in enumerate(sorted(sources.items())):
            data = path.read_bytes()
            bundle[name] = hashlib.sha256(data).hexdigest()
            archive.writestr("Codex-Dafeiyu/" + name, data)
            if index and index % 5000 == 0:
                print("PORTABLE_PACKED", index, flush=True)
        archive.writestr("Codex-Dafeiyu/BUNDLE.json", json.dumps(dict(version=version, platform="windows-x64", files=bundle),
                                                              indent=2, ensure_ascii=False) + "\n")
    with zipfile.ZipFile(portable_zip) as archive:
        if archive.testzip():
            raise RuntimeError("Portable archive CRC check failed")
    print(f"PORTABLE_READY {portable_zip.name} {portable_zip.stat().st_size} bytes, {len(bundle)} files", flush=True)
    checksums = "".join(f"{digest(path)}  {path.name}\n" for path in (portable_zip, asset_zip))
    (args.output_dir / "SHA256SUMS.txt").write_text(checksums, encoding="utf-8")
    print(checksums, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
