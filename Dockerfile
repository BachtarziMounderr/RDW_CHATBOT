FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt requirements-ia.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-ia.txt \
    && useradd --create-home --uid 10001 rdw

COPY --chown=rdw:rdw . .

USER rdw

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','8080')+'/health', timeout=4)" || exit 1

CMD ["sh", "-c", "python -m bot.main init-db && exec python -m bot.main run"]
