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

# ------------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL")
PORT = int(os.getenv("PORT", "10000"))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INURL_FILE = os.path.join(BASE_DIR, "shop.txt")
KEYWORDS_FILE = os.path.join(BASE_DIR, "keywords.txt")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Conversation states
ASK_KEYWORD, ASK_TARGETS = range(2)


# ------------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------------
def load_wordlist(path: str) -> list[str]:
    """Load a wordlist file, stripping whitespace and skipping empty lines."""
    if not os.path.exists(path):
        logger.warning(f"Wordlist not found: {path}")
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def build_site_filter(raw: str) -> str:
    """
    Turn 'uk, us, au' into '(site:.uk OR site:.us OR site:.au)'
    Return '' for none/empty.
    """
    raw = raw.strip().lower()
    if raw in ("", "none", "no", "-", "null", "skip"):
        return ""
    parts = [p.strip().lstrip(".") for p in raw.split(",") if p.strip()]
    if not parts:
        return ""
    if len(parts) == 1:
        return f"site:.{parts[0]}"
    return "(" + " OR ".join(f"site:.{p}" for p in parts) + ")"


def generate_dorks(
    keywords: list[str],
    inurl_words: list[str],
    keyword_words: list[str],
    site_filter: str = "",
) -> list[str]:
    """
    Format:
        inurl:<inurl_word> intext:(<KEYWORD>) <keyword_word> [site filter]
    """
    suffix = f" {site_filter}" if site_filter else ""
    dorks = []
    for kw in keywords:
        for iu in inurl_words:
            for kww in keyword_words:
                dorks.append(f"inurl:{iu} intext:({kw}) {kww}{suffix}")
    return dorks


# ------------------------------------------------------------------
# HANDLERS
# ------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔍 *Dork Generator Bot*\n\n"
        "Send /create to begin.\n\n"
        "You'll be asked:\n"
        "1. What to look for (e.g. `braintree`)\n"
        "2. Target sites (e.g. `uk, us, au` or `none`)\n\n"
        "Result is sent as `dorks.txt`.\n\n"
        "Commands:\n"
        "/create — start\n"
        "/status — check wordlists\n"
        "/cancel — abort",
        parse_mode="Markdown",
    )


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    inurl_words = load_wordlist(INURL_FILE)
    keyword_words = load_wordlist(KEYWORDS_FILE)
    await update.message.reply_text(
        f"📋 *Wordlists loaded:*\n"
        f"• `shop.txt`: {len(inurl_words)} lines\n"
        f"• `keywords.txt`: {len(keyword_words)} lines",
        parse_mode="Markdown",
    )


async def create_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "🔎 *What to look for?*\n\n"
        "Examples:\n"
        "• `braintree`\n"
        "• `braintree, woocommerce`\n"
        "• `stripe, paypal`\n\n"
        "Send /cancel to abort.",
        parse_mode="Markdown",
    )
    return ASK_KEYWORD


async def ask_targets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.strip()
    keywords = [k.strip().upper() for k in raw.split(",") if k.strip()]

    if not keywords:
        await update.message.reply_text(
            "❌ No valid keyword. Try again or send /cancel."
        )
        return ASK_KEYWORD

    context.user_data["keywords"] = keywords

    await update.message.reply_text(
        "🌍 *Target sites?*\n\n"
        "Examples:\n"
        "• `uk`\n"
        "• `uk, us, au`\n"
        "• `none` (no site restriction)\n\n"
        "Send /cancel to abort.",
        parse_mode="Markdown",
    )
    return ASK_TARGETS


async def generate_and_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_targets = update.message.text.strip()
    site_filter = build_site_filter(raw_targets)

    keywords = context.user_data.get("keywords", [])
    if not keywords:
        await update.message.reply_text("❌ Session expired. Send /create again.")
        return ConversationHandler.END

    inurl_words = load_wordlist(INURL_FILE)
    keyword_words = load_wordlist(KEYWORDS_FILE)

    if not inurl_words:
        await update.message.reply_text(
            "❌ `shop.txt` is missing or empty.",
            parse_mode="Markdown",
        )
        return ConversationHandler.END
    if not keyword_words:
        await update.message.reply_text(
            "❌ `keywords.txt` is missing or empty.",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    dorks = generate_dorks(keywords, inurl_words, keyword_words, site_filter)
    total = len(dorks)
    target_display = site_filter if site_filter else "none"

    await update.message.reply_text(
        f"✅ Generating *{total}* dorks\n"
        f"Keywords: `{', '.join(keywords)}`\n"
        f"Targets: `{target_display}`\n\n"
        f"Sending as `dorks.txt`...",
        parse_mode="Markdown",
    )

    content = "\n".join(dorks) + "\n"
    file_bytes = io.BytesIO(content.encode("utf-8"))

    caption = (
        f"📄 dorks.txt — {total} dorks\n"
        f"Keywords: {', '.join(keywords)}\n"
        f"Targets: {target_display}"
    )[:1024]

    await update.message.reply_document(
        document=file_bytes,
        filename="dorks.txt",
        caption=caption,
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Cancelled. Send /create to start again.")
    return ConversationHandler.END


# ------------------------------------------------------------------
# APP BUILDER
# ------------------------------------------------------------------
def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).updater(None).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("create", create_start)],
        states={
            ASK_KEYWORD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_targets)
            ],
            ASK_TARGETS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, generate_and_send)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(conv)

    return app


# ------------------------------------------------------------------
# ENTRY POINT
# ------------------------------------------------------------------
if __name__ == "__main__":
    if not BOT_TOKEN:
        raise SystemExit("❌ BOT_TOKEN not set in environment variables.")

    app = build_app()

    if RENDER_URL:
        # Running on Render → webhook mode (Web Service)
        webhook_path = BOT_TOKEN
        webhook_url = f"{RENDER_URL}/{webhook_path}"
        logger.info(f"Starting webhook mode on {webhook_url}")
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=webhook_path,
            webhook_url=webhook_url,
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        # Local dev → polling mode
        logger.info("Starting polling mode (local dev)")
        app.run_polling(allowed_updates=Update.ALL_TYPES)
