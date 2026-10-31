"""Application logging policy: external SDK request/response bodies stay disabled."""

import logging

PROVIDER_LOGGERS = ("openai", "google.genai", "httpx", "httpx2", "httpcore", "httpcore2", "urllib3")


def protect_provider_logs() -> None:
    # Configure parents as sinks so future descendant loggers also cannot leak bodies.
    names = set(PROVIDER_LOGGERS) | {
        name for name in logging.Logger.manager.loggerDict if name.startswith(PROVIDER_LOGGERS)
    }
    for name in names:
        logger = logging.getLogger(name)
        logger.handlers[:] = [logging.NullHandler()]
        logger.propagate = False
        logger.disabled = True
