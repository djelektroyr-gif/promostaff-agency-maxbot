# users.phone — SQL пакет для диагностики и чистки дублей

Использовать для ручной операционной чистки «хвостов» идентичности в общей БД (`admin/client/worker`).

## 1) Базовый отчёт дублей

```sql
SELECT
  regexp_replace(phone, '\D', '', 'g') AS phone_norm,
  COUNT(*) AS cnt,
  array_agg(tg_id ORDER BY tg_id) AS tg_ids
FROM users
WHERE COALESCE(trim(phone), '') <> ''
GROUP BY 1
HAVING COUNT(*) > 1
ORDER BY cnt DESC, phone_norm;
```

## 2) Детализация по конкретному номеру

```sql
SELECT tg_id, max_user_id, role, full_name, phone, created_at, updated_at
FROM users
WHERE regexp_replace(phone, '\D', '', 'g') = '79685337332'
ORDER BY created_at;
```

## 3) Проверка связей для конкретного `tg_id`

```sql
SELECT * FROM clients WHERE user_id = 8545518666;
SELECT * FROM visit_clients WHERE user_id = 8545518666;
SELECT * FROM workers WHERE user_id = 8545518666;
```

## 4) Точечная безопасная правка для admin/manager

Если номер в `users.phone` приклеился к служебной роли и мешает входу публичного профиля:

```sql
BEGIN;

UPDATE users
SET phone = NULL,
    updated_at = NOW()
WHERE tg_id = 8545518666
  AND lower(role) IN ('admin', 'manager');

COMMIT;
```

## 5) Пост-проверка

```sql
SELECT
  regexp_replace(phone, '\D', '', 'g') AS phone_norm,
  COUNT(*) AS cnt,
  array_agg(tg_id ORDER BY tg_id) AS tg_ids
FROM users
WHERE COALESCE(trim(phone), '') <> ''
GROUP BY 1
HAVING COUNT(*) > 1
ORDER BY cnt DESC, phone_norm;
```

Ожидаемо: конфликтный номер исчезает из списка дублей или остаётся только в реальных конфликтных кейсах, требующих ручного разбора.
