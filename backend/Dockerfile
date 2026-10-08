FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv/backend
COPY requirements.lock ./requirements.lock
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
RUN pip install --no-cache-dir -r requirements.lock
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
