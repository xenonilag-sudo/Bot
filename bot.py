import os
import re
import time
import asyncio
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

TIMEOUT = 3 * 60 * 60  # 3 giờ

SUGGEST_LIMIT = 10


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
# GAME DATA
# =========================================================

games = {}

"""
games[channel_id] = {

    "word": "học sinh",

    "required": "sinh",

    "used": {
        "học sinh",
        "sinh viên"
    },

    "last_user": 123456789,

    "last_move": 1234567890.0,

    "state": "ACTIVE",

    "scores": {
        user_id: 5
    }
}
"""


# =========================================================
# UTILS
# =========================================================

def normalize(text: str) -> str:
    """
    Chuẩn hóa tin nhắn người chơi.
    """

    text = text.strip().lower()

    # Xóa khoảng trắng dư
    text = re.sub(r"\s+", " ", text)

    return text


def last_word(text: str) -> str:
    """
    Lấy từ cuối cùng.

    học sinh -> sinh
    sinh viên -> viên
    """

    parts = text.split()

    if not parts:
        return ""

    return parts[-1]


def now():
    return time.time()


def is_timeout(game):
    """
    Kiểm tra game ACTIVE đã im quá 3 tiếng chưa.
    """

    if game["state"] != "ACTIVE":
        return False

    if game["last_move"] is None:
        return False

    return now() - game["last_move"] >= TIMEOUT


# =========================================================
# API
# =========================================================

async def api_get(endpoint, params=None):

    url = f"{API_BASE}/{endpoint}"

    try:

        timeout = aiohttp.ClientTimeout(total=7)

        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:

            async with session.get(
                url,
                params=params
            ) as response:

                if response.status != 200:
                    return None

                return await response.json()

    except asyncio.TimeoutError:

        return None

    except Exception as e:

        print("API ERROR:", e)

        return None


# =========================================================
# LOOKUP
# =========================================================

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


# =========================================================
# SUGGEST
# =========================================================

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

    # Một số API có thể trả:
    #
    # ["sinh viên", "sinh học"]
    #
    # hoặc:
    #
    # {"suggestions": [...]}

    if isinstance(data, list):

        result = data

    elif isinstance(data, dict):

        result = data.get(
            "suggestions",
            []
        )

    cleaned = []

    for item in result:

        if isinstance(item, str):

            word = normalize(item)

        elif isinstance(item, dict):

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
            cleaned.append(word)

    return cleaned[:limit]


# =========================================================
# FIND VALID MOVES
# =========================================================

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

        # Đã dùng
        if word in game["used"]:
            continue

        # Phải bắt đầu bằng từ cần nối
        if not word.startswith(
            game["required"]
        ):
            continue

        # Xác nhận lại bằng lookup
        valid_check = await lookup_word(word)

        if not valid_check:
            continue

        valid.append(word)

        if len(valid) >= limit:
            break

    return valid


# =========================================================
# CREATE GAME
# =========================================================

def create_game(first_word):

    first_word = normalize(first_word)

    return {

        "word": first_word,

        "required": last_word(first_word),

        "used": {
            first_word
        },

        "last_user": None,

        "last_move": now(),

        "state": "ACTIVE",

        "scores": {}
    }


# =========================================================
# WAITING GAME
# =========================================================

def create_waiting_game(first_word):

    first_word = normalize(first_word)

    return {

        "word": first_word,

        "required": last_word(first_word),

        "used": {
            first_word
        },

        "last_user": None,

        "last_move": None,

        "state": "WAITING",

        "scores": {}
    }


# =========================================================
# START GAME
# =========================================================

@bot.command(name="noitu")
async def noitu(ctx, *, word=None):

    channel_id = ctx.channel.id

    # ---------------------------------------------
    # Nếu không nhập từ
    # ---------------------------------------------

    if not word:

        if channel_id in games:

            game = games[channel_id]

            await ctx.send(
                f"🔗 Game hiện tại đang chờ từ:\n"
                f"**{game['required']}**"
            )

            return

        # Từ mặc định
        word = "học sinh"

    word = normalize(word)

    # ---------------------------------------------
    # Kiểm tra từ
    # ---------------------------------------------

    valid = await lookup_word(word)

    if not valid:

        await ctx.send(
            f"❌ `{word}` không phải từ hợp lệ "
            f"hoặc không có trong từ điển."
        )

        return

    # ---------------------------------------------
    # Reset game
    # ---------------------------------------------

    games[channel_id] = create_game(
        word
    )

    game = games[channel_id]

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
        text="Hãy gửi một từ/cụm từ bắt đầu bằng từ trên."
    )

    await ctx.send(embed=embed)


# =========================================================
# RESET GAME
# =========================================================

async def reset_to_waiting(ctx, game):

    game["state"] = "WAITING"

    game["last_user"] = None

    game["last_move"] = None

    await ctx.send(
        "⏰ Màn trước đã kết thúc do quá 3 giờ "
        "không có lượt nối.\n"
        "🔗 Màn mới đang chờ người chơi."
    )


# =========================================================
# HELP
# =========================================================

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
            "Bắt đầu bằng từ mặc định.\n\n"
            "`!noitu học sinh`\n"
            "Bắt đầu bằng từ bạn chọn."
        ),
        inline=False
    )

    embed.add_field(
        name="🔗 Cách chơi",
        value=(
            "Người chơi tiếp theo phải dùng từ bắt đầu "
            "bằng **từ cuối** của lượt trước.\n\n"
            "Ví dụ:\n"
            "`học sinh` → `sinh viên` → `viên chức`"
        ),
        inline=False
    )

    embed.add_field(
        name="⚠️ Luật",
        value=(
            "• Không được dùng lại từ.\n"
            "• Không được nối hai lượt liên tiếp.\n"
            "• Từ phải tồn tại trong từ điển.\n"
            "• Nối đúng → bot react ✅.\n"
            "• Nối sai → bot báo lỗi.\n"
            "• Im quá 3 giờ → màn kết thúc.\n"
            "• Màn mới không có người chơi sẽ chờ vô thời hạn."
        ),
        inline=False
    )

    embed.add_field(
        name="💡 Trợ giúp",
        value=(
            "`!kho` — xin gợi ý.\n"
            "`!diem` — xem bảng điểm.\n"
            "`!dungnoitu` — dừng game."
        ),
        inline=False
    )

    embed.set_footer(
        text="Dictionary API: dict.minhqnd.com"
    )

    await ctx.send(embed=embed)


# =========================================================
# HINT
# =========================================================

@bot.command(name="kho")
async def kho(ctx):

    channel_id = ctx.channel.id

    if channel_id not in games:

        await ctx.send(
            "❌ Chưa có màn nối từ."
        )

        return

    game = games[channel_id]

    # Nếu ACTIVE và quá 3 tiếng
    if is_timeout(game):

        await reset_to_waiting(
            ctx,
            game
        )

        # Sau khi reset vẫn cho xin gợi ý
        return

    valid = await get_valid_moves(
        game,
        5
    )

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

    embed = discord.Embed(
        title="💡 Gợi ý",
        description=(
            f"Từ cần nối: **`{game['required']}`**"
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
# SCORE
# =========================================================

@bot.command(name="diem")
async def diem(ctx):

    channel_id = ctx.channel.id

    if channel_id not in games:

        await ctx.send(
            "❌ Chưa có game."
        )

        return

    game = games[channel_id]

    if not game["scores"]:

        await ctx.send(
            "📊 Chưa có ai ghi điểm."
        )

        return

    ranking = sorted(
        game["scores"].items(),
        key=lambda x: x[1],
        reverse=True
    )

    lines = []

    for index, (user_id, score) in enumerate(
        ranking,
        1
    ):

        member = ctx.guild.get_member(
            user_id
        )

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


# =========================================================
# STOP
# =========================================================

@bot.command(name="dungnoitu")
async def dung_noitu(ctx):

    channel_id = ctx.channel.id

    if channel_id not in games:

        await ctx.send(
            "❌ Không có game đang chạy."
        )

        return

    del games[channel_id]

    await ctx.send(
        "🛑 Đã dừng game nối từ."
    )


# =========================================================
# MESSAGE HANDLER
# =========================================================

@bot.event
async def on_message(message):

    if message.author.bot:
        return

    # ---------------------------------------------
    # Commands
    # ---------------------------------------------

    await bot.process_commands(message)

    # ---------------------------------------------
    # Ignore command
    # ---------------------------------------------

    if message.content.startswith(PREFIX):
        return

    channel_id = message.channel.id

    # ---------------------------------------------
    # Không có game
    # ---------------------------------------------

    if channel_id not in games:
        return

    game = games[channel_id]

    word = normalize(
        message.content
    )

    if not word:
        return

    # ---------------------------------------------
    # TIMEOUT
    #
    # Chỉ ACTIVE mới có timeout.
    #
    # Nếu WAITING:
    # Không reset.
    # Tin nhắn này có thể tiếp tục màn.
    # ---------------------------------------------

    if game["state"] == "ACTIVE":

        if is_timeout(game):

            # Kết thúc màn cũ
            game["state"] = "WAITING"

            game["last_user"] = None

            game["last_move"] = None

            # Không return!
            #
            # Tin nhắn hiện tại vẫn được xử lý
            # như một lượt của màn mới.

    # ---------------------------------------------
    # KIỂM TRA KHÔNG ĐƯỢC NỐI LIÊN TIẾP
    # ---------------------------------------------

    if (
        game["last_user"] is not None
        and
        game["last_user"] == message.author.id
    ):

        await message.reply(
            "⛔ Bạn vừa nối lượt trước. "
            "Hãy chờ người chơi khác."
        )

        return

    # ---------------------------------------------
    # KIỂM TRA BẮT ĐẦU BẰNG TỪ CẦN NỐI
    # ---------------------------------------------

    required = game["required"]

    if not word.startswith(required):

        await message.reply(
            f"❌ Không hợp lệ!\n"
            f"👉 Cần nối bằng **`{required}`**."
        )

        return

    # ---------------------------------------------
    # KHÔNG LẶP
    # ---------------------------------------------

    if word in game["used"]:

        await message.reply(
            "♻️ Từ này đã được sử dụng trong màn này."
        )

        return

    # ---------------------------------------------
    # LOOKUP
    # ---------------------------------------------

    valid = await lookup_word(word)

    if not valid:

        await message.reply(
            f"❌ `{word}` không được tìm thấy "
            f"trong từ điển."
        )

        return

    # ---------------------------------------------
    # ĐÚNG
    # ---------------------------------------------

    game["word"] = word

    game["required"] = last_word(word)

    game["used"].add(word)

    game["last_user"] = message.author.id

    game["last_move"] = now()

    game["state"] = "ACTIVE"

    # ---------------------------------------------
    # SCORE
    # ---------------------------------------------

    user_id = message.author.id

    game["scores"][user_id] = (
        game["scores"].get(
            user_id,
            0
        ) + 1
    )

    # ---------------------------------------------
    # CHỈ REACT
    # ---------------------------------------------

    try:

        await message.add_reaction("✅")

    except Exception as e:

        print(
            "Cannot react:",
            e
        )

    # ---------------------------------------------
    # KIỂM TRA HẾT TỪ
    #
    # Không gửi ngay.
    #
    # Chỉ kiểm tra xem còn nước đi hay không.
    # Nếu hết -> bot thông báo.
    # ---------------------------------------------

    valid_moves = await get_valid_moves(
        game,
        1
    )

    if not valid_moves:

        await message.channel.send(
            f"🏁 Không còn từ hợp lệ để nối với "
            f"`{game['required']}`.\n"
            f"🎮 Màn này kết thúc."
        )

        game["state"] = "WAITING"

        game["last_user"] = None

        game["last_move"] = None


# =========================================================
# READY
# =========================================================

@bot.event
async def on_ready():

    print(
        f"✅ Đăng nhập thành công: "
        f"{bot.user}"
    )

    print(
        f"📡 Đang phục vụ {len(bot.guilds)} server."
    )


# =========================================================
# ERROR
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

    print(
        "COMMAND ERROR:",
        repr(error)
    )


# =========================================================
# RUN
# =========================================================

if not TOKEN:

    raise RuntimeError(
        "❌ Chưa cấu hình DISCORD_TOKEN trong .env"
    )

bot.run(TOKEN) 
