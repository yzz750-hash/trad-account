import logging
import sys
from logging.handlers import RotatingFileHandler
import os
from contextvars import ContextVar

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")

# Context variable for request_id propagation into log records
request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)


class RequestIdFilter(logging.Filter):
    """Inject the current request_id into log records for correlation."""
    def filter(self, record):
        record.request_id = request_id_ctx.get(None) or "-"
        return True


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """
    Structured logging for the financial application.
    Writes to rotating files (audit log) and stdout.
    """
    os.makedirs(LOG_DIR, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Clear existing handlers to avoid duplicates on reload
    root_logger.handlers.clear()

    req_filter = RequestIdFilter()

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.addFilter(req_filter)
    console.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(request_id)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root_logger.addHandler(console)

    # File handler (rotating) - application log
    app_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, "app.log"),
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding="utf-8",
    )
    app_handler.setLevel(level)
    app_handler.addFilter(req_filter)
    app_handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(request_id)s | %(name)s | %(filename)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root_logger.addHandler(app_handler)

    # Audit log (separate file, always INFO+)
    audit_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, "audit.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=10,
        encoding="utf-8",
    )
    audit_handler.setLevel(logging.INFO)
    audit_handler.addFilter(req_filter)
    audit_handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(request_id)s | AUDIT | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root_logger.addHandler(audit_handler)

    logger = logging.getLogger("trad_account")
    logger.info("Logging system initialized")
    return logger
