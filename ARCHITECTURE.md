# Architecture du bot

## Vue d'ensemble
- `bot.py` : point d'entrée minimal. Il délègue tout au package `yishi_bot`.
- `yishi_bot/` : tout le code métier du bot.
- `data/` : fichiers JSON locaux utilisés uniquement en fallback quand `DATABASE_URL` n'est pas défini.

## Package principal
- `yishi_bot/launcher.py` : démarrage du bot, chargement des variables d'environnement, lancement du keep-alive.
- `yishi_bot/core.py` : classe `YishiBot`, persistance, logique métier centrale, sync et utilitaires internes.
- `yishi_bot/storage.py` : couche de persistance. Utilise Postgres si `DATABASE_URL` est défini, sinon écrit dans `data/`.
- `yishi_bot/web.py` : mini serveur Flask pour le ping/keep-alive.
- `yishi_bot/ticketing.py` : types de tickets, embeds de panel et helpers de nommage des salons.
- `yishi_bot/constants.py` : constantes globales, textes fixes, tables gacha, noms auto-configurés.
- `yishi_bot/helpers.py` : fonctions utilitaires pures réutilisables.
- `yishi_bot/views.py` : composants d'interface Discord (`View`, `Button`, `Select`, `Modal`).

## Cogs
- `yishi_bot/cogs/events.py` : listeners Discord (joins, logs, anti-lien, réactions, vocal, etc.).
- `yishi_bot/cogs/general.py` : aide, paiements, infos membres, messages, annonces, sondages.
- `yishi_bot/cogs/gacha.py` : spins, stock, notes joueurs, historique, taux de drop.
- `yishi_bot/cogs/moderation.py` : clear, kick, ban, mute, unmute, unban, warns.
- `yishi_bot/cogs/tickets.py` : panel tickets, ajout/retrait membres ticket.
- `yishi_bot/cogs/giveaways.py` : création, fin, liste et reroll des giveaways.
- `yishi_bot/cogs/sales.py` : annonces de vente, achat via bouton, fermeture des ventes.
- `yishi_bot/cogs/configuration.py` : rôles, salons, catégories et règlement.

## Données locales
- `data/config.json`
- `data/tickets.json`
- `data/warnings.json`
- `data/invites.json`
- `data/giveaways.json`
- `data/gacha.json`
- `data/sales.json`

## Persistance recommandée sur Render ou VPS
- Définir `DATABASE_URL` pour sortir complètement de la dépendance au filesystem local.
- Au premier démarrage avec `DATABASE_URL`, le bot migre automatiquement les états JSON locaux vers la table `bot_state`.
- Une fois Postgres activé, les JSON dans `data/` ne servent plus que de fallback local.
