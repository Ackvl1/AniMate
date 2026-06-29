import numpy as np
from pathlib import Path
import pickle
from typing import List, Tuple

class VectorStore:
    def __init__(self):
        self.chunks = []  # 存储文本块
        self.vectors = np.array([])  # 存储对应的向量

    def add(self, chunks: list[str], vectors: np.ndarray):
        if len(chunks) != vectors.shape[0]:
            raise ValueError("文本块数量与向量数量不匹配")
        
        if self.vectors.size == 0:
            self.vectors = vectors
        else:
            if self.vectors.shape[1] != vectors.shape[1]:
                raise ValueError("新向量的维度与现有向量的维度不匹配")
            else:
                self.vectors = np.vstack((self.vectors, vectors))
        self.chunks.extend(chunks)
    
    def search(self, query_vec: np.ndarray, top_k: int = 5) -> list[tuple[str, float]]:
        """余弦相似度检索。
        
        Args:
            query_vec: 查询向量，shape (dim,) 或 (1, dim)
            top_k: 返回 top-k 条结果
            
        Returns:
            [(chunk_text, score), ...]  按 score 降序排列
        """
        if self.vectors.size == 0:
            return []
       
        query_vec = np.atleast_2d(query_vec) #(1,dim)

        # ── 核心一行：矩阵乘法算余弦相似度 ──
        # self.vectors:  (N, dim)
        # query_vec.T:   (dim, 1)
        # → scores:      (N, 1)
        norms_v = np.linalg.norm(self.vectors, axis=1, keepdims=True)   # (N, 1)
        norm_q = np.linalg.norm(query_vec, axis=1, keepdims=True)       # (1, 1)
        # 为避免除零，添加一个小常数
        eps = 1e-10
        cos_sim = (self.vectors @ query_vec.T) / (norms_v * norm_q.T + eps)  # (N, 1)
        scores = cos_sim.flatten()

        top_indices = np.argsort(scores)[::-1][:top_k]

        return [(self.chunks[i], scores[i]) for i in top_indices]
    
    def save(self, path: Path):
        path =Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump((self.chunks, self.vectors), f)

    @classmethod
    def load(cls, path: Path) -> "VectorStore":
        if not path.exists():
            return cls() # 返回一个空的 VectorStore
        with open(path, "rb") as f:
            chunks, vectors = pickle.load(f)
        store = cls()
        store.chunks = chunks
        store.vectors = vectors
        return store
    