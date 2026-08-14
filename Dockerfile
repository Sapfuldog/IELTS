FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first: this layer is rebuilt only when requirements.txt changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY scripts/ ./scripts/
COPY run.py ./

# Runtime state (SQLite database, cached TTS audio) lives in these directories.
# They are declared as volumes in docker-compose.yml so data survives rebuilds.
# A fresh named volume inherits this ownership, so the unprivileged user can write.
RUN useradd --create-home --uid 1000 ielts \
    && mkdir -p /app/data /app/media/tts \
    && chown -R ielts:ielts /app

USER ielts

# Fail fast on a broken content edit rather than at the first learner request.
RUN python scripts/validate_content.py

CMD ["python", "-m", "app.main"]
