from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any, Literal

import discord
from discord import app_commands
from discord.ext import commands

from tickets import build_custom_ticket_panel_embed, build_ticket_panel_embed
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
from yishi_bot.views import AnnouncementModal, TicketPanelView

if TYPE_CHECKING:
    from yishi_bot.core import YishiBot


class GeneralCog(commands.Cog):
    def __init__(self, bot: YishiBot) -> None:
        self.bot = bot

    @app_commands.command(name="aide", description="Affiche la liste des commandes")
    async def aide(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(title="Commandes", color=discord.Color.blurple())
        embed.add_field(
            name="Général",
            value="/aide\n/ping\n/paiement\n/invites\n/userinfo\n/stats_membre\n/fiche_joueur\n/spin_stock",
            inline=False,
        )
        embed.add_field(
            name="Messages",
            value="/dire\n/envoyer_message\n/annonce\n/annonce_create\n/sondage",
            inline=False,
        )
        embed.add_field(
            name="Modération",
            value="/clear\n/kick\n/ban\n/unban\n/mute\n/unmute\n/warn\n/list_warn",
            inline=False,
        )
        embed.add_field(
            name="Tickets",
            value="/envoyer_panel_tickets\n/envoyer_panel_tickets_custom\n/add_membre_ticket\n/remove_membre_ticket",
            inline=False,
        )
        embed.add_field(
            name="Giveaways",
            value="/giveaway_create\n/giveaway_list\n/giveaway_end\n/giveaway_reroll",
            inline=False,
        )
        embed.add_field(
            name="Gacha",
            value="/basic\n/advanced\n/deluxe\n/gacha_taux\n/basic_add\n/advanced_add\n/deluxe_add\n/spin_remove\n/spin_log\n/note_add\n/note_remove",
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
                "/config_salon_logs\n"
                "/config_role_regles\n"
                "/envoyer_reglement\n"
                "/envoyer_message_regles"
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="resync_commandes", description="Force la resynchronisation des slash commands")
    @app_commands.default_permissions(manage_guild=True)
    async def resync_commandes(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        await self.bot.sync_commands_once(force=True)
        await interaction.followup.send("Commandes resynchronisées sur tous les serveurs du bot.", ephemeral=True)

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

    @app_commands.command(name="stats_membre", description="Affiche les stats d'un membre")
    @app_commands.describe(membre="Le membre à afficher")
    async def stats_membre(
        self,
        interaction: discord.Interaction,
        membre: discord.Member | None = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return

        member = membre or interaction.user
        guild_id = interaction.guild.id
        warnings_count = len(self.bot.get_warning_store(guild_id).get(str(member.id), []))
        invites_count = self.bot.get_invite_count(guild_id, member.id)
        open_tickets = len(self.bot.get_open_tickets_for_user(guild_id, member.id))
        archived_tickets = sum(
            1
            for ticket in self.bot.get_ticket_store(guild_id)["channels"].values()
            if ticket["owner_id"] == member.id and ticket["status"] == "archived"
        )
        giveaways_won = sum(
            1
            for giveaway in self.bot.get_giveaway_store(guild_id).values()
            if member.id in giveaway.get("winners", [])
        )
        inventory = self.bot.get_gacha_inventory(member.id)
        notes_count = len(self.bot.get_member_notes(member.id))

        embed = discord.Embed(
            title=f"Stats de {member.display_name}",
            color=discord.Color.blurple(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Invitations", value=str(invites_count), inline=True)
        embed.add_field(name="Warns", value=str(warnings_count), inline=True)
        embed.add_field(name="Chances giveaway", value=f"x{get_member_giveaway_weight(member):g}", inline=True)
        embed.add_field(name="Tickets ouverts", value=str(open_tickets), inline=True)
        embed.add_field(name="Tickets archivés", value=str(archived_tickets), inline=True)
        embed.add_field(name="Giveaways gagnés", value=str(giveaways_won), inline=True)
        embed.add_field(
            name="Spins",
            value=f"B:{inventory.get('basic', 0)} | A:{inventory.get('advanced', 0)} | D:{inventory.get('deluxe', 0)}",
            inline=False,
        )
        embed.add_field(name="Notes staff", value=str(notes_count), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="fiche_joueur", description="Affiche toutes les infos utiles d'un joueur")
    @app_commands.describe(membre="Le membre à afficher")
    @app_commands.default_permissions(manage_guild=True)
    async def fiche_joueur(
        self,
        interaction: discord.Interaction,
        membre: discord.Member,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return

        guild_id = interaction.guild.id
        invites_count = self.bot.get_invite_count(guild_id, membre.id)
        warnings_count = len(self.bot.get_warning_store(guild_id).get(str(membre.id), []))
        inventory = self.bot.get_gacha_inventory(membre.id)
        notes = self.bot.get_member_notes(membre.id)
        grant_history = self.bot.get_member_grant_history(membre.id)[-5:]
        spin_history = [
            entry for entry in self.bot.gacha_data.get("history", []) if int(entry.get("user_id", 0)) == membre.id
        ][-5:]

        embed = discord.Embed(
            title=f"Fiche joueur • {membre.display_name}",
            color=discord.Color.gold(),
        )
        embed.set_thumbnail(url=membre.display_avatar.url)
        embed.add_field(name="Invitations", value=str(invites_count), inline=True)
        embed.add_field(name="Warns", value=str(warnings_count), inline=True)
        embed.add_field(name="Giveaway", value=f"x{get_member_giveaway_weight(membre):g}", inline=True)
        embed.add_field(name="Basic Spins", value=str(inventory.get("basic", 0)), inline=True)
        embed.add_field(name="Advanced Spins", value=str(inventory.get("advanced", 0)), inline=True)
        embed.add_field(name="Deluxe Spins", value=str(inventory.get("deluxe", 0)), inline=True)

        if grant_history:
            grant_lines = []
            for entry in reversed(grant_history):
                action = "+" if entry.get("action") == "add" else "-"
                reason = entry.get("reason") or "Aucune raison"
                grant_lines.append(
                    f"• {action}{entry.get('quantity', 0)} {str(entry.get('spin_type', '')).title()} par {entry.get('actor_name', 'Staff')} — {reason}"
                )
            embed.add_field(name="Historique spins accordés", value="\n".join(grant_lines), inline=False)

        if spin_history:
            spin_lines = []
            for entry in reversed(spin_history):
                spin_lines.append(
                    f"• #{entry['claim_number']} — {entry['spin_type'].title()} — {entry['reward']} ({entry['rarity']})"
                )
            embed.add_field(name="Derniers spins utilisés", value="\n".join(spin_lines), inline=False)

        if notes:
            note_lines = []
            start_index = max(1, len(notes) - 4)
            for index, note in enumerate(reversed(notes[-5:]), start=start_index):
                note_lines.append(f"• [{index}] {note.get('content', '')} — {note.get('author_name', 'Staff')}")
            embed.add_field(name="Notes staff", value="\n".join(note_lines), inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

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

    @app_commands.command(name="sondage", description="Crée un sondage rapide")
    @app_commands.describe(
        question="Question du sondage",
        option1="Première option",
        option2="Deuxième option",
        option3="Troisième option (optionnel)",
        option4="Quatrième option (optionnel)",
    )
    @app_commands.default_permissions(manage_messages=True)
    async def sondage(
        self,
        interaction: discord.Interaction,
        question: str,
        option1: str,
        option2: str,
        option3: str | None = None,
        option4: str | None = None,
    ) -> None:
        options = [option1, option2]
        if option3:
            options.append(option3)
        if option4:
            options.append(option4)

        emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"]
        lines = [f"{emoji} {option}" for emoji, option in zip(emojis, options)]
        embed = discord.Embed(
            title="📊 Sondage",
            description=f"**{question}**\n\n" + "\n".join(lines),
            color=discord.Color.blurple(),
        )
        embed.set_footer(text=f"Sondage créé par {interaction.user}")
        if interaction.channel is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        poll_message = await interaction.channel.send(embed=embed)
        for emoji in emojis[: len(options)]:
            await poll_message.add_reaction(emoji)
        await interaction.followup.send("Sondage envoyé.", ephemeral=True)

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

    @app_commands.command(name="annonce_create", description="Ouvre une fenêtre propre pour créer une annonce")
    @app_commands.describe(salon="Salon cible")
    @app_commands.default_permissions(manage_messages=True)
    async def annonce_create(
        self,
        interaction: discord.Interaction,
        salon: discord.TextChannel,
    ) -> None:
        await interaction.response.send_modal(AnnouncementModal(self.bot, salon))
