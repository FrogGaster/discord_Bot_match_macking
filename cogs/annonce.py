"""Cog для команды /annonce и записи на страны."""

import logging

import discord

log = logging.getLogger("annonce")
from discord import app_commands
from discord.ext import commands

from data import storage
from presets.countries import PRESETS


def build_message_text(
    date_time: str,
    mod_name: str,
    preset: dict,
    signups: dict[str, list[dict]],
    reserve: list[dict],
    stopped: bool = False,
    ping_everyone: bool = False,
) -> str:
    prefix = "@everyone " if ping_everyone else ""
    lines = [
        f"{prefix}{date_time} будет проводиться игра в моде **{mod_name}**.",
        "",
    ]
    faction_emojis = {
        "Центральные державы": "🇩🇪",
        "Антанта": "🇫🇷",
        "Ось": "🇩🇪",
        "Союзники": "🇬🇧",
        "Другие": "🌍",
        "Рейхспакт": "🇩🇪",
        "Энтанта": "🇫🇷",
        "Интернационал": "☭",
        "Малые страны": "🌍",
        "Эквестрия": "🐴",
        "Грифус": "🦅",
        "НКР": "⭐",
        "Легион": "⚔",
        "Лига Наций": "🏛",
        "Реваншисты": "🔥",
    }
    idx = 0
    for faction, countries in preset.items():
        emoji = faction_emojis.get(faction, "•")
        lines.append(f"{emoji} **{faction}:**")
        for item in countries:
            name = item["name"] if isinstance(item, dict) else item[0]
            players = signups.get(str(idx), [])
            names_str = ", ".join(f"<@{p['id']}>" for p in players) if players else ""
            suffix = f" — {names_str}" if names_str else " — "
            lines.append(f"• {name}{suffix}")
            idx += 1
        lines.append("")
    if reserve:
        lines.append("**Резерв:** " + ", ".join(f"<@{p['id']}>" for p in reserve))
        lines.append("")
    status = "⛔ Запись закрыта" if stopped else "**КАТКА ПОД ЗАПИСЬ!** Запись по кнопкам ниже 👇"
    lines.append(status)
    return "\n".join(lines).strip()


class SignupView(discord.ui.View):
    def __init__(self, message_id: int, game: dict, *, timeout: None = None):
        super().__init__(timeout=timeout)
        self.message_id = message_id
        self.game = game
        self._add_buttons()

    def _add_buttons(self) -> None:
        self.clear_items()
        stopped = self.game.get("stopped", False)
        countries = self.game["countries"]
        signups = self.game["signups"]
        if len(countries) <= 20:
            self._add_country_buttons(countries, signups, stopped)
        else:
            self._add_country_select(countries, signups, stopped)
        self._add_extra_buttons(stopped)

    def _add_country_buttons(self, countries, signups, stopped):
        for i, country in enumerate(countries):
            players = signups.get(str(i), [])
            filled = len(players)
            slots = country["slots"]
            short_name = country["name"][:70] if len(country["name"]) > 70 else country["name"]
            label = f"{short_name} ({filled}/{slots})"
            if len(label) > 80:
                label = country["name"][:55] + f".. ({filled}/{slots})"
            custom_id = f"signup:{self.message_id}:{i}"
            btn = discord.ui.Button(
                label=label,
                custom_id=custom_id,
                style=discord.ButtonStyle.primary if filled < slots else discord.ButtonStyle.success,
                disabled=stopped,
            )
            btn.callback = self._make_callback(i)
            self.add_item(btn)

    def _add_country_select(self, countries, signups, stopped):
        options = []
        for i, country in enumerate(countries[:25]):
            players = signups.get(str(i), [])
            filled, slots = len(players), country["slots"]
            label = f"{country['name'][:70]} ({filled}/{slots})"[:100]
            options.append(discord.SelectOption(label=label, value=str(i)))
        sel = discord.ui.Select(
            placeholder="Выберите страну",
            options=options,
            disabled=stopped,
            custom_id=f"country_select:{self.message_id}",
        )
        sel.callback = self._select_callback
        self.add_item(sel)

    def _add_extra_buttons(self, stopped):
        if not stopped and len(self.children) < 24:
            reserve_btn = discord.ui.Button(
                label="В резерв",
                custom_id=f"reserve:{self.message_id}",
                style=discord.ButtonStyle.secondary,
            )
            reserve_btn.callback = self._reserve_callback
            self.add_item(reserve_btn)
        if not stopped:
            unsub_btn = discord.ui.Button(label="Отписаться", custom_id=f"unsub:{self.message_id}", style=discord.ButtonStyle.danger)
            unsub_btn.callback = self._unsub_callback
            self.add_item(unsub_btn)
        if not stopped:
            rem_btn = discord.ui.Button(label="🔔 Напомнить", custom_id=f"remind:{self.message_id}", style=discord.ButtonStyle.secondary)
            rem_btn.callback = self._remind_callback
            self.add_item(rem_btn)

    def _make_callback(self, country_index: int):
        async def cb(interaction: discord.Interaction):
            await handle_signup(interaction, self.message_id, country_index)
        return cb

    async def _select_callback(self, interaction: discord.Interaction):
        try:
            idx = int(interaction.data["values"][0])
            await handle_signup(interaction, self.message_id, idx)
        except (ValueError, IndexError):
            pass

    async def _reserve_callback(self, interaction: discord.Interaction):
        await handle_reserve(interaction, self.message_id)

    async def _unsub_callback(self, interaction: discord.Interaction):
        await handle_unsubscribe(interaction, self.message_id)

    async def _remind_callback(self, interaction: discord.Interaction):
        await handle_remind(interaction, self.message_id)

    @classmethod
    def from_game(cls, message_id: int) -> "SignupView | None":
        game = storage.get_game(message_id)
        if not game:
            return None
        return cls(message_id=message_id, game=game)


async def handle_signup(interaction: discord.Interaction, message_id: int, country_index: int) -> None:
    await interaction.response.defer(ephemeral=True)
    game = storage.get_game(message_id)
    if not game:
        return
    success, _ = storage.toggle_signup(
        message_id, country_index,
        interaction.user.id, interaction.user.display_name,
    )
    if not success:
        return
    await _update_message_and_roles(interaction, message_id, game)
    await _log_signup(interaction, message_id, game, country_index, "country")


async def handle_remind(interaction: discord.Interaction, message_id: int) -> None:
    await interaction.response.defer(ephemeral=True)
    game = storage.get_game(message_id)
    if not game or not interaction.guild:
        return
    users = set()
    for players in game.get("signups", {}).values():
        for p in players:
            users.add(p["id"])
    for p in game.get("reserve", []):
        users.add(p["id"])
    if not users:
        return
    pings = " ".join(f"<@{uid}>" for uid in users)
    try:
        ch = interaction.client.get_channel(game["channel_id"])
        if ch:
            thread_id = game.get("thread_id")
            target = interaction.client.get_channel(thread_id) if thread_id else ch
            if target:
                await target.send(f"⏰ Напоминание: игра через 30 минут!\n{pings}")
    except Exception:
        pass


async def handle_unsubscribe(interaction: discord.Interaction, message_id: int) -> None:
    """Снять запись со страны или из резерва."""
    await interaction.response.defer(ephemeral=True)
    game = storage.get_game(message_id)
    if not game:
        return
    success, _ = storage.remove_signup_anywhere(message_id, interaction.user.id, interaction.user.display_name)
    if not success:
        return
    role_id = game.get("role_id")
    if role_id and interaction.guild and interaction.user:
        try:
            role = interaction.guild.get_role(role_id)
            if role:
                await interaction.user.remove_roles(role)
        except Exception:
            pass
    game = storage.get_game(message_id)
    await _update_message(interaction.client, message_id, game)


async def handle_reserve(interaction: discord.Interaction, message_id: int) -> None:
    await interaction.response.defer(ephemeral=True)
    game = storage.get_game(message_id)
    if not game:
        return
    success, _ = storage.toggle_reserve(message_id, interaction.user.id, interaction.user.display_name)
    if not success:
        return
    game = storage.get_game(message_id)
    await _update_message(interaction.client, message_id, game)


async def _update_message_and_roles(
    interaction: discord.Interaction, message_id: int, game: dict,
) -> None:
    game = storage.get_game(message_id)
    if not game:
        return
    role_id = game.get("role_id")
    if role_id and interaction.guild:
        try:
            role = interaction.guild.get_role(role_id)
            if role and interaction.user:
                await interaction.user.add_roles(role)
        except Exception:
            pass
    await _update_message(interaction.client, message_id, game)


async def _update_message(bot, message_id: int, game: dict) -> None:
    preset = game.get("preset")
    if not preset:
        preset = {"Другие": game["countries"]}
    text = build_message_text(
        game["date_time"], game["mod_name"], preset,
        game["signups"], game.get("reserve", []), game.get("stopped", False),
        game.get("ping_everyone", False),
    )
    view = SignupView.from_game(message_id)
    try:
        channel = bot.get_channel(game["channel_id"])
        if channel:
            msg = await channel.fetch_message(message_id)
            await msg.edit(content=text, view=view)
    except Exception:
        pass


async def _log_signup(
    interaction: discord.Interaction, message_id: int, game: dict,
    country_index: int, signup_type: str,
) -> None:
    config = storage.get_guild_config(game["guild_id"])
    log_channel_id = config.get("log_channel_id")
    if not log_channel_id or not interaction.guild:
        return
    channel = interaction.guild.get_channel(log_channel_id)
    if not channel:
        return
    country = game["countries"][country_index]["name"]
    try:
        await channel.send(
            f"📝 {interaction.user.mention} записался на **{country}** "
            f"(игра: {game['mod_name']}, {game['date_time']})"
        )
    except Exception:
        pass


def _get_country_names(preset: dict) -> list[tuple[str, int]]:
    """Возвращает [(название, индекс), ...] для всех стран."""
    result = []
    idx = 0
    for faction_countries in preset.values():
        for item in faction_countries:
            name = item["name"] if isinstance(item, dict) else item[0]
            result.append((name, idx))
            idx += 1
    return result


class SlotsConfigView(discord.ui.View):
    """Выбор слотов для каждой страны через выпадающие списки."""

    def __init__(self, preset_id: str, preset: dict, mod_name: str, date_time: str, create_thread: bool, reminder_mins: int | None, guild_id: int, channel_id: int, ping_everyone: bool):
        super().__init__(timeout=300)
        self.preset_id = preset_id
        self.preset = preset
        self.mod_name = mod_name
        self.date_time = date_time
        self.create_thread = create_thread
        self.reminder_mins = reminder_mins
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.ping_everyone = ping_everyone
        countries = _get_country_names(preset)
        self.slots = {idx: 1 for _, idx in countries}
        _sl = lambda n: "слотов" if n >= 5 else ("слота" if n >= 2 else "слот")
        slot_opts = [discord.SelectOption(label=f"{n} {_sl(n)}", value=str(n)) for n in range(1, 6)]
        for i, (name, idx) in enumerate(countries[:25]):
            short = name[:25] + ".." if len(name) > 25 else name
            sel = discord.ui.Select(
                placeholder=f"{short} — слотов",
                options=slot_opts,
                custom_id=f"slots:{idx}",
            )
            sel.callback = self._make_slot_callback(idx)
            self.add_item(sel)
        btn = discord.ui.Button(label="Создать анонс", style=discord.ButtonStyle.success, custom_id="create_annonce")
        btn.callback = self._on_create
        self.add_item(btn)

    def _make_slot_callback(self, idx: int):
        async def cb(interaction: discord.Interaction):
            val = int(interaction.data["values"][0])
            self.slots[idx] = val
            await interaction.response.defer(ephemeral=True)
        return cb

    async def _on_create(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        countries = _get_country_names(self.preset)
        slots_list = [self.slots.get(idx, 1) for _, idx in countries]
        total = len(countries)
        text = build_message_text(
            self.date_time, self.mod_name, self.preset,
            {str(i): [] for i in range(total)}, [], False, self.ping_everyone,
        )
        allowed = discord.AllowedMentions(everyone=self.ping_everyone) if self.ping_everyone else discord.AllowedMentions(everyone=False)
        channel = interaction.client.get_channel(self.channel_id)
        msg = await channel.send(content=text, allowed_mentions=allowed)
        thread_id = None
        if self.create_thread:
            try:
                thread = await msg.create_thread(name=f"Обсуждение: {self.mod_name} — {self.date_time}", auto_archive_duration=10080)
                thread_id = thread.id
            except Exception as e:
                log.warning(f"Ошибка создания ветки: {e}")
        config = storage.get_guild_config(self.guild_id)
        role_id = config.get("game_role_id")
        storage.save_game(
            message_id=msg.id, channel_id=self.channel_id, guild_id=self.guild_id,
            date_time=self.date_time, mod_name=self.mod_name, preset=self.preset,
            slots_per_country=slots_list, thread_id=thread_id, role_id=role_id, ping_everyone=self.ping_everyone,
        )
        if self.reminder_mins:
            storage.update_game(msg.id, reminder_minutes=self.reminder_mins)
        view = SignupView.from_game(msg.id)
        await msg.edit(view=view)
        await interaction.followup.send("Анонс создан!", ephemeral=True)
        self.stop()
        for item in self.children:
            item.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass


class AnnonceModal(discord.ui.Modal, title="Создание анонса"):
    date_time = discord.ui.TextInput(label="Дата и время", placeholder="8 марта в 22:30 по МСК", max_length=100, required=True)
    mod_name = discord.ui.TextInput(label="Название мода", placeholder="The Great War Redux", max_length=100, required=True)
    create_thread = discord.ui.TextInput(label="Ветка под анонсом", placeholder="да", required=False, max_length=3)
    reminder = discord.ui.TextInput(label="Напомнить за N минут", placeholder="30", required=False, max_length=5)

    def __init__(self, preset_id: str, mod_default: str = ""):
        super().__init__()
        self.preset_id = preset_id
        if mod_default:
            self.mod_name.placeholder = mod_default[:100]

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if self.preset_id.startswith("custom:"):
            name = self.preset_id[7:]
            custom = storage.get_custom_presets(interaction.guild.id) if interaction.guild else {}
            if name not in custom:
                await interaction.response.send_message("Пресет не найден.", ephemeral=True)
                return
            data = custom[name]
            mod_default, preset = data["mod_name"], data["preset"]
            if preset and next(iter(preset.values()), []):
                first = next(iter(preset.values()))[0]
                if isinstance(first, dict):
                    preset = {k: [(c["name"], c.get("slots", 1)) for c in v] for k, v in preset.items()}
        else:
            preset_data = PRESETS.get(self.preset_id.lower())
            if not preset_data:
                await interaction.response.send_message("Ошибка: пресет не найден.", ephemeral=True)
                return
            mod_default, preset = preset_data
        mod_display = self.mod_name.value.strip() or mod_default
        date_time = self.date_time.value.strip()
        create_raw = self.create_thread.value.strip().lower()
        create = create_raw in ("да", "yes", "1", "д")
        reminder_mins = None
        rm = self.reminder.value.strip()
        if rm.isdigit():
            reminder_mins = min(120, max(5, int(rm)))
        guild_id = interaction.guild.id if interaction.guild else 0
        channel_id = interaction.channel_id or 0
        ping_everyone = bool(interaction.user.guild_permissions.administrator)

        log.info(f"[{interaction.guild.name if interaction.guild else 'DM'}] Создание анонса: переход к настройке слотов")

        slots_view = SlotsConfigView(
            preset_id=self.preset_id, preset=preset, mod_name=mod_display, date_time=date_time,
            create_thread=create, reminder_mins=reminder_mins, guild_id=guild_id, channel_id=channel_id, ping_everyone=ping_everyone,
        )
        await interaction.response.send_message(
            "**Настройте слоты для каждой страны** (по умолчанию 1). Затем нажмите **Создать анонс**:",
            view=slots_view, ephemeral=True,
        )


class OpenModalView(discord.ui.View):
    def __init__(self, preset_id: str, mod_default: str = ""):
        super().__init__(timeout=300)
        self.preset_id = preset_id
        self.mod_default = mod_default

    @discord.ui.button(label="Ввести дату и мод", style=discord.ButtonStyle.primary)
    async def open_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = AnnonceModal(preset_id=self.preset_id, mod_default=self.mod_default)
        await interaction.response.send_modal(modal)


class PresetSelect(discord.ui.Select):
    def __init__(self, custom_presets: dict = None):
        options = [
            discord.SelectOption(label=pid.upper(), value=pid, description=data[0][:50])
            for pid, data in PRESETS.items()
        ]
        for name, data in (custom_presets or {}).items():
            options.append(discord.SelectOption(label=f"⭐ {name}", value=f"custom:{name}", description=data.get("mod_name", "")))
        super().__init__(placeholder="Выберите пресет", min_values=1, max_values=1, options=options[:25])

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            preset_id = self.values[0]
            if preset_id.startswith("custom:"):
                name = preset_id[7:]
                presets = storage.get_custom_presets(interaction.guild.id)
                if name not in presets:
                    await interaction.response.send_message("Пресет не найден.", ephemeral=True)
                    return
                data = presets[name]
                preset = data["preset"]
                mod_name = data["mod_name"]
            else:
                preset_data = PRESETS.get(preset_id.lower())
                if not preset_data:
                    await interaction.response.send_message("Ошибка: пресет не найден.", ephemeral=True)
                    return
                mod_name, preset = preset_data

            lines = ["**Порядок стран:**"]
            idx = 1
            for faction, countries in preset.items():
                for item in countries:
                    name = item["name"] if isinstance(item, dict) else item[0]
                    lines.append(f"{idx}. {name}")
                    idx += 1
            view = OpenModalView(preset_id=preset_id, mod_default=mod_name)
            await interaction.response.send_message(
                "\n".join(lines) + "\n\nНажмите кнопку для ввода даты и мода:",
                view=view, ephemeral=True,
            )
        except Exception as e:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"Ошибка: {e}", ephemeral=True)


class PresetSelectView(discord.ui.View):
    def __init__(self, guild_id: int = None):
        super().__init__(timeout=120)
        custom = storage.get_custom_presets(guild_id) if guild_id else {}
        self.add_item(PresetSelect(custom))


class AnnonceCog(commands.Cog):
    @app_commands.command(name="annonce", description="Создать анонс игры")
    async def annonce(self, interaction: discord.Interaction):
        view = PresetSelectView(interaction.guild_id)
        await interaction.response.send_message("Выберите пресет стран:", view=view, ephemeral=False)

    @app_commands.command(name="annonce_slots", description="Изменить слоты для страны")
    @app_commands.describe(message_id="ID анонса", country_index="Номер страны (1,2,3...)", slots="Новых слотов (1-5)")
    @app_commands.default_permissions(administrator=True)
    async def annonce_slots(self, interaction: discord.Interaction, message_id: str, country_index: int, slots: int):
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message("Неверный ID.", ephemeral=True)
            return
        idx = country_index - 1
        if idx < 0:
            await interaction.response.send_message("Индекс от 1.", ephemeral=True)
            return
        new_slots = min(5, max(1, slots))
        log.info(f"[{interaction.guild.name}] annonce_slots: msg={mid} country={country_index} new_slots={new_slots}")
        if storage.update_slots(mid, idx, new_slots):
            game = storage.get_game(mid)
            preset = game.get("preset", {"Другие": game["countries"]})
            text = build_message_text(
                game["date_time"], game["mod_name"], preset,
                game["signups"], game.get("reserve", []), game.get("stopped", False),
                game.get("ping_everyone", False),
            )
            view = SignupView.from_game(mid)
            try:
                ch = interaction.client.get_channel(game["channel_id"])
                if ch:
                    msg = await ch.fetch_message(mid)
                    await msg.edit(content=text, view=view)
            except Exception:
                pass
            await interaction.response.send_message("Слоты обновлены.", ephemeral=True)
        else:
            log.warning(f"[{interaction.guild.name}] annonce_slots: не удалось (msg={mid})")
            await interaction.response.send_message("Ошибка (страна занята или не найдена).", ephemeral=True)

    @app_commands.command(name="annonce_stop", description="Закрыть запись на игру")
    @app_commands.describe(message_id="ID сообщения с анонсом (правый клик по сообщению — Копировать ID)")
    async def annonce_stop(self, interaction: discord.Interaction, message_id: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Нужны права администратора.", ephemeral=True)
            return
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message("Неверный ID сообщения.", ephemeral=True)
            return
        if not storage.stop_game(mid):
            await interaction.response.send_message("Игра не найдена.", ephemeral=True)
            return
        game = storage.get_game(mid)
        if game:
            preset = game.get("preset", {"Другие": game["countries"]})
            text = build_message_text(
                game["date_time"], game["mod_name"], preset,
                game["signups"], game.get("reserve", []), True,
                game.get("ping_everyone", False),
            )
            view = SignupView.from_game(mid)
            try:
                ch = interaction.client.get_channel(game["channel_id"])
                if ch:
                    msg = await ch.fetch_message(mid)
                    await msg.edit(content=text, view=view)
            except Exception:
                pass
        await interaction.response.send_message("Запись закрыта.", ephemeral=True)

    @app_commands.command(name="annonce_delete", description="Удалить анонс")
    @app_commands.describe(message_id="ID сообщения с анонсом")
    async def annonce_delete(self, interaction: discord.Interaction, message_id: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Нужны права администратора.", ephemeral=True)
            return
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message("Неверный ID.", ephemeral=True)
            return
        game = storage.get_game(mid)
        if not game:
            await interaction.response.send_message("Игра не найдена.", ephemeral=True)
            return
        try:
            ch = interaction.client.get_channel(game["channel_id"])
            if ch:
                msg = await ch.fetch_message(mid)
                await msg.delete()
        except Exception:
            pass
        storage.delete_game(mid)
        await interaction.response.send_message("Анонс удалён.", ephemeral=True)

    @app_commands.command(name="annonce_move", description="Перенести анонс в другой канал")
    @app_commands.describe(message_id="ID сообщения", channel="Целевой канал")
    async def annonce_move(self, interaction: discord.Interaction, message_id: str, channel: discord.TextChannel):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Нужны права администратора.", ephemeral=True)
            return
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message("Неверный ID.", ephemeral=True)
            return
        game = storage.get_game(mid)
        if not game:
            await interaction.response.send_message("Игра не найдена.", ephemeral=True)
            return
        try:
            old_ch = interaction.client.get_channel(game["channel_id"])
            if old_ch:
                msg = await old_ch.fetch_message(mid)
                preset = game.get("preset", {"Другие": game["countries"]})
                text = build_message_text(
                    game["date_time"], game["mod_name"], preset,
                    game["signups"], game.get("reserve", []), game.get("stopped", False),
                    game.get("ping_everyone", False),
                )
                new_msg = await channel.send(content=text)
                storage.delete_game(mid)
                storage.save_game(
                    message_id=new_msg.id, channel_id=channel.id, guild_id=interaction.guild_id,
                    date_time=game["date_time"], mod_name=game["mod_name"], preset=game["preset"],
                    slots_per_country=[c["slots"] for c in game["countries"]],
                    thread_id=game.get("thread_id"), role_id=game.get("role_id"),
                    signups=game.get("signups"), reserve=game.get("reserve", []), stopped=game.get("stopped", False),
                    ping_everyone=game.get("ping_everyone", False),
                )
                view = SignupView.from_game(new_msg.id)
                await new_msg.edit(view=view)
                await msg.delete()
                await interaction.response.send_message(f"Анонс перенесён в {channel.mention}.", ephemeral=True)
            else:
                await interaction.response.send_message("Канал не найден.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Ошибка: {e}", ephemeral=True)

    @app_commands.command(name="мои_записи", description="Показать ваши записи на игры")
    async def my_signups(self, interaction: discord.Interaction):
        games = storage.get_games_for_user(interaction.guild_id, interaction.user.id)
        if not games:
            await interaction.response.send_message("Вы никуда не записаны.", ephemeral=True)
            return
        lines = []
        for g in games:
            gm = g["game"]
            link = f"https://discord.com/channels/{gm['guild_id']}/{gm['channel_id']}/{g['message_id']}"
            t = "📋 резерв" if g["type"] == "reserve" else "🎮 страна"
            for idx, players in gm.get("signups", {}).items():
                if any(p["id"] == interaction.user.id for p in players):
                    country = gm["countries"][int(idx)]["name"]
                    lines.append(f"• {gm['mod_name']} ({gm['date_time']}) — **{country}** [{t}]({link})")
                    break
            else:
                lines.append(f"• {gm['mod_name']} ({gm['date_time']}) — резерв [{t}]({link})")
        await interaction.response.send_message("**Ваши записи:**\n" + "\n".join(lines), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AnnonceCog(bot))
