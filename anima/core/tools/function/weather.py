"""WeatherTool — 天气查询（Open-Meteo，完全免费，无需 API Key）"""

from anima.core.tools.base import LocalTool


class WeatherTool(LocalTool):
    """查询全球城市当前天气。"""
    name = "weather"
    description = "查询指定城市的当前天气、温度、湿度、风速等信息"
    is_read_only = True
    is_parallel_safe = True
    is_destructive = False
    parameters = {
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "城市名，如 'Beijing'、'Tokyo'、'London'",
            },
        },
        "required": ["city"],
    }

    GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
    WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

    def execute(self, city: str) -> str:
        import requests

        try:
            # 1. 地理编码：城市名 → 经纬度
            geo_resp = requests.get(
                self.GEO_URL,
                params={"name": city, "count": 1, "language": "zh", "format": "json"},
                timeout=10,
            )
            geo_resp.raise_for_status()
            geo_data = geo_resp.json()

            if not geo_data.get("results"):
                # 尝试英文查询
                geo_resp = requests.get(
                    self.GEO_URL,
                    params={"name": city, "count": 1, "format": "json"},
                    timeout=10,
                )
                geo_resp.raise_for_status()
                geo_data = geo_resp.json()
                if not geo_data.get("results"):
                    return f"未找到城市: {city}"

            loc = geo_data["results"][0]
            lat, lon = loc["latitude"], loc["longitude"]
            name = loc.get("name", city)
            country = loc.get("country", "")

            # 2. 查询天气
            weather_resp = requests.get(
                self.WEATHER_URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m,wind_direction_10m",
                    "timezone": "auto",
                },
                timeout=10,
            )
            weather_resp.raise_for_status()
            w = weather_resp.json()["current"]

            # 天气代码 → 中文描述
            code_text = self._code_to_text(w.get("weather_code", 0))

            return (
                f"📍 {name}, {country}\n"
                f"🌡️ 温度: {w['temperature_2m']}°C (体感 {w['apparent_temperature']}°C)\n"
                f"💧 湿度: {w['relative_humidity_2m']}%\n"
                f"🌤️ 天气: {code_text}\n"
                f"💨 风速: {w['wind_speed_10m']} km/h"
            )

        except Exception as e:
            return f"天气查询失败: {e}"

    def _code_to_text(self, code: int) -> str:
        codes = {
            0: "晴天", 1: "大部晴朗", 2: "局部多云", 3: "多云",
            45: "雾", 48: "雾凇",
            51: "小毛毛雨", 53: "毛毛雨", 55: "大毛毛雨",
            61: "小雨", 63: "中雨", 65: "大雨",
            71: "小雪", 73: "中雪", 75: "大雪",
            80: "小阵雨", 81: "中阵雨", 82: "大阵雨",
            95: "雷暴", 96: "雷暴+小冰雹", 99: "雷暴+大冰雹",
        }
        return codes.get(code, f"未知({code})")
