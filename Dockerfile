FROM python:3.12.13-alpine3.23@sha256:601d3d3797e90e2534782e69c85fafb7971b43f24c7b1b079b7e48dd435e458d

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.lock .
RUN python -m pip install --require-hashes -r requirements.lock

COPY alembic.ini .
COPY migrations ./migrations
COPY app ./app

RUN addgroup -S app \
    && adduser -S -D -H -G app app \
    && mkdir /app/uploads \
    && chown app:app /app/uploads
USER app

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
