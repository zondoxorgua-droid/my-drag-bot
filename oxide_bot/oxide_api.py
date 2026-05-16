"""Минимальный клиент для Xsolla API магазина Oxide."""
import aiohttp


PROJECT_ID = 274717
RAZER_GOLD_METHOD_ID = 3217
SHOP_ORIGIN = "https://shop.playoxide.com"
STORE_BASE = f"https://store.xsolla.com/api/v2/project/{PROJECT_ID}"


# Каталог товаров: sku -> (название, цена USD, лучшая страна для Razer Gold)
# BY выбран для BP (там 45 BYN ≈ $16.20 vs $19.99 USD).
# Для остальных товаров локальной скидки нет, ставим US.
CATALOG: list[tuple[str, str, str, str]] = [
    # sku, название, цена USD, рекомендованная страна
    ("premium",                 "💎 PREMIUM подписка",          "$4.99",   "US"),
    ("bp.season6.elite",        "🎖️ Battle Pass Elite",         "$19.99",  "BY"),
    ("bp.season6.regular",      "🥉 Battle Pass обычный",       "$9.99",   "BY"),
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


CATALOG_BY_SKU = {sku: (name, price, country) for sku, name, price, country in CATALOG}


async def create_payment_token(sku: str, country: str) -> tuple[str, int]:
    """Создаёт Xsolla-токен оплаты. Возвращает (token, order_id)."""
    url = f"{STORE_BASE}/payment/item/{sku}?country={country}"
    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            json={},
            headers={
                "Content-Type": "application/json",
                "Origin": SHOP_ORIGIN,
                "Accept": "application/json",
            },
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            data = await resp.json()
    token = data.get("token")
    order_id = data.get("order_id")
    if not token:
        raise RuntimeError(f"Xsolla не вернул токен: {data}")
    return token, order_id


def build_razer_gold_url(token: str) -> str:
    """Формирует прямую ссылку на оплату Oxide через Razer Gold."""
    return f"https://secure.xsolla.com/paystation4/payment/{RAZER_GOLD_METHOD_ID}?token={token}"
