"""Конфиг сервера: канал логов, роль игроков, кастомные пресеты."""

import discord
from discord import app_commands
from discord.ext import commands

from data import storage


class ConfigCog(commands.Cog):
    @app_commands.command(name="config_log", description="Канал для лога записей")
    @app_commands.describe(channel="Канал для логов")
    @app_commands.default_permissions(administrator=True)
    async def config_log(self, interaction: discord.Interaction, channel: discord.TextChannel):
        storage.set_guild_config(interaction.guild_id, log_channel_id=channel.id)
        await interaction.response.send_message(f"Лог записей: {channel.mention}", ephemeral=True)

    @app_commands.command(name="config_role", description="Роль для записавшихся")
    @app_commands.describe(role="Роль")
    @app_commands.default_permissions(administrator=True)
    async def config_role(self, interaction: discord.Interaction, role: discord.Role):
        storage.set_guild_config(interaction.guild_id, game_role_id=role.id)
        await interaction.response.send_message(f"Роль для игроков: {role.mention}", ephemeral=True)

    @app_commands.command(name="preset_save", description="Сохранить свой пресет")
    @app_commands.describe(
        name="Название пресета",
        countries="Страны через запятую (напр: Ось: Германия, Италия | Союзники: СССР, США)",
        mod_name="Название мода",
    )
    @app_commands.default_permissions(administrator=True)
    async def preset_save(self, interaction: discord.Interaction, name: str, countries: str, mod_name: str):
        try:
            preset = {}
            for block in countries.split("|"):
                block = block.strip()
                if ":" in block:
                    faction, rest = block.split(":", 1)
                    faction = faction.strip()
                    countries_list = [(c.strip(), 1) for c in rest.split(",") if c.strip()]
                    preset[faction] = countries_list
                else:
                    lst = [(c.strip(), 1) for c in block.split(",") if c.strip()]
                    if lst:
                        preset.setdefault("Другие", []).extend(lst)
            if not preset:
                await interaction.response.send_message("Неверный формат.", ephemeral=True)
                return
            storage.save_custom_preset(interaction.guild_id, name, preset, mod_name)
            await interaction.response.send_message(f"Пресет «{name}» сохранён.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Ошибка: {e}", ephemeral=True)

    @app_commands.command(name="stats", description="Статистика записей")
    async def stats(self, interaction: discord.Interaction):
        items = storage.get_stats(interaction.guild_id)
        if not items:
            await interaction.response.send_message("Пока нет данных.", ephemeral=True)
            return
        lines = [f"**Топ записей:**"] + [f"{i+1}. {name} — {cnt}" for i, (_, name, cnt) in enumerate(items[:10])]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ConfigCog(bot))
