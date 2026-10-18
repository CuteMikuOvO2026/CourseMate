"""uvicorn 入口：``uvicorn app.server:app``。"""

from .main import create_app

app = create_app()
