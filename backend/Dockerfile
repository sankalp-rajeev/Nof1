FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1
RUN pip install --no-cache-dir uv==0.10.2
WORKDIR /srv/nof1/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY backend ./
COPY config /srv/nof1/config
COPY data /srv/nof1/data
RUN useradd --create-home --uid 10001 nof1
USER nof1
ENV PATH="/srv/nof1/backend/.venv/bin:${PATH}"
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]
