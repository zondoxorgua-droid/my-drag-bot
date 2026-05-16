"""Клиент для Xsolla API магазина Oxide.

Поток получения прямой Razer Gold ссылки:
1. POST sb-user-id-service.xsolla.com/api/v1/user-id  -> JWT с user_id игрока
2. POST store.xsolla.com/.../payment/item/{sku}?country=...  (Bearer JWT) -> paystation token
3. GET  paystation2/api/payment_form?id=3217  (с paystation token) -> форма Razer Gold с полями
4. POST paystation2/api/directpayment  с xps_*-полями -> ответ с checkout.data.data (base64)
5. Декодируем base64 → внутри есть base64-encoded URL global.gold.razer.com
6. Возвращаем декодированный URL пользователю
"""
import asyncio
import base64
import json
import re
from typing import Any

import aiohttp


# ──────────────── константы Oxide / Xsolla ─────────────────
PROJECT_ID = 274717
MERCHANT_ID = 751385
LOGIN_ID = "ba0f246d-c403-413c-a4af-724f91b33659"
WEBHOOK_URL = "https://api.oxidesurvival.com/webhook/xsolla/login"
RAZER_GOLD_METHOD_ID = 3217

SHOP_ORIGIN = "https://shop.playoxide.com"
USER_ID_SERVICE = "https://sb-user-id-service.xsolla.com/api/v1"
STORE_BASE = f"https://store.xsolla.com/api/v2/project/{PROJECT_ID}"
PAYSTATION_API = "https://secure.xsolla.com/paystation2/api"


# ──────────────── каталог ──────────────────────────────────
# sku, название, цена USD, рекомендованная страна (Razer Gold работает только с US/SEA/LatAm).
# BY дала бы дешевле для BP'ов через карту, но Razer Gold там не подключён,
# поэтому всё мапим на US — там Razer Gold точно отрабатывает.
CATALOG: list[tuple[str, str, str, str]] = [
    ("premium",                 "💎 PREMIUM подписка",          "$4.99",   "US"),
    ("bp.season6.elite",        "🎖️ Battle Pass Elite",         "$19.99",  "US"),
    ("bp.season6.regular",      "🥉 Battle Pass обычный",       "$9.99",   "US"),
    ("50.coins",                "🪙 50 монет",                  "$1.99",   "US"),
    ("135.coins",               "🪙 135 монет",                 "$4.99",   "US"),
    ("290.coins",               "🪙 290 монет (-15%)",          "$9.99",   "US"),
    ("630.coins",               "🪙 630 монет (-25%)",          "$19.99",  "US"),
    ("1675.coins",              "🪙 1675 монет (-30%)",         "$49.99",  "US"),
    ("3550.coins",              "🪙 3550 монет (-40%)",         "$99.99",  "US"),
    ("bp.coins.small",          "💠 25 BP-монет",               "$4.99",   "US"),
    ("bp.coins.medium",         "💠 75 BP-монет",               "$14.99",  "US"),
    ("bp.coins.big",            "💠 250 BP-монет",              "$49.99",  "US"),
    ("nw.roll.two",             "🎟️ 5 билетов гачи",            "$4.99",   "US"),
    ("nw.roll.three",           "🎟️ 11 билетов гачи",           "$9.99",   "US"),
    ("nw.roll.four",            "🎟️ 28 билетов гачи",           "$19.99",  "US"),
    ("nw.roll.five",            "🎟️ 75 билетов гачи",           "$49.99",  "US"),
    ("nw.roll.six",             "🎟️ 160 билетов гачи",          "$99.99",  "US"),
    ("legendary.box.small.offer", "🎁 5 легендарных ящиков",    "$49.99",  "US"),
    ("legendary.box.big.offer",   "🎁 10 легендарных ящиков",   "$99.99",  "US"),
]

CATALOG_BY_SKU: dict[str, tuple[str, str, str]] = {
    sku: (name, price, country) for sku, name, price, country in CATALOG
}


# ──────────────── исключения ────────────────────────────────
class OxideApiError(RuntimeError):
    pass


# ──────────────── HTTP-обёртка ─────────────────────────────
def _b64url_decode(data: str) -> bytes:
    pad = len(data) % 4
    if pad:
        data += "=" * (4 - pad)
    return base64.urlsafe_b64decode(data)


def _b64_decode(data: str) -> bytes:
    pad = len(data) % 4
    if pad:
        data += "=" * (4 - pad)
    return base64.b64decode(data)


async def _login_with_user_id(
    session: aiohttp.ClientSession, oxide_id: str, country: str = "US"
) -> str:
    """Шаг 1: получаем user-JWT от Xsolla с зашитым oxide_id."""
    url = f"{USER_ID_SERVICE}/user-id"
    body = {
        "settings": {"projectId": PROJECT_ID, "merchantId": MERCHANT_ID},
        "loginId": LOGIN_ID,
        "webhookUrl": WEBHOOK_URL,
        "user": {"id": oxide_id, "country": country},
        "isUserIdFromWebhook": False,
    }
    async with session.post(
        url,
        json=body,
        headers={"Origin": SHOP_ORIGIN, "Referer": SHOP_ORIGIN + "/"},
    ) as resp:
        data = await resp.json()
    if resp.status not in (200, 201):
        raise OxideApiError(f"user-id login failed (HTTP {resp.status}): {data}")
    token = data.get("token")
    if not token:
        raise OxideApiError(f"user-id login: no token in response: {data}")
    return token


async def _create_pay_token(
    session: aiohttp.ClientSession, sku: str, country: str, user_jwt: str
) -> tuple[str, int]:
    """Шаг 2: paystation token (с авторизацией через Bearer)."""
    url = f"{STORE_BASE}/payment/item/{sku}?country={country}"
    async with session.post(
        url,
        json={},
        headers={
            "Content-Type": "application/json",
            "Origin": SHOP_ORIGIN,
            "Authorization": f"Bearer {user_jwt}",
        },
    ) as resp:
        data = await resp.json()
    if resp.status not in (200, 201):
        raise OxideApiError(f"create-token failed (HTTP {resp.status}): {data}")
    return data["token"], data.get("order_id", 0)


async def _fetch_payment_form(
    session: aiohttp.ClientSession, pay_token: str
) -> dict[str, Any]:
    """Шаг 3: получаем форму Razer Gold с её hidden-полями (signature, fix_v1 и пр.)."""
    url = f"{PAYSTATION_API}/payment_form"
    async with session.get(
        url,
        params={"access_token": pay_token, "id": str(RAZER_GOLD_METHOD_ID)},
        headers={"X-Requested-With": "XMLHttpRequest"},
    ) as resp:
        data = await resp.json()
    pf = data.get("payment_form") or {}
    if pf.get("errors"):
        raise OxideApiError(f"payment_form errors: {pf['errors']}")
    form = pf.get("form")
    if not form:
        raise OxideApiError("payment_form: no form fields returned")
    # Если Xsolla подсунул дефолтную форму карты вместо Razer Gold — Razer Gold
    # для этой страны/товара не подключён.
    if pf.get("pid") != RAZER_GOLD_METHOD_ID:
        raise OxideApiError(
            f"Razer Gold недоступен для этой страны (получили pid={pf.get('pid')}, "
            f"title={pf.get('title')!r})"
        )
    return form


async def _submit_form(
    session: aiohttp.ClientSession,
    pay_token: str,
    form: dict[str, Any],
    email: str,
    zip_code: str,
) -> dict[str, Any]:
    """Шаг 4: submit формы через directpayment c xps_*-полями."""
    url = f"{PAYSTATION_API}/directpayment"
    payload: list[tuple[str, str]] = [("access_token", pay_token)]
    overrides = {"email": email, "zip": zip_code}
    for key, field in form.items():
        if not isinstance(field, dict):
            continue
        value = overrides.get(key, field.get("value", "") or "")
        if value is None:
            value = ""
        if not isinstance(value, str):
            value = str(value)
        payload.append((f"xps_{key}", value))

    async with session.post(
        url,
        data=payload,
        headers={
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://secure.xsolla.com",
            "Referer": "https://secure.xsolla.com/paystation4/",
        },
    ) as resp:
        data = await resp.json()

    errors = data.get("errors") or []
    if errors:
        raise OxideApiError(f"directpayment errors: {errors}")

    checkout = data.get("checkout") or {}
    if not checkout.get("data", {}).get("data"):
        raise OxideApiError(f"no checkout.data.data in response (status={data.get('currentCommand')})")
    return data


def _extract_razer_url(submit_response: dict[str, Any]) -> str:
    """Шаг 5+6: декодируем base64 payload → достаём прямую global.gold.razer.com ссылку."""
    outer_b64 = submit_response["checkout"]["data"]["data"]
    outer = json.loads(_b64url_decode(outer_b64))
    fields = outer["request"]["form"]["fields"]
    inner_url_b64 = fields["url"]
    razer_url_bytes = _b64_decode(inner_url_b64)
    razer_url = razer_url_bytes.decode("utf-8")
    if "global.gold.razer.com" not in razer_url:
        raise OxideApiError(f"Unexpected redirect URL: {razer_url[:200]}")
    return razer_url


# ──────────────── публичный API ────────────────────────────
async def get_razer_gold_url(
    sku: str, country: str, oxide_id: str, email: str, zip_code: str = "97180"
) -> tuple[str, int]:
    """Главная точка входа: возвращает прямую ссылку на Razer Gold + invoice id.

    :param sku:        sku товара из CATALOG (e.g. "premium")
    :param country:    ISO-код страны для региональной цены ("US", "BY", ...)
    :param oxide_id:   игровой ID Oxide пользователя (e.g. "8Q-2ZR-2FD")
    :param email:      email для чека
    :param zip_code:   ZIP (обязателен для Razer, дефолт безопасный)
    :return: (razer_url, invoice_id)
    """
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        user_jwt = await _login_with_user_id(session, oxide_id, country)
        pay_token, _ = await _create_pay_token(session, sku, country, user_jwt)
        form = await _fetch_payment_form(session, pay_token)
        submit = await _submit_form(session, pay_token, form, email, zip_code)
        razer_url = _extract_razer_url(submit)
        invoice_id = (submit.get("userSession") or {}).get("purchase_invoice_id", 0)
        return razer_url, invoice_id


# ──────────────── обратная совместимость ───────────────────
async def create_payment_token(sku: str, country: str) -> tuple[str, int]:
    """Создаёт анонимный paystation-токен (без user-id) — используется как fallback."""
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        url = f"{STORE_BASE}/payment/item/{sku}?country={country}"
        async with session.post(
            url,
            json={},
            headers={"Content-Type": "application/json", "Origin": SHOP_ORIGIN},
        ) as resp:
            data = await resp.json()
    if not data.get("token"):
        raise OxideApiError(f"Xsolla не вернул токен: {data}")
    return data["token"], data.get("order_id", 0)


def build_razer_gold_url(token: str) -> str:
    """Старая ссылка-фолбэк — paystation4 с автовыбором Razer Gold (требует +1 клик)."""
    return f"https://secure.xsolla.com/paystation4/payment/{RAZER_GOLD_METHOD_ID}?token={token}"
