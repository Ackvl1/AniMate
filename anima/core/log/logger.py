"""统一日志配置"""

import logging

_LOG_FORMAT = "[%(asctime)s] [%(name)s] %(levelname)s: %(message)s"
_DATE_FORMAT = "%H:%M:%S"


def setup_logger(name: str, level: int = logging.WARNING) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger


def set_log_level(level: int) -> None:
    """运行时切换所有 anima.* logger 的级别。"""
    for name in list(logging.root.manager.loggerDict):
        if name.startswith("anima"):
            logging.getLogger(name).setLevel(level)
