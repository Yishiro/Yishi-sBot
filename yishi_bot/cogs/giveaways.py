from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any, Literal

import discord
from discord import app_commands
from discord.ext import commands

from yishi_bot.ticketing import build_custom_ticket_panel_embed, build_ticket_panel_embed
from yishi_bot.constants import (
    AUTO_ARCHIVE_CATEGORY_NAME,
    AUTO_ARCHIVE_ROLE_NAME,
    AUTO_GACHA_LOGS_CHANNEL_NAME,
    AUTO_GACHA_SPIN_CHANNEL_NAME,
    AUTO_GACHA_WINNER_CHANNEL_NAME,
    AUTO_LOGS_CHANNEL_NAME,
    AUTO_STAFF_ROLE_NAME,
    AUTO_TICKET_CATEGORY_NAME,
    AUTO_TRANSCRIPT_CHANNEL_NAME,
    GACHA_REWARDS,
    GACHA_SPIN_TYPES,
    RULES_ACCEPT_TEXT,
    RULES_TEXT,
    WELCOME_ADVANTAGES,
    WELCOME_CHECKLIST,
)
from yishi_bot.helpers import can_moderate, parse_duration, split_long_message
from yishi_bot.views import AnnouncementModal, GiveawayView, TicketPanelView

if TYPE_CHECKING:
    from yishi_bot.core import YishiBot


class GiveawaysCog(commands.Cog):
    def __init__(self, bot: YishiBot) -> None:
        self.bot = bot

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

        store = self.bot.get_giveaway_entries(interaction.guild.id)
        store[str(message.id)] = {
            "message_id": message.id,
            "channel_id": salon.id,
            "prize": prix,
            "winners_count": int(gagnants),
            "participants": [],
            "winners": [],
            "forced_winner_id": None,
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

        store = self.bot.get_giveaway_entries(interaction.guild.id)
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

    @app_commands.command(name="giveaway_blacklist_add", description="Blacklist un membre des giveaways")
    @app_commands.describe(membre="Membre à blacklist", raison="Raison staff de la blacklist")
    @app_commands.default_permissions(manage_guild=True)
    async def giveaway_blacklist_add(
        self,
        interaction: discord.Interaction,
        membre: discord.Member,
        raison: str,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return
        store = self.bot.get_giveaway_blacklist(interaction.guild.id)
        store[str(membre.id)] = {
            "reason": raison,
            "added_by": interaction.user.id,
            "added_at": discord.utils.utcnow().isoformat(),
        }
        self.bot.save_giveaways()
        await interaction.response.send_message(
            f"{membre.mention} a été blacklist des giveaways.",
            ephemeral=True,
        )

    @app_commands.command(name="giveaway_blacklist_remove", description="Retire un membre de la blacklist giveaways")
    @app_commands.describe(membre="Membre à retirer de la blacklist")
    @app_commands.default_permissions(manage_guild=True)
    async def giveaway_blacklist_remove(
        self,
        interaction: discord.Interaction,
        membre: discord.Member,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return
        store = self.bot.get_giveaway_blacklist(interaction.guild.id)
        removed = store.pop(str(membre.id), None)
        self.bot.save_giveaways()
        if removed is None:
            await interaction.response.send_message("Ce membre n'était pas blacklist.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"{membre.mention} a été retiré de la blacklist giveaways.",
            ephemeral=True,
        )

    @app_commands.command(name="giveaway_blacklist_list", description="Affiche la blacklist giveaways")
    @app_commands.default_permissions(manage_guild=True)
    async def giveaway_blacklist_list(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return
        store = self.bot.get_giveaway_blacklist(interaction.guild.id)
        if not store:
            await interaction.response.send_message("Aucun membre blacklist des giveaways.", ephemeral=True)
            return

        lines = []
        for member_id, data in list(store.items())[:25]:
            member = interaction.guild.get_member(int(member_id))
            label = member.mention if member is not None else member_id
            reason = data.get("reason", "Aucune raison")
            lines.append(f"{label} • {reason}")

        embed = discord.Embed(
            title="Blacklist giveaways",
            description="\n".join(lines),
            color=discord.Color.red(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="giveaway_force_winner", description="Force discrètement un gagnant pour un giveaway")
    @app_commands.describe(message_id="ID du message du giveaway", membre="Membre à faire gagner")
    @app_commands.default_permissions(manage_guild=True)
    async def giveaway_force_winner(
        self,
        interaction: discord.Interaction,
        message_id: str,
        membre: discord.Member,
    ) -> None:
        if interaction.guild is None or not message_id.isdigit():
            await interaction.response.send_message("ID invalide.", ephemeral=True)
            return

        store = self.bot.get_giveaway_entries(interaction.guild.id)
        giveaway = store.get(message_id)
        if giveaway is None:
            await interaction.response.send_message("Giveaway introuvable.", ephemeral=True)
            return

        giveaway["forced_winner_id"] = membre.id
        self.bot.save_giveaways()
        await interaction.response.send_message(
            f"Gagnant forcé défini pour **{giveaway['prize']}** : {membre.mention}.",
            ephemeral=True,
        )

    @app_commands.command(name="giveaway_force_winner_clear", description="Retire le gagnant forcé d'un giveaway")
    @app_commands.describe(message_id="ID du message du giveaway")
    @app_commands.default_permissions(manage_guild=True)
    async def giveaway_force_winner_clear(self, interaction: discord.Interaction, message_id: str) -> None:
        if interaction.guild is None or not message_id.isdigit():
            await interaction.response.send_message("ID invalide.", ephemeral=True)
            return

        store = self.bot.get_giveaway_entries(interaction.guild.id)
        giveaway = store.get(message_id)
        if giveaway is None:
            await interaction.response.send_message("Giveaway introuvable.", ephemeral=True)
            return

        giveaway["forced_winner_id"] = None
        self.bot.save_giveaways()
        await interaction.response.send_message(
            f"Gagnant forcé retiré pour **{giveaway['prize']}**.",
            ephemeral=True,
        )

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
