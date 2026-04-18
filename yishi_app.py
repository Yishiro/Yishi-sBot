import asyncio
import random
import re
from datetime import timedelta
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from storage import CONFIG_FILE, GIVEAWAYS_FILE, INVITES_FILE, TICKETS_FILE, WARNINGS_FILE, load_json, save_json
from tickets import TICKET_TYPES, build_ticket_panel_embed, slugify_name


AUTO_STAFF_ROLE_NAME = "👑・𝐒taff"
AUTO_ARCHIVE_ROLE_NAME = "👑・𝐅ondateur"
AUTO_TICKET_CATEGORY_NAME = "Tickets"
AUTO_ARCHIVE_CATEGORY_NAME = "Ticket-Close"


def parse_duration(duration: str) -> int | None:
    match = re.fullmatch(r"(\d+)([mhd])", duration.lower().strip())
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
    if unit == "d":
        return amount * 24 * 60 * 60
    return None


def can_moderate(
    actor: discord.Member,
    target: discord.Member,
    bot_member: discord.Member,
) -> str | None:
    if target == actor:
        return "Tu ne peux pas te moderer toi-meme."
    if target == bot_member:
        return "Je ne peux pas me moderer moi-meme."
    if target.top_role >= actor.top_role and actor != actor.guild.owner:
        return "Tu ne peux pas moderer ce membre car son role est egal ou superieur au tien."
    if target.top_role >= bot_member.top_role:
        return "Je ne peux pas moderer ce membre car son role est trop eleve."
    return None


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
            placeholder="Selectionnez la raison de votre ticket...",
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
            label="Reouvrir",
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
        self.guild_sync_done = False

    async def setup_hook(self) -> None:
        self.add_view(TicketPanelView(self))
        self.add_view(TicketCloseView(self))
        self.add_view(TicketArchiveView(self))
        self.add_view(GiveawayView(self))
        register_commands(self)
        print("Preparation des commandes slash terminee.")

    def get_guild_config(self, guild_id: int) -> dict[str, Any]:
        key = str(guild_id)
        if key not in self.config_data:
            self.config_data[key] = {
                "staff_role_id": None,
                "archive_role_id": None,
                "ticket_category_id": None,
                "archive_category_id": None,
                "welcome_channel_id": None,
                "rules_role_id": None,
                "rules_message_id": None,
                "rules_channel_id": None,
            }
            self.save_config()
        return self.config_data[key]

    def get_ticket_store(self, guild_id: int) -> dict[str, Any]:
        key = str(guild_id)
        if key not in self.ticket_data:
            self.ticket_data[key] = {"channels": {}}
            self.save_tickets()
        return self.ticket_data[key]

    def save_config(self) -> None:
        save_json(CONFIG_FILE, self.config_data)

    def save_tickets(self) -> None:
        save_json(TICKETS_FILE, self.ticket_data)

    def get_warning_store(self, guild_id: int) -> dict[str, Any]:
        key = str(guild_id)
        if key not in self.warning_data:
            self.warning_data[key] = {}
            self.save_warnings()
        return self.warning_data[key]

    def save_warnings(self) -> None:
        save_json(WARNINGS_FILE, self.warning_data)

    def get_invite_store(self, guild_id: int) -> dict[str, Any]:
        key = str(guild_id)
        if key not in self.invite_data:
            self.invite_data[key] = {}
            self.save_invites()
        return self.invite_data[key]

    def save_invites(self) -> None:
        save_json(INVITES_FILE, self.invite_data)

    def get_giveaway_store(self, guild_id: int) -> dict[str, Any]:
        key = str(guild_id)
        if key not in self.giveaway_data:
            self.giveaway_data[key] = {}
            self.save_giveaways()
        return self.giveaway_data[key]

    def save_giveaways(self) -> None:
        save_json(GIVEAWAYS_FILE, self.giveaway_data)

    def get_invite_count(self, guild_id: int, user_id: int) -> int:
        store = self.get_invite_store(guild_id)
        return int(store.get(str(user_id), 0))

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

        inviter = None
        new_cache = {invite.code: invite.uses or 0 for invite in invites}
        for invite in invites:
            old_uses = before.get(invite.code, 0)
            new_uses = invite.uses or 0
            if new_uses > old_uses and invite.inviter is not None:
                inviter = invite.inviter
                break

        self.invite_cache[member.guild.id] = new_cache
        if inviter is None:
            return None

        store = self.get_invite_store(member.guild.id)
        inviter_key = str(inviter.id)
        store[inviter_key] = int(store.get(inviter_key, 0)) + 1
        self.save_invites()
        return member.guild.get_member(inviter.id)

    async def schedule_existing_giveaways(self) -> None:
        for guild_id, giveaways in self.giveaway_data.items():
            for message_id, giveaway in giveaways.items():
                if giveaway.get("status") == "active":
                    self.schedule_giveaway_end(int(guild_id), int(message_id), int(giveaway["end_at"]))

    def schedule_giveaway_end(self, guild_id: int, message_id: int, end_at: int) -> None:
        task_key = f"{guild_id}:{message_id}"
        if task_key in self.giveaway_tasks:
            self.giveaway_tasks[task_key].cancel()
        self.giveaway_tasks[task_key] = asyncio.create_task(self._giveaway_end_task(guild_id, message_id, end_at))

    async def _giveaway_end_task(self, guild_id: int, message_id: int, end_at: int) -> None:
        await asyncio.sleep(max(0, end_at - int(discord.utils.utcnow().timestamp())))
        await self.finish_giveaway(guild_id, message_id, ended_by=None)

    async def join_giveaway(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.message is None:
            await interaction.response.send_message("Impossible de participer ici.", ephemeral=True)
            return

        store = self.get_giveaway_store(interaction.guild.id)
        giveaway = store.get(str(interaction.message.id))
        if giveaway is None or giveaway.get("status") != "active":
            await interaction.response.send_message("Ce giveaway n'est plus actif.", ephemeral=True)
            return

        user_id = interaction.user.id
        participants = giveaway.setdefault("participants", [])
        if user_id in participants:
            await interaction.response.send_message("Tu participes deja a ce giveaway.", ephemeral=True)
            return

        min_invites = int(giveaway.get("min_invites", 0))
        invite_count = self.get_invite_count(interaction.guild.id, user_id)
        if invite_count < min_invites:
            await interaction.response.send_message(
                f"Tu dois avoir au moins {min_invites} invitation(s) pour participer. Tu en as {invite_count}.",
                ephemeral=True,
            )
            return

        participants.append(user_id)
        self.save_giveaways()

        await interaction.response.send_message("Participation enregistree.", ephemeral=True)
        try:
            await interaction.user.send(f"Tu participes au giveaway : {giveaway['prize']}")
        except discord.Forbidden:
            pass

    async def finish_giveaway(self, guild_id: int, message_id: int, ended_by: discord.Member | None) -> None:
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

        participants = list(dict.fromkeys(giveaway.get("participants", [])))
        valid_participants = [
            user_id
            for user_id in participants
            if self.get_invite_count(guild_id, user_id) >= int(giveaway.get("min_invites", 0))
        ]
        winners_count = min(int(giveaway["winners_count"]), len(valid_participants))
        winners = random.sample(valid_participants, winners_count) if winners_count > 0 else []

        giveaway["status"] = "ended"
        giveaway["winners"] = winners
        self.save_giveaways()

        mentions = ", ".join(f"<@{winner_id}>" for winner_id in winners)
        if mentions:
            await channel.send(f"🎉 Giveaway termine ! Gagnant(s) pour **{giveaway['prize']}** : {mentions}")
        else:
            await channel.send(f"🎉 Giveaway termine pour **{giveaway['prize']}**, mais aucun participant valide n'a ete trouve.")

    async def reroll_giveaway(self, guild_id: int, message_id: int) -> list[int]:
        store = self.get_giveaway_store(guild_id)
        giveaway = store.get(str(message_id))
        if giveaway is None:
            return []

        participants = list(dict.fromkeys(giveaway.get("participants", [])))
        previous_winners = set(giveaway.get("winners", []))
        valid_participants = [
            user_id
            for user_id in participants
            if user_id not in previous_winners
            and self.get_invite_count(guild_id, user_id) >= int(giveaway.get("min_invites", 0))
        ]
        winners_count = min(int(giveaway["winners_count"]), len(valid_participants))
        winners = random.sample(valid_participants, winners_count) if winners_count > 0 else []
        giveaway["winners"] = winners
        self.save_giveaways()
        return winners

    async def ensure_ticket_config(self, guild: discord.Guild) -> None:
        config = self.get_guild_config(guild.id)

        staff_role = guild.get_role(config["staff_role_id"]) if config["staff_role_id"] else None
        if staff_role is None:
            staff_role = discord.utils.get(guild.roles, name=AUTO_STAFF_ROLE_NAME)
            if staff_role is None:
                staff_role = await guild.create_role(
                    name=AUTO_STAFF_ROLE_NAME,
                    reason="Auto configuration du systeme de tickets",
                )
            config["staff_role_id"] = staff_role.id

        archive_role = guild.get_role(config["archive_role_id"]) if config["archive_role_id"] else None
        if archive_role is None:
            archive_role = discord.utils.get(guild.roles, name=AUTO_ARCHIVE_ROLE_NAME)
            if archive_role is None:
                archive_role = await guild.create_role(
                    name=AUTO_ARCHIVE_ROLE_NAME,
                    reason="Auto configuration du systeme de tickets",
                )
            config["archive_role_id"] = archive_role.id

        ticket_category = guild.get_channel(config["ticket_category_id"]) if config["ticket_category_id"] else None
        if not isinstance(ticket_category, discord.CategoryChannel):
            ticket_category = discord.utils.get(guild.categories, name=AUTO_TICKET_CATEGORY_NAME)
            if ticket_category is None:
                ticket_category = await guild.create_category(
                    AUTO_TICKET_CATEGORY_NAME,
                    reason="Auto configuration du systeme de tickets",
                )
            config["ticket_category_id"] = ticket_category.id

        archive_category = guild.get_channel(config["archive_category_id"]) if config["archive_category_id"] else None
        if not isinstance(archive_category, discord.CategoryChannel):
            archive_category = discord.utils.get(guild.categories, name=AUTO_ARCHIVE_CATEGORY_NAME)
            if archive_category is None:
                archive_category = await guild.create_category(
                    AUTO_ARCHIVE_CATEGORY_NAME,
                    reason="Auto configuration du systeme de tickets",
                )
            config["archive_category_id"] = archive_category.id

        self.save_config()

    def get_open_tickets_for_user(self, guild_id: int, user_id: int) -> list[dict[str, Any]]:
        store = self.get_ticket_store(guild_id)
        return [
            ticket
            for ticket in store["channels"].values()
            if ticket["owner_id"] == user_id and ticket["status"] == "open"
        ]

    def get_next_ticket_number(self, guild_id: int) -> int:
        store = self.get_ticket_store(guild_id)
        used_numbers = sorted(
            ticket["number"]
            for ticket in store["channels"].values()
            if ticket["status"] == "open"
        )
        expected = 1
        for number in used_numbers:
            if number == expected:
                expected += 1
            elif number > expected:
                break
        return expected

    async def create_ticket(self, interaction: discord.Interaction, ticket_type: str) -> None:
        guild = interaction.guild
        user = interaction.user
        if guild is None or not isinstance(user, discord.Member):
            await interaction.response.send_message("Impossible de creer un ticket ici.", ephemeral=True)
            return

        config = self.get_guild_config(guild.id)
        required = [
            config["staff_role_id"],
            config["archive_role_id"],
            config["ticket_category_id"],
            config["archive_category_id"],
        ]
        if not all(required):
            await interaction.response.send_message("Le systeme de tickets n'est pas encore configure.", ephemeral=True)
            return

        staff_role = guild.get_role(config["staff_role_id"])
        archive_role = guild.get_role(config["archive_role_id"])
        ticket_category = guild.get_channel(config["ticket_category_id"])
        archive_category = guild.get_channel(config["archive_category_id"])
        if (
            staff_role is None
            or archive_role is None
            or not isinstance(ticket_category, discord.CategoryChannel)
            or not isinstance(archive_category, discord.CategoryChannel)
        ):
            await interaction.response.send_message("La configuration des tickets est invalide.", ephemeral=True)
            return

        if len(self.get_open_tickets_for_user(guild.id, user.id)) >= 3:
            await interaction.response.send_message(
                "Tu as deja 3 tickets ouverts. Ferme-en un avant d'en creer un autre.",
                ephemeral=True,
            )
            return

        ticket_number = self.get_next_ticket_number(guild.id)
        channel_name = f"{ticket_number}-{slugify_name(user.display_name)}"
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True, embed_links=True),
            staff_role: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_messages=True),
            archive_role: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_messages=True),
        }
        channel = await guild.create_text_channel(name=channel_name, category=ticket_category, overwrites=overwrites, reason=f"Creation du ticket {ticket_type} par {user}")

        store = self.get_ticket_store(guild.id)
        store["channels"][str(channel.id)] = {"channel_id": channel.id, "owner_id": user.id, "status": "open", "type": ticket_type, "number": ticket_number}
        self.save_tickets()

        embed = discord.Embed(title=f"Ticket {TICKET_TYPES[ticket_type]['label']}", description=f"{user.mention}, ton ticket a ete cree avec succes.\nExplique ta demande avec le plus de details possible.", color=discord.Color.green())
        embed.add_field(name="Categorie", value=TICKET_TYPES[ticket_type]["label"], inline=True)
        embed.add_field(name="Numero", value=str(ticket_number), inline=True)
        await channel.send(content=f"{user.mention} {staff_role.mention}", embed=embed, view=TicketCloseView(self))
        await interaction.response.defer(ephemeral=True, thinking=False)

    async def archive_ticket(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        channel = interaction.channel
        user = interaction.user
        if guild is None or channel is None or not isinstance(user, discord.Member):
            await interaction.response.send_message("Impossible de fermer ce ticket.", ephemeral=True)
            return

        store = self.get_ticket_store(guild.id)
        ticket = store["channels"].get(str(channel.id))
        if ticket is None:
            await interaction.response.send_message("Ce salon n'est pas gere comme un ticket par le bot.", ephemeral=True)
            return
        if ticket["status"] != "open":
            await interaction.response.send_message("Ce ticket est deja archive.", ephemeral=True)
            return

        config = self.get_guild_config(guild.id)
        staff_role = guild.get_role(config["staff_role_id"]) if config["staff_role_id"] else None
        archive_role = guild.get_role(config["archive_role_id"]) if config["archive_role_id"] else None
        archive_category = guild.get_channel(config["archive_category_id"]) if config["archive_category_id"] else None
        owner = guild.get_member(ticket["owner_id"])
        if archive_role is None or not isinstance(archive_category, discord.CategoryChannel):
            await interaction.response.send_message("La configuration des archives est invalide.", ephemeral=True)
            return

        is_allowed = user.id == guild.owner_id or archive_role in user.roles or (staff_role is not None and staff_role in user.roles)
        if not is_allowed:
            await interaction.response.send_message("Tu n'as pas la permission de fermer ce ticket.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        await channel.edit(category=archive_category, reason=f"Archivage du ticket par {user}")
        if owner is not None:
            await channel.set_permissions(owner, overwrite=discord.PermissionOverwrite(view_channel=False))
        if staff_role is not None:
            await channel.set_permissions(staff_role, overwrite=discord.PermissionOverwrite(view_channel=False))
        await channel.set_permissions(archive_role, overwrite=discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_messages=True))
        await channel.set_permissions(guild.default_role, overwrite=discord.PermissionOverwrite(view_channel=False))

        ticket["status"] = "archived"
        ticket["closed_by"] = user.id
        self.save_tickets()
        embed = discord.Embed(title="Ticket archive", description=f"Ce ticket a ete archive par {user.mention}.\nSeul le staff superieur peut maintenant consulter cette archive.", color=discord.Color.orange())
        await channel.send(embed=embed, view=TicketArchiveView(self))
        await interaction.followup.send("Le ticket a ete archive.", ephemeral=True)

    async def reopen_ticket(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        channel = interaction.channel
        user = interaction.user
        if guild is None or channel is None or not isinstance(user, discord.Member):
            await interaction.response.send_message("Impossible de reouvrir ce ticket.", ephemeral=True)
            return

        store = self.get_ticket_store(guild.id)
        ticket = store["channels"].get(str(channel.id))
        if ticket is None:
            await interaction.response.send_message("Ce salon n'est pas gere comme un ticket par le bot.", ephemeral=True)
            return
        if ticket["status"] != "archived":
            await interaction.response.send_message("Ce ticket n'est pas archive.", ephemeral=True)
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
            await interaction.response.send_message("La configuration des tickets est invalide.", ephemeral=True)
            return

        is_allowed = user.id == guild.owner_id or archive_role in user.roles
        if not is_allowed:
            await interaction.response.send_message("Seul le staff superieur peut reouvrir ce ticket.", ephemeral=True)
            return

        if owner is None:
            await interaction.response.send_message("Le createur du ticket n'est plus sur le serveur.", ephemeral=True)
            return

        if len(self.get_open_tickets_for_user(guild.id, owner.id)) >= 3:
            await interaction.response.send_message(
                "Impossible de reouvrir ce ticket car l'utilisateur a deja 3 tickets ouverts.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        await channel.edit(category=ticket_category, reason=f"Reouverture du ticket par {user}")
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
        await channel.set_permissions(guild.default_role, overwrite=discord.PermissionOverwrite(view_channel=False))

        ticket["status"] = "open"
        ticket["reopened_by"] = user.id
        self.save_tickets()

        embed = discord.Embed(
            title="Ticket reouvert",
            description=f"Ce ticket a ete reouvert par {user.mention}.",
            color=discord.Color.green(),
        )
        await channel.send(embed=embed, view=TicketCloseView(self))
        await interaction.followup.send("Le ticket a ete reouvert.", ephemeral=True)


def create_bot() -> YishiBot:
    return YishiBot()


def register_commands(bot: YishiBot) -> None:
    @bot.event
    async def on_ready() -> None:
        if not bot.guild_sync_done:
            for guild in bot.guilds:
                await bot.ensure_ticket_config(guild)
                await bot.cache_invites(guild)
                bot.tree.copy_global_to(guild=guild)
                synced = await bot.tree.sync(guild=guild)
                print(f"{len(synced)} commande(s) slash synchronisee(s) sur {guild.name}.")
            await bot.schedule_existing_giveaways()
            bot.tree.clear_commands(guild=None)
            await bot.tree.sync()
            bot.guild_sync_done = True
        print(f"Bot connecte en tant que {bot.user}")

    @bot.event
    async def on_member_join(member: discord.Member) -> None:
        config = bot.get_guild_config(member.guild.id)
        welcome_channel = member.guild.get_channel(config["welcome_channel_id"]) if config["welcome_channel_id"] else member.guild.system_channel
        inviter = await bot.track_member_invite(member)
        if isinstance(welcome_channel, discord.TextChannel):
            await welcome_channel.send(
                "🌙 Bienvenue sur Yishi’s Shop, "
                f"{member.mention} !\n"
                "Nous sommes ravis de t’accueillir sur le serveur. Ici, tu trouveras un shop fiable, rapide et professionnel specialise sur Blox Fruits.\n\n"
                "✨ Avant de commencer, pense a :\n"
                "• Lire les salons importants\n"
                "• Consulter la boutique disponible\n"
                "• Ouvrir un ticket si tu as une question ou si tu veux passer commande\n\n"
                "💎 Chez Yishi’s Shop, notre objectif est de t’offrir un service serieux, securise et de qualite.\n\n"
                "📩 Besoin d’aide ? Le staff est la pour toi.\n"
                "Profite bien du serveur et merci de ta confiance."
            )
            if inviter is not None:
                await welcome_channel.send(f"{member.mention} a ete invite par {inviter.mention}.")
            else:
                await welcome_channel.send(f"Impossible de detecter qui a invite {member.mention}.")

    @bot.event
    async def on_raw_reaction_add(payload: discord.RawReactionActionEvent) -> None:
        if payload.guild_id is None or str(payload.emoji) != "✅":
            return
        if payload.user_id == bot.user.id:
            return

        config = bot.get_guild_config(payload.guild_id)
        if payload.message_id != config.get("rules_message_id"):
            return

        guild = bot.get_guild(payload.guild_id)
        if guild is None:
            return

        role_id = config.get("rules_role_id")
        if role_id is None:
            return

        role = guild.get_role(role_id)
        if role is None:
            return

        member = guild.get_member(payload.user_id)
        if member is None or member.bot:
            return

        if role in member.roles:
            return

        await member.add_roles(role, reason="Validation du reglement par reaction")

    @bot.tree.command(name="aide", description="Affiche la liste des commandes")
    async def aide(interaction: discord.Interaction) -> None:
        embed = discord.Embed(title="Commandes", color=discord.Color.blurple())
        embed.add_field(name="/aide", value="Affiche cette aide.", inline=False)
        embed.add_field(name="/ping", value="Teste la latence du bot.", inline=False)
        embed.add_field(name="/paiement", value="Affiche les moyens de paiement du shop.", inline=False)
        embed.add_field(name="/invites", value="Affiche ton nombre d'invitations.", inline=False)
        embed.add_field(name="/dire", value="Fait parler le bot.", inline=False)
        embed.add_field(name="/envoyer_message", value="Envoie un message dans le salon de ton choix.", inline=False)
        embed.add_field(name="/annonce", value="Envoie une annonce en embed dans un salon.", inline=False)
        embed.add_field(name="/userinfo", value="Affiche les informations d'un membre.", inline=False)
        embed.add_field(name="/clear", value="Supprime des messages.", inline=False)
        embed.add_field(name="/kick", value="Expulse un membre.", inline=False)
        embed.add_field(name="/ban", value="Bannit un membre.", inline=False)
        embed.add_field(name="/mute", value="Timeout un membre.", inline=False)
        embed.add_field(name="/unmute", value="Retire le timeout d'un membre.", inline=False)
        embed.add_field(name="/warn", value="Avertit un membre avec une raison.", inline=False)
        embed.add_field(name="/list_warn", value="Affiche les avertissements d'un membre.", inline=False)
        embed.add_field(name="/add_membre_ticket", value="Ajoute un membre au ticket actuel.", inline=False)
        embed.add_field(name="/giveaway_create", value="Cree un giveaway.", inline=False)
        embed.add_field(name="/giveaway_end", value="Termine un giveaway.", inline=False)
        embed.add_field(name="/giveaway_reroll", value="Retire un nouveau gagnant.", inline=False)
        embed.add_field(name="/config_role_staff", value="Definit le role staff des tickets ouverts.", inline=False)
        embed.add_field(name="/config_role_archive", value="Definit le role staff superieur des archives.", inline=False)
        embed.add_field(name="/config_categorie_tickets", value="Definit la categorie des tickets ouverts.", inline=False)
        embed.add_field(name="/config_categorie_archives", value="Definit la categorie des tickets archives.", inline=False)
        embed.add_field(name="/config_salon_bienvenue", value="Definit le salon des messages de bienvenue.", inline=False)
        embed.add_field(name="/config_role_regles", value="Definit le role donne apres acceptation du reglement.", inline=False)
        embed.add_field(name="/envoyer_reglement", value="Envoie le reglement officiel dans le salon choisi.", inline=False)
        embed.add_field(name="/envoyer_message_regles", value="Envoie le message de validation avec reaction ✅.", inline=False)
        embed.add_field(name="/envoyer_panel_tickets", value="Envoie le panneau de tickets dans un salon.", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bot.tree.command(name="ping", description="Teste la latence du bot")
    async def ping(interaction: discord.Interaction) -> None:
        await interaction.response.send_message(f"Pong ! {round(bot.latency * 1000)} ms")

    @bot.tree.command(name="paiement", description="Affiche les moyens de paiement du shop")
    async def paiement(interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="Moyens de paiement",
            description="Voici les moyens de paiement disponibles pour Yishi's Shop.",
            color=discord.Color.green(),
        )
        embed.add_field(name="PayPal", value="YishisShops", inline=False)
        embed.add_field(name="Revolut", value="https://revolut.me/souillarda", inline=False)
        await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="invites", description="Affiche ton nombre d'invitations")
    @app_commands.describe(membre="Membre dont tu veux voir les invitations")
    async def invites(
        interaction: discord.Interaction,
        membre: discord.Member | None = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return

        target = membre or interaction.user
        count = bot.get_invite_count(interaction.guild.id, target.id)
        await interaction.response.send_message(
            f"{target.mention} a {count} invitation(s).",
            ephemeral=True,
        )

    @bot.tree.command(name="dire", description="Fait parler le bot")
    @app_commands.describe(message="Le message que le bot doit envoyer")
    @app_commands.default_permissions(manage_messages=True)
    async def dire(interaction: discord.Interaction, message: str) -> None:
        if interaction.channel is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return
        await interaction.response.send_message("Message envoye.", ephemeral=True)
        await interaction.channel.send(message)

    @bot.tree.command(name="envoyer_message", description="Envoie un message dans le salon de ton choix")
    @app_commands.describe(
        salon="Le salon dans lequel envoyer le message",
        message="Le message que le bot doit envoyer",
    )
    @app_commands.default_permissions(manage_messages=True)
    async def envoyer_message(
        interaction: discord.Interaction,
        salon: discord.TextChannel,
        message: str,
    ) -> None:
        await salon.send(message)
        await interaction.response.send_message(
            f"Message envoye dans {salon.mention}.",
            ephemeral=True,
        )

    @bot.tree.command(name="annonce", description="Envoie une annonce en embed dans le salon de ton choix")
    @app_commands.describe(
        salon="Le salon dans lequel envoyer l'annonce",
        titre="Le titre de l'annonce",
        message="Le texte de l'annonce",
    )
    @app_commands.default_permissions(manage_messages=True)
    async def annonce(
        interaction: discord.Interaction,
        salon: discord.TextChannel,
        titre: str,
        message: str,
    ) -> None:
        embed = discord.Embed(
            title=titre,
            description=message,
            color=discord.Color.blurple(),
        )
        embed.set_footer(text=f"Annonce par {interaction.user}")
        await salon.send(embed=embed)
        await interaction.response.send_message(
            f"Annonce envoyee dans {salon.mention}.",
            ephemeral=True,
        )

    @bot.tree.command(name="userinfo", description="Affiche les informations d'un membre")
    @app_commands.describe(membre="Le membre a afficher")
    async def userinfo(
        interaction: discord.Interaction,
        membre: discord.Member | None = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return
        member = membre or interaction.user
        embed = discord.Embed(title=f"Infos de {member}", color=discord.Color.green())
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="ID", value=str(member.id), inline=False)
        embed.add_field(name="Nom", value=member.name, inline=True)
        embed.add_field(name="Pseudo", value=member.display_name, inline=True)
        embed.add_field(name="Compte cree le", value=member.created_at.strftime("%d/%m/%Y %H:%M"), inline=False)
        if member.joined_at:
            embed.add_field(name="A rejoint le serveur le", value=member.joined_at.strftime("%d/%m/%Y %H:%M"), inline=False)
        await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="clear", description="Supprime un certain nombre de messages")
    @app_commands.describe(nombre="Nombre de messages a supprimer")
    @app_commands.default_permissions(manage_messages=True)
    async def clear(
        interaction: discord.Interaction,
        nombre: app_commands.Range[int, 1, 100],
    ) -> None:
        if interaction.channel is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=nombre)
        await interaction.followup.send(f"{len(deleted)} message(s) supprime(s).", ephemeral=True)

    @bot.tree.command(name="add_membre_ticket", description="Ajoute un membre au ticket actuel")
    @app_commands.describe(membre="Le membre a ajouter au ticket")
    @app_commands.default_permissions(manage_channels=True)
    async def add_membre_ticket(
        interaction: discord.Interaction,
        membre: discord.Member,
    ) -> None:
        if interaction.guild is None or interaction.channel is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return

        store = bot.get_ticket_store(interaction.guild.id)
        ticket = store["channels"].get(str(interaction.channel.id))
        if ticket is None:
            await interaction.response.send_message(
                "Cette commande doit etre utilisee dans un ticket.",
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
            f"{membre.mention} a ete ajoute au ticket.",
            ephemeral=True,
        )
        await interaction.channel.send(f"{membre.mention} a ete ajoute au ticket par {interaction.user.mention}.")

    @bot.tree.command(name="kick", description="Expulse un membre du serveur")
    @app_commands.describe(membre="Le membre a expulser", raison="La raison du kick")
    @app_commands.default_permissions(kick_members=True)
    async def kick(
        interaction: discord.Interaction,
        membre: discord.Member,
        raison: str = "Aucune raison fournie",
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return
        bot_member = interaction.guild.me
        if bot_member is None:
            await interaction.response.send_message("Impossible de verifier mes permissions.", ephemeral=True)
            return
        error = can_moderate(interaction.user, membre, bot_member)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        await membre.kick(reason=raison)
        await interaction.response.send_message(f"{membre} a ete expulse. Raison : {raison}")

    @bot.tree.command(name="ban", description="Bannit un membre du serveur")
    @app_commands.describe(membre="Le membre a bannir", raison="La raison du ban")
    @app_commands.default_permissions(ban_members=True)
    async def ban(
        interaction: discord.Interaction,
        membre: discord.Member,
        raison: str = "Aucune raison fournie",
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return
        bot_member = interaction.guild.me
        if bot_member is None:
            await interaction.response.send_message("Impossible de verifier mes permissions.", ephemeral=True)
            return
        error = can_moderate(interaction.user, membre, bot_member)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        await membre.ban(reason=raison)
        await interaction.response.send_message(f"{membre} a ete banni. Raison : {raison}")

    @bot.tree.command(name="mute", description="Timeout un membre pendant un certain temps")
    @app_commands.describe(membre="Le membre a mute", minutes="Duree du timeout en minutes", raison="La raison du mute")
    @app_commands.default_permissions(moderate_members=True)
    async def mute(
        interaction: discord.Interaction,
        membre: discord.Member,
        minutes: app_commands.Range[int, 1, 40320],
        raison: str = "Aucune raison fournie",
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return
        bot_member = interaction.guild.me
        if bot_member is None:
            await interaction.response.send_message("Impossible de verifier mes permissions.", ephemeral=True)
            return
        error = can_moderate(interaction.user, membre, bot_member)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        timeout_until = discord.utils.utcnow() + timedelta(minutes=minutes)
        await membre.timeout(timeout_until, reason=raison)
        await interaction.response.send_message(f"{membre} a ete mute pendant {minutes} minute(s). Raison : {raison}")

    @bot.tree.command(name="unmute", description="Retire le timeout d'un membre")
    @app_commands.describe(membre="Le membre a unmute", raison="La raison du unmute")
    @app_commands.default_permissions(moderate_members=True)
    async def unmute(
        interaction: discord.Interaction,
        membre: discord.Member,
        raison: str = "Aucune raison fournie",
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return
        bot_member = interaction.guild.me
        if bot_member is None:
            await interaction.response.send_message("Impossible de verifier mes permissions.", ephemeral=True)
            return
        error = can_moderate(interaction.user, membre, bot_member)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        await membre.timeout(None, reason=raison)
        await interaction.response.send_message(f"{membre} n'est plus mute. Raison : {raison}")

    @bot.tree.command(name="warn", description="Avertit un membre avec une raison")
    @app_commands.describe(membre="Le membre a avertir", raison="La raison de l'avertissement")
    @app_commands.default_permissions(moderate_members=True)
    async def warn(
        interaction: discord.Interaction,
        membre: discord.Member,
        raison: str,
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return

        bot_member = interaction.guild.me
        if bot_member is None:
            await interaction.response.send_message("Impossible de verifier mes permissions.", ephemeral=True)
            return

        error = can_moderate(interaction.user, membre, bot_member)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return

        store = bot.get_warning_store(interaction.guild.id)
        member_key = str(membre.id)
        if member_key not in store:
            store[member_key] = []

        store[member_key].append(
            {
                "reason": raison,
                "moderator_id": interaction.user.id,
                "moderator_name": str(interaction.user),
                "created_at": discord.utils.utcnow().strftime("%d/%m/%Y %H:%M"),
            }
        )
        bot.save_warnings()

        await interaction.response.send_message(
            f"{membre.mention} a recu un avertissement. Raison : {raison}"
        )

    @bot.tree.command(name="list_warn", description="Affiche les avertissements d'un membre")
    @app_commands.describe(membre="Le membre dont tu veux voir les avertissements")
    @app_commands.default_permissions(moderate_members=True)
    async def list_warn(
        interaction: discord.Interaction,
        membre: discord.Member,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return

        store = bot.get_warning_store(interaction.guild.id)
        warnings = store.get(str(membre.id), [])
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

    @bot.tree.command(name="giveaway_create", description="Cree un giveaway")
    @app_commands.describe(
        salon="Salon dans lequel envoyer le giveaway",
        prix="Prix du giveaway",
        duree="Duree du giveaway. Exemple : 10m, 2h, 1d",
        gagnants="Nombre de gagnants",
        invitations_minimum="Nombre minimum d'invitations pour participer",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def giveaway_create(
        interaction: discord.Interaction,
        salon: discord.TextChannel,
        prix: str,
        duree: str,
        gagnants: app_commands.Range[int, 1, 20],
        invitations_minimum: app_commands.Range[int, 0, 1000],
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return

        seconds = parse_duration(duree)
        if seconds is None:
            await interaction.response.send_message(
                "Duree invalide. Utilise le format `10m`, `2h` ou `1d`.",
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
                f"Invitations requises : **{invitations_minimum}**\n\n"
                "Clique sur Participer pour rejoindre le giveaway."
            ),
            color=discord.Color.gold(),
        )
        message = await salon.send(embed=embed, view=GiveawayView(bot))

        store = bot.get_giveaway_store(interaction.guild.id)
        store[str(message.id)] = {
            "message_id": message.id,
            "channel_id": salon.id,
            "prize": prix,
            "winners_count": int(gagnants),
            "min_invites": int(invitations_minimum),
            "participants": [],
            "winners": [],
            "end_at": end_at,
            "status": "active",
            "created_by": interaction.user.id,
        }
        bot.save_giveaways()
        bot.schedule_giveaway_end(interaction.guild.id, message.id, end_at)

        await interaction.response.send_message(
            f"Giveaway cree dans {salon.mention}. ID du message : `{message.id}`",
            ephemeral=True,
        )

    @bot.tree.command(name="giveaway_end", description="Termine un giveaway maintenant")
    @app_commands.describe(message_id="ID du message du giveaway")
    @app_commands.default_permissions(manage_guild=True)
    async def giveaway_end(interaction: discord.Interaction, message_id: str) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return

        if not message_id.isdigit():
            await interaction.response.send_message("L'ID du message doit etre un nombre.", ephemeral=True)
            return

        await bot.finish_giveaway(interaction.guild.id, int(message_id), ended_by=interaction.user)
        await interaction.response.send_message("Giveaway termine si l'ID etait valide.", ephemeral=True)

    @bot.tree.command(name="giveaway_reroll", description="Retire un nouveau gagnant pour un giveaway")
    @app_commands.describe(message_id="ID du message du giveaway")
    @app_commands.default_permissions(manage_guild=True)
    async def giveaway_reroll(interaction: discord.Interaction, message_id: str) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return

        if not message_id.isdigit():
            await interaction.response.send_message("L'ID du message doit etre un nombre.", ephemeral=True)
            return

        winners = await bot.reroll_giveaway(interaction.guild.id, int(message_id))
        if not winners:
            await interaction.response.send_message("Aucun nouveau gagnant valide trouve.", ephemeral=True)
            return

        mentions = ", ".join(f"<@{winner_id}>" for winner_id in winners)
        await interaction.response.send_message(f"Nouveau gagnant : {mentions}")

    @bot.tree.command(name="config_role_staff", description="Definit le role staff pour les tickets ouverts")
    @app_commands.describe(role="Role qui verra les tickets ouverts")
    @app_commands.default_permissions(manage_guild=True)
    async def config_role_staff(interaction: discord.Interaction, role: discord.Role) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return
        config = bot.get_guild_config(interaction.guild.id)
        config["staff_role_id"] = role.id
        bot.save_config()
        await interaction.response.send_message(f"Le role staff des tickets ouverts est maintenant {role.mention}.", ephemeral=True)

    @bot.tree.command(name="config_role_archive", description="Definit le role staff superieur des archives")
    @app_commands.describe(role="Role qui verra les tickets archives")
    @app_commands.default_permissions(manage_guild=True)
    async def config_role_archive(interaction: discord.Interaction, role: discord.Role) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return
        config = bot.get_guild_config(interaction.guild.id)
        config["archive_role_id"] = role.id
        bot.save_config()
        await interaction.response.send_message(f"Le role des archives est maintenant {role.mention}.", ephemeral=True)

    @bot.tree.command(name="config_categorie_tickets", description="Definit la categorie des tickets ouverts")
    @app_commands.describe(categorie="Categorie des tickets ouverts")
    @app_commands.default_permissions(manage_guild=True)
    async def config_categorie_tickets(
        interaction: discord.Interaction,
        categorie: discord.CategoryChannel,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return
        config = bot.get_guild_config(interaction.guild.id)
        config["ticket_category_id"] = categorie.id
        bot.save_config()
        await interaction.response.send_message(f"La categorie des tickets ouverts est maintenant {categorie.name}.", ephemeral=True)

    @bot.tree.command(name="config_categorie_archives", description="Definit la categorie des tickets archives")
    @app_commands.describe(categorie="Categorie des tickets archives")
    @app_commands.default_permissions(manage_guild=True)
    async def config_categorie_archives(
        interaction: discord.Interaction,
        categorie: discord.CategoryChannel,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return
        config = bot.get_guild_config(interaction.guild.id)
        config["archive_category_id"] = categorie.id
        bot.save_config()
        await interaction.response.send_message(f"La categorie des tickets archives est maintenant {categorie.name}.", ephemeral=True)

    @bot.tree.command(name="config_salon_bienvenue", description="Definit le salon des messages de bienvenue")
    @app_commands.describe(salon="Salon dans lequel envoyer les messages de bienvenue")
    @app_commands.default_permissions(manage_guild=True)
    async def config_salon_bienvenue(
        interaction: discord.Interaction,
        salon: discord.TextChannel,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return
        config = bot.get_guild_config(interaction.guild.id)
        config["welcome_channel_id"] = salon.id
        bot.save_config()
        await interaction.response.send_message(
            f"Le salon de bienvenue est maintenant {salon.mention}.",
            ephemeral=True,
        )

    @bot.tree.command(name="config_role_regles", description="Definit le role donne apres acceptation du reglement")
    @app_commands.describe(role="Role a donner quand un membre accepte le reglement")
    @app_commands.default_permissions(manage_guild=True)
    async def config_role_regles(interaction: discord.Interaction, role: discord.Role) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return
        config = bot.get_guild_config(interaction.guild.id)
        config["rules_role_id"] = role.id
        bot.save_config()
        await interaction.response.send_message(
            f"Le role des regles est maintenant {role.mention}.",
            ephemeral=True,
        )

    @bot.tree.command(name="envoyer_reglement", description="Envoie le reglement officiel du serveur")
    @app_commands.describe(salon="Salon dans lequel envoyer le reglement")
    @app_commands.default_permissions(manage_guild=True)
    async def envoyer_reglement(
        interaction: discord.Interaction,
        salon: discord.TextChannel,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return

        await salon.send(
            "📜 𝐑èglement Officiel\n"
            "Bienvenue sur Yishi’s Shop.\n"
            "Afin de garantir une expérience sérieuse, fluide et agréable à l’ensemble des membres, chaque utilisateur est tenu de respecter le règlement ci-dessous.\n\n"
            "✧ 1. Respect & comportement\n"
            "Le respect envers tous les membres du serveur est obligatoire.\n"
            "Tout comportement toxique, irrespectueux, provocateur, agressif, insultant ou humiliant est strictement interdit.\n\n"
            "✧ 2. Spam & flood interdits\n"
            "Les messages répétitifs, le flood, le spam, les abus de majuscules, les mentions abusives ainsi que l’utilisation excessive d’emojis sont interdits.\n\n"
            "✧ 3. Contenus inappropriés\n"
            "Tout contenu choquant, violent, haineux, discriminatoire, sexuel, offensant ou inadapté au serveur est formellement interdit.\n\n"
            "✧ 4. Publicité non autorisée\n"
            "La publicité, sous quelque forme que ce soit, est interdite sans autorisation préalable du staff.\n"
            "Cela inclut les serveurs Discord, shops, réseaux sociaux, sites, services ou messages privés à but promotionnel.\n\n"
            "✧ 5. Utilisation correcte des salons\n"
            "Chaque salon possède une utilité précise.\n"
            "Merci de respecter leur fonction et d’éviter le hors-sujet afin de préserver une organisation claire et professionnelle.\n\n"
            "✧ 6. Commandes sérieuses uniquement\n"
            "Les commandes, demandes ou réservations doivent être sérieuses.\n"
            "Toute perte de temps volontaire, troll, faux intérêt ou abus envers le staff pourra être sanctionné.\n\n"
            "✧ 7. Tolérance zéro envers les arnaques\n"
            "Toute tentative d’arnaque, fraude, faux paiement, fausse preuve, chargeback, manipulation ou tromperie entraînera une sanction immédiate pouvant aller jusqu’au bannissement définitif.\n\n"
            "✧ 8. Paiements & preuves\n"
            "Les consignes données par le staff concernant les paiements, preuves, validations et tickets doivent être respectées.\n"
            "Toute tentative de contourner le système ou de fournir de fausses informations est interdite.\n\n"
            "✧ 9. Respect du staff\n"
            "Le staff est présent pour assurer le bon fonctionnement du serveur.\n"
            "Le manque de respect, la provocation, l’abus ou le refus délibéré de coopération avec l’équipe de modération ne seront pas tolérés.\n\n"
            "✧ 10. Tickets & support\n"
            "Les tickets doivent être ouverts uniquement pour une raison valable : commande, question importante, assistance ou problème réel.\n"
            "Tout abus de ticket pourra entraîner une restriction d’accès au support.\n\n"
            "✧ 11. Sécurité personnelle\n"
            "Ne partagez jamais vos informations sensibles : mots de passe, codes, adresses e-mail, moyens de paiement ou données privées.\n"
            "Vous êtes responsable de la sécurité de votre compte et de vos échanges.\n\n"
            "✧ 12. Transactions & services\n"
            "Les échanges et services proposés au sein du shop doivent rester clairs, honnêtes et conformes à ce qui est annoncé.\n"
            "Toute tentative de nuisance, de faux deal ou de perturbation volontaire sera sanctionnée.\n\n"
            "✧ 13. Sanctions\n"
            "Le non-respect du règlement peut entraîner, selon la gravité des faits :\n\n"
            "avertissement\n"
            "mute\n"
            "exclusion temporaire\n"
            "bannissement définitif\n\n"
            "Le staff se réserve le droit d’adapter les sanctions selon la situation.\n\n"
            "✧ 14. Acceptation du règlement\n"
            "En restant sur Yishi’s Shop, vous acceptez automatiquement l’ensemble des règles mentionnées ci-dessus et vous engagez à les respecter pleinement.\n\n"
            "Merci de votre confiance et bon shopping sur Yishi’s Shop"
        )
        await interaction.response.send_message(
            f"Le reglement a ete envoye dans {salon.mention}.",
            ephemeral=True,
        )

    @bot.tree.command(name="envoyer_message_regles", description="Envoie le message de validation du reglement")
    @app_commands.describe(salon="Salon dans lequel envoyer le message de validation")
    @app_commands.default_permissions(manage_guild=True)
    async def envoyer_message_regles(
        interaction: discord.Interaction,
        salon: discord.TextChannel,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return

        config = bot.get_guild_config(interaction.guild.id)
        if config.get("rules_role_id") is None:
            await interaction.response.send_message(
                "Configure d'abord le role a donner avec /config_role_regles.",
                ephemeral=True,
            )
            return

        message = await salon.send(
            "En réagissant avec ✅ à ce message, tu acceptes le règlement du serveur et tu obtiens l’accès complet au serveur."
        )
        await message.add_reaction("✅")

        config["rules_message_id"] = message.id
        config["rules_channel_id"] = salon.id
        bot.save_config()

        await interaction.response.send_message(
            f"Le message de validation a ete envoye dans {salon.mention}.",
            ephemeral=True,
        )

    @bot.tree.command(name="envoyer_panel_tickets", description="Envoie le panneau interactif de tickets")
    @app_commands.describe(salon="Salon dans lequel envoyer le panneau")
    @app_commands.default_permissions(manage_guild=True)
    async def envoyer_panel_tickets(
        interaction: discord.Interaction,
        salon: discord.TextChannel,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return
        config = bot.get_guild_config(interaction.guild.id)
        required = [
            config["staff_role_id"],
            config["archive_role_id"],
            config["ticket_category_id"],
            config["archive_category_id"],
        ]
        if not all(required):
            await interaction.response.send_message("Configure d'abord les roles et categories avant d'envoyer le panneau.", ephemeral=True)
            return
        await salon.send(embed=build_ticket_panel_embed(), view=TicketPanelView(bot))
        await interaction.response.send_message(f"Panneau de tickets envoye dans {salon.mention}.", ephemeral=True)
