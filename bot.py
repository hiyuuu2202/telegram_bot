import os
import random
import logging

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

from openai import OpenAI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("motivation-bot")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")
if not OPENAI_API_KEY:
    raise RuntimeError("Missing OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)

MAIN_KB = ReplyKeyboardMarkup(
    [["🔥 Cho tôi 1 câu", "🌤️ Tích cực", "😈 Hơi gắt", "🕳️ Dark", "🎯 5 phút bắt đầu"]],
    resize_keyboard=True
)

SYSTEM_STYLE = (
    "Bạn là một coach tạo câu nói ngắn kéo người dùng ra khỏi trì hoãn.\n"
    "Yêu cầu:\n"
    "- Tiếng Việt tự nhiên, 1-2 câu, có thể hài hước.\n"
    "- Kết thúc bằng 1 hành động nhỏ làm trong 5 phút.\n"
    "- Không được cổ vũ tự hại, bạo lực, thù ghét.\n"
    "- Không chẩn đoán y khoa, không đưa lời khuyên y tế.\n"
)

def build_prompt(mode: str) -> str:
    if mode == "positive":
        tone = "tích cực, ấm áp"
    elif mode == "tough":
        tone = "thẳng thắn, hơi cà khịa nhưng không xúc phạm"
    elif mode == "dark":
        tone = "hard-truth, đen tối có kiểm soát nhưng vẫn an toàn"
    else:
        tone = random.choice(["tích cực", "hơi gắt", "hard-truth an toàn"])

    return (
        f"Tạo 1 câu động lực theo tone: {tone}. "
        "Bối cảnh: người dùng đang mất động lực làm việc và trì hoãn. "
        "Độ dài: 1-2 câu. Kết thúc bằng 1 việc làm ngay trong 5 phút."
    )

def gen_quote(mode: str) -> str:
    resp = client.responses.create(
        model=OPENAI_MODEL,
        instructions=SYSTEM_STYLE,
        input=build_prompt(mode),
        max_output_tokens=120,
    )
    text = (resp.output_text or "").strip()
    return text if text else "Ok, làm 1 bước nhỏ thôi: mở task lên và viết 1 dòng đầu tiên trong 5 phút."

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Chào bạn. Bấm nút hoặc dùng lệnh:\n"
        "/motivation (random)\n"
        "/soft (tích cực)\n"
        "/tough (hơi gắt)\n"
        "/dark (dark)\n"
        "/five (chế độ 5 phút)\n",
        reply_markup=MAIN_KB
    )

async def send_quote(update: Update, mode: str) -> None:
    try:
        await update.message.reply_text(gen_quote(mode), reply_markup=MAIN_KB)
    except Exception as e:
        logger.exception("OpenAI error")
        await update.message.reply_text(f"⚠️ Lỗi gọi OpenAI API: {e}")

async def motivation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_quote(update, "random")

async def soft(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_quote(update, "positive")

async def tough(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_quote(update, "tough")

async def dark(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_quote(update, "dark")

async def five(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    steps = [
        "1) Mở đúng file/tab/task cần làm",
        "2) Tắt thông báo 5 phút",
        "3) Làm hành động nhỏ nhất (viết tiêu đề / tạo TODO / viết 1 dòng)",
        "4) Nếu vẫn kẹt: bấm 🔥 hoặc gõ /motivation"
    ]
    await update.message.reply_text("🎯 Chế độ 5 phút bắt đầu:\n" + "\n".join(steps), reply_markup=MAIN_KB)

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip()
    if text == "🔥 Cho tôi 1 câu":
        await send_quote(update, "random")
    elif text == "🌤️ Tích cực":
        await send_quote(update, "positive")
    elif text == "😈 Hơi gắt":
        await send_quote(update, "tough")
    elif text == "🕳️ Dark":
        await send_quote(update, "dark")
    elif text == "🎯 5 phút bắt đầu":
        await five(update, context)
    else:
        await send_quote(update, "random")

def main() -> None:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("motivation", motivation))
    app.add_handler(CommandHandler("soft", soft))
    app.add_handler(CommandHandler("tough", tough))
    app.add_handler(CommandHandler("dark", dark))
    app.add_handler(CommandHandler("five", five))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    print("Bot is running (polling)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
