"""Load the replaceable Python driver against the application's PostgreSQL client."""

import os
import sys
from pathlib import Path


def load_packaged_driver() -> None:
    sys.dont_write_bytecode = True
    override = os.environ.get("MUYI_PSYCOPG_PATH")
    if override:
        replacement = Path(override).expanduser().resolve()
        if not (replacement / "psycopg" / "__init__.py").is_file():
            raise ImportError("MUYI_PSYCOPG_PATH must contain a psycopg package")
        sys.path.insert(0, str(replacement))

    root = Path(sys.executable).resolve().parent / "tools" / "postgres"
    search_key, bin_dir = ("PATH", "bin") if os.name == "nt" else ("DYLD_LIBRARY_PATH", "lib")
    previous = os.environ.get(search_key)
    os.environ[search_key] = os.pathsep.join(filter(None, (str(root / bin_dir), previous)))
    os.environ["PSYCOPG_IMPL"] = "python"
    try:
        import psycopg  # noqa: F401
    finally:
        if previous is None:
            del os.environ[search_key]
        else:
            os.environ[search_key] = previous


load_packaged_driver()
