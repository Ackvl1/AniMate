from pathlib import Path
from anima.core.rag.KeywordStore import KeywordStore
from anima.core.rag.chunker import chunk_text
from anima.core.rag.embedder import embed
from anima.core.rag.loader import load_documents
from anima.core.rag.VectorStore import VectorStore
from anima.core.paths import data_root

if __name__ == "__main__":

    store_name = input("请输入库名:\n")
    store_path = data_root() / "vectorlibrary" / f"{store_name}.pkl"
    untrained_dir = data_root() / "documents" / store_name / "UnTranned"
    trained_dir = data_root() / "documents" / store_name / "Trained"
    shared_trained_dir = data_root() / "documents" / "Shared"
    keyword_store_path = data_root() / "keywordlibrary" / f"{store_name}.pkl"

    answer = input("需要使用共享文档建库么 Y/N\n")
    need_use_shared = answer in {"Y", "y", "Yes", "YES", "yes"}

    vector_store = VectorStore.load(store_path)
    keyword_store = KeywordStore.load(keyword_store_path)

    documents = []
    if untrained_dir.exists():
        local_docs = load_documents(untrained_dir)
        documents.extend(local_docs)

    if need_use_shared and shared_trained_dir.exists():
        shared_docs = load_documents(shared_trained_dir)
        documents.extend(shared_docs)

    if not documents:
        print("目录下没有待处理文档")
        exit(0)

    texts = []
    for name, content in documents:
        print(f"文件名: {name}, 内容长度: {len(content)}")
        chunks = chunk_text(content)
        for chunk in chunks:
            texts.append(chunk)

    print(f"总待处理chunk数量: {len(texts)}")

    if texts:
        vectors = embed(texts)
        vector_store.add(texts, vectors)
        for chunk in texts:
            keyword_store.add(chunk)

        vector_store.save(store_path)
        keyword_store.save(keyword_store_path)
        print(f"知识库 '{store_name}' 构建完成")
        print(f"  → 向量库: {store_path}")
        print(f"  → 关键词库: {keyword_store_path}")
    else:
        print("没有文本块需要处理")
