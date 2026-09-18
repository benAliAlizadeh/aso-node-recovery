FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system aso \
    && useradd --system --gid aso --home-dir /app --create-home aso

WORKDIR /app

COPY pyproject.toml README.md VERSION ./
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
COPY scripts ./scripts

RUN python -m pip install --no-cache-dir . \
    && mkdir -p /var/lib/aso/secrets /var/lib/aso/backups \
    && chown -R aso:aso /app /var/lib/aso

USER aso

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
