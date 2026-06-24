"""AniMate 路径中央配置 — 所有数据目录统一在此解析。"""

from __future__ import annotations

from pathlib import Path


def project_root() -> Path:
    """返回项目根目录（包含 animate/ 的目录）。"""
    return Path(__file__).resolve().parent.parent.parent


def data_root() -> Path:
    """返回数据层根目录 animate/data/。"""
    return project_root() / "animate" / "data"


def documents_dir() -> Path:
    return data_root() / "documents"


def vectorlibrary_dir() -> Path:
    return data_root() / "vectorlibrary"


def keywordlibrary_dir() -> Path:
    return data_root() / "keywordlibrary"


def logs_dir() -> Path:
    return data_root() / "logs"


def memory_dir() -> Path:
    d = data_root() / "memory"
    d.mkdir(parents=True, exist_ok=True)
    return d


def sessions_dir() -> Path:
    d = data_root() / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d
