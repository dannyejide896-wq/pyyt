import logging
import os

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

import sports

logging.basicConfig(
    format="%(asctime)s %(name)s %(levelname)s: %(message)s", level=logging.INFO
)
log = logging.getLogger("sports-bot")

BOT_TOKEN = os.environ["BOT_TOKEN"]
DEFAULT_SPORT = "football"


def sport_arg(context: ContextTypes.DEFAULT_TYPE, default: str = DEFAULT_SPORT) -> str:
    return context.args[0].lower() if context.args else default


async def reply(update: Update, text: str | None):
    if text is None:
        text = "Unknown sport. Send /sports to see the available ones."
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply(
        update,
        "🏆 <b>Sports News Bot</b>\n\n"
        "Latest sports news, live scores, match results, fixtures and "
        "team updates, all in one place.\n\n"
        "/scores &lt;sport&gt; – today's matches\n"
        "/fixtures &lt;sport&gt; – upcoming games\n"
        "/news &lt;sport&gt; – latest headlines\n"
        "/transfers – football transfer news\n"
        "/sports – list of sports\n\n"
        "Example: <code>/scores nba</code>",
    )


async def sports_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply(update, sports.sports_list_text())


async def scores(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply(update, await sports.get_scores(sport_arg(context)))


async def fixtures(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply(update, await sports.get_fixtures(sport_arg(context)))


async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply(update, await sports.get_news(sport_arg(context, default="all")))


async def transfers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply(update, await sports.get_transfers())


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.exception("Unhandled error", exc_info=context.error)
    if isinstance(update, Update) and update.message:
        await update.message.reply_text("⚠️ Something went wrong. Please try again.")


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler(["start", "help"], start))
    app.add_handler(CommandHandler("sports", sports_cmd))
    app.add_handler(CommandHandler("scores", scores))
    app.add_handler(CommandHandler("fixtures", fixtures))
    app.add_handler(CommandHandler("news", news))
    app.add_handler(CommandHandler("transfers", transfers))
    app.add_error_handler(on_error)
    log.info("Bot starting...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
