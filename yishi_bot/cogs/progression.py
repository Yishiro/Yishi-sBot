from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

if TYPE_CHECKING:
    from yishi_bot.core import YishiBot


class ProgressionCog(commands.Cog):
    def __init__(self, bot: YishiBot) -> None:
        self.bot = bot

    @app_commands.command(name="level", description="Affiche la carte de niveau d'un membre")
    @app_commands.describe(membre="Membre à afficher")
    async def level(self, interaction: discord.Interaction, membre: discord.Member | None = None) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return
        target = membre or interaction.user
        if not isinstance(target, discord.Member):
            await interaction.response.send_message("Membre introuvable.", ephemeral=True)
            return

        await interaction.response.defer()
        image_path = self.bot.render_level_card(target)
        await interaction.followup.send(file=discord.File(image_path, filename="level-card.png"))

    @app_commands.command(name="voc_lock", description="Verrouille ton vocal temporaire")
    async def voc_lock(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return
        if not self.bot.can_manage_voice_feature(interaction.user, "lock"):
            await interaction.response.send_message("Ton grade ne te permet pas encore de verrouiller un vocal.", ephemeral=True)
            return
        await interaction.response.send_message(await self.bot.lock_temp_voice(interaction.user), ephemeral=True)

    @app_commands.command(name="voc_unlock", description="Déverrouille ton vocal temporaire")
    async def voc_unlock(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return
        if not self.bot.can_manage_voice_feature(interaction.user, "unlock"):
            await interaction.response.send_message("Ton grade ne te permet pas encore de déverrouiller un vocal.", ephemeral=True)
            return
        await interaction.response.send_message(await self.bot.unlock_temp_voice(interaction.user), ephemeral=True)

    @app_commands.command(name="voc_limit", description="Définit la limite de ton vocal temporaire")
    @app_commands.describe(nombre="Nombre maximum de personnes")
    async def voc_limit(self, interaction: discord.Interaction, nombre: app_commands.Range[int, 0, 99]) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return
        if not self.bot.can_manage_voice_feature(interaction.user, "limit"):
            await interaction.response.send_message("Ton grade ne te permet pas encore de gérer la limite du vocal.", ephemeral=True)
            return
        await interaction.response.send_message(await self.bot.set_temp_voice_limit(interaction.user, int(nombre)), ephemeral=True)

    @app_commands.command(name="voc_invite", description="Invite un membre dans ton vocal temporaire")
    @app_commands.describe(membre="Membre à inviter")
    async def voc_invite(self, interaction: discord.Interaction, membre: discord.Member) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return
        if not self.bot.can_manage_voice_feature(interaction.user, "invite"):
            await interaction.response.send_message("Ton grade ne te permet pas encore d'inviter un membre.", ephemeral=True)
            return
        await interaction.response.send_message(await self.bot.invite_to_temp_voice(interaction.user, membre), ephemeral=True)

    @app_commands.command(name="voc_kick", description="Expulse un membre de ton vocal temporaire")
    @app_commands.describe(membre="Membre à expulser")
    async def voc_kick(self, interaction: discord.Interaction, membre: discord.Member) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return
        if not self.bot.can_manage_voice_feature(interaction.user, "kick"):
            await interaction.response.send_message("Ton grade ne te permet pas encore d'expulser un membre.", ephemeral=True)
            return
        await interaction.response.send_message(await self.bot.kick_from_temp_voice(interaction.user, membre), ephemeral=True)

    @app_commands.command(name="voc_rename", description="Renomme ton vocal temporaire")
    @app_commands.describe(nom="Nouveau nom du vocal")
    async def voc_rename(self, interaction: discord.Interaction, nom: str) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return
        if not self.bot.can_manage_voice_feature(interaction.user, "rename"):
            await interaction.response.send_message("Ton grade ne te permet pas encore de renommer un vocal.", ephemeral=True)
            return
        await interaction.response.send_message(await self.bot.rename_temp_voice(interaction.user, nom), ephemeral=True)

    @app_commands.command(name="voc_transfer", description="Transfère la propriété de ton vocal temporaire")
    @app_commands.describe(membre="Nouveau propriétaire")
    async def voc_transfer(self, interaction: discord.Interaction, membre: discord.Member) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Commande indisponible ici.", ephemeral=True)
            return
        if not self.bot.can_manage_voice_feature(interaction.user, "transfer"):
            await interaction.response.send_message("Ton grade ne te permet pas encore de transférer un vocal.", ephemeral=True)
            return
        await interaction.response.send_message(await self.bot.transfer_temp_voice(interaction.user, membre), ephemeral=True)
