"""Build a clean QGIS ZIP and optionally export its public source tree."""

import argparse
import configparser
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
from urllib.parse import urlparse
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {
    "__init__.py", "plugin.py", "metadata.txt", "README.md", "LICENSE",
    "THIRD_PARTY.md", "CHANGELOG.md",
}
SOURCE_DIRS = {
    "controllers", "core", "gui", "models", "services", "docs", "tools", "tests",
}
TEXT_SUFFIXES = {".py", ".md"}
MAX_BYTES = 25_000_000


def source_files():
    """Use an allowlist so local datasets and build products cannot leak in."""
    files = []
    for path in sorted(ROOT.rglob("*")):
        relative = path.relative_to(ROOT)
        if (not path.is_file() or path.is_symlink()
                or any(part.startswith(".") or part == "__pycache__"
                       for part in relative.parts)):
            continue
        if relative.as_posix() in ROOT_FILES:
            files.append(path)
        elif (relative.parts[0] in SOURCE_DIRS
              and path.suffix in TEXT_SUFFIXES):
            files.append(path)
    return files


def validate(files, preview=False):
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(ROOT / "metadata.txt", encoding="utf-8")
    meta = parser["general"]
    errors = []
    names = {p.relative_to(ROOT).as_posix() for p in files}
    for name in ROOT_FILES:
        if name not in names:
            errors.append(f"Missing required file: {name}")
    for key in ("name", "description", "version", "qgisMinimumVersion",
                "author", "email", "about", "license"):
        if not meta.get(key, "").strip():
            errors.append(f"Missing metadata: {key}")
    for key in ("homepage", "repository", "tracker"):
        value = meta.get(key, "").strip()
        url = urlparse(value)
        valid = url.scheme in {"https", "http"} and bool(url.hostname)
        if not valid:
            message = f"Missing/invalid public URL: {key}"
            if preview:
                print(f"PREVIEW WARNING: {message}", file=sys.stderr)
            else:
                errors.append(message)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", meta.get("version", "")):
        errors.append("Version cannot be used safely as a filename")
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
            if path.suffix == ".py":
                compile(text, str(path.relative_to(ROOT)), "exec")
            elif path.suffix == ".json":
                json.loads(text)
        except (SyntaxError, ValueError, UnicodeError) as exc:
            errors.append(f"Invalid source {path.relative_to(ROOT)}: {exc}")
    if errors:
        raise ValueError("\n".join(errors))
    return meta


def build(preview=False, source_dir=None):
    files = source_files()
    meta = validate(files, preview=preview)
    payloads = {p.relative_to(ROOT).as_posix(): p.read_bytes() for p in files}
    manifest = {name: hashlib.sha256(data).hexdigest()
                for name, data in payloads.items()}
    # Confirm syntax and size before writing any output.
    total_size = sum(map(len, payloads.values()))
    if total_size > MAX_BYTES:
        raise ValueError("Uncompressed package exceeds 25 MB")
    destination = None
    if source_dir:
        destination = Path(source_dir).resolve()
        if ROOT / "dist" not in destination.parents:
            raise ValueError("Source export must be a new directory inside dist/")
        if destination.exists():
            raise ValueError("Source export directory already exists; choose a new path")
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    suffix = "-preview" if preview else ""
    archive = output / f"geolichen-{meta['version']}{suffix}.zip"
    with ZipFile(archive, "w", compression=ZIP_DEFLATED, compresslevel=9) as package:
        for name, data in payloads.items():
            info = ZipInfo(f"geolichen/{name}", date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            package.writestr(info, data)
    if archive.stat().st_size > MAX_BYTES:
        archive.unlink()
        raise ValueError("ZIP exceeds 25 MB")
    with ZipFile(archive) as package:
        if package.testzip() is not None:
            raise ValueError("ZIP integrity check failed")
        for name, digest in manifest.items():
            if hashlib.sha256(package.read(f"geolichen/{name}")).hexdigest() != digest:
                raise ValueError(f"ZIP/source mismatch: {name}")
    report = {
        "preview": preview,
        "version": meta["version"],
        "file_count": len(manifest),
        "uncompressed_bytes": total_size,
        "zip_bytes": archive.stat().st_size,
        "zip_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "files": manifest,
    }
    manifest_path = archive.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if destination:
        destination.mkdir(parents=True)
        for name, data in payloads.items():
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        shutil.copyfile(ROOT / ".gitignore", destination / ".gitignore")
    print(json.dumps({k: v for k, v in report.items() if k != "files"}, indent=2))
    print(archive)
    print(manifest_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", action="store_true",
                        help="Allow incomplete public URLs for local tests only")
    parser.add_argument("--source-dir", help="Export public source into a new dist/ directory")
    args = parser.parse_args()
    try:
        build(preview=args.preview, source_dir=args.source_dir)
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f"Release build failed:\n{exc}\n")


if __name__ == "__main__":
    main()
