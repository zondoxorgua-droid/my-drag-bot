"""Telegram-бот для покупки Oxide Survival Island через Razer Gold.

Поток:
1. /start          → каталог кнопками
2. Жмёшь товар     → бот спрашивает Oxide ID
3. Вводишь ID      → бот спрашивает email
4. Вводишь email   → бот шлёт прямую ссылку на Razer Gold с открытой страницей оплаты
"""
import asyncio
import logging
import os
import re
from dataclasses import dataclass

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from oxide_api import (
    CATALOG,
    CATALOG_BY_SKU,
    build_razer_gold_url,
    create_payment_token,
)


# ─────────────────────────────────────── config ────────────────────────────────
TG_TOKEN = os.environ.get("OXIDE_BOT_TOKEN", "").strip()
if not TG_TOKEN:
    raise SystemExit("Установи переменную OXIDE_BOT_TOKEN с токеном Telegram-бота")

EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]+$")
OXIDE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{2,32}$")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("oxide-bot")

# ─────────────────────────────────────── FSM ───────────────────────────────────
class Order(StatesGroup):
    waiting_for_oxide_id = State()
    waiting_for_email = State()


@dataclass
class Selection:
    sku: str
    name: str
    price: str
    country: str


router = Router()


# ─────────────────────────────────────── UI ────────────────────────────────────
def build_catalog_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for sku, name, price, _ in CATALOG:
        rows.append(
            [InlineKeyboardButton(text=f"{name} — {price}", callback_data=f"buy:{sku}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад в меню", callback_data="menu")]]
    )


# ─────────────────────────────────────── handlers ──────────────────────────────
@router.message(CommandStart())
@router.message(Command("menu"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "🛒 <b>Магазин Oxide Survival Island</b>\n\n"
        "Выбери товар — пришлю прямую ссылку на оплату через <b>Razer Gold</b>.\n\n"
        "🇧🇾 Battle Pass'ы автоматически идут через Беларусь — там дешевле.\n"
        "🇺🇸 Остальные товары — через США (USD).",
        reply_markup=build_catalog_keyboard(),
    )


@router.callback_query(F.data == "menu")
async def cb_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text(
        "🛒 <b>Магазин Oxide Survival Island</b>\n\nВыбери товар:",
        reply_markup=build_catalog_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("buy:"))
async def cb_buy(callback: CallbackQuery, state: FSMContext) -> None:
    sku = callback.data.split(":", 1)[1]
    item = CATALOG_BY_SKU.get(sku)
    if not item:
        await callback.answer("Товар не найден", show_alert=True)
        return
    name, price, country = item
    sel = Selection(sku=sku, name=name, price=price, country=country)
    await state.update_data(sel=sel.__dict__)
    await state.set_state(Order.waiting_for_oxide_id)
    await callback.message.edit_text(
        f"Выбрано: <b>{name}</b> — {price}\n"
        f"Регион оплаты: <b>{country}</b>\n\n"
        f"Введи свой <b>Oxide ID</b> (видно в игре в настройках профиля):",
        reply_markup=back_to_menu(),
    )
    await callback.answer()


@router.message(Order.waiting_for_oxide_id)
async def on_oxide_id(message: Message, state: FSMContext) -> None:
    oxide_id = (message.text or "").strip()
    if not OXIDE_ID_RE.match(oxide_id):
        await message.answer(
            "❌ Похоже это не Oxide ID. Должно быть 2–32 символа: буквы, цифры, _ или -.\n"
            "Попробуй ещё раз:"
        )
        return
    await state.update_data(oxide_id=oxide_id)
    await state.set_state(Order.waiting_for_email)
    await message.answer(
        f"Oxide ID: <code>{oxide_id}</code> ✅\n\nТеперь введи <b>email</b> для чека:",
        reply_markup=back_to_menu(),
    )


@router.message(Order.waiting_for_email)
async def on_email(message: Message, state: FSMContext) -> None:
    email = (message.text or "").strip()
    if not EMAIL_RE.match(email):
        await message.answer("❌ Это не похоже на email. Попробуй ещё раз:")
        return

    data = await state.get_data()
    sel_dict = data.get("sel") or {}
    sel = Selection(**sel_dict)
    oxide_id = data.get("oxide_id", "")

    await state.clear()

    status_msg = await message.answer("⏳ Создаю заказ в Xsolla…")
    try:
        token, order_id = await create_payment_token(sel.sku, sel.country)
    except Exception as exc:
        log.exception("create_payment_token failed")
        await status_msg.edit_text(
            f"❌ Не получилось создать заказ: <code>{exc}</code>\n\n"
            "Попробуй ещё раз через /start.",
        )
        return

    pay_url = build_razer_gold_url(token)

    pay_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить через Razer Gold", url=pay_url)],
            [InlineKeyboardButton(text="🛒 Купить ещё", callback_data="menu")],
        ]
    )
    await status_msg.edit_text(
        f"✅ Заказ <b>#{order_id}</b> создан!\n\n"
        f"📦 <b>{sel.name}</b> — {sel.price}\n"
        f"🌍 Регион: <b>{sel.country}</b>\n"
        f"🎮 Oxide ID: <code>{oxide_id}</code>\n"
        f"📧 Email: <code>{email}</code>\n\n"
        f"👇 Жми кнопку ниже — откроется страница оплаты Xsolla с уже выбранным "
        f"<b>Razer Gold</b>. На странице вводишь Oxide ID и email — те что выше.",
        reply_markup=pay_kb,
    )


# ─────────────────────────────────────── main ──────────────────────────────────
async def main() -> None:
    bot = Bot(
        token=TG_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    log.info("Oxide bot is starting…")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
