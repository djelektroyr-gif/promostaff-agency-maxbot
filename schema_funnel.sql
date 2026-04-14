-- Воронка визитки MAX (отдельно от таблицы users в PRO). Приложение создаёт таблицу само через init_schema;
-- этот файл — для ручного применения или справки.

CREATE TABLE IF NOT EXISTS agency_max_funnel (
    max_user_id BIGINT PRIMARY KEY,
    state TEXT,
    funnel_last_step TEXT,
    funnel_last_step_at TIMESTAMP,
    funnel_phone_reached_at TIMESTAMP,
    funnel_completed_at TIMESTAMP,
    funnel_reminder_24h_sent_at TIMESTAMP,
    funnel_reminder_72h_sent_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agency_max_funnel_incomplete
    ON agency_max_funnel (funnel_last_step_at)
    WHERE funnel_completed_at IS NULL;
