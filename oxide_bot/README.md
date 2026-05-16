# Oxide Razer Gold Bot

Простейший Telegram-бот: показывает каталог Oxide Survival Island и
выдаёт прямую ссылку на оплату через **Razer Gold**.

## Поток

1. `/start` — каталог кнопками
2. Жмёшь товар — бот спрашивает Oxide ID
3. Вводишь ID — бот спрашивает email
4. Вводишь email — бот пришлёт **готовую ссылку на оплату Xsolla с уже выбранным Razer Gold**

Регион подбирается автоматически:
- 🇧🇾 **Беларусь** для Battle Pass (там 45 BYN ≈ $16.20 вместо $19.99)
- 🇺🇸 **США** для всего остального

## Запуск

```bash
cd oxide_bot
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export OXIDE_BOT_TOKEN="<токен_от_botfather>"
python main.py
```

## Запуск через systemd на сервере (опционально)

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

## Под капотом

- `POST store.xsolla.com/api/v2/project/274717/payment/item/{sku}?country={ISO}` → создаёт токен оплаты
- `https://secure.xsolla.com/paystation4/payment/3217?token={token}` → прямая ссылка с автовыбранным Razer Gold (`3217` — это его id у Xsolla)
- Никакой авторизации/cookies не нужно — store-API анонимный
