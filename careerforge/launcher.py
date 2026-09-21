"""PyInstaller entry point for the standalone desktop distribution."""

import os
import webbrowser
from threading import Timer

import uvicorn

from careerforge.main import app


def open_browser() -> None:
    host = os.getenv("CAREERFORGE_BIND_HOST", "127.0.0.1")
    port = int(os.getenv("CAREERFORGE_BIND_PORT", "8787"))
    webbrowser.open(f"http://{host}:{port}/docs")


if __name__ == "__main__":
    # Open only when launched interactively; service deployments can set this false.
    if os.getenv("CAREERFORGE_OPEN_BROWSER", "true").lower() == "true":
        Timer(0.75, open_browser).start()
    uvicorn.run(
        app,
        host=os.getenv("CAREERFORGE_BIND_HOST", "127.0.0.1"),
        port=int(os.getenv("CAREERFORGE_BIND_PORT", "8787")),
    )
