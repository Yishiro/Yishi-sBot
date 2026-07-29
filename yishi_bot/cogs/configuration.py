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
from yishi_bot.views import AnnouncementModal, TicketPanelView

if TYPE_CHECKING:
    from yishi_bot.core import YishiBot


class ConfigurationCog(commands.Cog):
    def __init__(self, bot: YishiBot) -> None:
        self.bot = bot

    @app_commands.command(name="setup", description="Reconstruit automatiquement le serveur Yishi's Shop")
    @app_commands.default_permissions(manage_guild=True)
    async def setup_server(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        summary = await self.bot.rebuild_server(interaction.guild)
        await interaction.followup.send(
            (
                "Configuration terminée.\n"
                f"Rôles préparés : {summary['roles']}\n"
                f"Salons conservés/créés : {summary['channels']}\n"
                f"Catégories préparées : {summary['categories']}"
            ),
            ephemeral=True,
        )

    @app_commands.command(name="free_post", description="Publie un compte free Netflix ou Crunchyroll")
    @app_commands.describe(service="Service concerné", contenu="Texte à publier dans le salon free")
    async def free_post(
        self,
        interaction: discord.Interaction,
        service: Literal["netflix", "crunchyroll"],
        contenu: str,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return
        if not self.bot.is_helper_member(interaction.user):  # type: ignore[arg-type]
            await interaction.response.send_message("Commande réservée au staff.", ephemeral=True)
            return

        config = self.bot.get_guild_config(interaction.guild.id)
        key = "free_netflix_channel_id" if service == "netflix" else "free_crunchyroll_channel_id"
        channel = interaction.guild.get_channel(config.get(key))
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("Le salon free correspondant n'est pas configuré.", ephemeral=True)
            return

        color = discord.Color.red() if service == "netflix" else discord.Color.orange()
        embed = discord.Embed(
            title=f"{service.title()} Free",
            description=contenu,
            color=color,
        )
        embed.set_footer(text=f"Publié par {interaction.user.display_name}")
        await channel.send(embed=embed)
        await interaction.response.send_message(f"Publication envoyée dans {channel.mention}.", ephemeral=True)

    @app_commands.command(name="free_status", description="Affiche le statut weekly free d'un membre")
    @app_commands.describe(membre="Membre à vérifier")
    async def free_status(self, interaction: discord.Interaction, membre: discord.Member | None = None) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return
        target = membre or interaction.user
        weekly = self.bot.get_weekly_invite_count(interaction.guild.id, target.id)
        total = self.bot.get_invite_count(interaction.guild.id, target.id)
        embed = discord.Embed(title=f"Statut free • {target.display_name}", color=discord.Color.teal())
        embed.add_field(name="Invitations semaine", value=str(weekly), inline=True)
        embed.add_field(name="Invitations totales", value=str(total), inline=True)
        embed.add_field(name="Accès free", value="Oui" if weekly >= 2 else "Non", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="free_refresh", description="Met à jour les accès free de tout le serveur")
    async def free_refresh(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return
        if not self.bot.is_helper_member(interaction.user):  # type: ignore[arg-type]
            await interaction.response.send_message("Commande réservée au staff.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await self.bot.sync_all_free_access_roles(interaction.guild)
        await interaction.followup.send("Accès free mis à jour.", ephemeral=True)

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

    @app_commands.command(name="config_salon_logs", description="Définit le salon des logs complets")
    @app_commands.describe(salon="Salon de logs")
    @app_commands.default_permissions(manage_guild=True)
    async def config_salon_logs(
        self,
        interaction: discord.Interaction,
        salon: discord.TextChannel,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return
        config = self.bot.get_guild_config(interaction.guild.id)
        config["logs_channel_id"] = salon.id
        self.bot.save_config()
        await self.bot.configure_logs_channel_permissions(interaction.guild, salon)
        await interaction.response.send_message(
            f"Le salon de logs est maintenant {salon.mention}.",
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
