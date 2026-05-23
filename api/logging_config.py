import logging
import sys


def configure_logging(environment="development"):
    level = logging.INFO
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)

    if environment == "production":
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name):
    return logging.getLogger(name)

