from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any, Literal

import discord
from discord import app_commands
from discord.ext import commands

from yishi_bot.ticketing import build_custom_ticket_panel_embed, build_ticket_panel_embed
from yishi_bot.constants import (
    ADMIN_ROLE_NAME,
    AUTO_ARCHIVE_CATEGORY_NAME,
    AUTO_ARCHIVE_ROLE_NAME,
    AUTO_GACHA_LOGS_CHANNEL_NAME,
    AUTO_GACHA_SPIN_CHANNEL_NAME,
    AUTO_GACHA_WINNER_CHANNEL_NAME,
    AUTO_LOGS_CHANNEL_NAME,
    AUTO_STAFF_ROLE_NAME,
    AUTO_TICKET_CATEGORY_NAME,
    AUTO_TRANSCRIPT_CHANNEL_NAME,
    FOUNDER_ROLE_NAME,
    FREE_ACCESS_ROLE_NAME,
    GACHA_REWARDS,
    GACHA_SPIN_TYPES,
    HELPER_ROLE_NAME,
    INVITE_ROLE_REQUIREMENTS,
    MEMBER_ROLE_NAME,
    MODERATOR_ROLE_NAME,
    PRESERVED_CLIENT_ROLE_ID,
    RESPONSABLE_ROLE_NAME,
    RULES_ACCEPT_TEXT,
    RULES_TEXT,
    TRIAL_MOD_ROLE_NAME,
    WELCOME_ADVANTAGES,
    WELCOME_CHECKLIST,
    XP_ROLE_BY_GRADE,
    XP_ROLE_NAMES,
)
from yishi_bot.helpers import can_moderate, parse_duration, split_long_message
from yishi_bot.views import AnnouncementModal, TicketPanelView

if TYPE_CHECKING:
    from yishi_bot.core import YishiBot


class ConfigurationCog(commands.Cog):
    def __init__(self, bot: YishiBot) -> None:
        self.bot = bot

    def can_manage_role(self, guild: discord.Guild, role: discord.Role) -> bool:
        me = guild.me
        if me is None:
            return False
        if role.is_default() or role.managed:
            return False
        return me.guild_permissions.manage_roles and me.top_role > role

    @app_commands.command(name="roles_rebuild", description="Supprime les rôles supprimables et recrée une hiérarchie propre")
    @app_commands.default_permissions(manage_guild=True)
    async def roles_rebuild(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild
        config = self.bot.get_guild_config(guild.id)

        preserved_role = guild.get_role(PRESERVED_CLIENT_ROLE_ID)
        deleted_roles: list[str] = []
        blocked_roles: list[str] = []

        for role in sorted(guild.roles, key=lambda item: item.position, reverse=True):
            if role.is_default() or role.managed or role.id == PRESERVED_CLIENT_ROLE_ID:
                continue
            if not self.can_manage_role(guild, role):
                blocked_roles.append(role.name)
                continue
            await role.delete(reason="Reconstruction complète des rôles")
            deleted_roles.append(role.name)

        role_specs: list[tuple[str, discord.Color]] = [
            (MEMBER_ROLE_NAME, discord.Color.from_rgb(52, 152, 219)),
            (FREE_ACCESS_ROLE_NAME, discord.Color.from_rgb(26, 188, 156)),
            ("\U0001f949\u30fbInviteur Bronze [5]", discord.Color.from_rgb(205, 127, 50)),
            ("\U0001f948\u30fbInviteur Silver [10]", discord.Color.from_rgb(192, 192, 192)),
            ("\U0001f947\u30fbInviteur Gold [15]", discord.Color.from_rgb(241, 196, 15)),
            ("\U0001f48e\u30fbInviteur Diamond [20]", discord.Color.from_rgb(85, 239, 196)),
            ("\u2728\u30fbNiveau Novice", discord.Color.from_rgb(149, 165, 166)),
            ("\U0001f31f\u30fbNiveau Actif", discord.Color.from_rgb(52, 152, 255)),
            ("\U0001f4a0\u30fbNiveau Confirm\u00e9", discord.Color.from_rgb(63, 217, 157)),
            ("\U0001f525\u30fbNiveau Elite", discord.Color.from_rgb(174, 82, 255)),
            ("\U0001f451\u30fbNiveau L\u00e9gende", discord.Color.from_rgb(255, 198, 64)),
            (HELPER_ROLE_NAME, discord.Color.from_rgb(46, 204, 113)),
            (TRIAL_MOD_ROLE_NAME, discord.Color.from_rgb(39, 174, 96)),
            (MODERATOR_ROLE_NAME, discord.Color.from_rgb(230, 126, 34)),
            (RESPONSABLE_ROLE_NAME, discord.Color.from_rgb(231, 76, 60)),
            (ADMIN_ROLE_NAME, discord.Color.from_rgb(155, 89, 182)),
            (AUTO_STAFF_ROLE_NAME, discord.Color.from_rgb(52, 73, 94)),
            (FOUNDER_ROLE_NAME, discord.Color.from_rgb(243, 156, 18)),
            (AUTO_ARCHIVE_ROLE_NAME, discord.Color.from_rgb(142, 68, 173)),
        ]

        created_roles: dict[str, discord.Role] = {}
        for role_name, color in role_specs:
            role = await guild.create_role(
                name=role_name,
                color=color,
                mentionable=False,
                reason="Reconstruction complète des rôles",
            )
            created_roles[role_name] = role

        ordered_roles = [created_roles[name] for name, _ in role_specs]
        positions = {role: index for index, role in enumerate(ordered_roles, start=1)}
        await guild.edit_role_positions(positions=positions)

        config["helper_role_id"] = created_roles[HELPER_ROLE_NAME].id
        config["trial_mod_role_id"] = created_roles[TRIAL_MOD_ROLE_NAME].id
        config["moderator_role_id"] = created_roles[MODERATOR_ROLE_NAME].id
        config["responsable_role_id"] = created_roles[RESPONSABLE_ROLE_NAME].id
        config["admin_role_id"] = created_roles[ADMIN_ROLE_NAME].id
        config["staff_role_id"] = created_roles[AUTO_STAFF_ROLE_NAME].id
        config["founder_role_id"] = created_roles[FOUNDER_ROLE_NAME].id
        config["archive_role_id"] = created_roles[AUTO_ARCHIVE_ROLE_NAME].id
        config["free_access_role_id"] = created_roles[FREE_ACCESS_ROLE_NAME].id
        self.bot.save_config()

        member_role = created_roles[MEMBER_ROLE_NAME]
        assigned_count = 0
        for member in guild.members:
            if member_role not in member.roles:
                await member.add_roles(member_role, reason="Attribution du rôle membre")
                assigned_count += 1

        await self.bot.sync_all_xp_roles(guild)
        await self.bot.sync_all_free_access_roles(guild)

        result_lines = [
            "Reconstruction des rôles terminée.",
            f"Rôle conservé : {preserved_role.name if preserved_role else PRESERVED_CLIENT_ROLE_ID}",
            f"Rôles supprimés : {len(deleted_roles)}",
            f"Nouveaux rôles créés : {len(created_roles)}",
            f"Membres ayant reçu {MEMBER_ROLE_NAME} : {assigned_count}",
        ]
        if blocked_roles:
            result_lines.append("")
            result_lines.append("Rôles non supprimés car au-dessus du bot :")
            result_lines.extend(blocked_roles)

        await interaction.followup.send("\n".join(result_lines), ephemeral=True)

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
        await self.bot.send_rules_text(interaction.guild, salon)
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
