import os

from dotenv import load_dotenv

from keep_alive import keep_alive
from yishi_app import create_bot


load_dotenv()

token = os.getenv("DISCORD_TOKEN")
if not token:
    raise RuntimeError("La variable d'environnement DISCORD_TOKEN est manquante.")

bot = create_bot()
keep_alive()
bot.run(token)
