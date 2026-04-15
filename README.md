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
- Визитка: сценарий перенесён с **PROMOSTAFF-AGENCY BOT** (`keyboards.py` + тексты/FSM из `handlers.py`): главное меню, разделы, расчёт (6 шагов), вопрос, анкета в команду (5 шагов + выбор должности). Контакты и ссылки — из `config` (см. `.env.example`, дефолты как на рабочем столе).  

## Timeweb App Platform

1. Репозиторий: этот GitHub, ветка `main`, корень репозитория.  
2. **Запуск (важно):** в логах ошибки `Invalid value for '--port': '${PORT:-8000}'` и `app:app: Syntax error` значат, что в **настройках приложения** всё ещё указана **старая** команда с `${PORT:-8000}` или битый `sh -c "..."`.  
   - **Вариант A (Python / Backend):** в поле «Команда запуска» укажите **только** `sh start.sh` (без кавычек вокруг всей строки). Поле «Сборка» — как раньше: `pip install -r requirements.txt` (или ваш вариант).  
   - **Вариант B (Docker):** в репозитории есть `Dockerfile` с `CMD ["sh", "start.sh"]`. Если Timeweb собирает образ из него — **очистите** кастомную команду запуска в UI (или совпадайте с CMD), иначе платформа перезапишет запуск и снова подставит невалидный порт.  
   Не используйте в одной строке с uvicorn конструкцию `${PORT:-8000}` — без оболочки она не раскрывается.  
3. Запасной вариант без скрипта: `uvicorn app:app --host 0.0.0.0 --port 8000` — только если в настройках сервиса явно указан внутренний порт **8000**.  
4. Переменные окружения: **`MAX_TOKEN`** (токен бота визитки), при необходимости **`PORT`**.  
   Для будущих уведомлений (расчёты, отклики): **`SMTP_*`**, **`NOTIFY_EMAIL_TO`**, **`SMTP_PASSWORD`**; в MAX — **`ADMIN_MAX_USER_IDS`** (числовые `user_id` через запятую). См. `.env.example`. В **`/health`** отображаются флаги `smtp_configured` и `admin_max_ids_count` (без секретов).  
   Воронка и напоминания в MAX (логика как `funnel_*` в PRO): задайте **`DATABASE_URL`** (Postgres), опционально **`FUNNEL_REMINDERS_ENABLED=1`** и **`FUNNEL_REMINDERS_INTERVAL_SEC`**. Таблица `agency_max_funnel` создаётся при старте; см. `schema_funnel.sql`.  
5. Подписка MAX: `POST …/subscriptions` с `url` = `https://<ваш-домен>/webhook` и `update_types`: `bot_started`, `user_added`, `message_created`, `message_callback`.

Связанный план в монорепо PRO: репозиторий `promostaff-bot`, файл `docs/PLAN_AGENCY_MAX_VISIT_BOT.md`.
Операционные процедуры: `OPERATIONS_VISITCARD.md`.

## Секреты

Токен и URL только в переменных окружения Timeweb / `.env` (не в git).
