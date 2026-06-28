"""FileTools — 文件读写与搜索工具"""

import os
import regex
import glob as glob_module
from pathlib import Path

from anima.core.tools.base import LocalTool


class ReadFileTool(LocalTool):
    """读取文件内容。"""
    name = "read_file"
    description = "读取指定路径的文件内容，支持文本文件"
    is_read_only = True
    is_parallel_safe = True
    is_destructive = False
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "文件路径（绝对路径或相对于项目根目录）",
            },
            "max_chars": {
                "type": "integer",
                "description": "最大读取字符数（默认 5000）",
            },
        },
        "required": ["path"],
    }

    def execute(self, path: str, max_chars: int = 5000) -> str:
        try:
            p = Path(path)
            if not p.exists():
                return f"文件不存在: {path}"
            content = p.read_text(encoding="utf-8")
            if len(content) > max_chars:
                content = content[:max_chars] + "\n...(已截断)"
            return content
        except Exception as e:
            return f"读取失败: {e}"


class WriteFileTool(LocalTool):
    """写入文件内容（覆盖模式）。"""
    name = "write_file"
    description = "写入内容到文件（会覆盖已有内容）"
    is_read_only = False
    is_parallel_safe = False
    is_destructive = False
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "文件路径",
            },
            "content": {
                "type": "string",
                "description": "要写入的内容",
            },
        },
        "required": ["path", "content"],
    }

    def execute(self, path: str, content: str) -> str:
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return f"已写入 {len(content)} 字符到 {path}"
        except Exception as e:
            return f"写入失败: {e}"


class SearchFilesTool(LocalTool):
    """在文件中搜索文本或查找文件。"""
    name = "search_files"
    description = "在项目中搜索文件内容或按文件名查找文件"
    is_read_only = True
    is_parallel_safe = True
    is_destructive = False
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "搜索内容（正则表达式）或文件名通配符（如 *.py）",
            },
            "path": {
                "type": "string",
                "description": "搜索目录（默认当前目录）",
            },
            "mode": {
                "type": "string",
                "enum": ["content", "filename"],
                "description": "搜索模式：content=搜文件内容，filename=按文件名查找",
            },
            "max_results": {
                "type": "integer",
                "description": "最大返回结果数（默认 10）",
            },
        },
        "required": ["pattern"],
    }

    def execute(self, pattern: str, path: str = ".", mode: str = "content", max_results: int = 10) -> str:
        try:
            root = Path(path).resolve()
            if not root.exists():
                return f"目录不存在: {path}"

            if mode == "filename":
                matches = []
                for f in root.rglob(pattern):
                    if f.is_file():
                        rel = f.relative_to(root)
                        matches.append(str(rel))
                        if len(matches) >= max_results:
                            break
                if not matches:
                    return f"未找到匹配文件: {pattern}"
                return "\n".join(matches)

            # content 搜索（使用 regex 库带超时，防 ReDoS）
            results = []
            for f in root.rglob("*"):
                if not f.is_file():
                    continue
                try:
                    text = f.read_text(encoding="utf-8", errors="ignore")
                    for i, line in enumerate(text.split("\n"), 1):
                        try:
                            if regex.search(pattern, line, timeout=2):
                                rel = f.relative_to(root)
                                results.append(f"{rel}:{i}: {line.strip()[:120]}")
                                if len(results) >= max_results:
                                    break
                        except regex.TimeoutError:
                            continue  # 这行正则超时，跳过继续搜
                except Exception:
                    continue
                if len(results) >= max_results:
                    break

            if not results:
                return f"未找到匹配内容: {pattern}"
            return "\n".join(results)

        except Exception as e:
            return f"搜索失败: {e}"
