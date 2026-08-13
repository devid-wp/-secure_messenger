FROM python:3.12.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.lock .
RUN python -m pip install --require-hashes -r requirements.lock

COPY alembic.ini .
COPY migrations ./migrations
COPY app ./app

RUN addgroup --system app \
    && adduser --system --ingroup app app \
    && mkdir /app/uploads \
    && chown app:app /app/uploads
USER app

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
