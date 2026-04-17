# Vendor: PROMOSTAFF PRO для визитки MAX

Регистрация исполнителя (те же `users.state`, колбэки и шаги, что в `promostaff-bot/max_webhook/max_bot.py`) подключается из:

```
promostaff-agency-maxbot/vendor/promostaff-bot/
```

## Submodule

Из корня `promostaff-agency-maxbot`:

```bash
git submodule add <url-promostaff-bot> vendor/promostaff-bot
git submodule update --init --recursive
```

Нужны `DATABASE_URL` (общая Postgres с таблицей `users`) и `MAX_TOKEN`. При старте вызывается `init_postgres` из `promostaff-bot` для пула соединений.

См. также Telegram-визитку: `promostaff-agency-bot/vendor/README.md`.
