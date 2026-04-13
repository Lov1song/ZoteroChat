"""
测试 retriever：用 cache 里的真实 index 做一次检索。
"""
from pathlib import Path
from src.indexing.cache import load_index
from src.retrieval.retriever import search_with_rerank


def main():
    # 加载索引
    print("加载索引...")
    index = load_index(Path("data/cache"))
    if index is None:
        print("❌ 缓存不存在，请先跑 builder")
        return
    
    print(f"✅ 索引加载成功: {len(index.chunks)} chunks")
    
    # 测试几个查询
    queries = [
        "Mamba for hyperspectral reconstruction",
        "什么是 wavelet transform",
        "spectral-wise self-attention",
    ]
    
    for query in queries:
        print("\n" + "=" * 70)
        print(f"查询: {query}")
        print("=" * 70)
        
        results = search_with_rerank(
            query=query,
            chunks=index.chunks,
            vectors=index.vectors,
            recall_k=40,
            final_k=5,
        )
        
        for i, (chunk, score) in enumerate(results, 1):
            print(f"\n[{i}] score={score:.3f} | level={chunk.level} | {chunk.paper_title[:60]}")
            print(f"    section: {chunk.section_title}")
            print(f"    collections: {chunk.collections}")
            print(f"    text: {chunk.text[:200]}...")


if __name__ == "__main__":
    main()