"""Tests for animate/core/paths.py — data directory resolution."""

from pathlib import Path
from anima.core.paths import (
    project_root,
    data_root,
    documents_dir,
    vectorlibrary_dir,
    keywordlibrary_dir,
    logs_dir,
)


def test_project_root_is_absolute_path():
    """project_root() 应返回绝对路径。"""
    root = project_root()
    assert isinstance(root, Path)
    assert root.is_absolute()


def test_data_root_is_under_animate():
    """data_root() 应在 project_root/animate/data/。"""
    root = data_root()
    assert root.name == "data"
    assert root.parent.name == "animate"
    assert root.parent.parent == project_root()


def test_project_root_contains_animate():
    """project_root 应包含 animate/ 目录。"""
    root = project_root()
    assert (root / "animate").is_dir()


def test_documents_dir():
    """documents_dir() 应返回 data/documents/。"""
    d = documents_dir()
    assert d == data_root() / "documents"


def test_vectorlibrary_dir():
    """vectorlibrary_dir() 应返回 data/vectorlibrary/。"""
    d = vectorlibrary_dir()
    assert d == data_root() / "vectorlibrary"


def test_keywordlibrary_dir():
    """keywordlibrary_dir() 应返回 data/keywordlibrary/。"""
    d = keywordlibrary_dir()
    assert d == data_root() / "keywordlibrary"


def test_logs_dir():
    """logs_dir() 应返回 animate/data/logs/。"""
    d = logs_dir()
    assert d == data_root() / "logs"
