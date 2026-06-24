"""WikipediaTool — 维基百科搜索与摘要"""

from animate.core.tools.base import LocalTool


class WikipediaTool(LocalTool):
    """搜索并获取维基百科文章摘要。"""
    name = "wikipedia"
    description = "搜索维基百科并返回文章摘要。用于获取人物、事件、概念等知识"
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
            "lang": {
                "type": "string",
                "enum": ["zh", "en", "ja"],
                "description": "语言（zh=中文, en=英文, ja=日文）",
            },
        },
        "required": ["query"],
    }

    SEARCH_URL = "https://{lang}.wikipedia.org/w/api.php"

    def execute(self, query: str, lang: str = "zh") -> str:
        import requests

        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "format": "json",
            "srlimit": 3,
        }
        try:
            resp = requests.get(
                self.SEARCH_URL.format(lang=lang),
                params=params,
                timeout=10,
                headers={"User-Agent": "AniMate/1.0"},
            )
            resp.raise_for_status()
            data = resp.json()

            results = []
            for item in data.get("query", {}).get("search", [])[:3]:
                title = item.get("title", "")
                snippet = item.get("snippet", "").replace("<span class=\"searchmatch\">", "").replace("</span>", "")
                results.append(f"【{title}】\n{snippet}")

            if not results:
                return f"未找到 '{query}' 的相关结果"

            return "\n\n---\n\n".join(results)

        except Exception as e:
            return f"维基百科查询失败: {e}"
