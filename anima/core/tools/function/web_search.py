"""WebSearchTool — 网页搜索（DuckDuckGo，无需 API Key）"""

from anima.core.tools.base import LocalTool


class WebSearchTool(LocalTool):
    """搜索互联网获取实时信息。"""
    name = "web_search"
    description = "搜索互联网，获取实时信息。适合查询新闻、资讯、事实等"
    is_read_only = True
    is_parallel_safe = True
    is_destructive = False
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词",
            },
            "max_results": {
                "type": "integer",
                "description": "最大返回结果数（默认 5）",
            },
        },
        "required": ["query"],
    }

    def execute(self, query: str, max_results: int = 5) -> str:
        try:
            from ddgs import DDGS
            results = []
            with DDGS() as ddgs:
                for i, r in enumerate(ddgs.text(query, max_results=max_results)):
                    title = r.get("title", "")
                    body = r.get("body", "")
                    href = r.get("href", "")
                    results.append(f"[{i+1}] {title}\n{body}\n{href}")

            if not results:
                return f"未搜索到 '{query}' 的相关结果"

            return "\n\n".join(results)

        except Exception as e:
            return f"搜索失败: {e}"
