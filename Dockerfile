# Timeweb / любой Docker: порт из переменной окружения PORT (см. start.sh).
FROM python:3.12-slim-bookworm

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY app.py config.py handlers.py max_client.py max_attachments.py visit_card.py start.sh ./

# Явный запуск без shell-подстановок в одной строке uvicorn (как в панели Timeweb).
CMD ["sh", "start.sh"]
