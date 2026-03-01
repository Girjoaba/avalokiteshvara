"""/start, /help, /cancel, settings handlers."""

from __future__ import annotations

from datetime import datetime, timezone

from telegram import Update
from telegram.ext import ContextTypes

from ..api_client import ArkeAPIClient
from ..formatters import HELP_TEXT, WELCOME_TEXT, format_connected, format_settings
from ..keyboards import back_to_menu_keyboard, main_menu_keyboard, settings_keyboard
from .common import answer_callback, clear_awaiting, ensure_configured, get_client


# ------------------------------------------------------------------
# /start
# ------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    context.user_data["awaiting_input"] = "api_url"
    await update.message.reply_text(WELCOME_TEXT, parse_mode="HTML")  # type: ignore[union-attr]


async def handle_api_url_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    url = update.message.text.strip().rstrip("/")  # type: ignore[union-attr]

    if not url.startswith(("http://", "https://")):
        await update.message.reply_text(  # type: ignore[union-attr]
            "\u274c Please enter a valid URL starting with "
            "<code>http://</code> or <code>https://</code>",
            parse_mode="HTML",
        )
        return

    client = ArkeAPIClient(url)

    try:
        await client.authenticate()
    except Exception as exc:
        await update.message.reply_text(  # type: ignore[union-attr]
            f"\u274c Failed to authenticate with <code>{url}</code>\n"
            f"<code>{exc}</code>\n\nPlease check the URL and try again.",
            parse_mode="HTML",
        )
        return

    context.user_data["api_base_url"] = url
    context.user_data["api_client"] = client
    clear_awaiting(context)

    await update.message.reply_text(  # type: ignore[union-attr]
        format_connected(url),
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )


# ------------------------------------------------------------------
# /help
# ------------------------------------------------------------------

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(  # type: ignore[union-attr]
        HELP_TEXT,
        parse_mode="HTML",
        reply_markup=back_to_menu_keyboard(),
    )


# ------------------------------------------------------------------
# /cancel
# ------------------------------------------------------------------

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    was_awaiting = context.user_data.get("awaiting_input")
    clear_awaiting(context)
    if was_awaiting:
        await update.message.reply_text(  # type: ignore[union-attr]
            "\u274c Input cancelled.",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )
    else:
        await update.message.reply_text(  # type: ignore[union-attr]
            "Nothing to cancel. Use /menu for the main menu."
        )


async def cb_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    clear_awaiting(context)
    await update.callback_query.edit_message_text(  # type: ignore[union-attr]
        "\u274c Input cancelled.",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )


# ------------------------------------------------------------------
# Settings
# ------------------------------------------------------------------

async def cb_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    clear_awaiting(context)
    url = context.user_data.get("api_base_url") or "(not set)"
    client = get_client(context)
    sim_now = client.get_sim_now() if client else None
    sim_rate = client._sim_rate if client else 1.0
    await update.callback_query.edit_message_text(  # type: ignore[union-attr]
        format_settings(url, sim_now=sim_now, sim_rate=sim_rate),
        parse_mode="HTML",
        reply_markup=settings_keyboard(),
    )


async def cb_change_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    context.user_data["awaiting_input"] = "api_url"
    await update.callback_query.edit_message_text(  # type: ignore[union-attr]
        "\U0001f517 Enter the new API base URL:",
        parse_mode="HTML",
    )


# ------------------------------------------------------------------
# Simulation clock settings
# ------------------------------------------------------------------

async def cb_set_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    client = await ensure_configured(update, context)
    if not client:
        return
    context.user_data["awaiting_input"] = "set_time"
    await update.callback_query.edit_message_text(  # type: ignore[union-attr]
        "\U0001f552 <b>Set Simulation Time</b>\n\n"
        "Enter the new UTC time in one of these formats:\n"
        "<code>2026-03-01 08:00</code>\n"
        "<code>2026-03-01T08:00:00</code>\n\n"
        "Or type <code>now</code> to reset to real UTC time.",
        parse_mode="HTML",
    )


async def cb_set_rate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    client = await ensure_configured(update, context)
    if not client:
        return
    context.user_data["awaiting_input"] = "set_rate"
    await update.callback_query.edit_message_text(  # type: ignore[union-attr]
        "\u23e9 <b>Set Time Rate</b>\n\n"
        "Enter a multiplier for simulation speed:\n"
        "<code>1</code> = real-time\n"
        "<code>60</code> = 1 real second = 1 sim minute\n"
        "<code>3600</code> = 1 real second = 1 sim hour\n\n"
        f"Current rate: <code>{client._sim_rate}x</code>",
        parse_mode="HTML",
    )


async def cb_reset_clock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    client = await ensure_configured(update, context)
    if not client:
        return
    client.reset_sim_clock()
    url = context.user_data.get("api_base_url") or "(not set)"
    await update.callback_query.edit_message_text(  # type: ignore[union-attr]
        "\u2705 Clock reset to real UTC time at 1x speed.\n\n"
        + format_settings(url, sim_now=client.get_sim_now(), sim_rate=client._sim_rate),
        parse_mode="HTML",
        reply_markup=settings_keyboard(),
    )


async def handle_set_time_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    client = await ensure_configured(update, context)
    if not client:
        return

    text = update.message.text.strip()  # type: ignore[union-attr]
    if text.lower() == "now":
        client.reset_sim_clock()
        clear_awaiting(context)
        url = context.user_data.get("api_base_url") or "(not set)"
        await update.message.reply_text(  # type: ignore[union-attr]
            "\u2705 Clock reset to real UTC time.\n\n"
            + format_settings(url, sim_now=client.get_sim_now(), sim_rate=client._sim_rate),
            parse_mode="HTML",
            reply_markup=settings_keyboard(),
        )
        return

    dt = None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            dt = datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
            break
        except ValueError:
            continue

    if dt is None:
        await update.message.reply_text(  # type: ignore[union-attr]
            "\u274c Invalid format. Use <code>YYYY-MM-DD HH:MM</code> or <code>now</code>.",
            parse_mode="HTML",
        )
        return

    client.set_sim_time(dt)
    clear_awaiting(context)
    url = context.user_data.get("api_base_url") or "(not set)"
    await update.message.reply_text(  # type: ignore[union-attr]
        f"\u2705 Simulation time set to <code>{dt.strftime('%Y-%m-%d %H:%M:%S')} UTC</code>\n\n"
        + format_settings(url, sim_now=client.get_sim_now(), sim_rate=client._sim_rate),
        parse_mode="HTML",
        reply_markup=settings_keyboard(),
    )


async def handle_set_rate_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    client = await ensure_configured(update, context)
    if not client:
        return

    text = update.message.text.strip()  # type: ignore[union-attr]
    try:
        rate = float(text)
        if rate <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(  # type: ignore[union-attr]
            "\u274c Please enter a positive number (e.g. <code>1</code>, <code>60</code>, <code>3600</code>).",
            parse_mode="HTML",
        )
        return

    client.set_sim_rate(rate)
    clear_awaiting(context)
    url = context.user_data.get("api_base_url") or "(not set)"
    rate_label = "real-time" if rate == 1.0 else f"{rate}x"
    await update.message.reply_text(  # type: ignore[union-attr]
        f"\u2705 Time rate set to <code>{rate_label}</code>\n\n"
        + format_settings(url, sim_now=client.get_sim_now(), sim_rate=client._sim_rate),
        parse_mode="HTML",
        reply_markup=settings_keyboard(),
    )
