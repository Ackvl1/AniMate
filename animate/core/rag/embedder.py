import numpy as np
from animate.core.config import get_embedding_config, embedding_model_name

_EMBEDDING_CLIENT = None
_EMBEDDING_CLIENT_KEY = ""  # 记录创建 client 时的配置指纹
_EMBED_TIMEOUT = 30.0


def _client_key() -> str:
    """当前 embedding 配置的指纹（provider + api_key + base_url）。"""
    cfg = get_embedding_config()
    return f"{cfg.api_key}@{cfg.base_url}"


def _get_client():
    """全局缓存 embedding client，配置变化后自动重建。"""
    global _EMBEDDING_CLIENT, _EMBEDDING_CLIENT_KEY

    current_key = _client_key()
    if _EMBEDDING_CLIENT is not None and _EMBEDDING_CLIENT_KEY != current_key:
        _EMBEDDING_CLIENT = None  # 配置变了，重建

    if _EMBEDDING_CLIENT is None:
        import openai
        cfg = get_embedding_config()
        _EMBEDDING_CLIENT = openai.OpenAI(
            api_key=cfg.api_key,
            base_url=cfg.base_url,
            timeout=_EMBED_TIMEOUT,
        )
        _EMBEDDING_CLIENT_KEY = current_key
    return _EMBEDDING_CLIENT


def embed(texts: list[str]) -> np.ndarray:
    index = 0
    batch_size = 10
    client = _get_client()
    model_name = embedding_model_name()
    embeddings = []
    while index < len(texts):
        input_text = texts[index:index + batch_size]
        completion = client.embeddings.create(
            model=model_name,
            input=input_text,
            timeout=_EMBED_TIMEOUT,
        )
        embeddings.extend([item.embedding for item in completion.data])
        index += batch_size

    return np.array(embeddings, dtype=np.float32)
