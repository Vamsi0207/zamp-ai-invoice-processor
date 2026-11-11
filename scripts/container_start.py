"""Single-worker container entrypoint; never seed an existing database."""
import os
from pathlib import Path

from app.demo_access import credentials
from app.public_demo import enabled, mark_new_workspace, settings


def initialize_database(path):
    path = Path(path)
    public = enabled()
    document_root = Path(os.getenv("ZAMP_DOCUMENT_DIR", str(path.parent / "documents")))
    if public and not path.exists() and document_root.exists() and any(document_root.iterdir()):
        raise RuntimeError("Choose a new empty public-demo document directory; existing files were not changed")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Exclusive creation distinguishes new from empty/partially initialized DBs.
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    os.close(fd)
    from scripts.seed import seed
    seed(str(path))
    if public:
        mark_new_workspace(str(path), document_root)
    return True


def main():
    if not enabled():
        os.environ["ZAMP_REQUIRE_DEMO_AUTH"] = "1"
    else:
        settings()
        os.environ.setdefault("OMP_THREAD_LIMIT", "1")
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
    command = ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0",
               "--port", str(port), "--workers", "1", "--no-access-log"]
    if enabled():
        command += ["--limit-concurrency", "16", "--backlog", "32", "--timeout-keep-alive", "5"]
    os.execvp("python", command)


if __name__ == "__main__":
    main()
