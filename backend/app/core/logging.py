 

# """
# app/core/logging.py
# Structured JSON logging via structlog.
# """
# import logging
# import os
# from logging.handlers import RotatingFileHandler
# from pathlib import Path

# import structlog
# from app.core.config import settings


# def configure_logging() -> None:
#     log_level = logging.DEBUG if settings.DEBUG else logging.INFO

#     # Standard logging handlers
#     handlers = [logging.StreamHandler()]  # Console output (important for Docker)

#     # File logging is optional in containerized environments where some paths
#     # can be read-only. We try preferred paths and gracefully fallback.
#     log_dir_candidates = []
#     env_log_dir = os.environ.get("LOG_DIR")
#     if env_log_dir:
#         log_dir_candidates.append(Path(env_log_dir))
#     log_dir_candidates.extend([Path("logs"), Path("/tmp/punk_ai_logs")])

#     for log_dir in log_dir_candidates:
#         try:
#             log_dir.mkdir(parents=True, exist_ok=True)
#             log_file = log_dir / "app.log"
#             handlers.append(
#                 RotatingFileHandler(
#                     str(log_file),
#                     maxBytes=10 * 1024 * 1024,  # 10MB
#                     backupCount=5,
#                 )
#             )
#             break
#         except OSError:
#             # Keep startup resilient: console logging is enough to run.
#             continue

#     # Configure standard logging
#     logging.basicConfig(
#         level=log_level,
#         format="%(message)s",
#         handlers=handlers,
#     )

#     # Configure structlog
#     structlog.configure(
#         processors=[
#             structlog.contextvars.merge_contextvars,
#             structlog.processors.add_log_level,
#             structlog.processors.TimeStamper(fmt="iso"),
#             structlog.processors.JSONRenderer() 
#             if not settings.DEBUG and os.environ.get("ENVIRONMENT") == "production" 
#             else structlog.dev.ConsoleRenderer(colors=True),
#         ],
#         wrapper_class=structlog.make_filtering_bound_logger(log_level),
#         context_class=dict,
#         logger_factory=structlog.stdlib.LoggerFactory(),
#         cache_logger_on_first_use=True,
#     )


# logger = structlog.get_logger()

"""
app/core/logging.py
Structured logging with Structlog + Rich.
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

import structlog
from rich.logging import RichHandler

from app.core.config import settings


def configure_logging() -> None:
    log_level = logging.DEBUG if settings.DEBUG else logging.INFO

    # ---------------------------
    # Console Handler
    # ---------------------------
    console_handler = RichHandler(
        rich_tracebacks=True,
        markup=True,
        show_path=False,
        show_time=True,
    )

    handlers = [console_handler]

    # ---------------------------
    # File Handler
    # ---------------------------
    log_dir_candidates = []

    if os.getenv("LOG_DIR"):
        log_dir_candidates.append(Path(os.getenv("LOG_DIR")))

    log_dir_candidates.extend(
        [
            Path("logs"),
            Path("/tmp/punk_ai_logs"),
        ]
    )

    for log_dir in log_dir_candidates:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)

            handlers.append(
                RotatingFileHandler(
                    log_dir / "app.log",
                    maxBytes=10 * 1024 * 1024,
                    backupCount=5,
                    encoding="utf-8",
                )
            )
            break

        except OSError:
            continue

    # ---------------------------
    # Python Logging
    # ---------------------------
    logging.basicConfig(
        level=log_level,
        format="%(message)s",
        handlers=handlers,
        force=True,  # important
    )

    # Make uvicorn use the same handlers
    for logger_name in (
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "sqlalchemy.engine",
    ):
        log = logging.getLogger(logger_name)
        log.handlers = handlers
        log.setLevel(log_level)
        log.propagate = False

    # httpx logs the full request URL at INFO, which writes the Google Maps
    # `key=AIza...` into app.log; httpcore adds per-frame trace spam at DEBUG.
    # Nothing is lost - every tool logs its own outcome.
    for _noisy in ("httpx", "httpcore"):
        logging.getLogger(_noisy).setLevel(logging.WARNING)

    # ---------------------------
    # Structlog
    # ---------------------------
    if settings.DEBUG:
        renderer = structlog.dev.ConsoleRenderer(
            colors=True,
        )
    else:
        renderer = (
            structlog.processors.JSONRenderer()
            if os.getenv("ENVIRONMENT") == "production"
            else structlog.dev.ConsoleRenderer(colors=True)
        )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="%H:%M:%S"),
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        context_class=dict,
        cache_logger_on_first_use=True,
    )


logger = structlog.get_logger()
