"""Точка входа Discord-бота для записи на игры HOI4."""

import logging
import os

import discord

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("bot")
from discord.ext import commands
from dotenv import load_dotenv

from cogs.annonce import SignupView
from data import storage

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready() -> None:
    log.info(f"Бот запущен: {bot.user} (ID: {bot.user.id})")
    for guild in bot.guilds:
        log.info(f"Сервер: {guild.name} (ID: {guild.id})")
        try:
            synced = await bot.tree.sync(guild=guild)
            log.info(f"  [{guild.name}] Синхронизировано {len(synced)} команд")
        except Exception as e:
            log.error(f"  [{guild.name}] Ошибка синхронизации: {e}")
    for message_id in storage.get_active_message_ids():
        view = SignupView.from_game(message_id)
        if view:
            bot.add_view(view)
            print(f"Восстановлен View для сообщения {message_id}")


async def main() -> None:
    async with bot:
        await bot.load_extension("cogs.annonce")
        await bot.load_extension("cogs.config")
        token = os.getenv("DISCORD_TOKEN")
        if not token:
            raise ValueError("Установите DISCORD_TOKEN в .env")
        await bot.start(token)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
