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
        # An explicit page-close signal lets the process exit promptly. The
        # stale-tab timeout also covers a browser crash or forced termination.
        stale_after_seconds = 8
        last_tab_grace_seconds = 3
        empty_since: float | None = None
        while not server.should_exit:
            now = time.monotonic()
            app.state.client_tabs = {
                client_id: seen_at
                for client_id, seen_at in app.state.client_tabs.items()
                if now - seen_at < stale_after_seconds
            }
            if app.state.client_tabs:
                empty_since = None
            elif app.state.client_seen and empty_since is None:
                # pagehide also fires during a browser refresh; allow that tab
                # a short window to reconnect before ending the local service.
                empty_since = now
            elif app.state.client_seen and now - empty_since >= last_tab_grace_seconds:
                server.should_exit = True
                return
            time.sleep(1)

    Thread(target=shutdown_when_last_tab_closes, name="careerforge-tab-watchdog", daemon=True).start()
    server.run()
