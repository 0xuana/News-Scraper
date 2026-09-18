FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN addgroup --system news_collector \
    && adduser --system --ingroup news_collector news_collector

COPY pyproject.toml README.md ./
COPY news_collector ./news_collector

RUN pip install --no-cache-dir .

USER news_collector

ENTRYPOINT ["python", "-m", "news_collector"]
CMD ["scheduled"]
