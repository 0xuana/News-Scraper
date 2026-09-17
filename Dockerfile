FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN addgroup --system collector \
    && adduser --system --ingroup collector collector

COPY pyproject.toml README.md ./
COPY collector ./collector

RUN pip install --no-cache-dir .

USER collector

ENTRYPOINT ["python", "-m", "collector"]
CMD ["live"]
