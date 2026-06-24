"""WebExtractTool — 网页内容提取"""

from animate.core.tools.base import LocalTool


class WebExtractTool(LocalTool):
    """提取网页的文本内容。"""
    name = "web_extract"
    description = "读取指定 URL 的网页内容，返回纯文本。适合查看文章、文档等"
    is_read_only = True
    is_parallel_safe = True
    is_destructive = False
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "网页 URL",
            },
            "max_chars": {
                "type": "integer",
                "description": "最大返回字符数（默认 3000）",
            },
        },
        "required": ["url"],
    }

    def execute(self, url: str, max_chars: int = 3000) -> str:
        try:
            import requests
            from bs4 import BeautifulSoup

            resp = requests.get(
                url,
                timeout=15,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                },
            )
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")

            # 移除无用标签
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()

            text = soup.get_text(separator="\n", strip=True)

            # 清理多余空行
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            text = "\n".join(lines)

            if len(text) > max_chars:
                text = text[:max_chars] + "\n...(已截断)"

            return text

        except Exception as e:
            return f"网页读取失败: {e}"
