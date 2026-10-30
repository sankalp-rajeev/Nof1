"""ASGI entry point. Health does not access a database or LLM."""

from fastapi import FastAPI

app = FastAPI(title="Nof1", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
