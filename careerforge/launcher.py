"""PyInstaller entry point for the standalone desktop distribution."""

import os
import time
import webbrowser
from threading import Thread, Timer

import uvicorn

from careerforge.main import app


def open_browser() -> None:
    host = os.getenv("CAREERFORGE_BIND_HOST", "127.0.0.1")
    port = int(os.getenv("CAREERFORGE_BIND_PORT", "8787"))
    webbrowser.open(f"http://{host}:{port}/")


if __name__ == "__main__":
    # Open only when launched interactively; service deployments can set this false.
    if os.getenv("CAREERFORGE_OPEN_BROWSER", "true").lower() == "true":
        Timer(0.75, open_browser).start()
    config = uvicorn.Config(
        app,
        host=os.getenv("CAREERFORGE_BIND_HOST", "127.0.0.1"),
        port=int(os.getenv("CAREERFORGE_BIND_PORT", "8787")),
    )
    server = uvicorn.Server(config)

    def shutdown_when_last_tab_closes() -> None:
        grace_seconds = 15
        while not server.should_exit:
            if app.state.client_seen and time.monotonic() - app.state.last_client_heartbeat > grace_seconds:
                server.should_exit = True
                return
            time.sleep(2)

    Thread(target=shutdown_when_last_tab_closes, name="careerforge-tab-watchdog", daemon=True).start()
    server.run()
