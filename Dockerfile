FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=7860 \
    DJANGO_DEBUG=False \
    DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,struggler-safetyinspection.hf.space \
    CSRF_TRUSTED_ORIGINS=https://struggler-safetyinspection.hf.space \
    DJANGO_TIME_ZONE=Asia/Tehran \
    DATABASE_PATH=/tmp/safety-inspection.sqlite3 \
    PERSISTENCE_DIR=/data \
    MEDIA_ROOT=/data/private-media \
    MAX_UPLOAD_MB=20 \
    PERSISTENCE_CONFIRMED=0

RUN groupadd --gid 1000 app && useradd --uid 1000 --gid 1000 --create-home app \
    && mkdir -p /app /data /data/backups /data/private-media \
    && chown -R app:app /app /data
WORKDIR /app

COPY requirements.txt /app/requirements.txt
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=5
RUN pip install --no-cache-dir --disable-pip-version-check --timeout 120 --retries 5 --index-url "$PIP_INDEX_URL" -r /app/requirements.txt

COPY --chown=app:app . /app
RUN chmod 755 /app/docker-entrypoint.sh

USER 1000:1000
EXPOSE 7860
ENTRYPOINT ["/app/docker-entrypoint.sh"]
