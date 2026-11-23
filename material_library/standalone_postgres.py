"""Initialize and supervise a private PostgreSQL cluster for the standalone library."""

import os
import re
import secrets
import socket
import subprocess
import tempfile
from contextlib import contextmanager, nullcontext
from pathlib import Path

import psycopg
from psycopg.conninfo import make_conninfo


ROLE = "muyi_standalone"
OWNER_FILE = "muyi-standalone-password"


@contextmanager
def lock_data_directory(root: Path):
    """Prevent a second launcher from using or stopping this instance."""
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (root / ".launcher.lock").open("a+b") as lock:
        if os.name == "nt":
            import msvcrt

            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        return reservation.getsockname()[1]


def grant_windows_postgres_access(*directories: Path) -> None:
    """Allow PostgreSQL's restricted Windows token to use a private directory."""
    system = Path(os.environ["SystemRoot"]) / "System32"
    try:
        identity = subprocess.check_output(
            [str(system / "whoami.exe"), "/user", "/fo", "csv", "/nh"], timeout=10,
        )
        sid = re.search(rb"S-1-\d+(?:-\d+)+", identity)
        if not sid:
            raise RuntimeError("无法识别当前 Windows 用户以初始化独立数据库")
        access = f"*{sid[0].decode('ascii')}:(OI)(CI)F"
        for directory in directories:
            subprocess.run(
                [str(system / "icacls.exe"), str(directory), "/grant:r", access, "/q"],
                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
            )
    except subprocess.SubprocessError as error:
        raise RuntimeError("无法为当前 Windows 用户设置独立数据库目录权限") from error


class StandalonePostgres:
    def __init__(self, root: Path, binaries: Path):
        self.root = root
        self.data = root / "postgres"
        self.binaries = binaries
        self.password_file = self.data / OWNER_FILE

    def run(self, name: str, *args: str, check: bool = True, command_log: Path | None = None):
        exe = self.binaries / (name + (".exe" if os.name == "nt" else ""))
        if not exe.is_file():
            raise FileNotFoundError(f"缺少 PostgreSQL 程序 {exe}")
        # A detached server can inherit a pipe on Windows and keep communicate() waiting.
        with (command_log.open("ab") if command_log else nullcontext()) as output:
            result = subprocess.run(
                [str(exe), *args], stdin=subprocess.DEVNULL, text=True,
                stdout=output if output is not None else subprocess.PIPE,
                stderr=subprocess.STDOUT if output is not None else subprocess.PIPE,
                encoding="utf-8", errors="replace", timeout=90,
                env={k: v for k, v in os.environ.items() if not k.upper().startswith("PG")},
            )
        if check and result.returncode:
            detail = f"查看 {command_log}" if command_log else result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"{name} 失败。{detail}")
        return result

    def initialize(self) -> None:
        if self.data.exists():
            if not (self.password_file.is_file() and (self.data / "PG_VERSION").is_file()):
                raise RuntimeError("目标目录已有其他数据库或初始化不完整")
            return
        with tempfile.TemporaryDirectory(prefix=".creating-", dir=self.root) as working:
            staging = Path(working)
            if os.name == "nt":
                # initdb drops the administrator group and must retain the user's own access.
                grant_windows_postgres_access(self.root, staging)
            data = staging / "data"
            password = secrets.token_urlsafe(32)
            password_file = staging / "password"
            descriptor = os.open(password_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, "w", encoding="ascii") as output:
                output.write(password + "\n")
            self.run(
                "initdb", "-D", str(data), "-U", ROLE, "-A", "scram-sha-256",
                "--encoding=UTF8", "--no-locale", f"--pwfile={password_file}",
            )
            password_file.rename(data / OWNER_FILE)
            with (data / "postgresql.conf").open("a", encoding="ascii") as config:
                config.write("\nlisten_addresses = '127.0.0.1'\nunix_socket_directories = ''\n")
            data.rename(self.data)

    def active(self) -> bool:
        result = self.run("pg_ctl", "-D", str(self.data), "status", check=False)
        if result.returncode not in (0, 3):
            raise RuntimeError(f"无法确认独立数据库状态。{result.stderr.strip()}")
        return result.returncode == 0

    def connect_info(self, port: int) -> str:
        password = self.password_file.read_text(encoding="ascii").strip()
        dsn = make_conninfo(
            hostaddr="127.0.0.1", host="127.0.0.1", port=port, dbname="postgres",
            user=ROLE, password=password, sslmode="disable", connect_timeout=5,
        )
        with psycopg.connect(dsn) as db:
            path = db.execute("SHOW data_directory").fetchone()[0]
            listen = db.execute("SHOW listen_addresses").fetchone()[0]
            if Path(path).resolve() != self.data.resolve() or listen != "127.0.0.1":
                raise RuntimeError("独立数据库身份校验失败")
        return dsn

    @contextmanager
    def running(self):
        self.initialize()
        try:
            if self.active():
                pid_lines = (self.data / "postmaster.pid").read_bytes().splitlines()
                port = int(pid_lines[3])
            else:
                port = free_loopback_port()
                self.run(
                    "pg_ctl", "-D", str(self.data), "-l", str(self.root / "postgres.log"),
                    "-w", "-t", "30", "-o", f"-p {port}", "start",
                    command_log=self.root / "postgres-launch.log",
                )
            yield self.connect_info(port)
        finally:
            if self.active():
                self.run("pg_ctl", "-D", str(self.data), "-w", "-t", "30", "-m", "fast", "stop")
