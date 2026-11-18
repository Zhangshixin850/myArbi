FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY backend backend
COPY migrations migrations
COPY alembic.ini .
COPY scripts scripts
RUN mkdir -p /app/data /app/backups && useradd -u 10001 -r arbi && chown -R arbi /app
USER arbi
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 1 --no-access-log"]
