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


# =========================================================
# CONFIG
# =========================================================

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

API_BASE = "https://dict.minhqnd.com/api/v1"
PREFIX = "!"

TIMEOUT = 3 * 60 * 60
SUGGEST_LIMIT = 10
DAILY_HINT_LIMIT = 5
MAX_WRONG_ATTEMPTS = 3
BOT_PLAY_CHANCE = 0.30

DB_FILE = "game_data.db"
API_TIMEOUT = 10


# =========================================================
# DISCORD
# =========================================================

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix=PREFIX,
    intents=intents,
    help_command=None
)


# =========================================================
# GLOBAL STATE
# =========================================================

games = {}

http_session: Optional[aiohttp.ClientSession] = None


# =========================================================
# DATABASE
# =========================================================

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hint_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            count INTEGER DEFAULT 1,
            UNIQUE(user_id, date)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS game_channels (
            channel_id INTEGER PRIMARY KEY,
            game_active INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

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

    conn.commit()
    conn.close()


def get_user_hint_count(user_id: int) -> int:
    conn = get_db()

    today = time.strftime("%Y-%m-%d")

    row = conn.execute(
        """
        SELECT count
        FROM hint_usage
        WHERE user_id = ? AND date = ?
        """,
        (user_id, today)
    ).fetchone()

    conn.close()

    return row["count"] if row else 0


def increment_user_hint_count(user_id: int):
    conn = get_db()

    today = time.strftime("%Y-%m-%d")

    conn.execute(
        """
        INSERT INTO hint_usage (user_id, date, count)
        VALUES (?, ?, 1)
        ON CONFLICT(user_id, date)
        DO UPDATE SET count = count + 1
        """,
        (user_id, today)
    )

    conn.commit()
    conn.close()


def register_game_channel(channel_id: int):
    conn = get_db()

    conn.execute(
        """
        INSERT INTO game_channels (channel_id, game_active)
        VALUES (?, 1)
        ON CONFLICT(channel_id)
        DO UPDATE SET game_active = 1
        """,
        (channel_id,)
    )

    conn.commit()
    conn.close()


def deactivate_game_channel(channel_id: int):
    conn = get_db()

    conn.execute(
        """
        UPDATE game_channels
        SET game_active = 0
        WHERE channel_id = ?
        """,
        (channel_id,)
    )

    conn.commit()
    conn.close()


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
            correct_moves = correct_moves + excluded.correct_moves,
            wrong_moves = wrong_moves + excluded.wrong_moves,
            hints_used = hints_used + excluded.hints_used
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


def get_player_scores(channel_id: int):
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
        (channel_id,)
    ).fetchall()

    conn.close()

    return rows


# =========================================================
# TEXT HELPERS
# =========================================================

def normalize(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def count_words(text: str) -> int:
    return len(text.split())


def last_word(text: str) -> str:
    parts = text.split()

    if not parts:
        return ""

    return parts[-1]


def first_word(text: str) -> str:
    parts = text.split()

    if not parts:
        return ""

    return parts[0]


def is_valid_word_count(text: str) -> bool:
    count = count_words(text)
    return 2 <= count <= 3


def starts_with_required(word: str, required: str) -> bool:
    return first_word(word) == required


def hide_word(word: str) -> str:
    if len(word) <= 2:
        return word

    visible_chars = max(1, len(word) // 3)

    return (
        word[:visible_chars]
        + "#" * (len(word) - visible_chars)
    )


def current_time() -> float:
    return time.time()


# =========================================================
# GAME HELPERS
# =========================================================

def create_game(first_word: str):
    first_word = normalize(first_word)

    return {
        "word": first_word,
        "required": last_word(first_word),

        "used": {first_word},

        "last_user": None,
        "last_move": current_time(),

        "state": "ACTIVE",

        "scores": {},

        "wrong_attempts": {},

        "bot_turn": False,
        "bot_word": None
    }


def is_timeout(game) -> bool:
    if game["state"] != "ACTIVE":
        return False

    if game["last_move"] is None:
        return False

    return (
        current_time() - game["last_move"]
        >= TIMEOUT
    )


def end_game(channel_id: int):
    if channel_id in games:
        del games[channel_id]

    deactivate_game_channel(channel_id)


def reset_wrong_attempts(game):
    game["wrong_attempts"] = {}


# =========================================================
# API
# =========================================================

async def api_get(endpoint, params=None):
    global http_session

    if http_session is None or http_session.closed:
        timeout = aiohttp.ClientTimeout(
            total=API_TIMEOUT
        )

        http_session = aiohttp.ClientSession(
            timeout=timeout
        )

    url = f"{API_BASE}/{endpoint}"

    try:
        async with http_session.get(
            url,
            params=params
        ) as response:

            if response.status != 200:
                print(
                    f"API HTTP ERROR: "
                    f"{response.status} - {url}"
                )
                return None

            return await response.json()

    except asyncio.TimeoutError:
        print("API TIMEOUT:", url)
        return None

    except aiohttp.ClientError as e:
        print("API CLIENT ERROR:", e)
        return None

    except Exception as e:
        print("API ERROR:", repr(e))
        return None


async def lookup_word(word: str) -> bool:
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

    if isinstance(data, dict):
        return bool(data.get("exists", False))

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

    result = []

    if isinstance(data, list):
        result = data

    elif isinstance(data, dict):
        result = data.get("suggestions", [])

    cleaned = []

    for item in result:

        if isinstance(item, str):
            word = normalize(item)

        elif isinstance(item, dict):
            word = normalize(
                str(
                    item.get(
                        "word",
                        item.get("term", "")
                    )
                )
            )

        else:
            continue

        if word:
            cleaned.append(word)

    # Xóa duplicate nhưng giữ thứ tự
    cleaned = list(dict.fromkeys(cleaned))

    return cleaned[:limit]


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

        word = normalize(word)

        if not word:
            continue

        if word in game["used"]:
            continue

        if not is_valid_word_count(word):
            continue

        if not starts_with_required(
            word,
            game["required"]
        ):
            continue

        candidates.append(word)

    if not candidates:
        return []

    # Kiểm tra API song song
    results = await asyncio.gather(
        *(lookup_word(word) for word in candidates),
        return_exceptions=True
    )

    valid = []

    for word, result in zip(
        candidates,
        results
    ):
        if result is True:
            valid.append(word)

        if len(valid) >= limit:
            break

    return valid


# =========================================================
# RANDOM START
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

            word = normalize(word)

            if not is_valid_word_count(word):
                continue

            candidates.append(word)

        if not candidates:
            continue

        random.shuffle(candidates)

        for word in candidates[:10]:

            if await lookup_word(word):
                return word

    # Fallback
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
    user_key = str(user_id)

    attempts = (
        game["wrong_attempts"].get(user_key, 0)
        + 1
    )

    game["wrong_attempts"][user_key] = attempts

    # Luôn ghi nhận lần sai
    update_player_stats(
        user_id,
        message.channel.id,
        wrong=1
    )

    hint = await get_hint_for_wrong(game)

    hint_text = (
        f"\n💡 Gợi ý: `{hint}`"
        if hint
        else ""
    )

    if attempts == MAX_WRONG_ATTEMPTS:

        await message.reply(
            "⚠️ Bạn đã nối sai "
            f"{MAX_WRONG_ATTEMPTS} lần.\n"
            "Một lần sai nữa sẽ reset màn chơi."
            f"{hint_text}"
        )

        return False

    if attempts > MAX_WRONG_ATTEMPTS:

        await message.channel.send(
            "🔄 Màn chơi đã reset do "
            "nối sai quá nhiều lần."
        )

        game["state"] = "WAITING"
        game["last_user"] = None
        game["last_move"] = None
        game["bot_turn"] = False
        game["bot_word"] = None

        reset_wrong_attempts(game)

        return True

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

async def get_hint_for_wrong(game):
    valid_moves = await get_valid_moves(
        game,
        3
    )

    if not valid_moves:
        return None

    hint_word = random.choice(valid_moves)

    return hide_word(hint_word)


# =========================================================
# BOT TURN
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
            f"🏁 Không còn từ hợp lệ để nối với "
            f"`{game['required']}`.\n"
            "🎮 Màn này kết thúc."
        )

        end_game(message.channel.id)

        return False

    bot_word = random.choice(valid_moves)

    game["word"] = bot_word

    game["used"].add(bot_word)

    game["required"] = last_word(bot_word)

    game["bot_turn"] = True
    game["bot_word"] = bot_word

    game["last_move"] = current_time()

    await message.channel.send(
        f"> Yuki nối: **{bot_word}**\n"
        f"> Cần nối: **`{game['required']}`**"
    )

    return True


# =========================================================
# COMMAND: NOITU
# =========================================================

@bot.command(name="startt")
async def startt(
    ctx,
    *,
    word=None
):
    channel_id = ctx.channel.id

    # Nếu đã có game active
    if channel_id in games:

        game = games[channel_id]

        if is_timeout(game):

            end_game(channel_id)

            await ctx.send(
                "⏰ Màn trước đã kết thúc do "
                "quá 3 giờ không có lượt nối.\n"
                "🔗 Dùng `!noitu` để bắt đầu màn mới."
            )

            if word is None:
                word = await get_random_starting_word()

            else:
                # Cho phép !noitu abc sau timeout
                pass

        else:
            await ctx.send(
                "❌ Kênh này đang có một màn chơi.\n"
                f"👉 Từ cần nối: "
                f"**`{game['required']}`**"
            )

            return

    if not word:
        word = await get_random_starting_word()

    word = normalize(word)

    if not is_valid_word_count(word):

        await ctx.send(
            "❌ Từ bắt đầu phải có 2-3 từ.\n"
            "Ví dụ: `học sinh` → `sinh viên`"
        )

        return

    valid = await lookup_word(word)

    if not valid:

        await ctx.send(
            f"❌ `{word}` không phải từ hợp lệ "
            "hoặc không có trong từ điển."
        )

        return

    games[channel_id] = create_game(word)

    register_game_channel(channel_id)

    game = games[channel_id]

    embed = discord.Embed(
        title="🔗 NỐI TỪ — MÀN MỚI",
        description=(
            f"**Từ bắt đầu:** `{word}`\n\n"
            "Từ cần nối:\n"
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

    await ctx.send(embed=embed)


# =========================================================
# COMMAND: HELP
# =========================================================

@bot.command(name="yuki")
async def yuki(ctx):

    embed = discord.Embed(
        title="📖 Hướng dẫn — Nối từ",
        description=(
            "🔗 Game nối từ tiếng Việt\n"
            "By yuki and xenoliag."
        ),
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="🎮 Bắt đầu",
        value=(
            "`!noitu`\n"
            "Bắt đầu bằng từ ngẫu nhiên.\n\n"
            "`!noitu học sinh`\n"
            "Bắt đầu bằng từ bạn chọn."
        ),
        inline=False
    )

    embed.add_field(
        name="🔗 Cách chơi",
        value=(
            "Từ đầu tiên của lượt mới phải "
            "trùng với từ cuối của lượt trước.\n\n"
            "Ví dụ:\n"
            "`học sinh` → `sinh viên` → "
            "`viên chức`"
        ),
        inline=False
    )

    embed.add_field(
        name="⚠️ Luật",
        value=(
            "• Mỗi lượt có 2-3 từ.\n"
            "• Không được dùng lại từ.\n"
            "• Không được nối hai lượt liên tiếp.\n"
            "• Từ phải tồn tại trong từ điển.\n"
            "• Nối đúng → ✅\n"
            "• Sai 3 lần → cảnh báo.\n"
            "• Sai lần 4 → reset màn.\n"
            "• Bot có 30% tỉ lệ nối tiếp.\n"
            "• Không có lượt trong 3 giờ → kết thúc."
        ),
        inline=False
    )

    embed.add_field(
        name="💡 Trợ giúp",
        value=(
            "`!kho` — gợi ý, 5 lần/ngày.\n"
            "`!diem` — xem bảng điểm.\n"
            "`!dungnoitu` — dừng game."
        ),
        inline=False
    )

    await ctx.send(embed=embed)


# =========================================================
# COMMAND: KHO
# =========================================================

@bot.command(name="ewhat")
async def ewhat(ctx):

    channel_id = ctx.channel.id
    user_id = ctx.author.id

    if channel_id not in games:

        await ctx.send(
            "❌ Chưa có màn nối từ.\n"
            "Dùng `!noitu` để bắt đầu."
        )

        return

    game = games[channel_id]

    if is_timeout(game):

        end_game(channel_id)

        await ctx.send(
            "⏰ Màn chơi đã kết thúc do "
            "quá 3 giờ không có lượt nối.\n"
            "Dùng `!noitu` để bắt đầu màn mới."
        )

        return

    hint_count = get_user_hint_count(user_id)

    if hint_count >= DAILY_HINT_LIMIT:

        await ctx.send(
            f"❌ Bạn đã dùng hết "
            f"{DAILY_HINT_LIMIT} lần gợi ý hôm nay."
        )

        return

    valid = await get_valid_moves(
        game,
        5
    )

    if not valid:

        await ctx.send(
            f"💀 Không tìm thấy từ nào có thể "
            f"nối với `{game['required']}`.\n"
            "🏁 Màn kết thúc."
        )

        end_game(channel_id)

        return

    increment_user_hint_count(user_id)

    update_player_stats(
        user_id,
        channel_id,
        hints=1
    )

    remaining = (
        DAILY_HINT_LIMIT
        - get_user_hint_count(user_id)
    )

    embed = discord.Embed(
        title="💡 Gợi ý",
        description=(
            f"Từ cần nối: **`{game['required']}`**\n"
            f"Còn lại: "
            f"**{remaining}/{DAILY_HINT_LIMIT}**"
        ),
        color=discord.Color.gold()
    )

    embed.add_field(
        name="Có thể thử",
        value="\n".join(
            f"• `{word}`"
            for word in valid
        ),
        inline=False
    )

    await ctx.send(embed=embed)


# =========================================================
# COMMAND: DIEM
# =========================================================

@bot.command(name="bxh")
async def bxh(ctx):

    channel_id = ctx.channel.id

    if channel_id not in games:

        # Cho phép xem bảng điểm cũ
        scores = get_player_scores(channel_id)

        if not scores:
            await ctx.send(
                "❌ Chưa có điểm trong kênh này."
            )
            return

    else:
        scores = get_player_scores(channel_id)

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

        user_id = int(row["user_id"])

        member = None

        if ctx.guild:
            member = ctx.guild.get_member(
                user_id
            )

        if member:
            name = member.display_name
        else:
            name = f"User {user_id}"

        correct = row["correct_moves"]
        wrong = row["wrong_moves"]
        hints = row["hints_used"]

        lines.append(
            f"**{index}.** {name}\n"
            f"└ ✅ `{correct}` | "
            f"❌ `{wrong}` | "
            f"💡 `{hints}`"
        )

    embed = discord.Embed(
        title="🏆 Bảng điểm",
        description="\n".join(lines),
        color=discord.Color.gold()
    )

    embed.set_footer(
        text="Điểm được lưu trong database."
    )

    await ctx.send(embed=embed)


# =========================================================
# COMMAND: DUNGNOITU
# =========================================================

@bot.command(name="endd")
async def endd(ctx):

    channel_id = ctx.channel.id

    if channel_id not in games:

        await ctx.send(
            "❌ Không có game đang chạy."
        )

        return

    end_game(channel_id)

    await ctx.send(
        "🛑 Đã dừng game nối từ."
    )


# =========================================================
# GAME MESSAGE PROCESSING
# =========================================================

async def process_player_move(
    message,
    game,
    word
):
    channel_id = message.channel.id
    user_id = message.author.id
    user_key = str(user_id)

    # ---------------------------------------------
    # Check word count
    # ---------------------------------------------

    if not is_valid_word_count(word):

        await message.reply(
            "❌ Từ nối phải có **2-3 từ**.\n"
            "Ví dụ: `sinh viên`, `viên chức`"
        )

        return

    # ---------------------------------------------
    # Check required
    # ---------------------------------------------

    required = game["required"]

    if not starts_with_required(
        word,
        required
    ):

        await handle_wrong_attempt(
            message,
            game,
            user_id,
            "Không đúng từ cần nối!"
        )

        return

    # ---------------------------------------------
    # Check duplicate
    # ---------------------------------------------

    if word in game["used"]:

        await message.reply(
            "♻️ Từ này đã được sử dụng "
            "trong màn này."
        )

        return

    # ---------------------------------------------
    # Check dictionary
    # ---------------------------------------------

    valid = await lookup_word(word)

    if not valid:

        await message.reply(
            f"❌ `{word}` không được tìm thấy "
            "trong từ điển."
        )

        return

    # ---------------------------------------------
    # Correct move
    # ---------------------------------------------

    game["word"] = word
    game["used"].add(word)

    game["last_user"] = user_id
    game["last_move"] = current_time()

    game["state"] = "ACTIVE"

    game["scores"][user_key] = (
        game["scores"].get(user_key, 0) + 1
    )

    game["wrong_attempts"][user_key] = 0

    game["bot_turn"] = False
    game["bot_word"] = None

    update_player_stats(
        user_id,
        channel_id,
        correct=1
    )

    try:
        await message.add_reaction("✅")

    except discord.HTTPException:
        pass

    # ---------------------------------------------
    # Update required
    # ---------------------------------------------

    game["required"] = last_word(word)

    # ---------------------------------------------
    # Bot chance
    # ---------------------------------------------

    if random.random() < BOT_PLAY_CHANCE:

        await bot_play_turn(
            message,
            game
        )

        return

    # ---------------------------------------------
    # Check if game has any valid move
    # ---------------------------------------------

    valid_moves = await get_valid_moves(
        game,
        1
    )

    if not valid_moves:

        await message.channel.send(
            f"🏁 Không còn từ hợp lệ để nối với "
            f"`{game['required']}`.\n"
            "🎮 Màn này kết thúc."
        )

        end_game(channel_id)


# =========================================================
# ON MESSAGE
# =========================================================

@bot.event
async def on_message(message):

    # Ignore bots
    if message.author.bot:
        return

    # Commands
    await bot.process_commands(message)

    # Ignore command messages
    if message.content.startswith(PREFIX):
        return

    channel_id = message.channel.id

    # No game
    if channel_id not in games:
        return

    game = games[channel_id]

    # ---------------------------------------------
    # Timeout
    # ---------------------------------------------

    if is_timeout(game):

        end_game(channel_id)

        await message.channel.send(
            "⏰ Màn chơi đã kết thúc do "
            "quá 3 giờ không có lượt nối.\n"
            "🔗 Dùng `!noitu` để bắt đầu màn mới."
        )

        return

    # ---------------------------------------------
    # WAITING safety
    # ---------------------------------------------

    if game["state"] != "ACTIVE":

        return

    # ---------------------------------------------
    # Normalize
    # ---------------------------------------------

    word = normalize(message.content)

    if not word:
        return

    # ---------------------------------------------
    # BOT TURN
    # ---------------------------------------------

    if game["bot_turn"]:

        await process_player_move(
            message,
            game,
            word
        )

        return

    # ---------------------------------------------
    # Prevent same user twice
    # ---------------------------------------------

    if (
        game["last_user"] is not None
        and game["last_user"]
        == message.author.id
    ):

        await message.reply(
            "⛔ Bạn vừa nối lượt trước.\n"
            "Hãy chờ người chơi khác."
        )

        return

    # ---------------------------------------------
    # Normal player turn
    # ---------------------------------------------

    await process_player_move(
        message,
        game,
        word
    )


# =========================================================
# ON READY
# =========================================================

@bot.event
async def on_ready():

    init_db()

    print(
        f"✅ Đăng nhập thành công: "
        f"{bot.user}"
    )

    print(
        f"📡 Đang phục vụ "
        f"{len(bot.guilds)} server."
    )


# =========================================================
# COMMAND ERROR
# =========================================================

@bot.event
async def on_command_error(
    ctx,
    error
):

    if isinstance(
        error,
        commands.CommandNotFound
    ):
        return

    if isinstance(
        error,
        commands.MissingRequiredArgument
    ):

        await ctx.send(
            "❌ Thiếu tham số.\n"
            "Dùng `!helpnoitu` để xem hướng dẫn."
        )

        return

    if isinstance(
        error,
        commands.CommandOnCooldown
    ):

        await ctx.send(
            "⏳ Vui lòng thử lại sau."
        )

        return

    print(
        "COMMAND ERROR:",
        repr(error)
    )


# =========================================================
# SHUTDOWN
# =========================================================

async def close_http_session():

    global http_session

    if (
        http_session is not None
        and not http_session.closed
    ):
        await http_session.close()

        http_session = None


# =========================================================
# MAIN
# =========================================================

if not TOKEN:

    raise RuntimeError(
        "❌ Chưa cấu hình "
        "DISCORD_TOKEN trong .env"
    )


init_db()


try:
    bot.run(TOKEN)

finally:
    try:
        loop = asyncio.new_event_loop()
        loop.run_until_complete(
            close_http_session()
        )
        loop.close()

    except Exception:
        pass
