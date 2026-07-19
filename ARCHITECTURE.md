# Architecture du bot

## Point d'entrée
- `bot.py` : démarre Flask keep-alive, charge le token et lance le bot.
- `yishi_bot_app.py` : wrapper de compatibilité qui réexporte `create_bot`.

## Package principal
- `yishi_bot/core.py` : classe `YishiBot`, stockage, logique métier centrale, sync et outils internes.
- `yishi_bot/constants.py` : constantes globales, textes fixes, tables gacha, noms auto-configurés.
- `yishi_bot/helpers.py` : helpers purs et fonctions utilitaires réutilisables.
- `yishi_bot/views.py` : composants d'interface Discord (`View`, `Button`, `Select`, `Modal`).

## Cogs
- `yishi_bot/cogs/events.py` : listeners Discord (joins, logs, anti-lien, réactions, vocal, etc.).
- `yishi_bot/cogs/general.py` : aide, paiements, infos membres, messages, annonces, sondages.
- `yishi_bot/cogs/gacha.py` : spins, stock, notes joueurs, historique, taux de drop.
- `yishi_bot/cogs/moderation.py` : clear, kick, ban, mute, unmute, unban, warns.
- `yishi_bot/cogs/tickets.py` : panel tickets, ajout/retrait membres ticket.
- `yishi_bot/cogs/giveaways.py` : création, fin, liste et reroll des giveaways.
- `yishi_bot/cogs/configuration.py` : rôles, salons, catégories et règlement.

## Fichiers de données
- `storage.py` : lecture/écriture JSON.
- `config.json`, `tickets.json` et les autres JSON : persistance locale.
