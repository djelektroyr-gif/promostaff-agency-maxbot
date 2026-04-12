# PROMOSTAFF Agency — бот-визитка в MAX

Лёгкий webhook-сервис для мессенджера [MAX](https://dev.max.ru/docs-api): меню, тексты, инлайн-кнопки (по мере наполнения).

## Локально

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
copy .env.example .env     # заполните MAX_TOKEN
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

- `GET http://127.0.0.1:8000/health` — проверка живости  
- `POST http://127.0.0.1:8000/webhook` — URL для подписки в кабинете MAX  

## Timeweb App Platform

1. Репозиторий: этот GitHub, ветка `main`, корень репозитория.  
2. **Команда запуска (Timeweb):** `sh start.sh` — скрипт в корне репозитория читает переменную окружения `PORT` (Timeweb задаёт её сам) и при отсутствии использует `8000`. Так обходятся ограничения панели: без `${…}` в одной строке и без `sh -c "…"`, из‑за которых часто бывает «Unterminated quoted string».  
   Запасной вариант без скрипта: `uvicorn app:app --host 0.0.0.0 --port 8000` — только если в настройках сервиса явно указан внутренний порт **8000**.  
3. Переменные окружения: **`MAX_TOKEN`** (токен бота визитки), при необходимости **`PORT`**.  
4. Подписка MAX: `POST …/subscriptions` с `url` = `https://<ваш-домен>/webhook` и `update_types`: `bot_started`, `user_added`, `message_created`, `message_callback`.

Связанный план в монорепо PRO: репозиторий `promostaff-bot`, файл `docs/PLAN_AGENCY_MAX_VISIT_BOT.md`.

## Секреты

Токен и URL только в переменных окружения Timeweb / `.env` (не в git).
