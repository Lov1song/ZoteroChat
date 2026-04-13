"""
测试工具能否独立跑通（不经过 agent）
"""
from pathlib import Path
from src.indexing.cache import load_index
from src.agent.tools import (
    set_index,
    search_paper,
    list_papers,
    get_paper_abstract,
    list_collections,
    search_in_collection,
)


def main():
    # 加载 index 并注入
    print("加载 index...")
    index = load_index(Path("data/cache"))
    set_index(index)
    print(f"✅ 已注入 {len(index.chunks)} chunks\n")
    
    # ========== 测试 list_collections ==========
    print("=" * 70)
    print("测试 1: list_collections")
    print("=" * 70)
    # 注意：@tool 装饰后的函数要用 .invoke() 调用
    result = list_collections.invoke({})
    print(result)
    
    # ========== 测试 search_paper ==========
    print("\n" + "=" * 70)
    print("测试 2: search_paper")
    print("=" * 70)
    result = search_paper.invoke({"query": "Mamba hyperspectral"})
    print(result[:1500])
    
    # ========== 测试 get_paper_abstract ==========
    print("\n" + "=" * 70)
    print("测试 3: get_paper_abstract")
    print("=" * 70)
    result = get_paper_abstract.invoke({"paper_name": "MST++"})
    print(result)
    
    # ========== 测试 search_in_collection ==========
    print("\n" + "=" * 70)
    print("测试 4: search_in_collection")
    print("=" * 70)
    result = search_in_collection.invoke({
        "collection": "光谱重建",
        "query": "wavelet transform"
    })
    print(result[:1500])
    
    # ========== 测试 list_papers ==========
    print("\n" + "=" * 70)
    print("测试 5: list_papers")
    print("=" * 70)
    result = list_papers.invoke({})
    print(result[:2000])


if __name__ == "__main__":
    # main()
        # 临时诊断，加在 test_tools.py 末尾或者单独跑
    from src.indexing.cache import load_index
    from pathlib import Path

    index = load_index(Path("data/cache"))

    # 方法 1：从 chunks 聚合
    keys_from_chunks = {c.paper_key for c in index.chunks}
    print(f"chunks 里的唯一 paper_key: {len(keys_from_chunks)}")

    # 方法 2：num_papers_succeeded 字段
    print(f"index.num_papers_succeeded: {index.num_papers_succeeded}")

    # 方法 3：paper_keys() 方法
    print(f"index.paper_keys(): {len(index.paper_keys())}")