"""Real backend for browser tests, isolated from all user data and API credentials."""
import os
import tempfile

import uvicorn

from app.main import create_app
from scripts.seed import seed


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="zamp-browser-") as directory:
        path = f"{directory}/test.sqlite3"
        os.environ["ZAMP_DOCUMENT_DIR"] = f"{directory}/documents"
        seed(path)
        uvicorn.run(create_app(path), host="127.0.0.1", port=8911, log_level="warning")
