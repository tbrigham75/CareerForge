import os

import uvicorn

from .main import app


if __name__ == "__main__":
    uvicorn.run(app, host=os.getenv("CAREERFORGE_BIND_HOST", "127.0.0.1"), port=int(os.getenv("CAREERFORGE_BIND_PORT", "8787")))
