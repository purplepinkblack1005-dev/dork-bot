import os
import io
import logging
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL")
PORT = int(os.getenv("PORT", "10000"))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INURL_FILE = os.path.join(BASE_DIR, "shop.txt")
KEYWORDS_FILE = os.path.join(BASE_DIR, "keywords.txt")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ASK_KEYWORD, ASK_TARGETS = range(2)


def load_wordlist(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip()]


def build_site_filter(raw):
    raw = raw.strip().lower()
    if raw in ("", "none", "no", "-"):
        return ""
    parts = [p.strip().lstrip(".") for p in raw.split(",") if p.strip()]
    if not parts:
        return ""
    if len(parts) == 1:
        return f"site:.{parts[0]}"
    return "(" + " OR ".join(f"site:.{p}" for p in parts) + ")"


def generate_dorks(keywords, inurl_words, keyword_words, site_filter=""):
    suffix = f" {site_filter}" if site_filter else ""
    return [
        f"inurl:{iu} intext:({kw}) {kww}{suffix}"
        for kw in keywords
        for iu in inurl_words
        for kww in keyword_words
    ]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔍 *Dork Bot*\n\nSend /create to begin.\n\n"
        "You'll be asked:\n"
        "1. What to look for (e.g. `braintree`)\n"
        "2. Target sites (e.g. `uk, us, au` or `none`)",
        parse_mode="Markdown",
    )


async def create_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "🔎 *What to look for?*\n"
        "Examples: `braintree` or `braintree, woocommerce`\n\n"
        "Send /cancel to abort.",
        parse_mode="Markdown",
    )
    return ASK_KEYWORD


async def ask_targets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keywords = [k.strip().upper() for k in update.message.text.split(",") if k.strip()]
    if not keywords:
        await update.message.reply_text("❌ Try again or /cancel.")
        return ASK_KEYWORD
    context.user_data["keywords"] = keywords
    await update.message.reply_text(
        "🌍 *Target sites?*\n"
        "Examples: `uk`, `uk, us, au`, or `none`\n\n"
        "Send /cancel to abort.",
        parse_mode="Markdown",
    )
    return ASK_TARGETS


async def generate_and_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    site_filter = build_site_filter(update.message.text)
    keywords = context.user_data.get("keywords", [])
    if not keywords:
        await update.message.reply_text("❌ Session expired. Send /create")
        return ConversationHandler.END

    inurl_words = load_wordlist(INURL_FILE)
    keyword_words = load_wordlist(KEYWORDS_FILE)
    if not inurl_words:
        await update.message.reply_text(f"❌ `{os.path.basename(INURL_FILE)}` missing/empty.", parse_mode="Markdown")
        return ConversationHandler.END
    if not keyword_words:
        await update.message.reply_text(f"❌ `{os.path.basename(KEYWORDS_FILE)}` missing/empty.", parse_mode="Markdown")
        return ConversationHandler.END

    dorks = generate_dorks(keywords, inurl_words, keyword_words, site_filter)
    target_display = site_filter or "none"

    await update.message.reply_text(
        f"✅ Generating *{len(dorks)}* dorks\n"
        f"Keywords: `{', '.join(keywords)}`\n"
        f"Targets: `{target_display}`",
        parse_mode="Markdown",
    )

    buf = io.BytesIO(("\n".join(dorks) + "\n").encode("utf-8"))
    await update.message.reply_document(
        document=buf,
        filename="dorks.txt",
        caption=f"📄 {len(dorks)} dorks | {', '.join(keywords)} | {target_display}"[:1024],
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END


def build_app():
    app = Application.builder().token(BOT_TOKEN).updater(None).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("create", create_start)],
        states={
            ASK_KEYWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_targets)],
            ASK_TARGETS: [MessageHandler(filters.TEXT & ~filters.COMMAND, generate_and_send)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(conv)
    return app


if __name__ == "__main__":
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN not set")

    app = build_app()

    if RENDER_URL:
        # Running on Render → webhook mode
        webhook_path = BOT_TOKEN
        webhook_url = f"{RENDER_URL}/{webhook_path}"
        logger.info(f"Starting webhook on {webhook_url}")
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=webhook_path,
            webhook_url=webhook_url,
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        # Local dev → polling
        logger.info("Starting polling (local dev)")
        app.run_polling(allowed_updates=Update.ALL_TYPES)
