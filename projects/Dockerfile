FROM python:3.11-slim

ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_DEFAULT_TIMEOUT=120

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --retries 8 --timeout "$PIP_DEFAULT_TIMEOUT" --index-url "$PIP_INDEX_URL" -r requirements.txt
COPY . .
RUN chmod +x scripts/docker-entrypoint.sh

EXPOSE 5000
ENTRYPOINT ["scripts/docker-entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "120", "app:app"]
