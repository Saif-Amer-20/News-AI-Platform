FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements/prod.txt /tmp/requirements.txt

RUN pip install --upgrade pip \
    && pip install -r /tmp/requirements.txt

# Pre-download ML models at build time (no runtime download)
RUN python -c "\
from sentence_transformers import SentenceTransformer; \
SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'); \
from transformers import pipeline; \
pipeline('ner', model='Davlan/xlm-roberta-base-ner-hrl', aggregation_strategy='simple'); \
"

COPY backend/ /app/

RUN chmod +x /app/scripts/*.sh \
    && useradd --create-home --shell /bin/bash app \
    && mkdir -p /app/staticfiles \
    && chown -R app:app /app

# Copy cached models to app user home
RUN cp -r /root/.cache /home/app/.cache 2>/dev/null || true \
    && chown -R app:app /home/app/.cache

USER app

ENTRYPOINT ["/app/scripts/entrypoint.sh"]
CMD ["/app/scripts/start-web.sh"]

