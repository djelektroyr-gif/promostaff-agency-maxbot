# MAX ↔ Telegram: паритет визитки (до ERP)

**Дата:** 2026-05  
**Статус прод:** webhook работает, бот отвечает на Старт.  
**Этап работ:** визитка и регистрации + **MAX Admin wave 1** (CRM/OPS/HRM read-model в мессенджере).

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

**Вне scope сейчас:** ERP write-операции (создание/редактирование смен, выплаты с изменением статуса, чек-ин/чек-аут в MAX, Mini App) — см. `docs/SHIFT_ASSIGNMENT_STATUS_CONTRACT.md` в agency-bot.

### 2.2. MAX admin parity (wave 1, нативно в мессенджере)

- Добавлены хабы `OPS / HRM / CRM / System` в `visit_card.py` и `visit_flows.py`.
- CRM: воронка заказов (`all / kp / urgent`), фильтр по стадии, карточка заявки, смена CRM-стадии прямо из MAX.
- OPS: активные смены, проекты, карточки смен/проектов, последние назначения (`shift_assignments`).
- HRM: список исполнителей, поиск исполнителя, карточка исполнителя, последние выплаты и карточка выплаты.
- HRM: смена статуса выплаты в MAX (`pending / approved / paid / cancelled`) из карточки выплаты.
- System: мониторинг, журнал входа по телефону, диагностика дублей `users.phone`, просмотр лога админ-действий.
- В хабах добавлены счётчики (open shifts, pending payouts, CRM in funnel), чтобы видеть нагрузку сразу в меню.

### 2.3. Следующий продуктовый шаг (статус после вертикального среза 2026-05-21)

- Контур формирования проекта заказчиком: в MAX включены `Мои проекты` + `Создать проект` с единым gate по подписке/лимиту.
- Контур подписки заказчика: в MAX добавлен экран `Подписка и лимиты` (статус, тариф, квота, окончание).
- Контур «Команда заказчика»: в MAX добавлен список исполнителей компании (read-модель по сменам проектов).
- Отчёты заказчика: в MAX добавлена точка входа в Excel/PDF через защищённый веб-кабинет.
- Перенос ключевых ERP-функций меню исполнителя в MAX (смены, выплаты, рабочие действия) до функционального паритета с Telegram.

### 2.1. Контур идентичности (обязательный паритет с Telegram)

- Вход по телефону для визитки опирается на `users.phone` только для публичных ролей (`client`, `worker`).
- Строки `users` с `role in ('admin','manager','администратор','менеджер')` не являются публичной телефонной идентичностью и должны игнорироваться в phone-resolve.
- Если дубли по номеру включают `synthetic tg_id` и один реальный `tg_id`, допускается safe auto-merge.
- Если дубли по номеру содержат несколько реальных `tg_id`, это ручной сценарий разбора (без автосклейки).
- Для админов MAX доступ к управлению агентством задаётся через `ADMIN_MAX_USER_IDS`, а не через регистрацию клиент/исполнитель.
- Отказ/сброс профиля приводят к единому состоянию `users.role = 'guest'` с очисткой профильных таблиц роли.
- При TG-сбросе должен удаляться и хвост `agency_max_visit_clients`, чтобы MAX и Telegram видели одинаковый статус.

---

## 3. Сводная таблица паритета (визитка, до ERP)

Легенда: **OK** — есть и близко к TG; **Частично** — урезано или без админ-цепочки; **Нет** — нет в MAX или заглушка.

### 3.1. Публичная визитка (гость)

| Блок | Telegram | MAX | Приоритет |
|------|----------|-----|-----------|
| Главное меню визитки | `visit_card_keyboard` (5 кнопок: О нас, меню заказчика/исполнителя, FAQ, связь) | OK (с 2026-05-16: убран «плоский» старый список из 9+ кнопок) | — |
| О нас, преимущества, как работаем, FAQ, отзывы, кейсы | подменю `about_section_keyboard` | OK (`about_keyboard` в MAX) | — |
| **Один телефон — один `users`, без смены роли** | `visit_user_identity` + шаг телефона в join/visit | OK (`user_identity.py`, шаг `phone` в `visit_flows`) | — |
| **«Уже регистрировался» / «Впервые»** перед телефоном | `visit_role_entry` + `role_entry_keyboard` | OK (2026-05-16: flow `role_entry`, `visit_card.role_entry_keyboard`) | — |
| **Журнал входа по телефону** | `visit_phone_login_log`, админ `/admin_phone_login` | OK (2026-05-16: `visit_phone_login_log.py`, `source=max`) | — |
| **Телефон с кнопки контакта** (не ручной ввод) | request_contact / Reply | OK (2026-05-16: `max_contact_phone.py`, vCard + HMAC) | — |
| **«Кабинет на сайте»** (одноразовая ссылка) | `open_web_cabinet` в TG | **Нет** | P1 после визитки; веб `/cabinet/enter` уже есть |
| Связаться (тел/email + вопрос менеджеру) | OK | OK | — |
| Хочу в команду → intro | `join_team_intro_keyboard` (3 кнопки) | OK (с 2026-05-16: не статический старый экран) | — |
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
| **Заказать проект** (quick_estimate) | только после `visit_clients.verified_at` | OK (`client_quote_quick`, `_gate_client_quote_access`) | — |
| **Коммерческое предложение** | только после verify | OK (`client_quote_cp`) | — |
| **Разместить объявление** (listing) | только после verify | OK (`client_quote_listing`, gate на submit) | — |
| Кнопка «Заказать расчёт» (legacy) | → регистрация / меню, не заявка | OK (`route_calculate_button`) | — |
| Заглушки: проекты, настройки, веб | TG | Частично | P2 |

### 3.3. Исполнитель (анкета + пре-ERP)

| Блок | Telegram (`JoinForm` + `join_anketa/`) | MAX (`visit_flows`) | Приоритет |
|------|--------------------------------------|---------------------|-----------|
| Согласие ПДн + terms перед селфи | OK | OK | — |
| Каталог профессий | OK | OK | — |
| Несколько профессий (profession_summary) | OK | OK (`join_profession_titles`, `prof_add_another` / `prof_done`) | — |
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

### 3.3.1. UI-checklist регистрации (TG → MAX)

- `consent_join_accept`:
  - профиль (`join_entry=profile`) → сразу `*ВЫБОР ПРОФЕССИИ*` (без экрана-приглашения);
  - вакансия (`join_entry=vacancy`) → сразу `profession_summary` с выбранной ролью.
- Экран review заказчика: `Проверка данных` + кнопки `✅ Всё верно, отправить администратору` / `✏️ Исправить данные`.
- Для заказчика в MAX есть меню точечной правки полей (`Юрлицо/ИНН/ФИО/Телефон/Email`) с возвратом `◀️ К проверке`.
- Тексты шагов заказчика (ИНН/ФИО/телефон/email) выровнены по формулировкам Telegram.

### 3.4. Вопрос менеджеру

| Блок | Telegram | MAX | Приоритет |
|------|----------|-----|-----------|
| Согласие + текст вопроса | `QuestionForm` | OK | — |
| `agency_visit_questions` | OK | OK | — |

### 3.5. Веб / панель (promostaff-bot)

| Блок | Готовность | Заметка |
|------|------------|---------|
| **Единый вход `/login` + `/cabinet/enter?token=`** | TG: кнопка в боте | Веб OK (2026-05-16, **promostaff-bot**); MAX-бот — ссылку пока не выдаёт | P1: `cabinet_web_login_tokens` из MAX |
| **Вход кабинета из браузера (телефон)** | `/login?role=client\|worker` | Код OK | Env **promostaff-web**: `CABINET_BROWSER_LOGIN_PHONE_ONLY=1`. **Не путать** с резолвом телефона в ботах MAX/TG. |
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
