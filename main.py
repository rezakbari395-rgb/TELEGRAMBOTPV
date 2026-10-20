"""
ربات پیوی تلگرام (Telegram PV / Contact Bot)
aiogram 3.x  +  SQLite
"""
import asyncio
import html
import logging
import os
import sys
import time
from collections import defaultdict, deque
from datetime import datetime

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatType, ParseMode
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BusinessConnection,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    Message,
    ReactionTypeEmoji,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

from db import DB

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("pvbot")

TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMINS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x.strip().isdigit()}
if not TOKEN or not ADMINS:
    sys.exit("❌ فایل .env را کامل کن: 8573209748:AAFPSMzfrMXssS6uiiZydMD74_IecKMs6q8 و 1143598012")

db = DB(os.getenv("DB_PATH", "bot.db"))
bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

admin_router = Router(name="admin")
user_router = Router(name="user")
admin_router.message.filter(F.chat.type == ChatType.PRIVATE, F.from_user.id.in_(ADMINS))
admin_router.callback_query.filter(F.from_user.id.in_(ADMINS))
user_router.message.filter(F.chat.type == ChatType.PRIVATE)

LINE = "━━━━━━━━━━━━━━━━"


# ════════════════════════════ ابزارها ════════════════════════════
def esc(s) -> str:
    return html.escape(str(s or ""))


def full_name(u) -> str:
    name = f"{u['first_name'] or ''} {u['last_name'] or ''}".strip()
    return name or "بدون‌نام"


def fmt_ts(ts) -> str:
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts).strftime("%Y/%m/%d  %H:%M")


def num(n: int) -> str:
    return f"{n:,}"


async def safe_edit(cb: CallbackQuery, text: str, kb: InlineKeyboardMarkup | None = None):
    try:
        await cb.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    except TelegramBadRequest as e:
        if "not modified" not in str(e):
            raise


def user_card(u) -> str:
    status = "🚫 مسدود" if u["banned"] else ("💤 ربات را بلاک کرده" if u["blocked"] else "🟢 فعال")
    uname = f"@{esc(u['username'])}" if u["username"] else "—"
    return (
        f"👤 <b>{esc(full_name(u))}</b>\n{LINE}\n"
        f"🆔 آیدی: <code>{u['id']}</code>\n"
        f"🔗 یوزرنیم: {uname}\n"
        f"📅 عضویت: {fmt_ts(u['joined_at'])}\n"
        f"🕒 آخرین فعالیت: {fmt_ts(u['last_seen'])}\n"
        f"💬 تعداد پیام‌ها: {num(u['msg_count'])}\n"
        f"📌 وضعیت: {status}"
    )


def user_actions_kb(u, back: str | None = None) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="💬 ارسال پیام", callback_data=f"u:msg:{u['id']}")
    if u["banned"]:
        b.button(text="✅ رفع مسدودی", callback_data=f"u:unban:{u['id']}")
    else:
        b.button(text="🚫 مسدود کردن", callback_data=f"u:ban:{u['id']}")
    b.button(text="🔗 پروفایل", url=f"tg://user?id={u['id']}")
    if back:
        b.button(text="⬅️ بازگشت", callback_data=back)
    b.adjust(2, 1, 1)
    return b.as_markup()


def incoming_kb(uid: int, name: str, banned: bool = False) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=f"👤 {name[:24]}", callback_data=f"u:info:{uid}")
    b.button(text="💬 پیام مستقیم", callback_data=f"u:msg:{uid}")
    b.button(text="✅ رفع بن" if banned else "🚫 مسدود", callback_data=f"u:{'unban' if banned else 'ban'}:{uid}")
    b.adjust(1, 2)
    return b.as_markup()


# ════════════════════════════ پنل ادمین ════════════════════════════
def not_cmd(m: Message) -> bool:
    """پیام‌هایی که با / شروع نمی‌شوند (شامل مدیا بدون متن)."""
    return not (m.text or "").startswith("/")


class Broadcast(StatesGroup):
    content = State()
    confirm = State()


class Search(StatesGroup):
    query = State()


class DirectMsg(StatesGroup):
    content = State()


class EditSetting(StatesGroup):
    value = State()


async def panel_text() -> str:
    s = await db.stats()
    on = (await db.get("enabled")) == "1"
    return (
        "🎛 <b>پنل مدیریت ربات</b>\n"
        f"{LINE}\n"
        f"👥 کاربران: <b>{num(s['users'])}</b>   |   🆕 امروز: <b>{num(s['new24'])}</b>\n"
        f"📥 پیام‌های امروز: <b>{num(s['in24'])}</b>   |   📤 پاسخ‌ها: <b>{num(s['out24'])}</b>\n"
        f"🚫 مسدود: <b>{num(s['banned'])}</b>\n"
        f"{LINE}\n"
        f"وضعیت ربات: {'🟢 روشن' if on else '🔴 خاموش'}\n\n"
        "💡 برای پاسخ به کاربر، روی پیامش <b>ریپلای</b> کن."
    )


def panel_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📊 آمار کامل", callback_data="p:stats")
    b.button(text="👥 کاربران", callback_data="p:users:0")
    b.button(text="🔍 جستجوی کاربر", callback_data="p:search")
    b.button(text="🚫 لیست مسدودها", callback_data="p:bans:0")
    b.button(text="📢 پیام همگانی", callback_data="p:bc")
    b.button(text="⚙️ تنظیمات", callback_data="p:set")
    b.adjust(2, 2, 1, 1)
    return b.as_markup()


def back_kb(to: str = "p:home") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ بازگشت", callback_data=to)]])


@admin_router.message(CommandStart())
@admin_router.message(Command("panel"))
async def admin_panel(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(await panel_text(), reply_markup=panel_kb())


@admin_router.message(Command("cancel"))
async def admin_cancel(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("❎ لغو شد.", reply_markup=panel_kb())


@admin_router.callback_query(F.data == "p:home")
async def cb_home(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_edit(cb, await panel_text(), panel_kb())
    await cb.answer()


@admin_router.callback_query(F.data == "p:stats")
async def cb_stats(cb: CallbackQuery):
    s = await db.stats()
    text = (
        "📊 <b>آمار کامل</b>\n"
        f"{LINE}\n"
        f"👥 کل کاربران: <b>{num(s['users'])}</b>\n"
        f"🆕 عضو جدید (۲۴ساعت): <b>{num(s['new24'])}</b>\n"
        f"🔥 فعال (۲۴ساعت): <b>{num(s['active24'])}</b>\n"
        f"🚫 مسدود شده: <b>{num(s['banned'])}</b>\n"
        f"💤 بلاک‌کننده ربات: <b>{num(s['blocked'])}</b>\n"
        f"{LINE}\n"
        f"📥 پیام دریافتی: <b>{num(s['in_total'])}</b>  (امروز {num(s['in24'])})\n"
        f"📤 پاسخ ارسالی: <b>{num(s['out_total'])}</b>  (امروز {num(s['out24'])})"
    )
    await safe_edit(cb, text, back_kb())
    await cb.answer()


# ---------- لیست کاربران ----------
async def render_users(cb: CallbackQuery, page: int, banned_only: bool):
    users, total = await db.list_users(page, banned_only=banned_only)
    pages = max(1, (total + 7) // 8)
    page = min(page, pages - 1)
    kind = "bans" if banned_only else "users"
    title = "🚫 <b>کاربران مسدود</b>" if banned_only else "👥 <b>کاربران</b>"
    b = InlineKeyboardBuilder()
    for u in users:
        icon = "🚫" if u["banned"] else "👤"
        b.button(text=f"{icon} {full_name(u)[:22]}", callback_data=f"u:info:{u['id']}:{kind}:{page}")
    b.adjust(1)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ قبلی", callback_data=f"p:{kind}:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="noop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="بعدی ▶️", callback_data=f"p:{kind}:{page + 1}"))
    kb = b.as_markup()
    kb.inline_keyboard.append(nav)
    kb.inline_keyboard.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="p:home")])
    text = f"{title}\n{LINE}\nمجموع: <b>{num(total)}</b> نفر"
    if not users:
        text += "\n\nهنوز موردی وجود ندارد."
    await safe_edit(cb, text, kb)


@admin_router.callback_query(F.data.regexp(r"^p:(users|bans):\d+$"))
async def cb_users(cb: CallbackQuery):
    _, kind, page = cb.data.split(":")
    await render_users(cb, int(page), kind == "bans")
    await cb.answer()


@admin_router.callback_query(F.data == "noop")
async def cb_noop(cb: CallbackQuery):
    await cb.answer()


# ---------- مدیریت یک کاربر ----------
@admin_router.callback_query(F.data.startswith("u:info:"))
async def cb_user_info(cb: CallbackQuery):
    parts = cb.data.split(":")
    uid = int(parts[2])
    back = f"p:{parts[3]}:{parts[4]}" if len(parts) >= 5 else None
    u = await db.get_user(uid)
    if not u:
        return await cb.answer("کاربر پیدا نشد", show_alert=True)
    if back:
        await safe_edit(cb, user_card(u), user_actions_kb(u, back))
    else:
        await cb.message.answer(user_card(u), reply_markup=user_actions_kb(u))
    await cb.answer()


@admin_router.callback_query(F.data.regexp(r"^u:(ban|unban):\d+$"))
async def cb_ban(cb: CallbackQuery):
    _, action, uid = cb.data.split(":")
    uid = int(uid)
    if uid in ADMINS:
        return await cb.answer("نمی‌شه ادمین رو مسدود کرد 😅", show_alert=True)
    banned = action == "ban"
    await db.set_banned(uid, banned)
    u = await db.get_user(uid)
    await cb.answer("🚫 مسدود شد" if banned else "✅ مسدودی برداشته شد")
    # اگر روی کارت پیام ورودی یا کارت کاربر بود، کیبورد را به‌روز کن
    try:
        first = cb.message.reply_markup.inline_keyboard[0][0].callback_data or ""
        if first.startswith("u:info:"):  # پیام ورودی کاربر (ممکن است مدیا باشد)
            await cb.message.edit_reply_markup(reply_markup=incoming_kb(uid, full_name(u), bool(u["banned"])))
        else:  # کارت کاربر
            await cb.message.edit_text(user_card(u), reply_markup=user_actions_kb(u))
    except (TelegramBadRequest, AttributeError, IndexError):
        pass


# ---------- جستجو ----------
@admin_router.callback_query(F.data == "p:search")
async def cb_search(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Search.query)
    await safe_edit(
        cb,
        "🔍 <b>جستجوی کاربر</b>\n\nآیدی عددی، یوزرنیم یا بخشی از اسم را بفرست.\n/cancel برای لغو",
        back_kb(),
    )
    await cb.answer()


@admin_router.message(StateFilter(Search.query), F.text, ~F.text.startswith("/"))
async def search_do(m: Message, state: FSMContext):
    res = await db.search_users(m.text)
    await state.clear()
    if not res:
        return await m.answer("😕 چیزی پیدا نشد.", reply_markup=panel_kb())
    if len(res) == 1:
        u = res[0]
        return await m.answer(user_card(u), reply_markup=user_actions_kb(u))
    b = InlineKeyboardBuilder()
    for u in res:
        b.button(text=f"👤 {full_name(u)[:24]}", callback_data=f"u:info:{u['id']}")
    b.adjust(1)
    await m.answer(f"🔍 <b>{len(res)}</b> نتیجه:", reply_markup=b.as_markup())


# ---------- پیام مستقیم ----------
@admin_router.callback_query(F.data.startswith("u:msg:"))
async def cb_dm(cb: CallbackQuery, state: FSMContext):
    uid = int(cb.data.split(":")[2])
    await state.set_state(DirectMsg.content)
    await state.update_data(uid=uid)
    await cb.message.answer("💬 پیامت را بفرست (هر نوع محتوایی).\n/cancel برای لغو")
    await cb.answer()


@admin_router.message(StateFilter(DirectMsg.content), not_cmd)
async def dm_send(m: Message, state: FSMContext):
    uid = (await state.get_data())["uid"]
    await state.clear()
    ok = await deliver(m, uid)
    await m.answer("✅ ارسال شد." if ok else "❌ ارسال نشد (کاربر ربات را بلاک کرده).", reply_markup=panel_kb())


async def deliver(m: Message, uid: int) -> bool:
    try:
        await bot.copy_message(uid, m.chat.id, m.message_id)
        await db.log(uid, "out")
        return True
    except TelegramForbiddenError:
        await db.set_blocked(uid, True)
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        return await deliver(m, uid)
    except TelegramBadRequest as e:
        log.warning("deliver failed: %s", e)
    return False


# ---------- پیام همگانی ----------
@admin_router.callback_query(F.data == "p:bc")
async def cb_bc(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Broadcast.content)
    await safe_edit(
        cb,
        "📢 <b>پیام همگانی</b>\n\nپیامی که می‌خوای برای همه کاربران برود را بفرست "
        "(متن، عکس، ویدیو، فایل، ...).\n/cancel برای لغو",
        back_kb(),
    )
    await cb.answer()


@admin_router.message(StateFilter(Broadcast.content), not_cmd)
async def bc_preview(m: Message, state: FSMContext):
    ids = await db.broadcast_ids()
    await state.update_data(chat_id=m.chat.id, msg_id=m.message_id, count=len(ids))
    await state.set_state(Broadcast.confirm)
    await m.answer("👆 پیش‌نمایش پیام شما. مطمئنی؟")
    b = InlineKeyboardBuilder()
    b.button(text=f"✅ ارسال برای {num(len(ids))} نفر", callback_data="bc:go")
    b.button(text="❌ لغو", callback_data="bc:cancel")
    b.adjust(1)
    await bot.copy_message(m.chat.id, m.chat.id, m.message_id, reply_markup=b.as_markup())


@admin_router.callback_query(StateFilter(Broadcast.confirm), F.data == "bc:cancel")
async def bc_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.answer("❎ ارسال همگانی لغو شد.", reply_markup=panel_kb())
    await cb.answer()


@admin_router.callback_query(StateFilter(Broadcast.confirm), F.data == "bc:go")
async def bc_go(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    await cb.answer("🚀 شروع شد")
    status = await cb.message.answer("🚀 در حال ارسال...")
    asyncio.create_task(run_broadcast(status, data["chat_id"], data["msg_id"]))


async def run_broadcast(status: Message, chat_id: int, msg_id: int):
    ids = await db.broadcast_ids()
    ok = fail = 0
    total = len(ids)
    started = time.time()
    for i, uid in enumerate(ids, 1):
        try:
            await bot.copy_message(uid, chat_id, msg_id)
            ok += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                await bot.copy_message(uid, chat_id, msg_id)
                ok += 1
            except Exception:
                fail += 1
        except TelegramForbiddenError:
            await db.set_blocked(uid, True)
            fail += 1
        except Exception:
            fail += 1
        if i % 25 == 0:
            try:
                await status.edit_text(f"🚀 در حال ارسال...\n{i}/{total}  ✅ {ok}  ❌ {fail}")
            except Exception:
                pass
        await asyncio.sleep(0.05)
    took = int(time.time() - started)
    await status.edit_text(
        f"🏁 <b>ارسال همگانی تمام شد</b>\n{LINE}\n"
        f"✅ موفق: <b>{num(ok)}</b>\n❌ ناموفق: <b>{num(fail)}</b>\n⏱ زمان: {took} ثانیه",
        reply_markup=back_kb(),
    )


# ---------- تنظیمات ----------
async def settings_view() -> tuple[str, InlineKeyboardMarkup]:
    enabled = (await db.get("enabled")) == "1"
    confirm = (await db.get("confirm")) == "1"
    rate = await db.get("rate_limit")
    chan = await db.get("force_channel")
    biz = (await db.get("biz_enabled")) == "1"
    text = (
        "⚙️ <b>تنظیمات ربات</b>\n"
        f"{LINE}\n"
        f"💼 پاسخ خودکار Business: {'✅ فعال' if biz else '❌ غیرفعال'}\n"
        f"🔌 وضعیت ربات: {'🟢 روشن' if enabled else '🔴 خاموش'}\n"
        f"🧾 رسید برای کاربر: {'✅ فعال' if confirm else '❌ غیرفعال'}\n"
        f"🛡 ضد اسپم: {'<b>' + rate + '</b> پیام در دقیقه' if rate != '0' else 'غیرفعال'}\n"
        f"📣 جوین اجباری: {esc(chan) if chan else 'غیرفعال'}"
    )
    b = InlineKeyboardBuilder()
    b.button(text="🔴 خاموش کردن ربات" if enabled else "🟢 روشن کردن ربات", callback_data="s:toggle:enabled")
    b.button(text="🧾 رسید: " + ("خاموش کن" if confirm else "روشن کن"), callback_data="s:toggle:confirm")
    b.button(text="✏️ پیام خوش‌آمد", callback_data="s:edit:welcome")
    b.button(text="📨 متن رسید", callback_data="s:edit:sent_text")
    b.button(text="🔧 متن خاموشی", callback_data="s:edit:off_text")
    b.button(text="🔎 متن اینلاین", callback_data="s:edit:inline_text")
    b.button(text="🛡 ضد اسپم", callback_data="s:edit:rate_limit")
    b.button(text="📣 جوین اجباری", callback_data="s:edit:force_channel")
    b.button(text="💼 پاسخ خودکار Business: " + ("خاموش کن" if biz else "روشن کن"), callback_data="s:toggle:biz_enabled")
    b.button(text="💼 متن پاسخ Business", callback_data="s:edit:biz_text")
    b.button(text="⬅️ بازگشت", callback_data="p:home")
    b.adjust(1, 1, 2, 2, 2, 1, 1, 1)
    return text, b.as_markup()


@admin_router.callback_query(F.data == "p:set")
async def cb_settings(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    text, kb = await settings_view()
    await safe_edit(cb, text, kb)
    await cb.answer()


@admin_router.callback_query(F.data.startswith("s:toggle:"))
async def cb_toggle(cb: CallbackQuery):
    key = cb.data.split(":")[2]
    await db.set(key, "0" if (await db.get(key)) == "1" else "1")
    text, kb = await settings_view()
    await safe_edit(cb, text, kb)
    await cb.answer("✅ انجام شد")


EDIT_PROMPTS = {
    "welcome": "✏️ <b>پیام خوش‌آمد</b> جدید را بفرست.\nبرای درج اسم کاربر از <code>{name}</code> استفاده کن. فرمت (بولد، ایتالیک، ...) حفظ می‌شود.",
    "sent_text": "📨 متن جدید <b>رسید ارسال</b> را بفرست.",
    "off_text": "🔧 متنی که وقتی ربات خاموش است به کاربر نشان داده شود را بفرست.",
    "inline_text": "🔎 متنی که در حالت اینلاین (تایپ @ربات در هر چت) نمایش داده می‌شود را بفرست.",
    "biz_text": "💼 متن <b>پاسخ خودکار</b> برای کسانی که در پیوی اکانت شخصی‌ات پیام می‌دهند را بفرست.\nایموجی پرمیوم هم می‌تونی بذاری.",
    "rate_limit": "🛡 حداکثر <b>تعداد پیام در دقیقه</b> برای هر کاربر را به عدد بفرست.\n(0 = بدون محدودیت)",
    "force_channel": (
        "📣 <b>جوین اجباری</b>\n\nیوزرنیم کانال (مثل <code>@mychannel</code>) یا آیدی عددی آن را بفرست.\n"
        "⚠️ ربات باید در کانال <b>ادمین</b> باشد.\nبرای غیرفعال‌سازی بفرست: <code>off</code>"
    ),
}


@admin_router.callback_query(F.data.startswith("s:edit:"))
async def cb_edit(cb: CallbackQuery, state: FSMContext):
    key = cb.data.split(":")[2]
    await state.set_state(EditSetting.value)
    await state.update_data(key=key)
    cur = await db.get(key)
    extra = f"\n\n<b>مقدار فعلی:</b>\n{cur}" if key in ("welcome", "sent_text", "off_text", "inline_text", "biz_text") else ""
    await safe_edit(cb, EDIT_PROMPTS[key] + extra + "\n\n/cancel برای لغو", back_kb("p:set"))
    await cb.answer()


@admin_router.message(StateFilter(EditSetting.value), F.text, ~F.text.startswith("/"))
async def edit_save(m: Message, state: FSMContext):
    key = (await state.get_data())["key"]
    val = m.text.strip()
    if key == "rate_limit":
        if not val.isdigit():
            return await m.answer("❌ فقط عدد بفرست.")
        await db.set(key, str(int(val)))
    elif key == "force_channel":
        if val.lower() == "off":
            await db.set("force_channel", "")
            await db.set("force_link", "")
        else:
            chat_ref = val if val.startswith("@") or val.lstrip("-").isdigit() else "@" + val
            if chat_ref.lstrip("-").isdigit():
                chat_ref = int(chat_ref)
            try:
                chat = await bot.get_chat(chat_ref)
                me = await bot.get_chat_member(chat.id, bot.id)
                if me.status not in ("administrator", "creator"):
                    return await m.answer("❌ ربات در این کانال ادمین نیست. اول ادمینش کن و دوباره بفرست.")
                link = f"https://t.me/{chat.username}" if chat.username else await bot.export_chat_invite_link(chat.id)
            except Exception as e:
                return await m.answer(f"❌ کانال پیدا نشد یا دسترسی ندارم.\n<code>{esc(e)}</code>")
            await db.set("force_channel", str(chat.id))
            await db.set("force_link", link)
    else:
        await db.set(key, m.html_text)
    await state.clear()
    text, kb = await settings_view()
    await m.answer("✅ ذخیره شد.\n\n" + text, reply_markup=kb)


# ---------- گرفتن آیدی ایموجی پرمیوم ----------
def has_custom_emoji(m: Message) -> bool:
    ents = (m.entities or []) + (m.caption_entities or [])
    return any(e.type == "custom_emoji" for e in ents)


@admin_router.message(StateFilter(None), has_custom_emoji, ~F.reply_to_message)
async def emoji_ids(m: Message):
    text = m.text or m.caption or ""
    ents = (m.entities or []) + (m.caption_entities or [])
    out = ["✨ <b>آیدی ایموجی‌های پرمیوم</b>", LINE]
    for e in ents:
        if e.type == "custom_emoji":
            ch = e.extract_from(text)
            out.append(f"{esc(ch)}  <code>{e.custom_emoji_id}</code>")
    out.append(
        "\n💡 لازم نیست دستی کد بنویسی: موقع ویرایش پیام خوش‌آمد (پنل ← تنظیمات)، "
        "متنت را مستقیم با ایموجی پرمیوم بفرست؛ خودش ذخیره می‌شود."
    )
    await m.answer("\n".join(out))


# ---------- پاسخ ادمین با ریپلای ----------
@admin_router.message(F.reply_to_message)
async def admin_reply(m: Message):
    uid = await db.mapped_user(m.chat.id, m.reply_to_message.message_id)
    if not uid:
        return await m.answer("⚠️ این پیام به کاربری وصل نیست. روی یکی از پیام‌های کاربران ریپلای کن.")
    if await deliver(m, uid):
        try:
            await m.react([ReactionTypeEmoji(emoji="👍")])
        except Exception:
            await m.answer("✅ ارسال شد.")
    else:
        await m.answer("❌ ارسال نشد؛ کاربر ربات را بلاک کرده است.")


@admin_router.message()
async def admin_fallback(m: Message):
    await m.answer(
        "ℹ️ برای پاسخ به کاربر روی پیامش <b>ریپلای</b> کن.\nپنل مدیریت: /panel",
        reply_markup=panel_kb(),
    )


# ════════════════════════════ سمت کاربر ════════════════════════════
_hits: dict[int, deque] = defaultdict(deque)


async def rate_limited(uid: int) -> bool:
    limit = int(await db.get("rate_limit") or 0)
    if limit <= 0:
        return False
    now = time.time()
    q = _hits[uid]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= limit:
        return True
    q.append(now)
    return False


async def is_member(uid: int) -> bool:
    chan = await db.get("force_channel")
    if not chan:
        return True
    try:
        mem = await bot.get_chat_member(int(chan), uid)
        return mem.status not in ("left", "kicked")
    except Exception as e:
        log.warning("join check failed: %s", e)
        return True  # اگر چک نشد، کاربر را بلاک نکن


async def join_prompt(target: Message):
    link = await db.get("force_link")
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📣 عضویت در کانال", url=link)],
            [InlineKeyboardButton(text="✅ عضو شدم", callback_data="chk:join")],
        ]
    )
    await target.answer("🔒 برای استفاده از ربات، اول در کانال ما عضو شو و بعد دکمه «عضو شدم» را بزن.", reply_markup=kb)


async def gate(m: Message) -> bool:
    """False یعنی پیام باید متوقف شود."""
    u = m.from_user
    if u.is_bot:
        return False
    await db.upsert_user(u)
    row = await db.get_user(u.id)
    if row["banned"]:
        return False
    if (await db.get("enabled")) != "1":
        await m.answer(await db.get("off_text"))
        return False
    if not await is_member(u.id):
        await join_prompt(m)
        return False
    return True


@user_router.message(CommandStart())
async def user_start(m: Message):
    is_new = not await db.get_user(m.from_user.id)
    if not await gate(m):
        return
    text = (await db.get("welcome")).replace("{name}", esc(m.from_user.first_name))
    await m.answer(text)
    if is_new:
        for a in ADMINS:
            try:
                row = await db.get_user(m.from_user.id)
                await bot.send_message(a, "🆕 <b>کاربر جدید</b>\n" + user_card(row), reply_markup=user_actions_kb(row))
            except Exception:
                pass


@user_router.callback_query(F.data == "chk:join")
async def user_chk_join(cb: CallbackQuery):
    if await is_member(cb.from_user.id):
        await cb.message.delete()
        await cb.message.answer("✅ عضویتت تأیید شد! حالا می‌تونی پیامت رو بفرستی.")
    else:
        await cb.answer("❌ هنوز عضو کانال نشدی!", show_alert=True)


@user_router.message()
async def user_message(m: Message):
    if not await gate(m):
        return
    if await rate_limited(m.from_user.id):
        return await m.answer("⏳ داری خیلی سریع پیام می‌فرستی. چند لحظه صبر کن.")
    uid = m.from_user.id
    row = await db.get_user(uid)
    name = full_name(row)
    delivered = False
    for a in ADMINS:
        try:
            copy = await bot.copy_message(
                a, m.chat.id, m.message_id, reply_markup=incoming_kb(uid, name, bool(row["banned"]))
            )
            await db.map_msg(a, copy.message_id, uid, m.message_id)
            delivered = True
        except Exception as e:
            log.warning("relay to admin %s failed: %s", a, e)
    if not delivered:
        return await m.answer("⚠️ مشکلی پیش اومد. لطفاً کمی بعد دوباره تلاش کن.")
    await db.inc_msg(uid)
    await db.log(uid, "in")
    if (await db.get("confirm")) == "1":
        await m.answer(await db.get("sent_text"))


# ════════════════════════════ اینلاین ════════════════════════════
BOT_USERNAME = ""


@user_router.inline_query()
async def inline_handler(q: InlineQuery):
    text = await db.get("inline_text")
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="📩 ارسال پیام", url=f"https://t.me/{BOT_USERNAME}?start=inline")]]
    )
    result = InlineQueryResultArticle(
        id="contact",
        title="📩 ارسال لینک پیام به من",
        description="این گزینه را بزن تا دکمه‌ی ارتباط با من در چت فرستاده شود",
        input_message_content=InputTextMessageContent(message_text=text, parse_mode="HTML"),
        reply_markup=kb,
    )
    await q.answer([result], cache_time=5, is_personal=False)


# ════════════════════════════ Business (پیوی اکانت شخصی) ════════════════════════════
_biz_owner: dict[str, int] = {}
_biz_last: dict[tuple, float] = {}
BIZ_COOLDOWN = 6 * 3600  # هر ۶ ساعت یک‌بار پاسخ خودکار به هر مخاطب


@user_router.business_connection()
async def on_business_connection(bc: BusinessConnection):
    _biz_owner[bc.id] = bc.user.id
    state = "✅ متصل شد" if bc.is_enabled else "❌ قطع شد"
    for a in ADMINS:
        try:
            await bot.send_message(a, f"💼 اتصال Business {state}\nاکانت: <b>{esc(bc.user.full_name)}</b>")
        except Exception:
            pass


@user_router.business_message()
async def on_business_message(m: Message):
    cid = m.business_connection_id
    u = m.from_user
    if not u:
        return
    owner = _biz_owner.get(cid)
    if owner is None:
        try:
            owner = (await bot.get_business_connection(cid)).user.id
            _biz_owner[cid] = owner
        except Exception:
            owner = None
    if u.id == owner or u.id in ADMINS:
        return  # پیام خودِ صاحب اکانت است
    ctype = str(getattr(m.content_type, "value", m.content_type))
    body = m.text or m.caption or f"[{ctype}]"
    uname = f"@{esc(u.username)}" if u.username else "—"
    for a in ADMINS:
        try:
            await bot.send_message(
                a,
                f"💼 <b>پیام جدید در پیوی اکانت شخصی</b>\n{LINE}\n"
                f"👤 {esc(u.full_name)}   {uname}\n🆔 <code>{u.id}</code>\n\n{esc(body)}",
            )
        except Exception:
            pass
    if (await db.get("biz_enabled")) == "1":
        key = (cid, m.chat.id)
        if time.time() - _biz_last.get(key, 0) > BIZ_COOLDOWN:
            _biz_last[key] = time.time()
            try:
                await bot.send_message(m.chat.id, await db.get("biz_text"), business_connection_id=cid)
            except Exception as e:
                log.warning("business reply failed: %s", e)


# ════════════════════════════ اجرا ════════════════════════════
async def main():
    global BOT_USERNAME
    await db.init()
    dp.include_router(admin_router)
    dp.include_router(user_router)
    me = await bot.get_me()
    BOT_USERNAME = me.username
    log.info("✅ ربات @%s بالا آمد | ادمین‌ها: %s", me.username, ", ".join(map(str, ADMINS)))
    for a in ADMINS:
        try:
            await bot.send_message(a, "🟢 ربات روشن شد.\nبرای ورود به پنل: /panel")
        except Exception:
            log.warning("ادمین %s هنوز /start نزده است.", a)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
