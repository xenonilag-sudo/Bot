# =========================================================
# messages.py
# Toàn bộ nội dung hiển thị cho người dùng
# =========================================================


# =========================================================
# GENERAL
# =========================================================

NO_GAME = (
    "❌ Chưa có màn nối từ.\n"
    "Dùng `{prefix}noitu` để bắt đầu."
)

GAME_ALREADY_RUNNING = (
    "❌ Kênh này đang có một màn chơi.\n"
    "👉 Từ cần nối: **`{required}`**"
)

GAME_STARTED = (
    "🔗 **NỐI TỪ — MÀN MỚI**\n\n"
    "Từ bắt đầu: `{word}`\n\n"
    "👉 Từ cần nối: **`{required}`**"
)

GAME_TIMEOUT = (
    "⏰ Màn chơi đã kết thúc do quá 3 giờ "
    "không có lượt nối.\n"
    "🔗 Dùng `{prefix}noitu` để bắt đầu màn mới."
)

GAME_STOPPED = (
    "🛑 Đã dừng game nối từ."
)

GAME_NO_MOVE = (
    "🏁 Không còn từ hợp lệ để nối với "
    "`{required}`.\n"
    "🎮 Màn này kết thúc."
)


# =========================================================
# MOVE
# =========================================================

INVALID_WORD_COUNT = (
    "❌ Từ nối phải có **2-3 từ**.\n"
    "Ví dụ: `sinh viên`, `viên chức`"
)

WRONG_REQUIRED = (
    "Không đúng từ cần nối!"
)

DUPLICATE_WORD = (
    "♻️ Từ này đã được sử dụng trong màn này."
)

WORD_NOT_FOUND = (
    "❌ `{word}` không được tìm thấy trong từ điển."
)

SAME_PLAYER = (
    "⛔ Bạn vừa nối lượt trước.\n"
    "Hãy chờ người chơi khác."
)

CORRECT_REACTION = "✅"


# =========================================================
# WRONG ATTEMPTS
# =========================================================

WRONG_THREE = (
    "⚠️ Bạn đã nối sai {max_attempts} lần.\n"
    "Một lần sai nữa sẽ reset màn chơi."
)

GAME_RESET_WRONG = (
    "🔄 Màn chơi đã reset do nối sai quá nhiều lần."
)


# =========================================================
# HINT
# =========================================================

HINT_LIMIT = (
    "❌ Bạn đã dùng hết {limit} lần gợi ý hôm nay."
)

HINT_EMPTY = (
    "💀 Không tìm thấy từ nào có thể nối với "
    "`{required}`.\n"
    "🏁 Màn kết thúc."
)

HINT_TITLE = "💡 Gợi ý"

HINT_CONTENT = (
    "Từ cần nối: **`{required}`**\n"
    "Còn lại: **{remaining}/{limit}** lần gợi ý"
)

HINT_MOVES_TITLE = "Có thể thử"


# =========================================================
# BOT
# =========================================================

BOT_MOVE = (
    "🤖 Yuki nối: **{word}**\n"
    "👉 Cần nối: **`{required}`**"
)


# =========================================================
# MONEY
# =========================================================

BALANCE = (
    "💰 **Số dư của {user}:** `{balance}` xu"
)

COIN_EARNED = (
    "💰 +{amount} xu"
)

NOT_ENOUGH_MONEY = (
    "❌ Bạn không đủ xu.\n"
    "💰 Cần: `{price}` xu\n"
    "💰 Bạn có: `{balance}` xu"
)

PURCHASE_SUCCESS = (
    "🛒 Đã mua **{item}** với giá `{price}` xu.\n"
    "💰 Số dư còn lại: `{balance}` xu"
)

ITEM_NOT_FOUND = (
    "❌ Không tìm thấy vật phẩm `{item}`."
)


# =========================================================
# INVENTORY
# =========================================================

INVENTORY_EMPTY = (
    "🎒 Túi đồ của bạn đang trống."
)

INVENTORY_TITLE = (
    "🎒 Túi đồ"
)

INVENTORY_MUTE = (
    "🔇 Mute: `{quantity}` cái"
)


# =========================================================
# MUTE
# =========================================================

MUTE_SUCCESS = (
    "🔇 Đã sử dụng **Mute** lên {user}.\n"
    "⏱️ Người chơi này sẽ không thể tham gia "
    "Nối Từ trong **{minutes} phút**."
)

MUTE_SELF = (
    "❌ Bạn không thể mute chính mình."
)

MUTE_BOT = (
    "❌ Bạn không thể mute bot."
)

MUTE_NO_PERMISSION = (
    "❌ Bạn không thể sử dụng vật phẩm này."
)

NO_MUTE_ITEM = (
    "❌ Bạn không có vật phẩm **Mute**.\n"
    "🛒 Mua trong shop bằng `{prefix}buy mute`."
)

MUTE_USAGE = (
    "❌ Cách dùng: `{prefix}use mute @user`"
)


# =========================================================
# SHOP
# =========================================================

SHOP_TITLE = (
    "🛒 SHOP"
)

SHOP_MUTE = (
    "🔇 **Mute**\n"
    "Giá: `{price}` xu\n"
    "Tác dụng: Khóa một người chơi khỏi Nối Từ "
    "trong `{minutes}` phút."
)

SHOP_FOOTER = (
    "Mua bằng `{prefix}buy mute`"
)

BUY_USAGE = (
    "❌ Cách dùng: `{prefix}buy <item>`\n"
    "Ví dụ: `{prefix}buy mute`"
)


# =========================================================
# HELP
# =========================================================

HELP_TITLE = (
    "📖 Hướng dẫn — Nối từ"
)

HELP_DESCRIPTION = (
    "🔗 Game nối từ tiếng Việt\n"
    "By yuki and xenoliag."
)

HELP_START = (
    "`{prefix}noitu`\n"
    "Bắt đầu bằng từ ngẫu nhiên.\n\n"
    "`{prefix}noitu học sinh`\n"
    "Bắt đầu bằng từ bạn chọn."
)

HELP_PLAY = (
    "Từ đầu tiên của lượt mới phải trùng "
    "với từ cuối của lượt trước.\n\n"
    "Ví dụ:\n"
    "`học sinh` → `sinh viên` → `viên chức`"
)

HELP_RULES = (
    "• Mỗi lượt có 2-3 từ.\n"
    "• Không được dùng lại từ.\n"
    "• Không được nối hai lượt liên tiếp.\n"
    "• Từ phải tồn tại trong từ điển.\n"
    "• Nối đúng → ✅ và nhận xu.\n"
    "• Sai 3 lần → cảnh báo.\n"
    "• Sai lần 4 → reset màn.\n"
    "• Bot có 30% tỉ lệ nối tiếp.\n"
    "• Không có lượt trong 3 giờ → kết thúc."
)

HELP_ECONOMY = (
    "💰 `{prefix}money` — xem số dư.\n"
    "🛒 `{prefix}shop` — xem shop.\n"
    "🛍️ `{prefix}buy mute` — mua Mute.\n"
    "🎒 `{prefix}inventory` — xem túi đồ.\n"
    "🔇 `{prefix}use mute @user` — sử dụng Mute."
)

HELP_OTHER = (
    "💡 `{prefix}kho` — xin gợi ý "
    "(5 lần/ngày).\n"
    "🏆 `{prefix}diem` — xem bảng điểm.\n"
    "🛑 `{prefix}dungnoitu` — dừng game."
)

HELP_FOOTER = (
    "Dictionary API: dict.minhqnd.com"
)
