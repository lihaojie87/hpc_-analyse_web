import logging
import structlog

def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO), format="%(message)s")
    structlog.configure(processors=[structlog.contextvars.merge_contextvars, structlog.processors.TimeStamper(fmt="iso"), structlog.processors.JSONRenderer()])
