# MAX ↔ Telegram: паритет визитки (до ERP)

**Дата:** 2026-05  
**Статус прод:** webhook работает, бот отвечает на Старт.  
**Этап работ:** визитка и регистрации **без ERP**; ERP в MAX — только после идентичности визитки.

---

## 1. Прод: переподключение MAX (зафиксировано)

| Параметр | Значение |
|----------|----------|
| Приложение Timeweb | `PROMOSTAFF AGENCY MAX BOT` |
| Репозиторий | `promostaff-agency-maxbot`, ветка `main` |
| **Канонический домен** | `https://djelektroyr-gif-promostaff-agency-maxbot-d923.twc1.net` |
| Health | `GET …/health` → `ok`, `max_token_configured`, `database_url_configured` |
| Webhook endpoint | `POST …/webhook` |
| Подписка MAX API | `POST https://platform-api.max.ru/subscriptions` → URL **должен совпадать с доменом в панели** (не `…-e4a0…`, не `…-ed89…`, не старый `promostaff-bot-*`) |
| Типы событий | `bot_started`, `user_added`, `message_created`, `message_callback` |

**Типовая ошибка:** подписка на другой twc1-домен → в логах только `GET /health`, нет `POST /webhook`, бот молчит.

**Env в Timeweb (имена):** `MAX_TOKEN`, `DATABASE_URL`, `TBANK_LK_URL`, `ADMIN_MAX_USER_IDS`, `WEBSITE_URL`, `PRIVACY_POLICY_URL`, `PYTHONUNBUFFERED`. (`AGENCY_FEE_PERCENT` в панели — код maxbot не читает.)

Инфра-снимок: `promostaff-bot/docs/TIMEWEB_APP_PLATFORM_SNAPSHOT.md` §3.  
Webhook API: `promostaff-bot/docs/MAX_WEBHOOK_AND_SUBSCRIPTIONS.md`.

---

## 2. Роли репозиториев

| Репозиторий | Роль в паритете визитки |
|-------------|-------------------------|
| **promostaff-agency-bot** | **Эталон** UX и записи: `handlers/visit_public.py`, `handlers/join_anketa/`, `keyboards/`, `db.py` |
| **promostaff-agency-maxbot** | **Зеркало MAX:** `visit_card.py`, `visit_flows.py`, `handlers.py`, `funnel_db.py` |
| **promostaff-bot** | **Чтение + панель:** общая PostgreSQL, synthetic `tg_id`, CRM/HRM, Customer 360 |

**Канон регистрации (оба бота):** `docs/REGISTRATION_AND_POST_MENU_SPEC.md` (дубликат в agency-bot и maxbot).  
**Заказчик / меню:** `promostaff-agency-bot/docs/VISIT_CARD_DEFERRED_AND_CUSTOMER_FLOW.md`.  
**Зеркало кода:** `.cursor/rules/visit-card-telegram-max-mirror.mdc`.

**Вне scope сейчас:** ERP (смены, чек-ин, админ-ERP, вакансии-кампании broadcast, Mini App) — см. `docs/SHIFT_ASSIGNMENT_STATUS_CONTRACT.md` в agency-bot.

---

## 3. Сводная таблица паритета (визитка, до ERP)

Легенда: **OK** — есть и близко к TG; **Частично** — урезано или без админ-цепочки; **Нет** — нет в MAX или заглушка.

### 3.1. Публичная визитка (гость)

| Блок | Telegram | MAX | Приоритет |
|------|----------|-----|-----------|
| Главное меню визитки | `visit_card_keyboard` | OK | — |
| О нас, преимущества, как работаем, FAQ, отзывы, кейсы | `visit_public` static | OK | — |
| Связаться (тел/email + вопрос менеджеру) | OK | OK | — |
| Хочу в команду → intro | OK | OK | — |
| Вакансии + кнопка «Хочу: …» на каждую | `vac_view` / `vac_apply_*` | OK (`vacancies_list_keyboard`, `vacancy_detail_keyboard`) | — |
| Подписка на канал (gate) | `check_subscribe` | Нет | P2 |
| Медиа-альбомы кейсов | `visit_card_media` | Нет (только текст) | P2 |

### 3.2. Заказчик (регистрация + пре-ERP меню)

| Блок | Telegram | MAX | Приоритет |
|------|----------|-----|-----------|
| Вход «Меню заказчика» + согласие ПДн | `client_visit_menu` | OK | — |
| Регистрация: компания, ИНН, ФИО, должность, телефон, email | `OrderForm` + `visitreg_*` | OK (без ЕГРЮЛ) | — |
| ЕГРЮЛ/ЕГРИП подтверждение ИНН | TG | **Нет** | P1 |
| Connect ID / Госуслуги | TG | **Нет** | P1 |
| Админ-верификация заказчика → доступ к расчётам | `cvf:` / `visit_clients` | OK (`visit_clients.verified_at`, меню до approve — `client_pre_erp_pending_keyboard`) | — |
| Запись в `users` + панель | `save_client` | OK (`synthetic tg_id`, `agency_max_visit_clients`) | — |
| Меню после рег.: история заказов | OK | OK (чтение БД) | — |
| **Заказать проект** (quick_estimate) | полный `OrderForm` | OK (без `public_ref` PSA на quick) | P1 |
| **Коммерческое предложение** | `cp_request` + CRM | OK | — |
| **Разместить объявление** (listing) | `client_quote_listing` | OK (`start_listing_order`, 4 шага + confirm) | — |
| Заглушки: проекты, настройки, веб | TG | Частично | P2 |

### 3.3. Исполнитель (анкета + пре-ERP)

| Блок | Telegram (`JoinForm` + `join_anketa/`) | MAX (`visit_flows`) | Приоритет |
|------|--------------------------------------|---------------------|-----------|
| Согласие ПДн + terms перед селфи | OK | OK | — |
| Каталог профессий | OK | OK | — |
| ФИО, телефон, ДР | OK | OK | — |
| Налоговые ветки (ФЛ/СЗ/ИП) | полные | OK (ИНН ФЛ 12 цифр → СНИЛС/реквизиты); СЗ/помощь → FSM Т-Банк при `TBANK_LK_URL` | — |
| T-Bank cabinet / register confirm | `tbank_*` states | OK (`join_tbank_*`, шаги `tbank_cabinet` / `tbank_register_confirm`) | — |
| СНИЛС, email исполнителя, реквизиты GPH | OK | OK (после налогового блока) | — |
| Опыт, параметры, форма, медкнижка, поездки, навыки | OK | OK | — |
| Портфолио PDF/URL | OK | OK (после согласия terms → меню портфолио) | — |
| Паспорт: кем/когда выдан, адрес регистрации | OK | OK | — |
| Город / метро работы | OK | OK (метро для крупных городов + «Пропустить») | — |
| Отправка → `agency_visit_join_requests` | OK | OK | — |
| Статус «на проверке» + меню ожидания | OK | OK (`worker_pending_verification_keyboard`, `message_role_home`) | — |
| Админ verify → меню исполнителя | `wvf:` + `workers` | OK (`workers.status=approved`, `is_max_visit_worker_verified`) | — |
| Уточнение анкеты (clarification) | `join_clarification` | OK (`clrf:start` / `clrf:ack`, `join_clarification_db`) | — |

### 3.4. Вопрос менеджеру

| Блок | Telegram | MAX | Приоритет |
|------|----------|-----|-----------|
| Согласие + текст вопроса | `QuestionForm` | OK | — |
| `agency_visit_questions` | OK | OK | — |

### 3.5. Веб / панель (promostaff-bot)

| Блок | Готовность | Заметка |
|------|------------|---------|
| Чтение `agency_visit_*` по `user_id` | OK | Работает с synthetic `tg_id` |
| Customer 360 / CRM / HRM join | OK | Метки MAX в UI |
| Запись заказов/join из MAX | Частично | Пишет maxbot; `source` желательно `max` |
| Уведомление заказчику о статусе заказа в MAX | OK | `promostaff-bot` `telegram_notify` + `send_max_plain` по `users.max_user_id` |
| PRO MAX `/kp` в `cp_requests` | OK | Отдельно от визитки агентства |

---

## 4. Рекомендуемый порядок спринта (только визитка)

1. **P0 — «бот живёт как TG до ERP»**
   - Вакансии: inline `vac_apply_*` на экране вакансий.
   - Исполнитель после submit: экран «на проверке», не публичное меню.
   - `is_max_visit_worker_verified`: читать `agency_visit_join_requests.payload.verification_status` / `workers` (как TG после approve в панели).
   - Согласовать с продуктом: заказчик MAX — мгновенный доступ vs админ-verify как в TG.

2. **P1 — полнота анкеты и заказчика**
   - Join: SNILS, email, GPH, паспорт (кем/когда), work_city/metro, portfolio.
   - T-Bank FSM (или явный plan Б в spec).
   - Заказчик: listing flow; quick order `public_ref`.
   - Join clarification flow.

3. **P1 — веб-синхронизация**
   - Уведомления в MAX (`send_max_plain`) для synthetic users при смене статуса заказа/HRM.
   - Единый `source='max'` на insert.

4. **P2 — полировка**
   - Funnel reminders (`FUNNEL_REMINDERS_ENABLED`).
   - Session persistence (`agency_max_funnel` уже есть; усилить recovery).
   - Медиа кейсов, channel subscribe gate.

**ERP (после зелёного P0+P1 визитки):** смены, маяк, выплаты, админ-ERP — не начинать до sign-off по §3.

---

## 5. Карта файлов для разработки

| Задача | Telegram (читать) | MAX (править) | Веб (если нужно) |
|--------|-------------------|---------------|------------------|
| Меню / static | `visit_public.py`, `keyboards/menus.py` | `visit_card.py` | — |
| Заказчик | `visit_public.py` OrderForm | `visit_flows.py` client_visit | `panel_queries.py` |
| Анкета | `handlers/join_anketa/handlers.py`, `states` JoinForm | `visit_flows.py` join | HRM routes |
| DB write | `db.py` save_* | `funnel_db.py` | `messenger_user_policy.py` |
| Callbacks | `callback_data` в keyboards | `handlers.py` + payloads в `visit_card.py` | — |

**Тесты:** agency-bot `tests/test_*visit*`, `test_join*` — ориентир; добавить `promostaff-agency-maxbot/tests/` по мере портирования.

---

## 6. Критерий «готово к ERP в MAX»

- [ ] Гость и обе роли проходят те же **обязательные** шаги, что в `REGISTRATION_AND_POST_MENU_SPEC.md` (или задокументированные plan Б).
- [ ] Заказчик: три ветки расчёта (проект / КП / listing) или явный waiver в spec.
- [ ] Исполнитель: submit → проверка → верификация из панели → меню исполнителя (без ERP-кнопок смен).
- [ ] Панель показывает лиды MAX с корректным `user_id` и `source`.
- [ ] Ручной smoke: сценарии из `OPERATIONS_VISITCARD.md` на прод-домене **d923**.

---

*Обновлять этот файл при закрытии пунктов P0/P1 и при смене домена Timeweb.*
