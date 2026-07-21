from __future__ import annotations

import os
from threading import Thread

from flask import Flask


app = Flask("")


@app.route("/")
def home() -> str:
    return "Le bot est en ligne !"


def run_web_server() -> None:
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, use_reloader=False)


def keep_alive() -> None:
    thread = Thread(target=run_web_server, daemon=True)
    thread.start()
