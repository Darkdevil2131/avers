FROM python:3.12-slim
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock \
    && useradd --create-home noesis \
    && mkdir /state && chown noesis:noesis /state
COPY noesis ./noesis
USER noesis
ENV NOESIS_DATABASE_URL=sqlite:////state/noesis.db NOESIS_DATA_DIR=/state/data
EXPOSE 8000
CMD ["uvicorn", "noesis.api.main:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8000"]
