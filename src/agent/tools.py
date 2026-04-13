"""
Agent 工具定义

所有工具都通过 @tool 装饰器暴露给 LangGraph。
工具函数的职责很单一：接收参数 → 查询 index 或 zotero_db → 返回格式化字符串。

注意：工具函数返回的是 str（而不是结构化数据），因为 LangGraph 的 ToolNode
会把返回值直接作为 tool message 的 content 传给 LLM。LLM 看到的是文本。
"""
from typing import Optional

from langchain_core.tools import tool

from src.zotero import db as zotero_db
from src.indexing.schema import Index
from src.retrieval.retriever import search_with_rerank


# ==================== 全局 index 注入 ====================
# 启动时用 set_index() 注入，之后所有工具函数从这里读取
_index: Optional[Index] = None


def set_index(index: Index) -> None:
    """启动时注入 index。所有 @tool 函数都会用这个全局 index。"""
    global _index
    _index = index


def _ensure_index() -> Index:
    """确保 index 已注入，否则抛错"""
    if _index is None:
        raise RuntimeError("Index 未加载，请先调用 set_index()")
    return _index


# ==================== 辅助函数：格式化检索结果 ====================

def _format_search_results(results: list, max_text_length: int = 400) -> str:
    """
    把 search_with_rerank 的结果格式化成 LLM 友好的字符串。
    
    设计要点：
    1. 每个结果带完整元数据（paper_title, collection, section, level）
    2. text 截断到 400 字符，防止单个 chunk 撑爆 context
    3. 用 --- 分隔结果，方便 LLM 识别边界
    """
    if not results:
        return "未找到相关内容。"
    
    parts = []
    for i, (chunk, score) in enumerate(results, 1):
        parts.append(
            f"[结果 {i}] (相关度: {score:.3f})\n"
            f"论文: {chunk.paper_title}\n"
            f"作者: {', '.join(chunk.authors[:3])}{' 等' if len(chunk.authors) > 3 else ''}\n"
            f"年份: {chunk.year or '未知'}\n"
            f"Collection: {', '.join(chunk.collections) if chunk.collections else '无'}\n"
            f"来源: {chunk.section_title or '正文'} ({chunk.level}级)\n"
            f"内容: {chunk.text[:max_text_length]}"
            f"{'...' if len(chunk.text) > max_text_length else ''}"
        )
    return "\n\n---\n\n".join(parts)


# ==================== 工具 1: search_paper ====================

@tool
def search_paper(query: str) -> str:
    """
    在所有已加载的论文中做语义检索，返回最相关的段落。
    
    使用场景：
    - 用户询问具体方法、实验细节、数据集等内容时
    - 用户询问"哪些论文用了 X"这类跨论文查询时
    - 需要具体文本依据来回答问题时
    
    参数：
        query: 用英文的检索关键词，3-6 个词最佳，例如 "Mamba hyperspectral reconstruction"
    
    返回：5 个最相关的 chunks（带论文名、章节、相关度等元信息）
    """
    index = _ensure_index()
    results = search_with_rerank(
        query=query,
        chunks=index.chunks,
        vectors=index.vectors,
        recall_k=40,
        final_k=5,
    )
    return _format_search_results(results)


# ==================== 工具 2: list_papers ====================

@tool
def list_papers() -> str:
    """
    列出 Zotero 中所有已加载的论文。
    
    使用场景：
    - 用户问"有哪些论文" / "你加载了什么"
    - 需要给用户一个全局概览时
    - 用户询问某篇论文是否在库里时
    
    返回：论文列表（标题、作者、年份、collection）
    """
    index = _ensure_index()
    
    # 从 chunks 里聚合出"每篇论文一条记录"
    # 用 paper_key 去重
    papers_seen = {}
    for chunk in index.chunks:
        if chunk.paper_key in papers_seen:
            continue
        papers_seen[chunk.paper_key] = chunk
    
    if not papers_seen:
        return "索引中没有论文。"
    
    # 按 collection 分组展示
    from collections import defaultdict
    by_collection = defaultdict(list)
    for chunk in papers_seen.values():
        cols = chunk.collections or ["未分类"]
        for col in cols:
            by_collection[col].append(chunk)
    
    lines = [f"共 {len(papers_seen)} 篇论文，按 collection 分组：\n"]
    for col_name in sorted(by_collection.keys()):
        papers = by_collection[col_name]
        lines.append(f"\n【{col_name}】({len(papers)} 篇)")
        for p in papers[:20]:  # 每个 collection 最多展示 20 篇，避免 context 炸
            authors_str = p.authors[0] if p.authors else "未知"
            if len(p.authors) > 1:
                authors_str += " 等"
            year_str = f" ({p.year})" if p.year else ""
            lines.append(f"  · {p.paper_title[:80]} - {authors_str}{year_str}")
        if len(papers) > 20:
            lines.append(f"  ... 还有 {len(papers) - 20} 篇未显示")
    
    return "\n".join(lines)


# ==================== 工具 3: get_paper_abstract ====================

@tool
def get_paper_abstract(paper_name: str) -> str:
    """
    根据论文标题（或关键词）获取该论文的摘要。
    
    使用场景：
    - 用户询问"XX 论文讲了什么"这类概括性问题
    - 比 search_paper 更快更直接，因为直接返回 Abstract，不需要语义检索
    
    参数：
        paper_name: 论文名称或标题中的关键词，例如 "MST++" 或 "WDTM-CL"
    
    返回：匹配论文的摘要（如果有多篇匹配，返回前 3 篇）
    """
    index = _ensure_index()
    
    # 在 chunks 里找 level=document 的（那是 Abstract）
    # 按 paper_name 模糊匹配
    query_lower = paper_name.lower()
    matches = []
    seen_keys = set()
    
    for chunk in index.chunks:
        if chunk.level != "document":
            continue
        if chunk.paper_key in seen_keys:
            continue
        if query_lower in chunk.paper_title.lower():
            matches.append(chunk)
            seen_keys.add(chunk.paper_key)
    
    if not matches:
        return f"未找到标题包含 '{paper_name}' 的论文。你可以先调用 list_papers 查看所有论文。"
    
    # 最多返回前 3 篇
    parts = []
    for chunk in matches[:3]:
        parts.append(
            f"论文: {chunk.paper_title}\n"
            f"作者: {', '.join(chunk.authors)}\n"
            f"年份: {chunk.year or '未知'}\n"
            f"Collection: {', '.join(chunk.collections) if chunk.collections else '无'}\n\n"
            f"摘要:\n{chunk.text}"
        )
    
    result = "\n\n" + "=" * 50 + "\n\n".join(parts) if len(matches) > 1 else parts[0]
    if len(matches) > 3:
        result += f"\n\n(还有 {len(matches) - 3} 篇匹配未显示)"
    return result


# ==================== 工具 4: list_collections ====================

@tool
def list_collections() -> str:
    """
    列出 Zotero 中所有的 collection（分类文件夹）。
    
    使用场景：
    - 用户问"你有哪些分类" / "我的 Zotero 有什么 collection"
    - 需要展示文献库的组织结构时
    
    返回：所有 collection 的名称和论文数量
    """
    collections = zotero_db.list_collections()
    
    if not collections:
        return "没有找到 collection。"
    
    # 按论文数降序排
    collections.sort(key=lambda c: c.paper_count, reverse=True)
    
    lines = [f"共 {len(collections)} 个 collection：\n"]
    for c in collections:
        parent_note = ""
        if c.parent_key:
            parent_note = f" (子集)"
        lines.append(f"  · {c.name}: {c.paper_count} 篇{parent_note}")
    
    return "\n".join(lines)


# ==================== 工具 5: search_in_collection ====================

@tool
def search_in_collection(collection: str, query: str) -> str:
    """
    在指定 collection 内做语义检索。
    
    使用场景：
    - 用户限定了搜索范围，比如 "在光谱重建 collection 里找 Mamba 相关论文"
    - 跨 collection 检索不合适时（防止噪声）
    
    参数：
        collection: collection 名称，例如 "光谱重建"
        query: 检索关键词，用英文
    
    返回：该 collection 内最相关的段落
    """
    index = _ensure_index()
    
    # 先过滤出属于这个 collection 的 chunks
    filtered_chunks = [
        c for c in index.chunks
        if collection in c.collections
    ]
    
    if not filtered_chunks:
        return f"Collection '{collection}' 不存在或为空。请用 list_collections 查看可用的 collection。"
    
    # 找到这些 chunks 在原 vectors 里的索引
    chunk_indices = []
    for i, c in enumerate(index.chunks):
        if collection in c.collections:
            chunk_indices.append(i)
    
    # 构造过滤后的 vectors（注意这里是 numpy 切片）
    import numpy as np
    filtered_vectors = index.vectors[chunk_indices]
    
    # 在过滤后的子集上检索
    results = search_with_rerank(
        query=query,
        chunks=filtered_chunks,
        vectors=filtered_vectors,
        recall_k=20,   # collection 较小，不需要召回那么多
        final_k=5,
    )
    
    header = f"在 collection '{collection}' 中检索 '{query}' 的结果（共 {len(filtered_chunks)} chunks 可用）：\n\n"
    return header + _format_search_results(results)

@tool
def list_tags() -> str:
    """
    列出 Zotero 中所有的 tag（标签）。
    
    使用场景：
    - 用户问"我打了哪些标签" / "有哪些 tag"
    - 需要了解文献库的标记结构时
    - 用户想知道有多少论文打了某个 tag 时
    
    返回：所有 tag 的名称和对应论文数
    """
    tags = zotero_db.list_tags()
    
    if not tags:
        return "文献库里没有任何 tag。"
    
    # 按论文数降序
    tags.sort(key=lambda t: t.paper_count, reverse=True)
    
    lines = [f"共 {len(tags)} 个 tag：\n"]
    for t in tags:
        lines.append(f"  · {t.name}: {t.paper_count} 篇")
    
    return "\n".join(lines)

@tool
def search_by_tag(tag: str, query: str) -> str:
    """
    在指定 tag 下的论文中做语义检索。
    
    使用场景：
    - 用户限定了 tag 范围，比如 "在 to_read 里找 Mamba 相关论文"
    - 需要在标记过的子集里做精确检索时
    
    参数：
        tag: tag 名称，例如 "to_read" 或 "Computer Vision"
        query: 检索关键词，用英文
    
    返回：该 tag 下最相关的段落
    """
    index = _ensure_index()
    
    # 过滤出打了这个 tag 的 chunks
    filtered_chunks = [
        c for c in index.chunks
        if tag in c.tags
    ]
    
    if not filtered_chunks:
        return f"没有论文打了 '{tag}' 这个 tag。请用 list_tags 查看可用的 tag。"
    
    # 找到这些 chunks 在原 vectors 里的索引
    chunk_indices = [
        i for i, c in enumerate(index.chunks)
        if tag in c.tags
    ]
    filtered_vectors = index.vectors[chunk_indices]
    
    # 在子集上检索
    results = search_with_rerank(
        query=query,
        chunks=filtered_chunks,
        vectors=filtered_vectors,
        recall_k=20,
        final_k=5,
    )
    
    header = f"在 tag '{tag}' 下检索 '{query}' 的结果（共 {len(filtered_chunks)} chunks 可用）：\n\n"
    return header + _format_search_results(results)

@tool
def get_papers_in_collection(collection: str) -> str:
    """
    列出指定 collection 下的所有论文。
    
    使用场景：
    - 用户问"XX collection 里有哪些论文"
    - 比 list_papers 更精确，不需要返回全库列表
    
    参数：
        collection: collection 名称，例如 "光谱重建"
    
    返回：该 collection 下所有论文的列表（标题、作者、年份）
    """
    index = _ensure_index()
    
    # 从 chunks 里聚合出该 collection 的论文
    papers_seen = {}
    for chunk in index.chunks:
        if collection not in chunk.collections:
            continue
        if chunk.paper_key in papers_seen:
            continue
        papers_seen[chunk.paper_key] = chunk
    
    if not papers_seen:
        return f"Collection '{collection}' 不存在或没有论文。请用 list_collections 查看可用的 collection。"
    
    lines = [f"Collection '{collection}' 下共 {len(papers_seen)} 篇论文：\n"]
    for chunk in papers_seen.values():
        authors_str = chunk.authors[0] if chunk.authors else "未知"
        if len(chunk.authors) > 1:
            authors_str += " 等"
        year_str = f" ({chunk.year})" if chunk.year else ""
        lines.append(f"  · {chunk.paper_title} - {authors_str}{year_str}")
    
    return "\n".join(lines)


# ==================== 导出 ====================

ALL_TOOLS = [
    search_paper,
    list_papers,
    get_paper_abstract,
    list_collections,
    search_in_collection,
    list_tags,                
    search_by_tag,         
    get_papers_in_collection,    
]