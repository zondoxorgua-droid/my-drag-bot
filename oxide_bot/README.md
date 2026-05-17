# Oxide Razer Gold Bot

Telegram-бот: показывает каталог Oxide Survival Island и выдаёт **прямую
ссылку на оплату через Razer Gold** — пользователь сразу попадает на
`global.gold.razer.com/PaymentWall/Checkout/index?token=...` без промежуточных
кликов на Xsolla.

## Поток

1. `/start` — каталог кнопками
2. Жмёшь товар → бот спрашивает Oxide ID
3. Вводишь ID → бот спрашивает email
4. Бот сам выполняет за пользователя:
   - логин в Xsolla User-ID Service с твоим Oxide ID
   - создание payment-токена
   - подгрузку формы Razer Gold (со всеми hidden-полями: `signature`, `fix_v1`, etc.)
   - submit формы через `directpayment` с `xps_*`-префиксами
   - распаковку base64 и извлечение прямой Razer-ссылки
5. Возвращает кнопку «💳 Оплатить через Razer Gold» — клик ведёт прямо на checkout Razer

## Запуск

```bash
cd oxide_bot
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export OXIDE_BOT_TOKEN="<токен_от_botfather>"
python main.py
```

## Запуск через systemd (опционально)

```ini
# /etc/systemd/system/oxide-bot.service
[Unit]
Description=Oxide Razer Gold Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/oxide_bot
Environment=OXIDE_BOT_TOKEN=ВСТАВЬ_ТОКЕН_СЮДА
ExecStart=/home/ubuntu/oxide_bot/.venv/bin/python main.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now oxide-bot
sudo journalctl -u oxide-bot -f
```

## Архитектура

```
Telegram /start
    ↓
catalog → выбор товара → ask Oxide ID → ask email
    ↓
oxide_api.get_razer_gold_url(sku, country, oxide_id, email)
  ├─ POST sb-user-id-service.xsolla.com/api/v1/user-id            → user JWT
  ├─ POST store.xsolla.com/.../payment/item/{sku}?country=...     → paystation token
  │   (с заголовком Authorization: Bearer <user JWT>, чтобы Xsolla
  │    зашил Oxide ID в requisites.id платёжной сессии)
  ├─ GET  paystation2/api/payment_form?id=3217                    → форма Razer Gold
  ├─ POST paystation2/api/directpayment с xps_*-префиксами        → checkout payload
  └─ декодируем base64 → внутри лежит url=base64(Razer URL)
      → возвращаем https://global.gold.razer.com/PaymentWall/Checkout/...
    ↓
Telegram: кнопка url=прямой Razer-ссылки
```

## Каталог товаров (19 шт.)

Все товары в Oxide идут с **фиксированной USD-ценой**, поэтому страна жёстко
зашита `US` (Razer Gold там точно подключён). Региональные скидки в BY/KZ есть,
**но только для оплаты картой** — Razer Gold для этих стран Xsolla не подключал.

## Запасной путь

Если Xsolla что-то поменяет в формате `directpayment` и прямая ссылка перестанет
извлекаться, бот **автоматически откатится** на `paystation4/payment/3217?token=...`
— это пейстейшн-страница с предвыбранным Razer Gold (требует +1 клик «Continue»).

## Под капотом — ключевые ID и URL

| Что | Значение |
|---|---|
| Xsolla project_id | `274717` |
| Xsolla merchant_id | `751385` |
| Site Builder login_id | `ba0f246d-c403-413c-a4af-724f91b33659` |
| Webhook URL | `https://api.oxidesurvival.com/webhook/xsolla/login` |
| Razer Gold method_id | `3217` |
| User-ID Service | `https://sb-user-id-service.xsolla.com/api/v1` |
| Store API | `https://store.xsolla.com/api/v2/project/274717` |
| Paystation API | `https://secure.xsolla.com/paystation2/api` |

## Тесты

Smoke-тест прямо в коде:

```bash
.venv/bin/python -c "
import asyncio
from oxide_api import get_razer_gold_url
url, inv = asyncio.run(get_razer_gold_url(
    sku='premium', country='US',
    oxide_id='YOUR-OXIDE-ID',
    email='you@example.com',
))
print(url)
"
```

В консоли должна появиться ссылка `https://global.gold.razer.com/PaymentWall/Checkout/index?token=...`.
