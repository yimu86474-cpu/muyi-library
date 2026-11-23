"""Build the local standalone preview with the host's Python and native tools."""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from importlib.metadata import distribution
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = "MuyiMaterialLibrary"


def validate_tools(postgres: Path | None, extension: str) -> None:
    if postgres:
        for name in ("initdb", "pg_ctl", "postgres"):
            if not (postgres / "bin" / (name + extension)).is_file():
                raise ValueError(f"PostgreSQL 目录缺少 {name + extension}")
        if not all((postgres / folder).is_dir() for folder in ("lib", "share")):
            raise ValueError("请提供包含 bin、lib、share 的 PostgreSQL 二进制分发目录")
        if (postgres / "data").exists() or (postgres / "PG_VERSION").exists():
            raise ValueError("请提供未初始化的 PostgreSQL 二进制分发目录")


def copy_licenses(bundle: Path) -> None:
    licenses = bundle / "licenses"
    licenses.mkdir()
    python = Path(sys.base_prefix)
    python_license = python / "LICENSE.txt"
    if not python_license.is_file():
        python_license = python / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "LICENSE.txt"
    shutil.copy2(python_license, licenses / "CPython.txt")
    for name in ("certifi", "psycopg", "psycopg-binary", "pyinstaller"):
        package = distribution(name)
        notice = next(path for path in package.files if path.name in {"LICENSE", "LICENSE.txt", "COPYING.txt"})
        shutil.copy2(package.locate_file(notice), licenses / f"{name}-{package.version}.txt")
    for name in ("vue", "hls.js"):
        source = ROOT / "frontend" / "node_modules" / name / "LICENSE"
        shutil.copy2(source, licenses / f"{name}.txt")


def package(output: Path, postgres: Path | None) -> None:
    frontend = ROOT / "frontend" / "dist"
    if not (frontend / "index.html").is_file():
        raise ValueError("先在 frontend 目录执行 npm ci 和 npm run build")
    if output.exists():
        raise ValueError("输出目录已存在，请另选空路径")
    extension = ".exe" if os.name == "nt" else ""
    validate_tools(postgres, extension)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".portable-build-", dir=output.parent) as temporary:
        staging = Path(temporary)
        subprocess.run(
            [
                sys.executable, "-m", "PyInstaller", "--noconfirm", "--onedir", "--name", APP,
                "--paths", str(ROOT), "--collect-all", "psycopg_binary",
                "--add-data", f"{frontend}:frontend", "--distpath", str(staging / "dist"),
                "--specpath", str(staging / "spec"), "--workpath", str(staging / "work"),
                str(ROOT / "material_library" / "standalone.py"),
            ],
            cwd=ROOT, check=True,
        )
        bundle = staging / "dist" / APP
        shutil.copytree(ROOT / "chrome-extension", bundle / "chrome-extension", ignore=shutil.ignore_patterns("tests"))
        if postgres:
            shutil.copytree(postgres, bundle / "tools" / "postgres", symlinks=True)
        copy_licenses(bundle)
        shutil.copy2(ROOT / "LICENSE", bundle / "LICENSE")
        shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.md", bundle / "THIRD_PARTY_NOTICES.md")
        shutil.copy2(ROOT / "docs" / "INSTALL.zh-CN.md", bundle / "INSTALL.zh-CN.md")
        bundle.rename(output)
    print(output / (APP + extension))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--postgres-root", type=Path, help="已解包且未初始化的 PostgreSQL 二进制目录")
    args = parser.parse_args()
    package(args.output.resolve(), args.postgres_root)


if __name__ == "__main__":
    main()
