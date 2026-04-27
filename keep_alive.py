import os
from threading import Thread

from flask import Flask


app = Flask("")


@app.route("/")
def home():
    return "Le bot est en ligne !"


def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, use_reloader=False)


def keep_alive():
    t = Thread(target=run, daemon=True)
    t.start()
