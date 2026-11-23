"""Desktop actions invoked only by explicit user operations."""
import base64
import subprocess
from pathlib import Path


def pick_windows_folder() -> str:
    script = """
    $ErrorActionPreference = 'Stop'
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    Add-Type -AssemblyName System.Windows.Forms
    $dialog = [System.Windows.Forms.FolderBrowserDialog]::new()
    try {
        $dialog.Description = '选择包含图片和视频的文件夹'
        $dialog.ShowNewFolderButton = $false
        if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
            [Console]::WriteLine($dialog.SelectedPath)
        }
    } finally { $dialog.Dispose() }
    """
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-STA", "-EncodedCommand", encoded],
        capture_output=True, timeout=300, check=True,
    )
    return result.stdout.decode("utf-8-sig").strip()


def move_to_macos_trash(path: Path) -> None:
    script = (
        "on run argv\n"
        "set targetFile to POSIX file (item 1 of argv) as alias\n"
        "tell application \"Finder\" to delete targetFile\n"
        "end run"
    )
    subprocess.run(
        ["osascript", "-e", script, str(path)],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    if path.exists():
        raise OSError("原文件仍在原位置，未确认进入废纸篓")


def open_macos_privacy_settings(program_path: Path) -> None:
    subprocess.run(
        ["/usr/bin/open", "-R", str(program_path)],
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    subprocess.run(
        ["/usr/bin/open", "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?Privacy_AllFiles"],
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
