import os
import time
import random
from typing import Optional

from dotenv import load_dotenv
import aiohttp
import discord
from discord.ext import commands

from text import TEXT

load_dotenv("")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

LOOKUP_API = "https://dict.minhqnd.com/api/v1/lookup"
SUGGEST_API = "https://dict.minhqnd.com/api/v1/suggest"

DEFAULT_LANG = "vi"
DEFAULT_DEF_LANG = "vi"

SUGGEST_COOLDOWN = 5 * 60

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

current_word: Optional[str] = None
last_suggest_usage: dict[int, float] = {}


async def fetch_json(url: str, params: dict):
    try:
        timeout = aiohttp.ClientTimeout(total=15)

        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:
            async with session.get(
                url,
                params=params
            ) as response:
                if response.status != 200:
                    return None

                return await response.json(
                    content_type=None
                )

    except Exception:
        return None


def normalize_word(content: str) -> str:
    return " ".join(
        content.strip().lower().split()
    )


def split_words(content: str) -> list[str]:
    return normalize_word(content).split()


def is_exactly_two_words(content: str) -> bool:
    return len(split_words(content)) == 2


def starts_with_required_word(
    content: str,
    required_word: str
) -> bool:
    words = split_words(content)

    return (
        len(words) == 2
        and words[0] == required_word
    )


async def suggest_words(
    prefix: str,
    limit: int = 10
) -> list[str]:
    data = await fetch_json(
        SUGGEST_API,
        {
            "q": prefix,
            "limit": limit,
        }
    )

    if not data:
        return []

    suggestions = []

    if isinstance(data, list):
        suggestions = data

    elif isinstance(data, dict):
        for key in [
            "suggestions",
            "results",
            "data",
            "words",
            "items",
            "entries",
        ]:
            value = data.get(key)

            if isinstance(value, list):
                suggestions = value
                break

    result = []

    for item in suggestions:
        if isinstance(item, str):
            word = item.strip().lower()

        elif isinstance(item, dict):
            word = str(
                item.get("word")
                or item.get("term")
                or item.get("text")
                or item.get("value")
                or ""
            ).strip().lower()

        else:
            continue

        if word:
            result.append(word)

    return list(dict.fromkeys(result))


async def get_start_word() -> Optional[str]:
    prefixes = [
        "a", "b", "c", "d", "e", "g",
        "h", "i", "k", "l", "m", "n",
        "o", "p", "q", "r", "s", "t",
        "u", "v", "x", "y"
    ]

    random.shuffle(prefixes)

    for prefix in prefixes:
        suggestions = await suggest_words(
            prefix,
            limit=50
        )

        valid_words = [
            word
            for word in suggestions
            if is_exactly_two_words(word)
        ]

        if valid_words:
            return random.choice(valid_words)

    return None


async def lookup_word(word: str) -> bool:
    data = await fetch_json(
        LOOKUP_API,
        {
            "word": word,
            "lang": DEFAULT_LANG,
            "def_lang": DEFAULT_DEF_LANG,
        }
    )

    if not data:
        return False

    if isinstance(data, dict):
        if data.get("found") is False:
            return False

        if data.get("error"):
            return False

        for field in [
            "definitions",
            "definition",
            "meanings",
            "entries",
            "results",
            "data",
        ]:
            if field in data and data[field]:
                return True

        return True

    if isinstance(data, list):
        return len(data) > 0

    return False


@bot.command(name="start")
async def start_game(ctx: commands.Context):
    global current_word

    current_word = await get_start_word()

    if not current_word:
        await ctx.send(
            TEXT["start_failed"]
        )
        return

    await ctx.send(
        TEXT["start_success"].format(
            word=current_word
        )
    )


@bot.command(name="ewhat")
async def suggest_next_words(ctx: commands.Context):
    global current_word

    if not current_word:
        await ctx.send(
            TEXT["game_not_started"]
        )
        return

    user_id = ctx.author.id
    now = time.time()

    last_used = last_suggest_usage.get(
        user_id,
        0
    )

    elapsed = now - last_used

    if elapsed < SUGGEST_COOLDOWN:
        remaining = int(
            SUGGEST_COOLDOWN - elapsed
        )

        await ctx.send(
            TEXT["suggest_cooldown"].format(
                remaining=remaining
            )
        )
        return

    last_suggest_usage[user_id] = now

    previous_words = split_words(
        current_word
    )

    if len(previous_words) != 2:
        await ctx.send(
            TEXT["suggest_not_found"]
        )
        return

    required_prefix = previous_words[-1]

    suggestions = await suggest_words(
        required_prefix,
        limit=50
    )

    valid_suggestions = []

    for suggestion in suggestions:
        if not is_exactly_two_words(
            suggestion
        ):
            continue

        if not starts_with_required_word(
            suggestion,
            required_prefix
        ):
            continue

        if suggestion == current_word:
            continue

        valid_suggestions.append(
            suggestion
        )

    valid_suggestions = list(
        dict.fromkeys(valid_suggestions)
    )

    if len(valid_suggestions) < 2:
        await ctx.send(
            TEXT["no_suggestion"]
        )
        return

    selected = random.sample(
        valid_suggestions,
        2
    )

    await ctx.send(
        TEXT["suggest_result"].format(
            suggestion_1=selected[0],
            suggestion_2=selected[1],
        )
    )


@bot.event
async def on_message(message: discord.Message):
    global current_word

    if message.author.bot:
        return

    await bot.process_commands(message)

    if message.content.startswith("!"):
        return

    if not current_word:
        return

    content = normalize_word(
        message.content
    )

    words = content.split()

    if len(words) < 2:
        if TEXT["invalid_less_than_2"]:
            await message.channel.send(
                TEXT["invalid_less_than_2"]
            )
        return

    if len(words) > 2:
        return

    previous_words = split_words(
        current_word
    )

    required_prefix = previous_words[-1]

    if words[0] != required_prefix:
        if TEXT["wrong_connection"]:
            await message.channel.send(
                TEXT["wrong_connection"]
            )

        await message.add_reaction("❌")
        return

    exists = await lookup_word(content)

    if not exists:
        if TEXT["word_not_found"]:
            await message.channel.send(
                TEXT["word_not_found"]
            )

        await message.add_reaction("❌")
        return

    current_word = content

    if TEXT["correct_connection"]:
        await message.channel.send(
            TEXT["correct_connection"]
        )

    await message.add_reaction("✅")


if not DISCORD_TOKEN:
    raise ValueError(
        "Chưa thiết lập biến môi trường DISCORD_TOKEN."
    )

bot.run(DISCORD_TOKEN) 
