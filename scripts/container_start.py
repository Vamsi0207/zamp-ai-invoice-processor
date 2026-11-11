"""Single-worker container entrypoint; never seed an existing database."""
import os
from pathlib import Path

from app.demo_access import credentials


def initialize_database(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Exclusive creation distinguishes new from empty/partially initialized DBs.
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    os.close(fd)
    from scripts.seed import seed
    seed(str(path))
    return True


def main():
    os.environ["ZAMP_REQUIRE_DEMO_AUTH"] = "1"
    credentials()  # Fail closed before seed/importing app.main.
    port = int(os.getenv("PORT", "8000"))
    if not 1 <= port <= 65535:
        raise RuntimeError("PORT must be between 1 and 65535")
    # A persistent disk may be mounted as root. Only adjust its mount root, then drop
    # privileges before reading documents, seeding, or serving requests.
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        Path("/data").mkdir(exist_ok=True)
        os.chown("/data", 10001, 10001)
        os.setgroups([])
        os.setgid(10001)
        os.setuid(10001)
    os.umask(0o077)
    initialize_database(os.environ.get("ZAMP_DB_PATH", "/data/zamp.sqlite3"))
    Path(os.environ.get("ZAMP_DOCUMENT_DIR", "/data/documents")).mkdir(parents=True, exist_ok=True)
    os.execvp("python", ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0",
                         "--port", str(port), "--workers", "1", "--no-access-log"])


if __name__ == "__main__":
    main()
