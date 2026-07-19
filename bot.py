import os

from dotenv import load_dotenv

from keep_alive import keep_alive
from yishi_bot import create_bot

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("La variable d'environnement DISCORD_TOKEN est introuvable.")

bot = create_bot()
keep_alive()
bot.run(TOKEN)
