from pathlib import Path
import pickle
import logging
import jieba
jieba.setLogLevel(logging.WARNING)
from collections import defaultdict

class KeywordStore:
    def __init__(self):
        self._index:dict[str,list[int]] = defaultdict(list)
        self._chunks:list[str]=[]
    
    def add(self, chunk: str) -> None:
        """添加单个文本块到索引。"""
        idx = len(self._chunks)
        self._chunks.append(chunk)
        tokens = set(jieba.cut(chunk))
        for token in tokens:
            if len(token.strip()) > 1:
                self._index[token].append(idx)
    
    def build(self,chunks:list[str])->None:
        self._chunks=chunks
        for i,chunk in enumerate(chunks):
            tokens = set(jieba.cut(chunk))
            for token in tokens:
                if len(token.strip())>1:
                    self._index[token].append(i)
    
    def search(self,query:str)->list[tuple[str,float]]:
        query_tokens=set(jieba.cut(query))
        
        hit_count:dict[int,int] ={}

        for token in query_tokens:
            for chunk_idx in self._index[token]:
                hit_count[chunk_idx]= hit_count.get(chunk_idx,0)+1

        num_tokens = len(query_tokens)

        sorted_items = [
            (self._chunks[chunk_idx], hit_count[chunk_idx] / num_tokens)
            for chunk_idx in hit_count
        ]

        sorted_items.sort(key=lambda x: x[1], reverse=True)
        return sorted_items
    
    def save(self,path:Path)->None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump((self._chunks, self._index), f)

    @classmethod
    def load(cls,path:Path) ->"KeywordStore":
        if not path.exists():
            return cls() # 返回一个空的 VectorStore
        with open(path, "rb") as f:
            chunks, index = pickle.load(f)
        
        store=cls()
        store._chunks=chunks
        store._index=index
        return store
        

        