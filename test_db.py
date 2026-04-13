"""
临时测试脚本：验证 src/zotero/db.py 的功能
"""
from src.zotero import db


def test_list_all():
    print("=" * 60)
    print("【测试 1: 列出所有论文】")
    print("=" * 60)
    
    papers = db.list_papers()
    print(f"\n共找到 {len(papers)} 篇论文\n")
    
    # 只打印前 5 篇的详情
    for i, p in enumerate(papers[:5], 1):
        print(f"--- 第 {i} 篇 ---")
        print(f"  title      : {p.title[:80]}")
        print(f"  key        : {p.key}")
        print(f"  type       : {p.item_type}")
        print(f"  authors    : {p.authors[:3]}{'...' if len(p.authors) > 3 else ''}")
        print(f"  year       : {p.year}")
        print(f"  collections: {p.collections}")
        print(f"  tags       : {p.tags}")
        print(f"  pdf exists : {p.pdf_path.exists()}")
        print()


def test_collection_filter():
    print("=" * 60)
    print("【测试 2: 按 collection 过滤】")
    print("=" * 60)
    
    # 随便找一个 collection
    all_papers = db.list_papers()
    
    # 统计每个 collection 出现了多少次
    from collections import Counter
    collection_counter = Counter()
    for p in all_papers:
        for c in p.collections:
            collection_counter[c] += 1
    
    print("\n你的 collection 分布:")
    for name, count in collection_counter.most_common(10):
        print(f"  {name:<30} {count}")
    
    # 如果有 collection，随机选一个过滤测试
    if collection_counter:
        test_col = collection_counter.most_common(1)[0][0]
        filtered = db.list_papers(collection=test_col)
        print(f"\n过滤 collection='{test_col}' 后得到 {len(filtered)} 篇论文")

def test_list_collections():
    print("=" * 60)
    print("【测试 3: list_collections】")
    print("=" * 60)
    
    cols = db.list_collections()
    print(f"\n共 {len(cols)} 个 collection\n")
    for c in cols[:10]:
        parent = f" (父: {c.parent_key[:8]}...)" if c.parent_key else ""
        print(f"  {c.name:<30} {c.paper_count} 篇{parent}")


def test_list_tags():
    print("=" * 60)
    print("【测试 4: list_tags】")
    print("=" * 60)
    
    tags = db.list_tags()
    print(f"\n共 {len(tags)} 个 tag\n")
    for t in tags[:10]:
        print(f"  {t.name:<30} {t.paper_count} 篇")


def test_get_paper():
    print("=" * 60)
    print("【测试 5: get_paper by key】")
    print("=" * 60)
    
    # 先用 list_papers 拿一个 key
    papers = db.list_papers()
    if not papers:
        print("没有论文，跳过测试")
        return
    
    first_key = papers[0].key
    print(f"\n用 key={first_key} 单独查询...")
    
    paper = db.get_paper(first_key)
    if paper:
        print(f"  ✅ 找到: {paper.title[:80]}")
    else:
        print(f"  ❌ 没找到")
    
    # 测试一个不存在的 key
    not_found = db.get_paper("NOTEXIST")
    print(f"\n用不存在的 key 查询: {not_found}")
if __name__ == "__main__":
    test_list_all()
    print()
    test_collection_filter()
    test_list_collections()
    test_list_tags()
    test_get_paper()