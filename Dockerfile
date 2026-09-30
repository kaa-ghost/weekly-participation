FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

WORKDIR /app

# зависимости отдельным слоем — кэшируется при смене только кода
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# SECRET_KEY, ADMIN_PASSWORD, DATABASE_URL задаются через переменные окружения
CMD gunicorn app:app --bind 0.0.0.0:${PORT} --workers 2
