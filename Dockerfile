FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml README.md LICENSE THIRD_PARTY_NOTICES.md ./
COPY third_party ./third_party
COPY tuxigap ./tuxigap
RUN pip install --no-cache-dir . \
    && useradd --uid 10001 --create-home appuser \
    && mkdir -p /app/data && chown -R appuser:appuser /app/data
USER appuser
VOLUME ["/app/data"]
HEALTHCHECK --interval=60s --timeout=5s --start-period=90s --retries=3 CMD ["python", "-m", "tuxigap.health"]
CMD ["python", "-m", "tuxigap"]
