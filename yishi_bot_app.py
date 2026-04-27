import asyncio
import random
import re
from datetime import timedelta
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from storage import (
    CONFIG_FILE,
    GIVEAWAYS_FILE,
    INVITES_FILE,
    TICKETS_FILE,
    WARNINGS_FILE,
    load_json,
    save_json,
)
from tickets import TICKET_TYPES, build_ticket_panel_embed, slugify_name


AUTO_STAFF_ROLE_NAME = "👑・𝐒taff"
AUTO_ARCHIVE_ROLE_NAME = "👑・𝐅ondateur"
AUTO_TICKET_CATEGORY_NAME = "Tickets"
AUTO_ARCHIVE_CATEGORY_NAME = "Ticket-Close"

INVITE_ROLE_WEIGHTS = {
    "🥉 Inviteur Bronze • 5": 1.5,
    "🥈 Inviteur Silver • 10": 2.0,
    "🥇 Inviteur Gold • 15": 2.5,
    "💎 Inviteur Diamond • 20": 3.0,
}

WELCOME_CHECKLIST = (
    "• Lire les salons importants\n"
    "• Consulter la boutique disponible\n"
    "• Ouvrir un ticket si tu as une question ou si tu veux passer commande"
)

WELCOME_ADVANTAGES = (
    "• Shop fiable, rapide et professionnel\n"
    "• Service sérieux, sécurisé et de qualité\n"
    "• Staff disponible pour t'aider"
)

RULES_TEXT = """📜 𝐑èglement Officiel
Bienvenue sur Yishi's Shop.
Afin de garantir une expérience sérieuse, fluide et agréable à l'ensemble des membres, chaque utilisateur est tenu de respecter le règlement ci-dessous.

✧ 1. Respect & comportement
Le respect envers tous les membres du serveur est obligatoire.
Tout comportement toxique, irrespectueux, provocateur, agressif, insultant ou humiliant est strictement interdit.

✧ 2. Spam & flood interdits
Les messages répétitifs, le flood, le spam, les abus de majuscules, les mentions abusives ainsi que l'utilisation excessive d'emojis sont interdits.

✧ 3. Contenus inappropriés
Tout contenu choquant, violent, haineux, discriminatoire, sexuel, offensant ou inadapté au serveur est formellement interdit.

✧ 4. Publicité non autorisée
La publicité, sous quelque forme que ce soit, est interdite sans autorisation préalable du staff.
Cela inclut les serveurs Discord, shops, réseaux sociaux, sites, services ou messages privés à but promotionnel.

✧ 5. Utilisation correcte des salons
Chaque salon possède une utilité précise.
Merci de respecter leur fonction et d'éviter le hors-sujet afin de préserver une organisation claire et professionnelle.

✧ 6. Commandes sérieuses uniquement
Les commandes, demandes ou réservations doivent être sérieuses.
Toute perte de temps volontaire, troll, faux intérêt ou abus envers le staff pourra être sanctionné.

✧ 7. Tolérance zéro envers les arnaques
Toute tentative d'arnaque, fraude, faux paiement, fausse preuve, chargeback, manipulation ou tromperie entraînera une sanction immédiate pouvant aller jusqu'au bannissement définitif.

✧ 8. Paiements & preuves
Les consignes données par le staff concernant les paiements, preuves, validations et tickets doivent être respectées.
Toute tentative de contourner le système ou de fournir de fausses informations est interdite.

✧ 9. Respect du staff
Le staff est présent pour assurer le bon fonctionnement du serveur.
Le manque de respect, la provocation, l'abus ou le refus délibéré de coopération avec l'équipe de modération ne seront pas tolérés.

✧ 10. Tickets & support
Les tickets doivent être ouverts uniquement pour une raison valable : commande, question importante, assistance ou problème réel.
Tout abus de ticket pourra entraîner une restriction d'accès au support.

✧ 11. Sécurité personnelle
Ne partagez jamais vos informations sensibles : mots de passe, codes, adresses e-mail, moyens de paiement ou données privées.
Vous êtes responsable de la sécurité de votre compte et de vos échanges.

✧ 12. Transactions & services
Les échanges et services proposés au sein du shop doivent rester clairs, honnêtes et conformes à ce qui est annoncé.
Toute tentative de nuisance, de faux deal ou de perturbation volontaire sera sanctionnée.

✧ 13. Sanctions
Le non-respect du règlement peut entraîner, selon la gravité des faits :

avertissement
mute
exclusion temporaire
bannissement définitif

Le staff se réserve le droit d'adapter les sanctions selon la situation.

✧ 14. Acceptation du règlement
En restant sur Yishi's Shop, vous acceptez automatiquement l'ensemble des règles mentionnées ci-dessus et vous engagez à les respecter pleinement.

Merci de votre confiance et bon shopping sur Yishi's Shop"""

RULES_ACCEPT_TEXT = (
    "En réagissant avec ✅ à ce message, tu acceptes le règlement du serveur "
    "et tu obtiens l'accès complet au serveur."
)


def parse_duration(value: str) -> int | None:
    match = re.fullmatch(r"(\d+)([mhd])", value.lower().strip())
    if match is None:
        return None

    amount = int(match.group(1))
    unit = match.group(2)
    if amount <= 0:
        return None
    if unit == "m":
        return amount * 60
    if unit == "h":
        return amount * 60 * 60
    return amount * 24 * 60 * 60


def split_long_message(text: str, limit: int = 1900) -> list[str]:
    if len(text) <= limit:
        return [text]

    parts: list[str] = []
    current = ""
    for block in text.split("\n\n"):
        candidate = block if not current else f"{current}\n\n{block}"
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            parts.append(current)
        current = block

    if current:
        parts.append(current)
    return parts


def default_config() -> dict[str, Any]:
    return {
        "staff_role_id": None,
        "archive_role_id": None,
        "ticket_category_id": None,
        "archive_category_id": None,
        "welcome_channel_id": None,
        "rules_role_id": None,
        "rules_message_id": None,
        "rules_channel_id": None,
    }


def can_moderate(
    actor: discord.Member,
    target: discord.Member,
    bot_member: discord.Member,
) -> str | None:
    if target == actor:
        return "Tu ne peux pas te modérer toi-même."
    if target == bot_member:
        return "Je ne peux pas me modérer moi-même."
    if target.top_role >= actor.top_role and actor != actor.guild.owner:
        return "Tu ne peux pas modérer ce membre car son rôle est égal ou supérieur au tien."
    if target.top_role >= bot_member.top_role:
        return "Je ne peux pas modérer ce membre car son rôle est trop élevé."
    return None


def get_member_giveaway_weight(member: discord.Member) -> float:
    weight = 1.0
    for role in member.roles:
        weight = max(weight, INVITE_ROLE_WEIGHTS.get(role.name, 1.0))

    if member.premium_since is not None or discord.utils.get(member.roles, name="Server Booster"):
        weight += 1.0
    return weight


class TicketPanelSelect(discord.ui.Select):
    def __init__(self, bot: "YishiBot") -> None:
        options = [
            discord.SelectOption(
                label=data["label"],
                value=key,
                description=data["description"],
                emoji=data["emoji"],
            )
            for key, data in TICKET_TYPES.items()
        ]
        super().__init__(
            placeholder="Sélectionnez la raison de votre ticket...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="ticket_panel_select",
        )
        self.bot = bot

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.message is not None:
            await interaction.message.edit(view=TicketPanelView(self.bot))
        await self.bot.create_ticket(interaction, self.values[0])


class TicketPanelView(discord.ui.View):
    def __init__(self, bot: "YishiBot") -> None:
        super().__init__(timeout=None)
        self.add_item(TicketPanelSelect(bot))


class TicketCloseButton(discord.ui.Button):
    def __init__(self, bot: "YishiBot") -> None:
        super().__init__(
            label="Fermer",
            style=discord.ButtonStyle.danger,
            emoji="🔒",
            custom_id="ticket_close_button",
        )
        self.bot = bot

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.bot.archive_ticket(interaction)


class TicketCloseView(discord.ui.View):
    def __init__(self, bot: "YishiBot") -> None:
        super().__init__(timeout=None)
        self.add_item(TicketCloseButton(bot))


class TicketReopenButton(discord.ui.Button):
    def __init__(self, bot: "YishiBot") -> None:
        super().__init__(
            label="Réouvrir",
            style=discord.ButtonStyle.success,
            emoji="🔓",
            custom_id="ticket_reopen_button",
        )
        self.bot = bot

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.bot.reopen_ticket(interaction)


class TicketArchiveView(discord.ui.View):
    def __init__(self, bot: "YishiBot") -> None:
        super().__init__(timeout=None)
        self.add_item(TicketReopenButton(bot))


class GiveawayJoinButton(discord.ui.Button):
    def __init__(self, bot: "YishiBot") -> None:
        super().__init__(
            label="Participer",
            style=discord.ButtonStyle.success,
            emoji="🎉",
            custom_id="giveaway_join_button",
        )
        self.bot = bot

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.bot.join_giveaway(interaction)


class GiveawayView(discord.ui.View):
    def __init__(self, bot: "YishiBot") -> None:
        super().__init__(timeout=None)
        self.add_item(GiveawayJoinButton(bot))


class YishiBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

        self.config_data = load_json(CONFIG_FILE, {})
        self.ticket_data = load_json(TICKETS_FILE, {})
        self.warning_data = load_json(WARNINGS_FILE, {})
        self.invite_data = load_json(INVITES_FILE, {})
        self.giveaway_data = load_json(GIVEAWAYS_FILE, {})

        self.invite_cache: dict[int, dict[str, int]] = {}
        self.giveaway_tasks: dict[str, asyncio.Task] = {}
        self.sync_done = False

    async def setup_hook(self) -> None:
        self.add_view(TicketPanelView(self))
        self.add_view(TicketCloseView(self))
        self.add_view(TicketArchiveView(self))
        self.add_view(GiveawayView(self))
        await self.add_cog(MainCog(self))

    def get_guild_config(self, guild_id: int) -> dict[str, Any]:
        key = str(guild_id)
        if key not in self.config_data:
            self.config_data[key] = default_config()
            self.save_config()
        return self.config_data[key]

    def get_ticket_store(self, guild_id: int) -> dict[str, Any]:
        key = str(guild_id)
        if key not in self.ticket_data:
            self.ticket_data[key] = {"channels": {}}
            self.save_tickets()
        return self.ticket_data[key]

    def get_warning_store(self, guild_id: int) -> dict[str, Any]:
        key = str(guild_id)
        if key not in self.warning_data:
            self.warning_data[key] = {}
            self.save_warnings()
        return self.warning_data[key]

    def get_invite_store(self, guild_id: int) -> dict[str, Any]:
        key = str(guild_id)
        if key not in self.invite_data:
            self.invite_data[key] = {}
            self.save_invites()
        return self.invite_data[key]

    def get_giveaway_store(self, guild_id: int) -> dict[str, Any]:
        key = str(guild_id)
        if key not in self.giveaway_data:
            self.giveaway_data[key] = {}
            self.save_giveaways()
        return self.giveaway_data[key]

    def save_config(self) -> None:
        save_json(CONFIG_FILE, self.config_data)

    def save_tickets(self) -> None:
        save_json(TICKETS_FILE, self.ticket_data)

    def save_warnings(self) -> None:
        save_json(WARNINGS_FILE, self.warning_data)

    def save_invites(self) -> None:
        save_json(INVITES_FILE, self.invite_data)

    def save_giveaways(self) -> None:
        save_json(GIVEAWAYS_FILE, self.giveaway_data)

    def get_invite_count(self, guild_id: int, user_id: int) -> int:
        return int(self.get_invite_store(guild_id).get(str(user_id), 0))

    def get_open_tickets_for_user(self, guild_id: int, user_id: int) -> list[dict[str, Any]]:
        return [
            ticket
            for ticket in self.get_ticket_store(guild_id)["channels"].values()
            if ticket["owner_id"] == user_id and ticket["status"] == "open"
        ]

    def get_next_ticket_number(self, guild_id: int) -> int:
        tickets = self.get_ticket_store(guild_id)["channels"].values()
        used_numbers = sorted(
            ticket["number"]
            for ticket in tickets
            if ticket["status"] == "open"
        )

        expected = 1
        for number in used_numbers:
            if number == expected:
                expected += 1
            elif number > expected:
                break
        return expected

    def get_bot_member(self, guild: discord.Guild) -> discord.Member | None:
        if self.user is None:
            return None
        return guild.get_member(self.user.id)

    async def ensure_ticket_config(self, guild: discord.Guild) -> None:
        config = self.get_guild_config(guild.id)

        staff_role = guild.get_role(config["staff_role_id"]) if config["staff_role_id"] else None
        if staff_role is None:
            staff_role = discord.utils.get(guild.roles, name=AUTO_STAFF_ROLE_NAME)
            if staff_role is None:
                staff_role = await guild.create_role(
                    name=AUTO_STAFF_ROLE_NAME,
                    reason="Auto configuration tickets",
                )
            config["staff_role_id"] = staff_role.id

        archive_role = guild.get_role(config["archive_role_id"]) if config["archive_role_id"] else None
        if archive_role is None:
            archive_role = discord.utils.get(guild.roles, name=AUTO_ARCHIVE_ROLE_NAME)
            if archive_role is None:
                archive_role = await guild.create_role(
                    name=AUTO_ARCHIVE_ROLE_NAME,
                    reason="Auto configuration tickets",
                )
            config["archive_role_id"] = archive_role.id

        ticket_category = guild.get_channel(config["ticket_category_id"]) if config["ticket_category_id"] else None
        if not isinstance(ticket_category, discord.CategoryChannel):
            ticket_category = discord.utils.get(guild.categories, name=AUTO_TICKET_CATEGORY_NAME)
            if ticket_category is None:
                ticket_category = await guild.create_category(
                    AUTO_TICKET_CATEGORY_NAME,
                    reason="Auto configuration tickets",
                )
            config["ticket_category_id"] = ticket_category.id

        archive_category = guild.get_channel(config["archive_category_id"]) if config["archive_category_id"] else None
        if not isinstance(archive_category, discord.CategoryChannel):
            archive_category = discord.utils.get(guild.categories, name=AUTO_ARCHIVE_CATEGORY_NAME)
            if archive_category is None:
                archive_category = await guild.create_category(
                    AUTO_ARCHIVE_CATEGORY_NAME,
                    reason="Auto configuration tickets",
                )
            config["archive_category_id"] = archive_category.id

        self.save_config()

    async def cache_invites(self, guild: discord.Guild) -> None:
        try:
            invites = await guild.invites()
        except discord.Forbidden:
            self.invite_cache[guild.id] = {}
            return
        self.invite_cache[guild.id] = {invite.code: invite.uses or 0 for invite in invites}

    async def track_member_invite(self, member: discord.Member) -> discord.Member | None:
        before = self.invite_cache.get(member.guild.id, {})
        try:
            invites = await member.guild.invites()
        except discord.Forbidden:
            return None

        inviter: discord.abc.User | None = None
        after = {invite.code: invite.uses or 0 for invite in invites}
        for invite in invites:
            previous_uses = before.get(invite.code, 0)
            current_uses = invite.uses or 0
            if current_uses > previous_uses and invite.inviter is not None:
                inviter = invite.inviter
                break

        self.invite_cache[member.guild.id] = after
        if inviter is None:
            return None

        store = self.get_invite_store(member.guild.id)
        key = str(inviter.id)
        store[key] = int(store.get(key, 0)) + 1
        self.save_invites()
        return member.guild.get_member(inviter.id)

    async def schedule_existing_giveaways(self) -> None:
        for guild_id, giveaways in self.giveaway_data.items():
            for message_id, giveaway in giveaways.items():
                if giveaway.get("status") == "active":
                    self.schedule_giveaway_end(
                        int(guild_id),
                        int(message_id),
                        int(giveaway["end_at"]),
                    )

    def schedule_giveaway_end(self, guild_id: int, message_id: int, end_at: int) -> None:
        task_key = f"{guild_id}:{message_id}"
        existing = self.giveaway_tasks.get(task_key)
        if existing is not None:
            existing.cancel()
        self.giveaway_tasks[task_key] = asyncio.create_task(
            self._giveaway_end_task(guild_id, message_id, end_at)
        )

    async def _giveaway_end_task(self, guild_id: int, message_id: int, end_at: int) -> None:
        await asyncio.sleep(max(0, end_at - int(discord.utils.utcnow().timestamp())))
        await self.finish_giveaway(guild_id, message_id)

    def cancel_giveaway_task(self, guild_id: int, message_id: int) -> None:
        task_key = f"{guild_id}:{message_id}"
        existing = self.giveaway_tasks.pop(task_key, None)
        if existing is not None:
            existing.cancel()

    async def send_rules_text(self, channel: discord.TextChannel) -> None:
        for part in split_long_message(RULES_TEXT):
            await channel.send(part)

    async def create_ticket(self, interaction: discord.Interaction, ticket_type: str) -> None:
        guild = interaction.guild
        user = interaction.user
        if guild is None or not isinstance(user, discord.Member):
            await interaction.response.send_message(
                "Impossible de créer un ticket ici.",
                ephemeral=True,
            )
            return

        config = self.get_guild_config(guild.id)
        staff_role = guild.get_role(config["staff_role_id"]) if config["staff_role_id"] else None
        archive_role = guild.get_role(config["archive_role_id"]) if config["archive_role_id"] else None
        ticket_category = guild.get_channel(config["ticket_category_id"]) if config["ticket_category_id"] else None
        archive_category = guild.get_channel(config["archive_category_id"]) if config["archive_category_id"] else None

        if (
            staff_role is None
            or archive_role is None
            or not isinstance(ticket_category, discord.CategoryChannel)
            or not isinstance(archive_category, discord.CategoryChannel)
        ):
            await interaction.response.send_message(
                "Le système de tickets n'est pas encore configuré correctement.",
                ephemeral=True,
            )
            return

        if len(self.get_open_tickets_for_user(guild.id, user.id)) >= 3:
            await interaction.response.send_message(
                "Tu as déjà 3 tickets ouverts. Ferme-en un avant d'en créer un autre.",
                ephemeral=True,
            )
            return

        number = self.get_next_ticket_number(guild.id)
        channel_name = f"{number}-{slugify_name(user.display_name)}"
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
            ),
            staff_role: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
            ),
            archive_role: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
            ),
        }
        channel = await guild.create_text_channel(
            name=channel_name,
            category=ticket_category,
            overwrites=overwrites,
            reason=f"Création du ticket {ticket_type} par {user}",
        )

        store = self.get_ticket_store(guild.id)
        store["channels"][str(channel.id)] = {
            "channel_id": channel.id,
            "owner_id": user.id,
            "status": "open",
            "type": ticket_type,
            "number": number,
        }
        self.save_tickets()

        embed = discord.Embed(
            title=f"Ticket {TICKET_TYPES[ticket_type]['label']}",
            description=(
                f"{user.mention}, ton ticket a été créé avec succès.\n"
                "Explique ta demande avec le plus de détails possible."
            ),
            color=discord.Color.green(),
        )
        embed.add_field(name="Catégorie", value=TICKET_TYPES[ticket_type]["label"], inline=True)
        embed.add_field(name="Numéro", value=str(number), inline=True)
        await channel.send(
            content=f"{user.mention} {staff_role.mention}",
            embed=embed,
            view=TicketCloseView(self),
        )
        await interaction.response.defer(ephemeral=True, thinking=False)

    async def archive_ticket(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        channel = interaction.channel
        user = interaction.user
        if guild is None or channel is None or not isinstance(user, discord.Member):
            await interaction.response.send_message(
                "Impossible de fermer ce ticket.",
                ephemeral=True,
            )
            return

        store = self.get_ticket_store(guild.id)
        ticket = store["channels"].get(str(channel.id))
        if ticket is None:
            await interaction.response.send_message(
                "Ce salon n'est pas un ticket géré par le bot.",
                ephemeral=True,
            )
            return
        if ticket["status"] != "open":
            await interaction.response.send_message(
                "Ce ticket est déjà archivé.",
                ephemeral=True,
            )
            return

        config = self.get_guild_config(guild.id)
        staff_role = guild.get_role(config["staff_role_id"]) if config["staff_role_id"] else None
        archive_role = guild.get_role(config["archive_role_id"]) if config["archive_role_id"] else None
        archive_category = guild.get_channel(config["archive_category_id"]) if config["archive_category_id"] else None
        owner = guild.get_member(ticket["owner_id"])

        if archive_role is None or not isinstance(archive_category, discord.CategoryChannel):
            await interaction.response.send_message(
                "La configuration des archives est invalide.",
                ephemeral=True,
            )
            return

        is_staff = staff_role is not None and staff_role in user.roles
        is_archive_staff = archive_role in user.roles
        if not (user.id == guild.owner_id or is_staff or is_archive_staff):
            await interaction.response.send_message(
                "Seul le staff peut fermer ce ticket.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        await channel.edit(category=archive_category, reason=f"Archivage du ticket par {user}")

        if owner is not None:
            await channel.set_permissions(
                owner,
                overwrite=discord.PermissionOverwrite(view_channel=False),
            )
        if staff_role is not None:
            await channel.set_permissions(
                staff_role,
                overwrite=discord.PermissionOverwrite(view_channel=False),
            )
        await channel.set_permissions(
            archive_role,
            overwrite=discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
            ),
        )
        if guild.owner is not None:
            await channel.set_permissions(
                guild.owner,
                overwrite=discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    manage_messages=True,
                ),
            )
        await channel.set_permissions(
            guild.default_role,
            overwrite=discord.PermissionOverwrite(view_channel=False),
        )

        ticket["status"] = "archived"
        ticket["closed_by"] = user.id
        self.save_tickets()

        embed = discord.Embed(
            title="Ticket archivé",
            description=(
                f"Ce ticket a été archivé par {user.mention}.\n"
                "Seul le staff supérieur peut maintenant consulter cette archive."
            ),
            color=discord.Color.orange(),
        )
        await channel.send(embed=embed, view=TicketArchiveView(self))
        await interaction.followup.send("Le ticket a été archivé.", ephemeral=True)

    async def reopen_ticket(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        channel = interaction.channel
        user = interaction.user
        if guild is None or channel is None or not isinstance(user, discord.Member):
            await interaction.response.send_message(
                "Impossible de réouvrir ce ticket.",
                ephemeral=True,
            )
            return

        store = self.get_ticket_store(guild.id)
        ticket = store["channels"].get(str(channel.id))
        if ticket is None:
            await interaction.response.send_message(
                "Ce salon n'est pas un ticket géré par le bot.",
                ephemeral=True,
            )
            return
        if ticket["status"] != "archived":
            await interaction.response.send_message(
                "Ce ticket n'est pas archivé.",
                ephemeral=True,
            )
            return

        config = self.get_guild_config(guild.id)
        staff_role = guild.get_role(config["staff_role_id"]) if config["staff_role_id"] else None
        archive_role = guild.get_role(config["archive_role_id"]) if config["archive_role_id"] else None
        ticket_category = guild.get_channel(config["ticket_category_id"]) if config["ticket_category_id"] else None
        owner = guild.get_member(ticket["owner_id"])

        if (
            staff_role is None
            or archive_role is None
            or not isinstance(ticket_category, discord.CategoryChannel)
        ):
            await interaction.response.send_message(
                "La configuration des tickets est invalide.",
                ephemeral=True,
            )
            return
        if not (user.id == guild.owner_id or archive_role in user.roles):
            await interaction.response.send_message(
                "Seul le staff supérieur peut réouvrir ce ticket.",
                ephemeral=True,
            )
            return
        if owner is None:
            await interaction.response.send_message(
                "Le créateur du ticket n'est plus sur le serveur.",
                ephemeral=True,
            )
            return
        if len(self.get_open_tickets_for_user(guild.id, owner.id)) >= 3:
            await interaction.response.send_message(
                "Impossible de réouvrir ce ticket car l'utilisateur a déjà 3 tickets ouverts.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        await channel.edit(category=ticket_category, reason=f"Réouverture du ticket par {user}")
        await channel.set_permissions(
            owner,
            overwrite=discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
            ),
        )
        await channel.set_permissions(
            staff_role,
            overwrite=discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
            ),
        )
        await channel.set_permissions(
            archive_role,
            overwrite=discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
            ),
        )
        if guild.owner is not None:
            await channel.set_permissions(
                guild.owner,
                overwrite=discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    manage_messages=True,
                ),
            )
        await channel.set_permissions(
            guild.default_role,
            overwrite=discord.PermissionOverwrite(view_channel=False),
        )

        ticket["status"] = "open"
        ticket["reopened_by"] = user.id
        self.save_tickets()

        embed = discord.Embed(
            title="Ticket réouvert",
            description=f"Ce ticket a été réouvert par {user.mention}.",
            color=discord.Color.green(),
        )
        await channel.send(embed=embed, view=TicketCloseView(self))
        await interaction.followup.send("Le ticket a été réouvert.", ephemeral=True)

    async def join_giveaway(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.message is None:
            await interaction.response.send_message(
                "Impossible de participer ici.",
                ephemeral=True,
            )
            return

        store = self.get_giveaway_store(interaction.guild.id)
        giveaway = store.get(str(interaction.message.id))
        if giveaway is None or giveaway.get("status") != "active":
            await interaction.response.send_message(
                "Ce giveaway n'est plus actif.",
                ephemeral=True,
            )
            return

        user_id = interaction.user.id
        participants = giveaway.setdefault("participants", [])
        if user_id in participants:
            await interaction.response.send_message(
                "Tu participes déjà à ce giveaway.",
                ephemeral=True,
            )
            return

        participants.append(user_id)
        self.save_giveaways()
        await interaction.response.send_message(
            "Participation enregistrée.",
            ephemeral=True,
        )
        try:
            await interaction.user.send(f"Tu participes au giveaway : {giveaway['prize']}")
        except discord.Forbidden:
            pass

    def _pick_weighted_winners(
        self,
        guild: discord.Guild,
        participant_ids: list[int],
        winners_count: int,
        excluded: set[int] | None = None,
    ) -> list[int]:
        pool: list[tuple[int, float]] = []
        excluded = excluded or set()

        for user_id in participant_ids:
            if user_id in excluded:
                continue
            member = guild.get_member(user_id)
            if member is None:
                continue
            pool.append((user_id, get_member_giveaway_weight(member)))

        winners: list[int] = []
        for _ in range(min(winners_count, len(pool))):
            total_weight = sum(weight for _, weight in pool)
            if total_weight <= 0:
                break
            pick = random.uniform(0, total_weight)
            running = 0.0
            chosen_index = 0
            for index, (_, weight) in enumerate(pool):
                running += weight
                if pick <= running:
                    chosen_index = index
                    break
            winner_id, _ = pool.pop(chosen_index)
            winners.append(winner_id)
        return winners

    async def finish_giveaway(self, guild_id: int, message_id: int) -> None:
        store = self.get_giveaway_store(guild_id)
        giveaway = store.get(str(message_id))
        if giveaway is None or giveaway.get("status") != "active":
            return

        guild = self.get_guild(guild_id)
        if guild is None:
            return
        channel = guild.get_channel(giveaway["channel_id"])
        if not isinstance(channel, discord.TextChannel):
            return

        participant_ids = list(dict.fromkeys(giveaway.get("participants", [])))
        winners = self._pick_weighted_winners(
            guild,
            participant_ids,
            int(giveaway["winners_count"]),
        )

        giveaway["status"] = "ended"
        giveaway["winners"] = winners
        self.save_giveaways()
        self.cancel_giveaway_task(guild_id, message_id)

        if winners:
            winner_names: list[str] = []
            for winner_id in winners:
                member = guild.get_member(winner_id)
                winner_names.append(member.display_name if member is not None else str(winner_id))
            names_text = ", ".join(winner_names)
            await channel.send(
                f"🎉 Giveaway terminé ! Gagnant(s) pour **{giveaway['prize']}** : {names_text}"
            )
        else:
            await channel.send(
                f"🎉 Giveaway terminé pour **{giveaway['prize']}**, "
                "mais aucun participant valide n'a été trouvé."
            )

    async def reroll_giveaway(self, guild_id: int, message_id: int) -> list[int]:
        store = self.get_giveaway_store(guild_id)
        giveaway = store.get(str(message_id))
        if giveaway is None:
            return []

        guild = self.get_guild(guild_id)
        if guild is None:
            return []

        participant_ids = list(dict.fromkeys(giveaway.get("participants", [])))
        previous_winners = set(giveaway.get("winners", []))
        winners = self._pick_weighted_winners(
            guild,
            participant_ids,
            int(giveaway["winners_count"]),
            excluded=previous_winners,
        )
        giveaway["winners"] = winners
        self.save_giveaways()
        return winners

    async def sync_commands_once(self) -> None:
        if self.sync_done:
            return

        for guild in self.guilds:
            await self.ensure_ticket_config(guild)
            await self.cache_invites(guild)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            print(f"{len(synced)} commande(s) slash synchronisée(s) sur {guild.name}.")

        self.tree.clear_commands(guild=None)
        await self.tree.sync()
        await self.schedule_existing_giveaways()
        self.sync_done = True


class MainCog(commands.Cog):
    def __init__(self, bot: YishiBot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        await self.bot.sync_commands_once()
        print(f"Bot connecté en tant que {self.bot.user}")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        config = self.bot.get_guild_config(member.guild.id)
        welcome_channel = (
            member.guild.get_channel(config["welcome_channel_id"])
            if config["welcome_channel_id"]
            else member.guild.system_channel
        )
        inviter = await self.bot.track_member_invite(member)
        if not isinstance(welcome_channel, discord.TextChannel):
            return

        embed = discord.Embed(
            title="Nouveau membre !",
            description=(
                f"## Bienvenue, {member.mention} 👋\n"
                f"Tu es le **{member.guild.member_count}ème membre** à rejoindre **Yishi's Shop**."
            ),
            color=discord.Color.gold(),
        )
        embed.add_field(name="Avant de commencer", value=WELCOME_CHECKLIST, inline=False)
        embed.add_field(name="Pourquoi nous choisir", value=WELCOME_ADVANTAGES, inline=False)
        embed.add_field(
            name="Invitation",
            value=f"Invité par {inviter.mention}" if inviter is not None else "Inviteur non détecté",
            inline=False,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        if member.guild.banner:
            embed.set_image(url=member.guild.banner.url)
        embed.set_author(
            name=member.guild.name,
            icon_url=member.guild.icon.url if member.guild.icon else None,
        )
        embed.set_footer(
            text=f"Bienvenue parmi nous • {discord.utils.utcnow().strftime('%H:%M')}",
            icon_url=member.guild.icon.url if member.guild.icon else None,
        )
        await welcome_channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.guild_id is None or str(payload.emoji) != "✅":
            return
        if self.bot.user is not None and payload.user_id == self.bot.user.id:
            return

        config = self.bot.get_guild_config(payload.guild_id)
        if payload.message_id != config["rules_message_id"]:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        role = guild.get_role(config["rules_role_id"]) if config["rules_role_id"] else None
        try:
            member = guild.get_member(payload.user_id) or await guild.fetch_member(payload.user_id)
        except (discord.Forbidden, discord.NotFound):
            return
        if role is None or member.bot or role in member.roles:
            return
        await member.add_roles(role, reason="Validation du règlement par réaction")

    @app_commands.command(name="aide", description="Affiche la liste des commandes")
    async def aide(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(title="Commandes", color=discord.Color.blurple())
        embed.add_field(
            name="Général",
            value="/aide\n/ping\n/paiement\n/invites\n/userinfo",
            inline=False,
        )
        embed.add_field(
            name="Messages",
            value="/dire\n/envoyer_message\n/annonce",
            inline=False,
        )
        embed.add_field(
            name="Modération",
            value="/clear\n/kick\n/ban\n/mute\n/unmute\n/warn\n/list_warn",
            inline=False,
        )
        embed.add_field(
            name="Tickets",
            value="/envoyer_panel_tickets\n/add_membre_ticket",
            inline=False,
        )
        embed.add_field(
            name="Giveaways",
            value="/giveaway_create\n/giveaway_list\n/giveaway_participants\n/giveaway_end\n/giveaway_reroll",
            inline=False,
        )
        embed.add_field(
            name="Configuration",
            value=(
                "/config_role_staff\n"
                "/config_role_archive\n"
                "/config_categorie_tickets\n"
                "/config_categorie_archives\n"
                "/config_salon_bienvenue\n"
                "/config_role_regles\n"
                "/envoyer_reglement\n"
                "/envoyer_message_regles"
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="ping", description="Teste la latence du bot")
    async def ping(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(f"Pong ! {round(self.bot.latency * 1000)} ms")

    @app_commands.command(name="paiement", description="Affiche les moyens de paiement du shop")
    async def paiement(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="Moyens de paiement",
            description="Voici les moyens de paiement disponibles pour Yishi's Shop.",
            color=discord.Color.green(),
        )
        embed.add_field(name="PayPal", value="YishisShops", inline=False)
        embed.add_field(name="Revolut", value="https://revolut.me/souillarda", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="invites", description="Affiche le nombre d'invitations")
    @app_commands.describe(membre="Membre dont tu veux voir les invitations")
    async def invites(
        self,
        interaction: discord.Interaction,
        membre: discord.Member | None = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Commande indisponible ici.",
                ephemeral=True,
            )
            return
        target = membre or interaction.user
        count = self.bot.get_invite_count(interaction.guild.id, target.id)
        await interaction.response.send_message(
            f"{target.mention} a {count} invitation(s).",
            ephemeral=True,
        )

    @app_commands.command(name="userinfo", description="Affiche les informations d'un membre")
    @app_commands.describe(membre="Le membre à afficher")
    async def userinfo(
        self,
        interaction: discord.Interaction,
        membre: discord.Member | None = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Commande indisponible ici.",
                ephemeral=True,
            )
            return
        member = membre or interaction.user
        embed = discord.Embed(title=f"Infos de {member}", color=discord.Color.green())
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="ID", value=str(member.id), inline=False)
        embed.add_field(name="Nom", value=member.name, inline=True)
        embed.add_field(name="Pseudo", value=member.display_name, inline=True)
        embed.add_field(
            name="Compte créé le",
            value=member.created_at.strftime("%d/%m/%Y %H:%M"),
            inline=False,
        )
        if member.joined_at:
            embed.add_field(
                name="A rejoint le serveur le",
                value=member.joined_at.strftime("%d/%m/%Y %H:%M"),
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="dire", description="Fait parler le bot dans le salon actuel")
    @app_commands.describe(message="Le message à envoyer")
    @app_commands.default_permissions(manage_messages=True)
    async def dire(self, interaction: discord.Interaction, message: str) -> None:
        if interaction.channel is None:
            await interaction.response.send_message(
                "Commande indisponible ici.",
                ephemeral=True,
            )
            return
        await interaction.channel.send(message)
        await interaction.response.send_message("Message envoyé.", ephemeral=True)

    @app_commands.command(name="envoyer_message", description="Envoie un message dans le salon de ton choix")
    @app_commands.describe(salon="Le salon cible", message="Le message à envoyer")
    @app_commands.default_permissions(manage_messages=True)
    async def envoyer_message(
        self,
        interaction: discord.Interaction,
        salon: discord.TextChannel,
        message: str,
    ) -> None:
        await salon.send(message)
        await interaction.response.send_message(
            f"Message envoyé dans {salon.mention}.",
            ephemeral=True,
        )

    @app_commands.command(name="annonce", description="Envoie une annonce en embed dans le salon de ton choix")
    @app_commands.describe(salon="Salon cible", titre="Titre de l'annonce", message="Texte de l'annonce")
    @app_commands.default_permissions(manage_messages=True)
    async def annonce(
        self,
        interaction: discord.Interaction,
        salon: discord.TextChannel,
        titre: str,
        message: str,
    ) -> None:
        embed = discord.Embed(title=titre, description=message, color=discord.Color.blurple())
        embed.set_footer(text=f"Annonce par {interaction.user}")
        await salon.send(embed=embed)
        await interaction.response.send_message(
            f"Annonce envoyée dans {salon.mention}.",
            ephemeral=True,
        )

    @app_commands.command(name="clear", description="Supprime un certain nombre de messages")
    @app_commands.describe(nombre="Nombre de messages à supprimer")
    @app_commands.default_permissions(manage_messages=True)
    async def clear(
        self,
        interaction: discord.Interaction,
        nombre: app_commands.Range[int, 1, 100],
    ) -> None:
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "Commande indisponible ici.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=nombre)
        await interaction.followup.send(
            f"{len(deleted)} message(s) supprimé(s).",
            ephemeral=True,
        )

    @app_commands.command(name="kick", description="Expulse un membre du serveur")
    @app_commands.describe(membre="Le membre à expulser", raison="La raison du kick")
    @app_commands.default_permissions(kick_members=True)
    async def kick(
        self,
        interaction: discord.Interaction,
        membre: discord.Member,
        raison: str = "Aucune raison fournie",
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Commande indisponible ici.",
                ephemeral=True,
            )
            return
        bot_member = self.bot.get_bot_member(interaction.guild)
        if bot_member is None:
            await interaction.response.send_message(
                "Impossible de vérifier mes permissions.",
                ephemeral=True,
            )
            return
        error = can_moderate(interaction.user, membre, bot_member)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        await membre.kick(reason=raison)
        await interaction.response.send_message(
            f"{membre} a été expulsé. Raison : {raison}"
        )

    @app_commands.command(name="ban", description="Bannit un membre du serveur")
    @app_commands.describe(membre="Le membre à bannir", raison="La raison du ban")
    @app_commands.default_permissions(ban_members=True)
    async def ban(
        self,
        interaction: discord.Interaction,
        membre: discord.Member,
        raison: str = "Aucune raison fournie",
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Commande indisponible ici.",
                ephemeral=True,
            )
            return
        bot_member = self.bot.get_bot_member(interaction.guild)
        if bot_member is None:
            await interaction.response.send_message(
                "Impossible de vérifier mes permissions.",
                ephemeral=True,
            )
            return
        error = can_moderate(interaction.user, membre, bot_member)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        await membre.ban(reason=raison)
        await interaction.response.send_message(
            f"{membre} a été banni. Raison : {raison}"
        )

    @app_commands.command(name="mute", description="Timeout un membre pendant un certain temps")
    @app_commands.describe(
        membre="Le membre à mute",
        minutes="Durée du timeout en minutes",
        raison="La raison du mute",
    )
    @app_commands.default_permissions(moderate_members=True)
    async def mute(
        self,
        interaction: discord.Interaction,
        membre: discord.Member,
        minutes: app_commands.Range[int, 1, 40320],
        raison: str = "Aucune raison fournie",
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Commande indisponible ici.",
                ephemeral=True,
            )
            return
        bot_member = self.bot.get_bot_member(interaction.guild)
        if bot_member is None:
            await interaction.response.send_message(
                "Impossible de vérifier mes permissions.",
                ephemeral=True,
            )
            return
        error = can_moderate(interaction.user, membre, bot_member)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        await membre.timeout(discord.utils.utcnow() + timedelta(minutes=minutes), reason=raison)
        await interaction.response.send_message(
            f"{membre} a été mute pendant {minutes} minute(s). Raison : {raison}"
        )

    @app_commands.command(name="unmute", description="Retire le timeout d'un membre")
    @app_commands.describe(membre="Le membre à unmute", raison="La raison du unmute")
    @app_commands.default_permissions(moderate_members=True)
    async def unmute(
        self,
        interaction: discord.Interaction,
        membre: discord.Member,
        raison: str = "Aucune raison fournie",
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Commande indisponible ici.",
                ephemeral=True,
            )
            return
        bot_member = self.bot.get_bot_member(interaction.guild)
        if bot_member is None:
            await interaction.response.send_message(
                "Impossible de vérifier mes permissions.",
                ephemeral=True,
            )
            return
        error = can_moderate(interaction.user, membre, bot_member)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        await membre.timeout(None, reason=raison)
        await interaction.response.send_message(
            f"{membre} n'est plus mute. Raison : {raison}"
        )

    @app_commands.command(name="warn", description="Avertit un membre avec une raison")
    @app_commands.describe(membre="Le membre à avertir", raison="La raison de l'avertissement")
    @app_commands.default_permissions(moderate_members=True)
    async def warn(
        self,
        interaction: discord.Interaction,
        membre: discord.Member,
        raison: str,
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Commande indisponible ici.",
                ephemeral=True,
            )
            return
        bot_member = self.bot.get_bot_member(interaction.guild)
        if bot_member is None:
            await interaction.response.send_message(
                "Impossible de vérifier mes permissions.",
                ephemeral=True,
            )
            return
        error = can_moderate(interaction.user, membre, bot_member)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return

        store = self.bot.get_warning_store(interaction.guild.id)
        key = str(membre.id)
        store.setdefault(key, []).append(
            {
                "reason": raison,
                "moderator_id": interaction.user.id,
                "moderator_name": str(interaction.user),
                "created_at": discord.utils.utcnow().strftime("%d/%m/%Y %H:%M"),
            }
        )
        self.bot.save_warnings()
        await interaction.response.send_message(
            f"{membre.mention} a reçu un avertissement. Raison : {raison}"
        )

    @app_commands.command(name="list_warn", description="Affiche les avertissements d'un membre")
    @app_commands.describe(membre="Le membre dont tu veux voir les avertissements")
    @app_commands.default_permissions(moderate_members=True)
    async def list_warn(self, interaction: discord.Interaction, membre: discord.Member) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Commande indisponible ici.",
                ephemeral=True,
            )
            return
        warnings = self.bot.get_warning_store(interaction.guild.id).get(str(membre.id), [])
        if not warnings:
            await interaction.response.send_message(
                f"{membre.mention} n'a aucun avertissement.",
                ephemeral=True,
            )
            return
        embed = discord.Embed(
            title=f"Avertissements de {membre}",
            color=discord.Color.orange(),
        )
        for index, warning in enumerate(warnings, start=1):
            embed.add_field(
                name=f"Warn #{index}",
                value=(
                    f"Raison : {warning['reason']}\n"
                    f"Staff : {warning['moderator_name']}\n"
                    f"Date : {warning['created_at']}"
                ),
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="add_membre_ticket", description="Ajoute un membre au ticket actuel")
    @app_commands.describe(membre="Le membre à ajouter au ticket")
    @app_commands.default_permissions(manage_channels=True)
    async def add_membre_ticket(
        self,
        interaction: discord.Interaction,
        membre: discord.Member,
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "Commande indisponible ici.",
                ephemeral=True,
            )
            return
        ticket = self.bot.get_ticket_store(interaction.guild.id)["channels"].get(str(interaction.channel.id))
        if ticket is None:
            await interaction.response.send_message(
                "Cette commande doit être utilisée dans un ticket.",
                ephemeral=True,
            )
            return

        await interaction.channel.set_permissions(
            membre,
            overwrite=discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
            ),
        )
        await interaction.response.send_message(
            f"{membre.mention} a été ajouté au ticket.",
            ephemeral=True,
        )
        await interaction.channel.send(
            f"{membre.mention} a été ajouté au ticket par {interaction.user.mention}."
        )

    @app_commands.command(name="giveaway_create", description="Crée un giveaway")
    @app_commands.describe(
        salon="Salon du giveaway",
        prix="Prix du giveaway",
        duree="Exemple : 10m, 2h, 1d",
        gagnants="Nombre de gagnants",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def giveaway_create(
        self,
        interaction: discord.Interaction,
        salon: discord.TextChannel,
        prix: str,
        duree: str,
        gagnants: app_commands.Range[int, 1, 20],
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Commande indisponible ici.",
                ephemeral=True,
            )
            return

        seconds = parse_duration(duree)
        if seconds is None:
            await interaction.response.send_message(
                "Durée invalide. Utilise `10m`, `2h` ou `1d`.",
                ephemeral=True,
            )
            return

        end_at = int(discord.utils.utcnow().timestamp()) + seconds
        embed = discord.Embed(
            title="🎉 Giveaway",
            description=(
                f"Prix : **{prix}**\n"
                f"Gagnant(s) : **{gagnants}**\n"
                f"Fin : <t:{end_at}:R>\n"
                "Chances bonus : **rôles invitations + Server Booster**\n\n"
                "Clique sur Participer pour rejoindre le giveaway."
            ),
            color=discord.Color.gold(),
        )
        message = await salon.send(embed=embed, view=GiveawayView(self.bot))

        store = self.bot.get_giveaway_store(interaction.guild.id)
        store[str(message.id)] = {
            "message_id": message.id,
            "channel_id": salon.id,
            "prize": prix,
            "winners_count": int(gagnants),
            "participants": [],
            "winners": [],
            "end_at": end_at,
            "status": "active",
            "created_by": interaction.user.id,
        }
        self.bot.save_giveaways()
        self.bot.schedule_giveaway_end(interaction.guild.id, message.id, end_at)
        await interaction.response.send_message(
            f"Giveaway créé dans {salon.mention}. ID du message : `{message.id}`",
            ephemeral=True,
        )

    @app_commands.command(name="giveaway_end", description="Termine un giveaway maintenant")
    @app_commands.describe(message_id="ID du message du giveaway")
    @app_commands.default_permissions(manage_guild=True)
    async def giveaway_end(self, interaction: discord.Interaction, message_id: str) -> None:
        if interaction.guild is None or not message_id.isdigit():
            await interaction.response.send_message("ID invalide.", ephemeral=True)
            return
        await self.bot.finish_giveaway(interaction.guild.id, int(message_id))
        await interaction.response.send_message(
            "Giveaway terminé si l'ID était valide.",
            ephemeral=True,
        )

    @app_commands.command(name="giveaway_list", description="Affiche la liste des giveaways avec leur ID")
    @app_commands.default_permissions(manage_guild=True)
    async def giveaway_list(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Commande indisponible ici.",
                ephemeral=True,
            )
            return

        store = self.bot.get_giveaway_store(interaction.guild.id)
        if not store:
            await interaction.response.send_message(
                "Aucun giveaway enregistré sur ce serveur.",
                ephemeral=True,
            )
            return

        giveaways = sorted(
            store.values(),
            key=lambda giveaway: int(giveaway.get("end_at", 0)),
            reverse=True,
        )

        embed = discord.Embed(
            title="Liste des giveaways",
            description="Voici les IDs des giveaways avec leur prix pour les reconnaître facilement.",
            color=discord.Color.blurple(),
        )
        for giveaway in giveaways[:25]:
            status = "Actif" if giveaway.get("status") == "active" else "Terminé"
            embed.add_field(
                name=f"{giveaway['prize']}",
                value=(
                    f"ID : `{giveaway['message_id']}`\n"
                    f"Statut : {status}\n"
                    f"Gagnants : {giveaway['winners_count']}"
                ),
                inline=False,
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="giveaway_participants", description="Affiche la liste des participants d'un giveaway")
    @app_commands.describe(message_id="ID du message du giveaway")
    @app_commands.default_permissions(manage_guild=True)
    async def giveaway_participants(self, interaction: discord.Interaction, message_id: str) -> None:
        if interaction.guild is None or not message_id.isdigit():
            await interaction.response.send_message("ID invalide.", ephemeral=True)
            return

        giveaway = self.bot.get_giveaway_store(interaction.guild.id).get(message_id)
        if giveaway is None:
            await interaction.response.send_message(
                "Aucun giveaway trouvé avec cet ID.",
                ephemeral=True,
            )
            return

        participant_ids = list(dict.fromkeys(giveaway.get("participants", [])))
        if not participant_ids:
            await interaction.response.send_message(
                f"Aucun participant pour **{giveaway['prize']}** (`{message_id}`).",
                ephemeral=True,
            )
            return

        lines: list[str] = []
        for user_id in participant_ids:
            member = interaction.guild.get_member(user_id)
            weight_text = ""
            if member is not None:
                weight_text = f" — chance x{get_member_giveaway_weight(member):g}"
                lines.append(f"• {member.mention} (`{user_id}`){weight_text}")
            else:
                lines.append(f"• Utilisateur inconnu (`{user_id}`)")

        chunks: list[str] = []
        current = ""
        for line in lines:
            candidate = line if not current else f"{current}\n{line}"
            if len(candidate) <= 3500:
                current = candidate
            else:
                chunks.append(current)
                current = line
        if current:
            chunks.append(current)

        embed = discord.Embed(
            title=f"Participants • {giveaway['prize']}",
            description=f"ID du giveaway : `{message_id}`\nParticipants : **{len(participant_ids)}**",
            color=discord.Color.gold(),
        )
        embed.add_field(name="Liste", value=chunks[0], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        for extra_chunk in chunks[1:]:
            extra_embed = discord.Embed(
                title=f"Participants • {giveaway['prize']} (suite)",
                color=discord.Color.gold(),
            )
            extra_embed.add_field(name="Liste", value=extra_chunk, inline=False)
            await interaction.followup.send(embed=extra_embed, ephemeral=True)

    @app_commands.command(name="giveaway_reroll", description="Retire un nouveau gagnant pour un giveaway")
    @app_commands.describe(message_id="ID du message du giveaway")
    @app_commands.default_permissions(manage_guild=True)
    async def giveaway_reroll(self, interaction: discord.Interaction, message_id: str) -> None:
        if interaction.guild is None or not message_id.isdigit():
            await interaction.response.send_message("ID invalide.", ephemeral=True)
            return
        winners = await self.bot.reroll_giveaway(interaction.guild.id, int(message_id))
        if not winners:
            await interaction.response.send_message(
                "Aucun nouveau gagnant valide trouvé.",
                ephemeral=True,
            )
            return
        mentions = ", ".join(f"<@{winner_id}>" for winner_id in winners)
        await interaction.response.send_message(f"Nouveau gagnant : {mentions}")

    @app_commands.command(name="config_role_staff", description="Définit le rôle staff pour les tickets ouverts")
    @app_commands.describe(role="Rôle staff")
    @app_commands.default_permissions(manage_guild=True)
    async def config_role_staff(self, interaction: discord.Interaction, role: discord.Role) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Commande indisponible ici.",
                ephemeral=True,
            )
            return
        config = self.bot.get_guild_config(interaction.guild.id)
        config["staff_role_id"] = role.id
        self.bot.save_config()
        await interaction.response.send_message(
            f"Le rôle staff des tickets ouverts est maintenant {role.mention}.",
            ephemeral=True,
        )

    @app_commands.command(name="config_role_archive", description="Définit le rôle staff supérieur des archives")
    @app_commands.describe(role="Rôle archives")
    @app_commands.default_permissions(manage_guild=True)
    async def config_role_archive(self, interaction: discord.Interaction, role: discord.Role) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Commande indisponible ici.",
                ephemeral=True,
            )
            return
        config = self.bot.get_guild_config(interaction.guild.id)
        config["archive_role_id"] = role.id
        self.bot.save_config()
        await interaction.response.send_message(
            f"Le rôle des archives est maintenant {role.mention}.",
            ephemeral=True,
        )

    @app_commands.command(name="config_categorie_tickets", description="Définit la catégorie des tickets ouverts")
    @app_commands.describe(categorie="Catégorie tickets")
    @app_commands.default_permissions(manage_guild=True)
    async def config_categorie_tickets(
        self,
        interaction: discord.Interaction,
        categorie: discord.CategoryChannel,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Commande indisponible ici.",
                ephemeral=True,
            )
            return
        config = self.bot.get_guild_config(interaction.guild.id)
        config["ticket_category_id"] = categorie.id
        self.bot.save_config()
        await interaction.response.send_message(
            f"La catégorie des tickets ouverts est maintenant {categorie.name}.",
            ephemeral=True,
        )

    @app_commands.command(name="config_categorie_archives", description="Définit la catégorie des tickets archivés")
    @app_commands.describe(categorie="Catégorie archives")
    @app_commands.default_permissions(manage_guild=True)
    async def config_categorie_archives(
        self,
        interaction: discord.Interaction,
        categorie: discord.CategoryChannel,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Commande indisponible ici.",
                ephemeral=True,
            )
            return
        config = self.bot.get_guild_config(interaction.guild.id)
        config["archive_category_id"] = categorie.id
        self.bot.save_config()
        await interaction.response.send_message(
            f"La catégorie des tickets archivés est maintenant {categorie.name}.",
            ephemeral=True,
        )

    @app_commands.command(name="config_salon_bienvenue", description="Définit le salon des messages de bienvenue")
    @app_commands.describe(salon="Salon de bienvenue")
    @app_commands.default_permissions(manage_guild=True)
    async def config_salon_bienvenue(
        self,
        interaction: discord.Interaction,
        salon: discord.TextChannel,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Commande indisponible ici.",
                ephemeral=True,
            )
            return
        config = self.bot.get_guild_config(interaction.guild.id)
        config["welcome_channel_id"] = salon.id
        self.bot.save_config()
        await interaction.response.send_message(
            f"Le salon de bienvenue est maintenant {salon.mention}.",
            ephemeral=True,
        )

    @app_commands.command(name="config_role_regles", description="Définit le rôle donné après acceptation du règlement")
    @app_commands.describe(role="Rôle des règles")
    @app_commands.default_permissions(manage_guild=True)
    async def config_role_regles(self, interaction: discord.Interaction, role: discord.Role) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Commande indisponible ici.",
                ephemeral=True,
            )
            return
        config = self.bot.get_guild_config(interaction.guild.id)
        config["rules_role_id"] = role.id
        self.bot.save_config()
        await interaction.response.send_message(
            f"Le rôle des règles est maintenant {role.mention}.",
            ephemeral=True,
        )

    @app_commands.command(name="envoyer_reglement", description="Envoie le règlement officiel du serveur")
    @app_commands.describe(salon="Salon du règlement")
    @app_commands.default_permissions(manage_guild=True)
    async def envoyer_reglement(
        self,
        interaction: discord.Interaction,
        salon: discord.TextChannel,
    ) -> None:
        await self.bot.send_rules_text(salon)
        await interaction.response.send_message(
            f"Le règlement a été envoyé dans {salon.mention}.",
            ephemeral=True,
        )

    @app_commands.command(name="envoyer_message_regles", description="Envoie le message de validation du règlement")
    @app_commands.describe(salon="Salon du message de validation")
    @app_commands.default_permissions(manage_guild=True)
    async def envoyer_message_regles(
        self,
        interaction: discord.Interaction,
        salon: discord.TextChannel,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Commande indisponible ici.",
                ephemeral=True,
            )
            return
        config = self.bot.get_guild_config(interaction.guild.id)
        if config["rules_role_id"] is None:
            await interaction.response.send_message(
                "Configure d'abord le rôle avec /config_role_regles.",
                ephemeral=True,
            )
            return

        message = await salon.send(RULES_ACCEPT_TEXT)
        await message.add_reaction("✅")
        config["rules_message_id"] = message.id
        config["rules_channel_id"] = salon.id
        self.bot.save_config()
        await interaction.response.send_message(
            f"Le message de validation a été envoyé dans {salon.mention}.",
            ephemeral=True,
        )

    @app_commands.command(name="envoyer_panel_tickets", description="Envoie le panneau interactif de tickets")
    @app_commands.describe(salon="Salon du panneau tickets")
    @app_commands.default_permissions(manage_guild=True)
    async def envoyer_panel_tickets(
        self,
        interaction: discord.Interaction,
        salon: discord.TextChannel,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Commande indisponible ici.",
                ephemeral=True,
            )
            return
        config = self.bot.get_guild_config(interaction.guild.id)
        if not all(
            [
                config["staff_role_id"],
                config["archive_role_id"],
                config["ticket_category_id"],
                config["archive_category_id"],
            ]
        ):
            await interaction.response.send_message(
                "Configure d'abord les rôles et catégories des tickets.",
                ephemeral=True,
            )
            return

        await salon.send(embed=build_ticket_panel_embed(), view=TicketPanelView(self.bot))
        await interaction.response.send_message(
            f"Panneau de tickets envoyé dans {salon.mention}.",
            ephemeral=True,
        )


def create_bot() -> YishiBot:
    return YishiBot()
