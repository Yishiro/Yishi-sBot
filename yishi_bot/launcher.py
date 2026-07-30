from __future__ import annotations

import os

from dotenv import load_dotenv

from yishi_bot.core import create_bot
from yishi_bot.web import keep_alive


def main() -> None:
    load_dotenv()

    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("La variable d'environnement DISCORD_TOKEN est introuvable.")

    bot = create_bot()
    keep_alive(bot)
    bot.run(token)
