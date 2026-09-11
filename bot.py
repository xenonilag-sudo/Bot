import os
import re
import time
import random
import asyncio
import aiohttp
import discord
import sqlite3
from datetime import datetime, timedelta

from dotenv import load_dotenv
from discord.ext import commands

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
API_BASE = "https://dict.minhqnd.com/api/v1"
PREFIX = "!"
TIMEOUT = 3 * 60 * 60
SUGGEST_LIMIT = 10
DAILY_HINT_LIMIT = 5
MAX_WRONG_ATTEMPTS = 3

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix=PREFIX,
    intents=intents,
    help_command=None
)

games = {}
db_file = "game_data.db"


def init_db():
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS hint_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            count INTEGER DEFAULT 1,
            UNIQUE(user_id, date)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS game_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER UNIQUE NOT NULL,
            game_active BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS player_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            correct_moves INTEGER DEFAULT 0,
            wrong_moves INTEGER DEFAULT 0,
            hints_used INTEGER DEFAULT 0,
            UNIQUE(user_id, channel_id)
        )
    ''')
    
    conn.commit()
    conn.close()


def get_user_hint_count(user_id):
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    
    cursor.execute(
        "SELECT count FROM hint_usage WHERE user_id = ? AND date = ?",
        (user_id, today)
    )
    result = cursor.fetchone()
    conn.close()
    
    return result[0] if result else 0


def increment_user_hint_count(user_id):
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    
    cursor.execute(
        "INSERT INTO hint_usage (user_id, date, count) VALUES (?, ?, 1) "
        "ON CONFLICT(user_id, date) DO UPDATE SET count = count + 1",
        (user_id, today)
    )
    
    conn.commit()
    conn.close()


def register_game_channel(channel_id):
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    
    cursor.execute(
        "INSERT OR IGNORE INTO game_channels (channel_id, game_active) VALUES (?, 1)",
        (channel_id,)
    )
    
    conn.commit()
    conn.close()


def update_player_stats(user_id, channel_id, correct=0, wrong=0, hints=0):
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    
    cursor.execute(
        "INSERT INTO player_stats (user_id, channel_id, correct_moves, wrong_moves, hints_used) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(user_id, channel_id) DO UPDATE SET "
        "correct_moves = correct_moves + ?, "
        "wrong_moves = wrong_moves + ?, "
        "hints_used = hints_used + ?",
        (user_id, channel_id, correct, wrong, hints, correct, wrong, hints)
    )
    
    conn.commit()
    conn.close()


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


def now():
    return time.time()


def is_timeout(game):
    if game["state"] != "ACTIVE":
        return False
    if game["last_move"] is None:
        return False
    return now() - game["last_move"] >= TIMEOUT


async def api_get(endpoint, params=None):
    url = f"{API_BASE}/{endpoint}"
    try:
        timeout = aiohttp.ClientTimeout(total=7)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params) as response:
                if response.status != 200:
                    return None
                return await response.json()
    except asyncio.TimeoutError:
        return None
    except Exception as e:
        print("API ERROR:", e)
        return None


async def lookup_word(word):
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
    return data.get("exists", False)


async def suggest_words(prefix, limit=SUGGEST_LIMIT):
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

    return cleaned[:limit]


async def get_valid_moves(game, limit=5):
    suggestions = await suggest_words(
        game["required"],
        SUGGEST_LIMIT
    )

    valid = []
    for word in suggestions:
        word = normalize(word)
        if not word:
            continue

        if word in game["used"]:
            continue

        if not word.startswith(game["required"]):
            continue

        if count_words(word) < 2:
            continue

        valid_check = await lookup_word(word)
        if not valid_check:
            continue

        valid.append(word)
        if len(valid) >= limit:
            break

    return valid


def create_game(first_word):
    first_word = normalize(first_word)
    return {
        "word": first_word,
        "required": last_word(first_word),
        "used": {first_word},
        "last_user": None,
        "last_move": now(),
        "state": "ACTIVE",
        "scores": {},
        "wrong_attempts": {},
        "bot_turn": False,
        "bot_word": None
    }


async def get_random_starting_word():
    for _ in range(5):
        suggestions = await suggest_words("a", 100)
        if suggestions:
            random_word = random.choice(suggestions)
            if count_words(random_word) >= 2:
                valid = await lookup_word(random_word)
                if valid:
                    return random_word
    return "học sinh"


@bot.command(name="noitu")
async def noitu(ctx, *, word=None):
    channel_id = ctx.channel.id

    if not word:
        if channel_id in games:
            game = games[channel_id]
            await ctx.send(
                f"🔗 Game hiện tại đang chờ từ:\n"
                f"**{game['required']}**"
            )
            return
        word = await get_random_starting_word()

    word = normalize(word)

    if count_words(word) < 2:
        await ctx.send(
            f"❌ Từ bắt đầu phải có ít nhất 2 từ. "
            f"Ví dụ: `học sinh`, `sinh viên`"
        )
        return

    valid = await lookup_word(word)
    if not valid:
        await ctx.send(
            f"❌ `{word}` không phải từ hợp lệ "
            f"hoặc không có trong từ điển."
        )
        return

    games[channel_id] = create_game(word)
    game = games[channel_id]
    
    register_game_channel(channel_id)

    embed = discord.Embed(
        title="🔗 NỐI TỪ — MÀN MỚI",
        description=(
            f"**Từ bắt đầu:** `{word}`\n\n"
            f"👉 Từ cần nối:\n"
            f"## {game['required']}"
        ),
        color=discord.Color.green()
    )

    embed.set_footer(
        text="Hãy gửi một từ/cụm từ (2-3 từ) bắt đầu bằng từ trên."
    )

    await ctx.send(embed=embed)


async def reset_to_waiting(ctx, game):
    game["state"] = "WAITING"
    game["last_user"] = None
    game["last_move"] = None
    game["wrong_attempts"] = {}
    game["bot_turn"] = False
    game["bot_word"] = None

    await ctx.send(
        "⏰ Màn trước đã kết thúc do quá 3 giờ "
        "không có lượt nối.\n"
        "🔗 Màn mới đang chờ người chơi."
    )


@bot.command(name="helpnoitu")
async def help_noitu(ctx):
    embed = discord.Embed(
        title="📖 Hướng dẫn — Nối từ",
        description=(
            "Game nối từ tiếng Việt dành cho nhiều người "
            "trong cùng một channel."
        ),
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="🎮 Bắt đầu",
        value=(
            "`!noitu`\n"
            "Bắt đầu bằng từ ngẫu nhiên từ từ điển.\n\n"
            "`!noitu học sinh`\n"
            "Bắt đầu bằng từ bạn chọn."
        ),
        inline=False
    )

    embed.add_field(
        name="🔗 Cách chơi",
        value=(
            "Người chơi tiếp theo phải dùng từ bắt đầu "
            "bằng **từ cuối** của lượt trước.\n"
            "Mỗi từ nối phải có **2-3 từ**.\n\n"
            "Ví dụ:\n"
            "`học sinh` → `sinh viên` → `viên chức`"
        ),
        inline=False
    )

    embed.add_field(
        name="⚠️ Luật",
        value=(
            "• Mỗi lượt phải nối từ có **2-3 từ**.\n"
            "• Không được dùng lại từ.\n"
            "• Không được nối hai lượt liên tiếp.\n"
            "• Từ phải tồn tại trong từ điển.\n"
            "• Nối đúng → bot react ✅.\n"
            "• Nối sai 3 lần → cảnh báo.\n"
            "• Nối sai lần 4 → reset màn.\n"
            "• Bot có 30% tỉ lệ nối tiếp theo.\n"
            "• Im quá 3 giờ → màn kết thúc."
        ),
        inline=False
    )

    embed.add_field(
        name="💡 Trợ giúp",
        value=(
            "`!kho` — xin gợi ý (5 lần/ngày).\n"
            "`!diem` — xem bảng điểm.\n"
            "`!dungnoitu` — dừng game."
        ),
        inline=False
    )

    embed.set_footer(
        text="Dictionary API: dict.minhqnd.com"
    )

    await ctx.send(embed=embed)


@bot.command(name="kho")
async def kho(ctx):
    channel_id = ctx.channel.id
    user_id = ctx.author.id

    if channel_id not in games:
        await ctx.send("❌ Chưa có màn nối từ.")
        return

    hint_count = get_user_hint_count(user_id)
    if hint_count >= DAILY_HINT_LIMIT:
        await ctx.send(
            f"❌ Bạn đã dùng hết {DAILY_HINT_LIMIT} lần gợi ý trong ngày hôm nay.\n"
            f"Quay lại vào ngày mai!"
        )
        return

    game = games[channel_id]

    if is_timeout(game):
        await reset_to_waiting(ctx, game)
        return

    valid = await get_valid_moves(game, 5)

    if not valid:
        await ctx.send(
            f"💀 Không tìm thấy từ nào có thể nối với "
            f"`{game['required']}`.\n"
            f"🏁 Màn kết thúc."
        )

        game["state"] = "WAITING"
        game["last_user"] = None
        game["last_move"] = None
        return

    increment_user_hint_count(user_id)
    update_player_stats(user_id, channel_id, hints=1)
    remaining_hints = DAILY_HINT_LIMIT - get_user_hint_count(user_id)

    embed = discord.Embed(
        title="💡 Gợi ý",
        description=(
            f"Từ cần nối: **`{game['required']}`**\n"
            f"Còn lại: **{remaining_hints}/{DAILY_HINT_LIMIT}** lần gợi ý"
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


@bot.command(name="diem")
async def diem(ctx):
    channel_id = ctx.channel.id

    if channel_id not in games:
        await ctx.send("❌ Chưa có game.")
        return

    game = games[channel_id]

    if not game["scores"]:
        await ctx.send("📊 Chưa có ai ghi điểm.")
        return

    ranking = sorted(
        game["scores"].items(),
        key=lambda x: x[1],
        reverse=True
    )

    lines = []

    for index, (user_id, score) in enumerate(ranking, 1):
        member = ctx.guild.get_member(int(user_id))
        name = (
            member.display_name
            if member
            else f"User {user_id}"
        )
        lines.append(
            f"**{index}.** {name} — `{score}`"
        )

    embed = discord.Embed(
        title="🏆 Bảng điểm",
        description="\n".join(lines),
        color=discord.Color.gold()
    )

    await ctx.send(embed=embed)


@bot.command(name="dungnoitu")
async def dung_noitu(ctx):
    channel_id = ctx.channel.id

    if channel_id not in games:
        await ctx.send("❌ Không có game đang chạy.")
        return

    del games[channel_id]
    await ctx.send("🛑 Đã dừng game nối từ.")


async def bot_play_turn(message, game):
    valid_moves = await get_valid_moves(game, 10)
    
    if not valid_moves:
        await message.channel.send(
            f"🏁 Không còn từ hợp lệ để nối với "
            f"`{game['required']}`.\n"
            f"🎮 Màn này kết thúc."
        )
        game["state"] = "WAITING"
        game["last_user"] = None
        game["last_move"] = None
        return False

    bot_word = random.choice(valid_moves)
    game["word"] = bot_word
    game["used"].add(bot_word)
    game["required"] = last_word(bot_word)
    game["bot_turn"] = True
    game["bot_word"] = bot_word
    game["last_move"] = now()

    embed = discord.Embed(
        title="🤖 Bot nối từ",
        description=(
            f"**Bot nối:** `{bot_word}`\n\n"
            f"👉 Bạn phải nối bằng:\n"
            f"## {game['required']}"
        ),
        color=discord.Color.blue()
    )

    await message.channel.send(embed=embed)
    return True


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    await bot.process_commands(message)

    if message.content.startswith(PREFIX):
        return

    channel_id = message.channel.id

    if channel_id not in games:
        return

    game = games[channel_id]

    word = normalize(message.content)

    if not word:
        return

    if game["state"] == "ACTIVE":
        if is_timeout(game):
            game["state"] = "WAITING"
            game["last_user"] = None
            game["last_move"] = None
            game["wrong_attempts"] = {}
            game["bot_turn"] = False

    if game["bot_turn"]:
        if not word.startswith(game["required"]):
            user_id = str(message.author.id)
            game["wrong_attempts"][user_id] = game["wrong_attempts"].get(user_id, 0) + 1

            if game["wrong_attempts"][user_id] == 3:
                await message.reply(
                    f"⚠️ Bạn đã nối sai 3 lần. Một lần sai nữa sẽ reset màn chơi."
                )
                return
            elif game["wrong_attempts"][user_id] >= 4:
                update_player_stats(int(user_id), channel_id, wrong=1)
                await message.channel.send(
                    f"🔄 Màn chơi đã reset do nối sai quá nhiều lần."
                )
                game["state"] = "WAITING"
                game["last_user"] = None
                game["last_move"] = None
                game["wrong_attempts"] = {}
                game["bot_turn"] = False
                return

            update_player_stats(int(user_id), channel_id, wrong=1)
            await message.reply(
                f"❌ Không hợp lệ!\n"
                f"👉 Cần nối bằng **`{game['required']}`**."
            )
            return

        if count_words(word) < 2 or count_words(word) > 3:
            await message.reply(
                f"❌ Từ nối phải có **2-3 từ**.\n"
                f"Ví dụ: `sinh viên`, `viên chức`"
            )
            return

        if word in game["used"]:
            await message.reply(
                "♻️ Từ này đã được sử dụng trong màn này."
            )
            return

        valid = await lookup_word(word)
        if not valid:
            await message.reply(
                f"❌ `{word}` không được tìm thấy trong từ điển."
            )
            return

        game["word"] = word
        game["used"].add(word)
        game["last_user"] = message.author.id
        game["last_move"] = now()
        game["state"] = "ACTIVE"

        user_id = str(message.author.id)
        game["scores"][user_id] = game["scores"].get(user_id, 0) + 1
        game["wrong_attempts"][user_id] = 0
        game["bot_turn"] = False

        update_player_stats(int(user_id), channel_id, correct=1)

        try:
            await message.add_reaction("✅")
        except Exception as e:
            print("Cannot react:", e)

        if random.random() < 0.3:
            await bot_play_turn(message, game)
        else:
            game["required"] = last_word(word)
            valid_moves = await get_valid_moves(game, 1)

            if not valid_moves:
                await message.channel.send(
                    f"🏁 Không còn từ hợp lệ để nối với "
                    f"`{game['required']}`.\n"
                    f"🎮 Màn này kết thúc."
                )
                game["state"] = "WAITING"
                game["last_user"] = None
                game["last_move"] = None
        return

    if (
        game["last_user"] is not None
        and game["last_user"] == message.author.id
    ):
        await message.reply(
            "⛔ Bạn vừa nối lượt trước. "
            "Hãy chờ người chơi khác."
        )
        return

    if count_words(word) < 2 or count_words(word) > 3:
        await message.reply(
            f"❌ Từ nối phải có **2-3 từ**.\n"
            f"Ví dụ: `sinh viên`, `viên chức`"
        )
        return

    required = game["required"]

    if not word.startswith(required):
        user_id = str(message.author.id)
        game["wrong_attempts"][user_id] = game["wrong_attempts"].get(user_id, 0) + 1

        if game["wrong_attempts"][user_id] == 3:
            await message.reply(
                f"⚠️ Bạn đã nối sai 3 lần. Một lần sai nữa sẽ reset màn chơi."
            )
            return
        elif game["wrong_attempts"][user_id] >= 4:
            update_player_stats(int(user_id), channel_id, wrong=1)
            await message.channel.send(
                f"🔄 Màn chơi đã reset do nối sai quá nhiều lần."
            )
            game["state"] = "WAITING"
            game["last_user"] = None
            game["last_move"] = None
            game["wrong_attempts"] = {}
            game["bot_turn"] = False
            return

        update_player_stats(int(user_id), channel_id, wrong=1)
        await message.reply(
            f"❌ Không hợp lệ!\n"
            f"👉 Cần nối bằng **`{required}`**."
        )
        return

    if word in game["used"]:
        await message.reply(
            "♻️ Từ này đã được sử dụng trong màn này."
        )
        return

    valid = await lookup_word(word)

    if not valid:
        await message.reply(
            f"❌ `{word}` không được tìm thấy "
            f"trong từ điển."
        )
        return

    game["word"] = word
    game["used"].add(word)
    game["last_user"] = message.author.id
    game["last_move"] = now()
    game["state"] = "ACTIVE"

    user_id = str(message.author.id)
    game["scores"][user_id] = (
        game["scores"].get(user_id, 0) + 1
    )
    game["wrong_attempts"][user_id] = 0

    update_player_stats(int(user_id), channel_id, correct=1)

    try:
        await message.add_reaction("✅")
    except Exception as e:
        print("Cannot react:", e)

    if random.random() < 0.3:
        await bot_play_turn(message, game)
    else:
        game["required"] = last_word(word)
        valid_moves = await get_valid_moves(game, 1)

        if not valid_moves:
            await message.channel.send(
                f"🏁 Không còn từ hợp lệ để nối với "
                f"`{game['required']}`.\n"
                f"🎮 Màn này kết thúc."
            )

            game["state"] = "WAITING"
            game["last_user"] = None
            game["last_move"] = None


@bot.event
async def on_ready():
    init_db()
    print(
        f"✅ Đăng nhập thành công: "
        f"{bot.user}"
    )
    print(
        f"📡 Đang phục vụ {len(bot.guilds)} server."
    )


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return

    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(
            "❌ Thiếu tham số.\n"
            "Dùng `!helpnoitu` để xem hướng dẫn."
        )
        return

    print("COMMAND ERROR:", repr(error))


if not TOKEN:
    raise RuntimeError(
        "❌ Chưa cấu hình DISCORD_TOKEN trong .env"
    )

bot.run(TOKEN)
