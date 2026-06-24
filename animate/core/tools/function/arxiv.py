"""ArxivTool — 学术论文搜索（arXiv，完全免费）"""

from animate.core.tools.base import LocalTool


class ArxivTool(LocalTool):
    """搜索 arXiv 学术论文。"""
    name = "arxiv"
    description = "搜索 arXiv 上的学术论文（科学、数学、计算机等领域的预印本）"
    is_read_only = True
    is_parallel_safe = True
    is_destructive = False
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词，如 'transformer' 或 'quantum computing'",
            },
            "max_results": {
                "type": "integer",
                "description": "最大返回篇数（默认 3）",
            },
        },
        "required": ["query"],
    }

    API_URL = "http://export.arxiv.org/api/query"

    def execute(self, query: str, max_results: int = 3) -> str:
        import feedparser

        try:
            params = {
                "search_query": f"all:{query}",
                "start": 0,
                "max_results": max_results,
                "sortBy": "relevance",
                "sortOrder": "descending",
            }
            import urllib.parse
            url = f"{self.API_URL}?{urllib.parse.urlencode(params)}"
            feed = feedparser.parse(url)

            entries = feed.get("entries", [])
            if not entries:
                return f"未找到相关论文: {query}"

            results = []
            for i, entry in enumerate(entries[:max_results]):
                title = entry.get("title", "").replace("\n", " ").strip()
                authors = ", ".join(a.get("name", "") for a in entry.get("authors", [])[:3])
                summary = entry.get("summary", "").replace("\n", " ").strip()[:200]
                link = entry.get("link", "")
                published = entry.get("published", "")[:10]

                results.append(
                    f"[{i+1}] {title}\n"
                    f"    作者: {authors}\n"
                    f"    日期: {published}\n"
                    f"    摘要: {summary}...\n"
                    f"    链接: {link}"
                )

            return "\n\n".join(results)

        except ImportError:
            return "需要安装 feedparser: pip install feedparser"
        except Exception as e:
            return f"论文搜索失败: {e}"
