# =========================================================
# bot.py
# Backend chính của bot Nối Từ
# =========================================================

import os
import re
import time
import random
import asyncio
import sqlite3
from typing import Optional

import aiohttp
import discord

from dotenv import load_dotenv
from discord.ext import commands

import messages


# =========================================================
# ENV
# =========================================================

load_dotenv()

TOKEN = os.getenv(
    "DISCORD_TOKEN"
)


# =========================================================
# CONFIG
# =========================================================

API_BASE = (
    "https://dict.minhqnd.com/api/v1"
)

PREFIX = "!"

DB_FILE = "game_data.db"

API_TIMEOUT = 10

TIMEOUT = (
    3 * 60 * 60
)

SUGGEST_LIMIT = 10

DAILY_HINT_LIMIT = 5

MAX_WRONG_ATTEMPTS = 3

BOT_PLAY_CHANCE = 0.30

# Số xu nhận được khi nối đúng
COIN_REWARD_CORRECT = 10


# =========================================================
# INTENTS
# =========================================================

intents = discord.Intents.default()

intents.message_content = True


# =========================================================
# BOT CLASS
# =========================================================

class NoituBot(commands.Bot):

    def __init__(self):

        super().__init__(
            command_prefix=PREFIX,
            intents=intents,
            help_command=None
        )

    async def setup_hook(self):

        # Load command economy/shop
        await self.load_extension(
            "commands_extra"
        )

    async def close(self):

        global http_session

        if (
            http_session is not None
            and not http_session.closed
        ):
            await http_session.close()

            http_session = None

        await super().close()


bot = NoituBot()


# =========================================================
# GLOBAL
# =========================================================

games = {}

http_session: Optional[
    aiohttp.ClientSession
] = None


# =========================================================
# DATABASE
# =========================================================

def get_db():

    conn = sqlite3.connect(
        DB_FILE,
        timeout=10
    )

    return conn


def init_db():

    conn = get_db()

    cursor = conn.cursor()

    # =====================================================
    # HINT USAGE
    # =====================================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hint_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            count INTEGER DEFAULT 1,
            UNIQUE(user_id, date)
        )
    """)

    # =====================================================
    # GAME CHANNELS
    # =====================================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS game_channels (
            channel_id INTEGER PRIMARY KEY,
            game_active INTEGER DEFAULT 0,
            created_at TIMESTAMP
                DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # =====================================================
    # PLAYER STATS
    # =====================================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS player_stats (
            user_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            correct_moves INTEGER DEFAULT 0,
            wrong_moves INTEGER DEFAULT 0,
            hints_used INTEGER DEFAULT 0,
            UNIQUE(user_id, channel_id)
        )
    """)

    # =====================================================
    # ECONOMY
    # =====================================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS economy (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 0
        )
    """)

    # =====================================================
    # INVENTORY
    # =====================================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            user_id INTEGER NOT NULL,
            item TEXT NOT NULL,
            quantity INTEGER DEFAULT 0,
            PRIMARY KEY(user_id, item)
        )
    """)

    # =====================================================
    # MUTES
    # =====================================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mutes (
            channel_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            expires_at REAL NOT NULL,
            PRIMARY KEY(channel_id, user_id)
        )
    """)

    conn.commit()

    conn.close()


# =========================================================
# HINT DATABASE
# =========================================================

def get_user_hint_count(
    user_id: int
) -> int:

    conn = get_db()

    today = time.strftime(
        "%Y-%m-%d"
    )

    row = conn.execute(
        """
        SELECT count
        FROM hint_usage
        WHERE user_id = ?
          AND date = ?
        """,
        (
            user_id,
            today
        )
    ).fetchone()

    conn.close()

    if row is None:
        return 0

    return row[0]


def increment_user_hint_count(
    user_id: int
):

    conn = get_db()

    today = time.strftime(
        "%Y-%m-%d"
    )

    conn.execute(
        """
        INSERT INTO hint_usage (
            user_id,
            date,
            count
        )
        VALUES (?, ?, 1)

        ON CONFLICT(user_id, date)
        DO UPDATE SET
            count = count + 1
        """,
        (
            user_id,
            today
        )
    )

    conn.commit()

    conn.close()


# =========================================================
# GAME DATABASE
# =========================================================

def register_game_channel(
    channel_id: int
):

    conn = get_db()

    conn.execute(
        """
        INSERT INTO game_channels (
            channel_id,
            game_active
        )
        VALUES (?, 1)

        ON CONFLICT(channel_id)
        DO UPDATE SET
            game_active = 1
        """,
        (
            channel_id,
        )
    )

    conn.commit()

    conn.close()


def deactivate_game_channel(
    channel_id: int
):

    conn = get_db()

    conn.execute(
        """
        UPDATE game_channels
        SET game_active = 0
        WHERE channel_id = ?
        """,
        (
            channel_id,
        )
    )

    conn.commit()

    conn.close()


# =========================================================
# PLAYER STATS
# =========================================================

def update_player_stats(
    user_id: int,
    channel_id: int,
    correct: int = 0,
    wrong: int = 0,
    hints: int = 0
):

    conn = get_db()

    conn.execute(
        """
        INSERT INTO player_stats (
            user_id,
            channel_id,
            correct_moves,
            wrong_moves,
            hints_used
        )
        VALUES (?, ?, ?, ?, ?)

        ON CONFLICT(user_id, channel_id)
        DO UPDATE SET
            correct_moves =
                correct_moves
                + excluded.correct_moves,

            wrong_moves =
                wrong_moves
                + excluded.wrong_moves,

            hints_used =
                hints_used
                + excluded.hints_used
        """,
        (
            user_id,
            channel_id,
            correct,
            wrong,
            hints
        )
    )

    conn.commit()

    conn.close()


def get_player_scores(
    channel_id: int
):

    conn = get_db()

    rows = conn.execute(
        """
        SELECT
            user_id,
            correct_moves,
            wrong_moves,
            hints_used

        FROM player_stats

        WHERE channel_id = ?
          AND correct_moves > 0

        ORDER BY correct_moves DESC
        """,
        (
            channel_id,
        )
    ).fetchall()

    conn.close()

    return rows


# =========================================================
# ECONOMY
# =========================================================

def get_balance(
    user_id: int
) -> int:

    conn = get_db()

    row = conn.execute(
        """
        SELECT balance
        FROM economy
        WHERE user_id = ?
        """,
        (
            user_id,
        )
    ).fetchone()

    conn.close()

    if row is None:
        return 0

    return row[0]


def add_money(
    user_id: int,
    amount: int
):

    if amount <= 0:
        return

    conn = get_db()

    conn.execute(
        """
        INSERT INTO economy (
            user_id,
            balance
        )
        VALUES (?, ?)

        ON CONFLICT(user_id)
        DO UPDATE SET
            balance =
                balance
                + excluded.balance
        """,
        (
            user_id,
            amount
        )
    )

    conn.commit()

    conn.close()


def remove_money(
    user_id: int,
    amount: int
) -> bool:

    if amount <= 0:
        return False

    conn = get_db()

    try:

        conn.execute(
            "BEGIN IMMEDIATE"
        )

        row = conn.execute(
            """
            SELECT balance
            FROM economy
            WHERE user_id = ?
            """,
            (
                user_id,
            )
        ).fetchone()

        if (
            row is None
            or row[0] < amount
        ):

            conn.rollback()

            return False

        conn.execute(
            """
            UPDATE economy
            SET balance =
                balance - ?
            WHERE user_id = ?
            """,
            (
                amount,
                user_id
            )
        )

        conn.commit()

        return True

    except Exception as e:

        conn.rollback()

        print(
            "REMOVE MONEY ERROR:",
            repr(e)
        )

        return False

    finally:

        conn.close()


# =========================================================
# INVENTORY
# =========================================================

def get_item_count(
    user_id: int,
    item: str
) -> int:

    conn = get_db()

    row = conn.execute(
        """
        SELECT quantity
        FROM inventory
        WHERE user_id = ?
          AND item = ?
        """,
        (
            user_id,
            item
        )
    ).fetchone()

    conn.close()

    if row is None:
        return 0

    return row[0]


def add_item(
    user_id: int,
    item: str,
    quantity: int = 1
):

    if quantity <= 0:
        return

    conn = get_db()

    conn.execute(
        """
        INSERT INTO inventory (
            user_id,
            item,
            quantity
        )
        VALUES (?, ?, ?)

        ON CONFLICT(user_id, item)
        DO UPDATE SET
            quantity =
                quantity
                + excluded.quantity
        """,
        (
            user_id,
            item,
            quantity
        )
    )

    conn.commit()

    conn.close()


def remove_item(
    user_id: int,
    item: str,
    quantity: int = 1
) -> bool:

    if quantity <= 0:
        return False

    conn = get_db()

    try:

        conn.execute(
            "BEGIN IMMEDIATE"
        )

        row = conn.execute(
            """
            SELECT quantity
            FROM inventory
            WHERE user_id = ?
              AND item = ?
            """,
            (
                user_id,
                item
            )
        ).fetchone()

        if (
            row is None
            or row[0] < quantity
        ):

            conn.rollback()

            return False

        new_quantity = (
            row[0] - quantity
        )

        if new_quantity <= 0:

            conn.execute(
                """
                DELETE FROM inventory
                WHERE user_id = ?
                  AND item = ?
                """,
                (
                    user_id,
                    item
                )
            )

        else:

            conn.execute(
                """
                UPDATE inventory
                SET quantity = ?
                WHERE user_id = ?
                  AND item = ?
                """,
                (
                    new_quantity,
                    user_id,
                    item
                )
            )

        conn.commit()

        return True

    except Exception as e:

        conn.rollback()

        print(
            "REMOVE ITEM ERROR:",
            repr(e)
        )

        return False

    finally:

        conn.close()


# =========================================================
# MUTE
# =========================================================

def mute_user(
    channel_id: int,
    user_id: int,
    minutes: int
):

    expires_at = (
        time.time()
        + minutes * 60
    )

    conn = get_db()

    conn.execute(
        """
        INSERT INTO mutes (
            channel_id,
            user_id,
            expires_at
        )
        VALUES (?, ?, ?)

        ON CONFLICT(channel_id, user_id)
        DO UPDATE SET
            expires_at =
                excluded.expires_at
        """,
        (
            channel_id,
            user_id,
            expires_at
        )
    )

    conn.commit()

    conn.close()


def is_user_muted(
    channel_id: int,
    user_id: int
) -> bool:

    conn = get_db()

    row = conn.execute(
        """
        SELECT expires_at
        FROM mutes
        WHERE channel_id = ?
          AND user_id = ?
        """,
        (
            channel_id,
            user_id
        )
    ).fetchone()

    if row is None:

        conn.close()

        return False

    expires_at = row[0]

    # Mute đã hết hạn
    if time.time() >= expires_at:

        conn.execute(
            """
            DELETE FROM mutes
            WHERE channel_id = ?
              AND user_id = ?
            """,
            (
                channel_id,
                user_id
            )
        )

        conn.commit()

        conn.close()

        return False

    conn.close()

    return True


# =========================================================
# TEXT HELPERS
# =========================================================

def normalize(
    text: str
) -> str:

    text = text.strip().lower()

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text


def count_words(
    text: str
) -> int:

    return len(
        text.split()
    )


def first_word(
    text: str
) -> str:

    parts = text.split()

    if not parts:
        return ""

    return parts[0]


def last_word(
    text: str
) -> str:

    parts = text.split()

    if not parts:
        return ""

    return parts[-1]


def is_valid_word_count(
    text: str
) -> bool:

    count = count_words(
        text
    )

    return (
        2 <= count <= 3
    )


def starts_with_required(
    word: str,
    required: str
) -> bool:

    return (
        first_word(word)
        == required
    )


def hide_word(
    word: str
) -> str:

    if len(word) <= 2:
        return word

    visible_chars = max(
        1,
        len(word) // 3
    )

    return (
        word[:visible_chars]
        + "#"
        * (
            len(word)
            - visible_chars
        )
    )


# =========================================================
# GAME
# =========================================================

def create_game(
    first_word: str
):

    first_word = normalize(
        first_word
    )

    return {
        "word": first_word,

        "required": last_word(
            first_word
        ),

        "used": {
            first_word
        },

        "last_user": None,

        "last_move": time.time(),

        "state": "ACTIVE",

        "wrong_attempts": {},

        "bot_turn": False,

        "bot_word": None
    }


def is_timeout(
    game
) -> bool:

    if game["state"] != "ACTIVE":
        return False

    if game["last_move"] is None:
        return False

    return (
        time.time()
        - game["last_move"]
        >= TIMEOUT
    )


def end_game(
    channel_id: int
):

    if channel_id in games:

        del games[
            channel_id
        ]

    deactivate_game_channel(
        channel_id
    )


# =========================================================
# API
# =========================================================

async def api_get(
    endpoint,
    params=None
):

    global http_session

    if (
        http_session is None
        or http_session.closed
    ):

        timeout = (
            aiohttp.ClientTimeout(
                total=API_TIMEOUT
            )
        )

        http_session = (
            aiohttp.ClientSession(
                timeout=timeout
            )
        )

    url = (
        f"{API_BASE}/{endpoint}"
    )

    try:

        async with http_session.get(
            url,
            params=params
        ) as response:

            if response.status != 200:

                print(
                    "API HTTP ERROR:",
                    response.status
                )

                return None

            return await response.json()

    except asyncio.TimeoutError:

        print(
            "API TIMEOUT:",
            url
        )

        return None

    except aiohttp.ClientError as e:

        print(
            "API CLIENT ERROR:",
            repr(e)
        )

        return None

    except Exception as e:

        print(
            "API ERROR:",
            repr(e)
        )

        return None


async def lookup_word(
    word: str
) -> bool:

    data = await api_get(
        "lookup",
        {
            "word": word,
            "lang": "vi",
            "def_lang": "vi"
        }
    )

    if not data:
        return False

    if isinstance(
        data,
        dict
    ):

        return bool(
            data.get(
                "exists",
                False
            )
        )

    return False


async def suggest_words(
    prefix: str,
    limit: int = SUGGEST_LIMIT
):

    data = await api_get(
        "suggest",
        {
            "q": prefix,
            "limit": limit
        }
    )

    if not data:
        return []

    if isinstance(
        data,
        list
    ):

        result = data

    elif isinstance(
        data,
        dict
    ):

        result = data.get(
            "suggestions",
            []
        )

    else:

        result = []

    cleaned = []

    for item in result:

        if isinstance(
            item,
            str
        ):

            word = normalize(
                item
            )

        elif isinstance(
            item,
            dict
        ):

            word = normalize(
                str(
                    item.get(
                        "word",
                        item.get(
                            "term",
                            ""
                        )
                    )
                )
            )

        else:

            continue

        if word:

            cleaned.append(
                word
            )

    # Remove duplicate
    cleaned = list(
        dict.fromkeys(
            cleaned
        )
    )

    return cleaned[:limit]


# =========================================================
# VALID MOVES
# =========================================================

async def get_valid_moves(
    game,
    limit: int = 5
):

    suggestions = await suggest_words(
        game["required"],
        SUGGEST_LIMIT
    )

    candidates = []

    for word in suggestions:

        word = normalize(
            word
        )

        if not word:
            continue

        if word in game["used"]:
            continue

        if not is_valid_word_count(
            word
        ):
            continue

        if not starts_with_required(
            word,
            game["required"]
        ):
            continue

        candidates.append(
            word
        )

    if not candidates:
        return []

    # Lookup API song song
    results = await asyncio.gather(
        *(
            lookup_word(word)
            for word in candidates
        ),
        return_exceptions=True
    )

    valid = []

    for word, result in zip(
        candidates,
        results
    ):

        if result is True:

            valid.append(
                word
            )

        if len(valid) >= limit:
            break

    return valid


# =========================================================
# RANDOM START WORD
# =========================================================

VIETNAMESE_CHARS = (
    "abcdefghijklmnopqrstuvwxyz"
    "áàảãạ"
    "ăằắẳẵặ"
    "âầấẩẫậ"
    "èéẻẽẹ"
    "êềếểễệ"
    "ìíỉĩị"
    "òóỏõọ"
    "ôồốổỗộ"
    "ơờớởỡợ"
    "ùúủũụ"
    "ưừứửữự"
    "ỳýỷỹỵ"
    "đ"
)


async def get_random_starting_word():

    for _ in range(10):

        random_char = random.choice(
            VIETNAMESE_CHARS
        )

        suggestions = await suggest_words(
            random_char,
            100
        )

        candidates = []

        for word in suggestions:

            word = normalize(
                word
            )

            if not is_valid_word_count(
                word
            ):
                continue

            candidates.append(
                word
            )

        random.shuffle(
            candidates
        )

        for word in candidates[:10]:

            if await lookup_word(
                word
            ):

                return word

    return "học sinh"


# =========================================================
# WRONG ATTEMPT
# =========================================================

async def handle_wrong_attempt(
    message,
    game,
    user_id: int,
    reason: str
):

    user_key = str(
        user_id
    )

    attempts = (
        game["wrong_attempts"].get(
            user_key,
            0
        )
        + 1
    )

    game["wrong_attempts"][
        user_key
    ] = attempts

    # Ghi nhận lần sai
    update_player_stats(
        user_id,
        message.channel.id,
        wrong=1
    )

    hint = await get_hint_for_wrong(
        game
    )

    hint_text = ""

    if hint:

        hint_text = (
            f"\n💡 Gợi ý: `{hint}`"
        )

    # =============================================
    # 3 lần sai
    # =============================================

    if attempts == MAX_WRONG_ATTEMPTS:

        await message.reply(
            messages.WRONG_THREE.format(
                max_attempts=
                    MAX_WRONG_ATTEMPTS
            )
            + hint_text
        )

        return False

    # =============================================
    # Lần thứ 4
    # =============================================

    if attempts > MAX_WRONG_ATTEMPTS:

        await message.channel.send(
            messages.GAME_RESET_WRONG
        )

        game["state"] = "WAITING"

        game["last_user"] = None

        game["last_move"] = None

        game["bot_turn"] = False

        game["bot_word"] = None

        game["wrong_attempts"] = {}

        return True

    # =============================================
    # Lần 1-2
    # =============================================

    await message.reply(
        f"❌ {reason}\n"
        f"👉 Cần nối bằng "
        f"**`{game['required']}`**."
        f"{hint_text}"
    )

    return False


# =========================================================
# HINT
# =========================================================

async def get_hint_for_wrong(
    game
):

    valid_moves = await get_valid_moves(
        game,
        3
    )

    if not valid_moves:
        return None

    hint_word = random.choice(
        valid_moves
    )

    return hide_word(
        hint_word
    )


# =========================================================
# BOT PLAY
# =========================================================

async def bot_play_turn(
    message,
    game
):

    valid_moves = await get_valid_moves(
        game,
        10
    )

    if not valid_moves:

        await message.channel.send(
            messages.GAME_NO_MOVE.format(
                required=
                    game["required"]
            )
        )

        end_game(
            message.channel.id
        )

        return False

    bot_word = random.choice(
        valid_moves
    )

    game["word"] = bot_word

    game["used"].add(
        bot_word
    )

    game["required"] = last_word(
        bot_word
    )

    game["bot_turn"] = True

    game["bot_word"] = bot_word

    game["last_move"] = time.time()

    await message.channel.send(
        messages.BOT_MOVE.format(
            word=bot_word,
            required=game["required"]
        )
    )

    return True


# =========================================================
# PROCESS CORRECT MOVE
# =========================================================

async def process_player_move(
    message,
    game,
    word
):

    channel_id = (
        message.channel.id
    )

    user_id = (
        message.author.id
    )

    user_key = str(
        user_id
    )

    # =============================================
    # Word count
    # =============================================

    if not is_valid_word_count(
        word
    ):

        await message.reply(
            messages.INVALID_WORD_COUNT
        )

        return

    # =============================================
    # Required word
    # =============================================

    required = game[
        "required"
    ]

    if not starts_with_required(
        word,
        required
    ):

        await handle_wrong_attempt(
            message,
            game,
            user_id,
            messages.WRONG_REQUIRED
        )

        return

    # =============================================
    # Duplicate
    # =============================================

    if word in game["used"]:

        await message.reply(
            messages.DUPLICATE_WORD
        )

        return

    # =============================================
    # Dictionary
    # =============================================

    valid = await lookup_word(
        word
    )

    if not valid:

        await message.reply(
            messages.WORD_NOT_FOUND.format(
                word=word
            )
        )

        return

    # =============================================
    # Correct
    # =============================================

    game["word"] = word

    game["used"].add(
        word
    )

    game["last_user"] = user_id

    game["last_move"] = time.time()

    game["state"] = "ACTIVE"

    game["wrong_attempts"][
        user_key
    ] = 0

    game["bot_turn"] = False

    game["bot_word"] = None

    # =============================================
    # Stats
    # =============================================

    update_player_stats(
        user_id,
        channel_id,
        correct=1
    )

    # =============================================
    # Economy
    # =============================================

    add_money(
        user_id,
        COIN_REWARD_CORRECT
    )

    # =============================================
    # Reaction
    # =============================================

    try:

        await message.add_reaction(
            messages.CORRECT_REACTION
        )

    except discord.HTTPException:
        pass

    # =============================================
    # Next required
    # =============================================

    game["required"] = last_word(
        word
    )

    # =============================================
    # Bot 30%
    # =============================================

    if (
        random.random()
        < BOT_PLAY_CHANCE
    ):

        await bot_play_turn(
            message,
            game
        )

        return

    # =============================================
    # Check whether there are moves
    # =============================================

    valid_moves = await get_valid_moves(
        game,
        1
    )

    if not valid_moves:

        await message.channel.send(
            messages.GAME_NO_MOVE.format(
                required=
                    game["required"]
            )
        )

        end_game(
            channel_id
        )


# =========================================================
# COMMAND: NOITU
# =========================================================

@bot.command(
    name="noitu"
)
async def noitu(
    ctx,
    *,
    word=None
):

    channel_id = (
        ctx.channel.id
    )

    # =============================================
    # Existing game
    # =============================================

    if channel_id in games:

        game = games[
            channel_id
        ]

        # Timeout
        if is_timeout(
            game
        ):

            end_game(
                channel_id
            )

            await ctx.send(
                messages.GAME_TIMEOUT.format(
                    prefix=PREFIX
                )
            )

        else:

            await ctx.send(
                messages.GAME_ALREADY_RUNNING.format(
                    required=
                        game["required"]
                )
            )

            return

    # =============================================
    # Random word
    # =============================================

    if not word:

        word = await get_random_starting_word()

    word = normalize(
        word
    )

    # =============================================
    # Word count
    # =============================================

    if not is_valid_word_count(
        word
    ):

        await ctx.send(
            messages.INVALID_WORD_COUNT
        )

        return

    # =============================================
    # Dictionary
    # =============================================

    valid = await lookup_word(
        word
    )

    if not valid:

        await ctx.send(
            messages.WORD_NOT_FOUND.format(
                word=word
            )
        )

        return

    # =============================================
    # Create
    # =============================================

    games[channel_id] = create_game(
        word
    )

    register_game_channel(
        channel_id
    )

    game = games[
        channel_id
    ]

    embed = discord.Embed(
        title="🔗 NỐI TỪ — MÀN MỚI",
        description=(
            f"**Từ bắt đầu:** `{word}`\n\n"
            "👉 **Từ cần nối:**\n"
            f"## {game['required']}"
        ),
        color=discord.Color.green()
    )

    embed.set_footer(
        text=(
            "Gửi một cụm từ 2-3 từ "
            "bắt đầu bằng từ được yêu cầu."
        )
    )

    await ctx.send(
        embed=embed
    )


# =========================================================
# COMMAND: KHO
# =========================================================

@bot.command(
    name="kho"
)
async def kho(ctx):

    channel_id = (
        ctx.channel.id
    )

    user_id = (
        ctx.author.id
    )

    # =============================================
    # Game?
    # =============================================

    if channel_id not in games:

        await ctx.send(
            messages.NO_GAME.format(
                prefix=PREFIX
            )
        )

        return

    game = games[
        channel_id
    ]

    # =============================================
    # Timeout
    # =============================================

    if is_timeout(
        game
    ):

        end_game(
            channel_id
        )

        await ctx.send(
            messages.GAME_TIMEOUT.format(
                prefix=PREFIX
            )
        )

        return

    # =============================================
    # Daily limit
    # =============================================

    hint_count = get_user_hint_count(
        user_id
    )

    if (
        hint_count
        >= DAILY_HINT_LIMIT
    ):

        await ctx.send(
            messages.HINT_LIMIT.format(
                limit=
                    DAILY_HINT_LIMIT
            )
        )

        return

    # =============================================
    # Find moves
    # =============================================

    valid = await get_valid_moves(
        game,
        5
    )

    if not valid:

        await ctx.send(
            messages.HINT_EMPTY.format(
                required=
                    game["required"]
            )
        )

        end_game(
            channel_id
        )

        return

    # =============================================
    # Consume hint
    # =============================================

    increment_user_hint_count(
        user_id
    )

    update_player_stats(
        user_id,
        channel_id,
        hints=1
    )

    remaining = (
        DAILY_HINT_LIMIT
        - get_user_hint_count(
            user_id
        )
    )

    # =============================================
    # Embed
    # =============================================

    embed = discord.Embed(
        title=messages.HINT_TITLE,
        description=messages.HINT_CONTENT.format(
            required=
                game["required"],
            remaining=remaining,
            limit=
                DAILY_HINT_LIMIT
        ),
        color=discord.Color.gold()
    )

    embed.add_field(
        name=messages.HINT_MOVES_TITLE,
        value="\n".join(
            f"• `{word}`"
            for word in valid
        ),
        inline=False
    )

    await ctx.send(
        embed=embed
    )


# =========================================================
# COMMAND: DIEM
# =========================================================

@bot.command(
    name="diem"
)
async def diem(ctx):

    channel_id = (
        ctx.channel.id
    )

    scores = get_player_scores(
        channel_id
    )

    if not scores:

        await ctx.send(
            "📊 Chưa có ai ghi điểm."
        )

        return

    lines = []

    for index, row in enumerate(
        scores,
        1
    ):

        user_id = int(
            row[0]
        )

        correct = int(
            row[1]
        )

        wrong = int(
            row[2]
        )

        hints = int(
            row[3]
        )

        member = None

        if ctx.guild:

            member = (
                ctx.guild.get_member(
                    user_id
                )
            )

        if member:

            name = (
                member.display_name
            )

        else:

            name = (
                f"User {user_id}"
            )

        lines.append(
            f"**{index}.** {name}\n"
            f"└ ✅ `{correct}` | "
            f"❌ `{wrong}` | "
            f"💡 `{hints}`"
        )

    embed = discord.Embed(
        title="🏆 Bảng điểm",
        description="\n".join(
            lines
        ),
        color=discord.Color.gold()
    )

    embed.set_footer(
        text=(
            "Điểm được lưu trong database."
        )
    )

    await ctx.send(
        embed=embed
    )


# =========================================================
# COMMAND: DUNGNOITU
# =========================================================

@bot.command(
    name="dungnoitu"
)
async def dung_noitu(ctx):

    channel_id = (
        ctx.channel.id
    )

    if channel_id not in games:

        await ctx.send(
            messages.NO_GAME.format(
                prefix=PREFIX
            )
        )

        return

    end_game(
        channel_id
    )

    await ctx.send(
        messages.GAME_STOPPED
    )


# =========================================================
# COMMAND: HELP
# =========================================================

@bot.command(
    name="helpnoitu"
)
async def help_noitu(ctx):

    embed = discord.Embed(
        title=messages.HELP_TITLE,
        description=messages.HELP_DESCRIPTION,
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="🎮 Bắt đầu",
        value=messages.HELP_START.format(
            prefix=PREFIX
        ),
        inline=False
    )

    embed.add_field(
        name="🔗 Cách chơi",
        value=messages.HELP_PLAY,
        inline=False
    )

    embed.add_field(
        name="⚠️ Luật",
        value=messages.HELP_RULES,
        inline=False
    )

    embed.add_field(
        name="💰 Kinh tế",
        value=messages.HELP_ECONOMY.format(
            prefix=PREFIX
        ),
        inline=False
    )

    embed.add_field(
        name="🛠️ Khác",
        value=messages.HELP_OTHER.format(
            prefix=PREFIX
        ),
        inline=False
    )

    embed.set_footer(
        text=messages.HELP_FOOTER
    )

    await ctx.send(
        embed=embed
    )


# =========================================================
# ON MESSAGE
# =========================================================

@bot.event
async def on_message(
    message
):

    # =============================================
    # Ignore bot
    # =============================================

    if message.author.bot:
        return

    # =============================================
    # MUTE CHECK
    #
    # CỰC KỲ QUAN TRỌNG:
    # kiểm tra trước process_commands.
    #
    # User bị mute -> bot hoàn toàn bỏ qua.
    # =============================================

    if is_user_muted(
        message.channel.id,
        message.author.id
    ):

        return

    # =============================================
    # Commands
    # =============================================

    await bot.process_commands(
        message
    )

    # =============================================
    # Ignore commands
    # =============================================

    if message.content.startswith(
        PREFIX
    ):

        return

    # =============================================
    # No game
    # =============================================

    channel_id = (
        message.channel.id
    )

    if channel_id not in games:
        return

    game = games[
        channel_id
    ]

    # =============================================
    # Timeout
    # =============================================

    if is_timeout(
        game
    ):

        end_game(
            channel_id
        )

        await message.channel.send(
            messages.GAME_TIMEOUT.format(
                prefix=PREFIX
            )
        )

        return

    # =============================================
    # Safety
    # =============================================

    if game["state"] != "ACTIVE":
        return

    # =============================================
    # Normalize
    # =============================================

    word = normalize(
        message.content
    )

    if not word:
        return

    # =============================================
    # BOT TURN
    #
    # Sau khi bot nối:
    # player được quyền nối tiếp.
    # =============================================

    if game["bot_turn"]:

        await process_player_move(
            message,
            game,
            word
        )

        return

    # =============================================
    # Prevent same player twice
    # =============================================

    if (
        game["last_user"] is not None
        and
        game["last_user"]
        == message.author.id
    ):

        await message.reply(
            messages.SAME_PLAYER
        )

        return

    # =============================================
    # Player move
    # =============================================

    await process_player_move(
        message,
        game,
        word
    )


# =========================================================
# READY
# =========================================================

@bot.event
async def on_ready():

    init_db()

    print(
        "========================================"
    )

    print(
        f"✅ Đăng nhập: {bot.user}"
    )

    print(
        f"📡 Server: {len(bot.guilds)}"
    )

    print(
        f"🎮 Prefix: {PREFIX}"
    )

    print(
        "========================================"
    )


# =========================================================
# COMMAND ERROR
# =========================================================

@bot.event
async def on_command_error(
    ctx,
    error
):

    # Unknown command
    if isinstance(
        error,
        commands.CommandNotFound
    ):

        return

    # Missing argument
    if isinstance(
        error,
        commands.MissingRequiredArgument
    ):

        await ctx.send(
            "❌ Thiếu tham số.\n"
            f"Dùng `{PREFIX}helpnoitu` "
            "để xem hướng dẫn."
        )

        return

    # Bad argument
    if isinstance(
        error,
        commands.BadArgument
    ):

        await ctx.send(
            "❌ Tham số không hợp lệ."
        )

        return

    print(
        "COMMAND ERROR:",
        repr(error)
    )


# =========================================================
# TOKEN CHECK
# =========================================================

if not TOKEN:

    raise RuntimeError(
        "❌ Chưa cấu hình "
        "DISCORD_TOKEN trong .env"
    )


# =========================================================
# DATABASE INIT
# =========================================================

init_db()


# =========================================================
# RUN
# =========================================================

bot.run(
    TOKEN
)
