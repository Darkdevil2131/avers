FROM node:22-bookworm-slim AS frontend
WORKDIR /build/web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm test && npm run build

FROM python:3.12-slim
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock && useradd --uid 10001 --create-home ares
COPY ares/ ./ares/
COPY scripts/ ./scripts/
COPY requirements-reasoner.txt ./
ARG WITH_REASONER=0
RUN if [ "$WITH_REASONER" = "1" ]; then pip install --no-cache-dir -r requirements-reasoner.txt; fi
ENV ORT_DISABLE_TELEMETRY=1 HF_HUB_DISABLE_TELEMETRY=1 DO_NOT_TRACK=1
COPY --from=frontend /build/ares/static ./ares/static
RUN mkdir state && chown ares:ares state
USER 10001
ENV ARES_DATABASE=/app/state/ares.db
EXPOSE 8000
CMD ["uvicorn", "ares.api:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8000"]
