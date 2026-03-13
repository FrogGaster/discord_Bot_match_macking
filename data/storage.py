"""Хранение данных игр и конфигов."""

import json
import logging

log = logging.getLogger("storage")
from pathlib import Path

DATA_DIR = Path(__file__).parent
GAMES_FILE = DATA_DIR / "games.json"
CONFIG_FILE = DATA_DIR / "guild_config.json"
STATS_FILE = DATA_DIR / "stats.json"
CUSTOM_PRESETS_FILE = DATA_DIR / "custom_presets.json"


def _load_json(path: Path, default: dict = None) -> dict:
    if not path.exists():
        return default if default is not None else {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_games() -> dict:
    return _load_json(GAMES_FILE, {})


def _save_games(data: dict) -> None:
    _save_json(GAMES_FILE, data)


def _parse_country(item) -> tuple[str, int]:
    """Извлекает (название, слоты) из tuple или dict."""
    if isinstance(item, dict):
        return item["name"], item.get("slots", 1)
    return item[0], item[1] if len(item) > 1 else 1


def save_game(
    message_id: int,
    channel_id: int,
    guild_id: int,
    date_time: str,
    mod_name: str,
    preset: dict,
    slots_per_country: int | list[int] = 1,
    thread_id: int | None = None,
    role_id: int | None = None,
    signups: dict | None = None,
    reserve: list | None = None,
    stopped: bool = False,
    ping_everyone: bool = False,
    created_by_id: int | None = None,
) -> None:
    """Сохраняет новую игру."""
    country_names = []
    for faction_countries in preset.values():
        for item in faction_countries:
            name, _ = _parse_country(item)
            country_names.append(name)
    n = len(country_names)
    if isinstance(slots_per_country, list):
        slots_list = [min(5, max(1, int(s))) for s in slots_per_country[:n]]
        slots_list.extend([1] * (n - len(slots_list)))
    else:
        slots_list = [min(5, max(1, int(slots_per_country)))] * n
    countries = [{"name": name, "slots": s} for name, s in zip(country_names, slots_list)]
    data = _load_games()
    idx = 0
    preset_stored = {}
    for faction, faction_countries in preset.items():
        preset_stored[faction] = [
            {"name": _parse_country(item)[0], "slots": slots_list[idx + i]}
            for i, item in enumerate(faction_countries)
        ]
        idx += len(faction_countries)
    log.info(f"save_game: msg={message_id} guild={guild_id} slots={slots_list} ping_everyone={ping_everyone}")
    data[str(message_id)] = {
        "channel_id": channel_id,
        "guild_id": guild_id,
        "date_time": date_time,
        "mod_name": mod_name,
        "preset": preset_stored,
        "countries": countries,
        "signups": signups if signups is not None else {str(i): [] for i in range(len(countries))},
        "reserve": reserve if reserve is not None else [],
        "stopped": stopped,
        "thread_id": thread_id,
        "role_id": role_id,
        "ping_everyone": ping_everyone,
        "created_by_id": created_by_id,
    }
    _save_games(data)


def get_game(message_id: int) -> dict | None:
    return _load_games().get(str(message_id))


def update_game(message_id: int, **kwargs) -> bool:
    """Обновляет поля игры."""
    game = get_game(message_id)
    if not game:
        return False
    game.update(kwargs)
    data = _load_games()
    data[str(message_id)] = game
    _save_games(data)
    return True


def stop_game(message_id: int) -> bool:
    game = get_game(message_id)
    if not game:
        return False
    game["stopped"] = True
    data = _load_games()
    data[str(message_id)] = game
    _save_games(data)
    return True


def delete_game(message_id: int) -> bool:
    data = _load_games()
    if str(message_id) not in data:
        return False
    del data[str(message_id)]
    _save_games(data)
    return True


def move_game(message_id: int, new_channel_id: int) -> bool:
    game = get_game(message_id)
    if not game:
        return False
    game["channel_id"] = new_channel_id
    data = _load_games()
    data[str(message_id)] = game
    _save_games(data)
    return True


def update_slots(message_id: int, country_index: int, new_slots: int) -> bool:
    game = get_game(message_id)
    if not game or country_index >= len(game["countries"]):
        return False
    country = game["countries"][country_index]
    signups = game["signups"].get(str(country_index), [])
    if new_slots < len(signups):
        return False
    country["slots"] = min(5, max(1, new_slots))
    preset = game.get("preset", {})
    flat_idx = 0
    for faction_countries in preset.values():
        for i in range(len(faction_countries)):
            if flat_idx == country_index:
                faction_countries[i]["slots"] = country["slots"]
                break
            flat_idx += 1
    data = _load_games()
    data[str(message_id)] = game
    _save_games(data)
    return True


def _remove_user_from_all_countries(game: dict, user_id: int) -> None:
    for idx, players in game["signups"].items():
        game["signups"][idx] = [s for s in players if s["id"] != user_id]


def remove_signup_anywhere(message_id: int, user_id: int, username: str) -> tuple[bool, str]:
    """Удаляет пользователя из страны или резерва. Возвращает (успех, где был: 'country' | 'reserve' | None)."""
    game = get_game(message_id)
    if not game or game.get("stopped"):
        return False, None
    for idx, players in game["signups"].items():
        for s in players:
            if s["id"] == user_id:
                game["signups"][idx] = [p for p in players if p["id"] != user_id]
                _save_game_data(message_id, game)
                _record_signup_stats(game["guild_id"], user_id, username, "removed")
                return True, "country"
    reserve = game.get("reserve", [])
    for s in reserve:
        if s["id"] == user_id:
            game["reserve"] = [p for p in reserve if p["id"] != user_id]
            _save_game_data(message_id, game)
            return True, "reserve"
    return False, None


def toggle_reserve(message_id: int, user_id: int, username: str) -> tuple[bool, str]:
    """Переключает запись в резерв. Возвращает (успех, действие)."""
    game = get_game(message_id)
    if not game or game.get("stopped"):
        return False, "not_found"
    reserve = game.get("reserve", [])
    for s in reserve:
        if s["id"] == user_id:
            reserve.remove(s)
            game["reserve"] = reserve
            data = _load_games()
            data[str(message_id)] = game
            _save_games(data)
            return True, "removed"
    if any(s["id"] == user_id for players in game["signups"].values() for s in players):
        return False, "already_signed"
    reserve.append({"id": user_id, "name": username})
    game["reserve"] = reserve
    data = _load_games()
    data[str(message_id)] = game
    _save_games(data)
    return True, "added"


def toggle_signup(message_id: int, country_index: int, user_id: int, username: str) -> tuple[bool, str]:
    game = get_game(message_id)
    if not game or game.get("stopped"):
        return False, "not_found"
    key = str(country_index)
    signups = game["signups"].get(key, [])
    country = game["countries"][country_index]

    for s in signups:
        if s["id"] == user_id:
            signups.remove(s)
            game["signups"][key] = signups
            _remove_from_reserve(game, user_id)
            _save_game_data(message_id, game)
            _record_signup_stats(game["guild_id"], user_id, username, "removed")
            return True, "removed"

    if len(signups) >= country["slots"]:
        return False, "full"

    _remove_user_from_all_countries(game, user_id)
    _remove_from_reserve(game, user_id)
    signups.append({"id": user_id, "name": username})
    game["signups"][key] = signups
    _save_game_data(message_id, game)
    _record_signup_stats(game["guild_id"], user_id, username, "added")
    return True, "added"


def _remove_from_reserve(game: dict, user_id: int) -> None:
    game["reserve"] = [s for s in game.get("reserve", []) if s["id"] != user_id]


def _save_game_data(message_id: int, game: dict) -> None:
    data = _load_games()
    data[str(message_id)] = game
    _save_games(data)


def _record_signup_stats(guild_id: int, user_id: int, username: str, action: str) -> None:
    data = _load_json(STATS_FILE, {})
    g, u = str(guild_id), str(user_id)
    if g not in data:
        data[g] = {}
    if u not in data[g]:
        data[g][u] = {"signups": 0, "name": username}
    data[g][u]["name"] = username
    if action == "added":
        data[g][u]["signups"] = data[g][u].get("signups", 0) + 1
    _save_json(STATS_FILE, data)


def get_active_message_ids() -> list[int]:
    data = _load_games()
    return [int(mid) for mid in data.keys()]


def get_games_for_user(guild_id: int, user_id: int) -> list[dict]:
    """Возвращает игры, в которых пользователь записан (страна или резерв)."""
    data = _load_games()
    result = []
    for mid, game in data.items():
        if game.get("guild_id") != guild_id:
            continue
        for players in game.get("signups", {}).values():
            if any(p["id"] == user_id for p in players):
                result.append({"message_id": int(mid), "game": game, "type": "country"})
                break
        else:
            for p in game.get("reserve", []):
                if p["id"] == user_id:
                    result.append({"message_id": int(mid), "game": game, "type": "reserve"})
                    break
    return result


def get_guild_config(guild_id: int) -> dict:
    data = _load_json(CONFIG_FILE, {})
    return data.get(str(guild_id), {})


def set_guild_config(guild_id: int, **kwargs) -> None:
    data = _load_json(CONFIG_FILE, {})
    g = str(guild_id)
    if g not in data:
        data[g] = {}
    data[g].update(kwargs)
    _save_json(CONFIG_FILE, data)


def get_stats(guild_id: int) -> list[tuple[int, str, int]]:
    """Возвращает [(user_id, username, signups_count), ...] отсортировано по убыванию."""
    data = _load_json(STATS_FILE, {})
    g = str(guild_id)
    if g not in data:
        return []
    items = [(int(uid), d.get("name", "?"), d.get("signups", 0)) for uid, d in data[g].items()]
    items.sort(key=lambda x: -x[2])
    return items


def update_stats_username(guild_id: int, user_id: int, username: str) -> None:
    data = _load_json(STATS_FILE, {})
    g, u = str(guild_id), str(user_id)
    if g not in data:
        data[g] = {}
    if u not in data[g]:
        data[g][u] = {"signups": 0}
    data[g][u]["name"] = username
    _save_json(STATS_FILE, data)


def get_custom_presets(guild_id: int) -> dict:
    data = _load_json(CUSTOM_PRESETS_FILE, {})
    return data.get(str(guild_id), {})


def save_custom_preset(guild_id: int, preset_name: str, preset: dict, mod_name: str) -> None:
    data = _load_json(CUSTOM_PRESETS_FILE, {})
    g = str(guild_id)
    if g not in data:
        data[g] = {}
    data[g][preset_name] = {"mod_name": mod_name, "preset": preset}
    _save_json(CUSTOM_PRESETS_FILE, data)

