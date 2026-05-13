"""
Telegram-бот для проверки кодов на Робуксы (Roblox gift card / promo codes).

Бот пытается проверить код через страницу погашения Roblox.
ВНИМАНИЕ: Roblox активно защищается от автоматических запросов,
поэтому проверка может не работать стабильно (капча, блокировки).
"""

import asyncio
import logging
import re
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import aiohttp

# ============ НАСТРОЙКИ ============
# Вставьте свой токен Telegram-бота
TOKEN = "ВАШ_ТОКЕН_БОТА"

# Roblox endpoints
ROBLOX_REDEEM_URL = "https://apis.roblox.com/redemption-authority/v1/codes/redeem"
ROBLOX_VALIDATE_URL = "https://apis.roblox.com/redemption-authority/v1/codes/validate"
ROBLOX_PROMO_URL = "https://www.roblox.com/promocodes/redeem"

# ============ ЛОГИРОВАНИЕ ============
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============ БОТ ============
bot = Bot(token=TOKEN)
dp = Dispatcher()


class CheckCode(StatesGroup):
    waiting_for_code = State()


# Regex для валидации формата кода
# Roblox gift cards: обычно 10-16 символов (цифры и буквы)
# Promo codes: текстовые строки разной длины
GIFT_CARD_PATTERN = re.compile(r'^[A-Za-z0-9]{10,20}$')
PROMO_CODE_PATTERN = re.compile(r'^[A-Za-z0-9_\-]{3,50}$')


async def check_gift_card(code: str) -> dict:
    """
    Попытка проверить gift card код через Roblox API.
    Возвращает dict с результатом.
    """
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Referer": "https://www.roblox.com/redeem",
        "Origin": "https://www.roblox.com",
    }

    payload = {
        "code": code,
    }

    try:
        async with aiohttp.ClientSession() as session:
            # Сначала пробуем validate endpoint
            async with session.post(
                ROBLOX_VALIDATE_URL,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as response:
                status = response.status
                try:
                    data = await response.json()
                except:
                    data = await response.text()

                if status == 200:
                    return {
                        "status": "valid",
                        "message": "Код ВАЛИДНЫЙ! Возможно, его можно активировать.",
                        "details": data
                    }
                elif status == 400:
                    return {
                        "status": "invalid",
                        "message": "Код НЕВАЛИДНЫЙ или уже использован.",
                        "details": data
                    }
                elif status == 429:
                    return {
                        "status": "rate_limited",
                        "message": "Слишком много запросов. Roblox заблокировал. Попробуйте позже.",
                        "details": None
                    }
                elif status == 403:
                    return {
                        "status": "blocked",
                        "message": "Запрос заблокирован Roblox (требуется авторизация/капча).",
                        "details": data
                    }
                elif status == 401:
                    return {
                        "status": "unauthorized",
                        "message": "Требуется авторизация. Код не проверен.",
                        "details": data
                    }
                else:
                    return {
                        "status": "unknown",
                        "message": f"Неизвестный ответ (HTTP {status}).",
                        "details": data
                    }
    except asyncio.TimeoutError:
        return {
            "status": "timeout",
            "message": "Roblox не ответил вовремя. Попробуйте позже.",
            "details": None
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Ошибка при проверке: {str(e)}",
            "details": None
        }


async def check_promo_code(code: str) -> dict:
    """
    Попытка проверить промокод через Roblox.
    """
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Referer": "https://www.roblox.com/promocodes",
    }

    try:
        async with aiohttp.ClientSession() as session:
            # Получаем страницу для CSRF токена
            async with session.get(
                "https://www.roblox.com/promocodes",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as page_resp:
                page_text = await page_resp.text()

                # Ищем CSRF token
                csrf_match = re.search(
                    r'data-token="([^"]+)"', page_text
                ) or re.search(
                    r'Roblox\.XsrfToken\.setToken\(\'([^\']+)\'\)', page_text
                )

                if not csrf_match:
                    return {
                        "status": "blocked",
                        "message": "Не удалось получить CSRF токен. Roblox блокирует бота.",
                        "details": None
                    }

                csrf_token = csrf_match.group(1)

            # Пробуем активировать промокод
            headers["X-CSRF-TOKEN"] = csrf_token
            payload = {"code": code}

            async with session.post(
                ROBLOX_PROMO_URL,
                data=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as response:
                status = response.status
                text = await response.text()

                if "successfully" in text.lower() or "redeemed" in text.lower():
                    return {
                        "status": "valid",
                        "message": "Промокод РАБОЧИЙ!",
                        "details": None
                    }
                elif "invalid" in text.lower() or "expired" in text.lower():
                    return {
                        "status": "invalid",
                        "message": "Промокод НЕВАЛИДНЫЙ или истёк.",
                        "details": None
                    }
                elif status == 429:
                    return {
                        "status": "rate_limited",
                        "message": "Слишком много запросов. Попробуйте позже.",
                        "details": None
                    }
                else:
                    return {
                        "status": "unknown",
                        "message": f"Не удалось определить статус (HTTP {status}).",
                        "details": text[:200] if text else None
                    }
    except asyncio.TimeoutError:
        return {
            "status": "timeout",
            "message": "Roblox не ответил вовремя.",
            "details": None
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Ошибка: {str(e)}",
            "details": None
        }


def format_result(result: dict, code: str, code_type: str) -> str:
    """Форматирование результата для отправки пользователю."""
    status_emoji = {
        "valid": "\u2705",
        "invalid": "\u274c",
        "rate_limited": "\u23f3",
        "blocked": "\U0001f6ab",
        "unauthorized": "\U0001f512",
        "timeout": "\u231b",
        "error": "\u26a0\ufe0f",
        "unknown": "\u2753",
    }

    emoji = status_emoji.get(result["status"], "\u2753")
    text = (
        f"{emoji} **Результат проверки**\n\n"
        f"\U0001f4cb Тип: {code_type}\n"
        f"\U0001f511 Код: `{code}`\n"
        f"\U0001f4ca Статус: {result['message']}\n"
    )

    if result.get("details") and isinstance(result["details"], dict):
        text += f"\n\U0001f4dd Детали: {result['details']}"

    text += (
        "\n\n\u26a0\ufe0f *Примечание:* Roblox может блокировать автоматические "
        "проверки. Результат не гарантирован на 100%."
    )

    return text


# ============ ХЕНДЛЕРЫ ============

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "\U0001f3ae **Бот проверки кодов Roblox**\n\n"
        "Я могу проверить:\n"
        "\u2022 Gift Card коды (карты оплаты на Робуксы)\n"
        "\u2022 Промокоды Roblox\n\n"
        "Команды:\n"
        "/check - Проверить код\n"
        "/help - Помощь\n\n"
        "\u26a0\ufe0f Roblox может блокировать автоматические запросы, "
        "поэтому результат не всегда точный.",
        parse_mode="Markdown"
    )


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "\U0001f4d6 **Как пользоваться:**\n\n"
        "1. Нажмите /check\n"
        "2. Отправьте код (gift card или промокод)\n"
        "3. Бот попытается проверить его\n\n"
        "**Форматы кодов:**\n"
        "\u2022 Gift Card: 10-20 символов (буквы + цифры)\n"
        "  Пример: `1234567890AB`\n"
        "\u2022 Промокод: текст 3-50 символов\n"
        "  Пример: `TWEETROBLOX`\n\n"
        "\u26a0\ufe0f **Важно:**\n"
        "\u2022 Бот НЕ активирует коды, только проверяет\n"
        "\u2022 Roblox может блокировать запросы\n"
        "\u2022 Не используйте для массовой проверки",
        parse_mode="Markdown"
    )


@dp.message(Command("check"))
async def cmd_check(message: types.Message, state: FSMContext):
    await state.set_state(CheckCode.waiting_for_code)
    await message.answer(
        "\U0001f511 Отправьте код для проверки:\n\n"
        "(Gift Card или промокод Roblox)"
    )


@dp.message(CheckCode.waiting_for_code)
async def process_code(message: types.Message, state: FSMContext):
    code = (message.text or "").strip()

    if not code:
        await message.answer("\u274c Пожалуйста, отправьте код текстом.")
        return

    # Определяем тип кода
    is_gift_card = bool(GIFT_CARD_PATTERN.match(code))
    is_promo = bool(PROMO_CODE_PATTERN.match(code))

    if not is_gift_card and not is_promo:
        await message.answer(
            "\u274c Неверный формат кода.\n\n"
            "Gift Card: 10-20 символов (буквы и цифры)\n"
            "Промокод: 3-50 символов (буквы, цифры, _, -)\n\n"
            "Попробуйте ещё раз или /start для выхода."
        )
        return

    # Отправляем сообщение о начале проверки
    checking_msg = await message.answer("\U0001f50d Проверяю код... Подождите.")

    if is_gift_card:
        code_type = "Gift Card (карта на Робуксы)"
        result = await check_gift_card(code)
    else:
        code_type = "Промокод"
        result = await check_promo_code(code)

    # Отправляем результат
    result_text = format_result(result, code, code_type)
    await checking_msg.edit_text(result_text, parse_mode="Markdown")

    await state.clear()
    await message.answer(
        "\U0001f504 Хотите проверить ещё один код? Нажмите /check"
    )


# Обработка любых сообщений вне состояния
@dp.message()
async def fallback(message: types.Message):
    await message.answer(
        "Используйте /check для проверки кода или /help для помощи."
    )


# ============ ЗАПУСК ============

async def main():
    logger.info("Запуск бота проверки кодов Roblox...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
