"""Discover media tools installed separately by the user."""

import os
import shutil
import sys
from pathlib import Path


def configure_media_tools(directory: Path | None) -> bool:
    if directory is not None:
        search = [str(directory.expanduser().resolve())]
    else:
        search = [os.environ.get("PATH", "")]
        if sys.platform == "darwin":
            # Homebrew's full build is keg-only, so its tools may be absent from PATH.
            search[:0] = ["/opt/homebrew/opt/ffmpeg-full/bin", "/opt/homebrew/bin", "/usr/local/bin"]
        elif os.name == "nt":
            for key in ("LOCALAPPDATA", "ProgramFiles"):
                if value := os.environ.get(key):
                    links = ("Microsoft", "WinGet", "Links") if key == "LOCALAPPDATA" else ("WinGet", "Links")
                    search.append(str(Path(value).joinpath(*links)))
    path = os.pathsep.join(filter(None, search))
    if not path or not all(shutil.which(tool, path=path) for tool in ("ffmpeg", "ffprobe")):
        return False
    os.environ["PATH"] = path if directory is None else path + os.pathsep + os.environ.get("PATH", "")
    return True
