"""
索引构建器

职责：把一堆 Zotero Paper 对象变成一个完整的 Index（chunks + vectors + metadata）。

核心流程：
    1. 遍历每篇论文
    2. 解析 PDF (paper_parser)
    3. 切分成 chunks (chunker)
    4. 注入 Zotero metadata
    5. 批量 embedding
    6. 构造并返回 Index

这个模块是里程碑 2 的核心，把 Zotero 数据和 RAG pipeline 连接起来。
"""
from datetime import datetime
from typing import Optional
import numpy as np

from sentence_transformers import SentenceTransformer

from src.zotero.schema import Paper
from src.parser.paper_parser import parse_paper
from src.indexing.chunker import build_hierarchical_chunks
from src.indexing.schema import Chunk, Index, FailedPaper


# ==================== 模块级资源 ====================

# embedding 模型：模块级加载，避免多次调用 build_index 时重复加载
# 第一次使用时才真正加载（lazy init）
_embedder: Optional[SentenceTransformer] = None
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"


def _get_embedder() -> SentenceTransformer:
    """获取 embedding 模型（懒加载）"""
    global _embedder
    if _embedder is None:
        print(f"首次加载 embedding 模型: {EMBEDDING_MODEL_NAME}")
        _embedder = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _embedder


# ==================== 单篇论文处理 ====================

def _dict_to_chunk(chunk_dict: dict, paper: Paper) -> Chunk:
    """
    把 chunker.py 返回的 dict 转成 Chunk 对象。
    同时注入 Zotero 元数据（authors, year, collections, tags）。
    
    chunker.py 返回的 dict 结构（基于 Paper Assistant 的版本）：
    {
        "text": str,
        "level": "document" | "section" | "paragraph",
        "paper_id": str,
        "paper_title": str,
        "section_number": str | None,
        "section_title": str | None,
        "chunk_id": int,
    }
    """
    return Chunk(
        # 来自 chunker 的字段
        text=chunk_dict["text"],
        level=chunk_dict["level"],
        chunk_id=chunk_dict["chunk_id"],
        section_number=chunk_dict.get("section_number"),
        section_title=chunk_dict.get("section_title"),
        
        # 论文标识：paper_key 用 Zotero 的 key（不是 chunker 的 paper_id）
        paper_key=paper.key,
        paper_title=paper.title,
        
        # 注入 Zotero 元数据
        authors=paper.authors,
        year=paper.year,
        item_type=paper.item_type,
        collections=paper.collections,
        tags=paper.tags,
    )


def _process_one_paper(paper: Paper) -> tuple[list[Chunk], Optional[FailedPaper]]:
    """
    处理单篇论文：PDF → chunks（带 Zotero metadata）。
    
    返回:
        (chunks, None)             处理成功
        ([], FailedPaper)          处理失败（不抛异常，记录失败信息）
    
    为什么不抛异常？因为上层需要"失败一篇继续下一篇"的能力。
    失败信息作为返回值传递，比 try/except 更清晰。
    """
    try:
        # Step 1: 解析 PDF
        paper_data = parse_paper(str(paper.pdf_path))
        
        # Step 2: 切分 chunks
        # chunker 需要 paper_id 作为标识，我们传 Zotero key
        chunk_dicts = build_hierarchical_chunks(paper_data, paper_id=paper.key)
        
        if not chunk_dicts:
            return [], FailedPaper(
                paper_key=paper.key,
                paper_title=paper.title,
                pdf_path=str(paper.pdf_path),
                error_message="chunker 返回了空列表",
                error_type="EmptyChunks",
            )
        
        # Step 3: 转换成 Chunk 对象 + 注入 Zotero metadata
        chunks = [_dict_to_chunk(d, paper) for d in chunk_dicts]
        
        return chunks, None
    
    except Exception as e:
        return [], FailedPaper(
            paper_key=paper.key,
            paper_title=paper.title,
            pdf_path=str(paper.pdf_path),
            error_message=str(e),
            error_type=type(e).__name__,
        )


# ==================== 主函数 ====================

def build_index(papers: list[Paper]) -> Index:
    """
    从 Zotero Paper 列表构建完整索引。
    
    流程：
    1. 对每篇论文处理（失败的记录到 failed_papers）
    2. 合并所有 chunks
    3. 批量 embedding
    4. 构造 Index
    
    Args:
        papers: 要索引的论文列表（来自 zotero_db.list_papers()）
    
    Returns:
        Index 对象
    """
    print(f"\n{'=' * 60}")
    print(f"开始构建索引，共 {len(papers)} 篇论文")
    print('=' * 60)
    
    all_chunks: list[Chunk] = []
    failed_papers: list[FailedPaper] = []
    
    # ========== 逐篇处理 ==========
    for i, paper in enumerate(papers, 1):
        print(f"\n[{i}/{len(papers)}] {paper.title[:70]}")
        
        chunks, failure = _process_one_paper(paper)
        
        if failure is not None:
            print(f"  ❌ 失败: {failure.error_type} - {failure.error_message[:80]}")
            failed_papers.append(failure)
            continue
        
        print(f"  ✅ 生成 {len(chunks)} 个 chunks")
        all_chunks.extend(chunks)
    
    # ========== 汇总统计 ==========
    num_succeeded = len(papers) - len(failed_papers)
    print(f"\n{'=' * 60}")
    print(f"解析完成：成功 {num_succeeded} 篇，失败 {len(failed_papers)} 篇")
    print(f"共生成 {len(all_chunks)} 个 chunks")
    print('=' * 60)
    
    # ========== Embedding ==========
    if not all_chunks:
        raise RuntimeError("没有任何 chunk 可供 embedding，请检查论文解析是否全部失败")
    
    print(f"\n开始 embedding（模型: {EMBEDDING_MODEL_NAME}）...")
    embedder = _get_embedder()
    
    texts = [c.text for c in all_chunks]
    vectors = embedder.encode(
        texts,
        batch_size=32,
        show_progress_bar=True,
        normalize_embeddings=True,  # 归一化向量，后面用点积等同于余弦相似度
        convert_to_numpy=True,
    ).astype(np.float32)
    
    print(f"Embedding 完成，向量 shape: {vectors.shape}")
    
    # ========== 构造 Index ==========
    index = Index(
        chunks=all_chunks,
        vectors=vectors,
        built_at=datetime.now(),
        embedding_model=EMBEDDING_MODEL_NAME,
        num_papers_succeeded=num_succeeded,
        num_papers_failed=len(failed_papers),
        failed_papers=failed_papers,
    )
    
    return index


# ==================== 命令行入口 ====================

if __name__ == "__main__":
    from pathlib import Path
    from src.zotero import db as zotero_db
    from src.indexing.cache import save_index, load_index, cache_exists
    
    CACHE_DIR = Path("data/cache")
    
    # 检查是否已有缓存
    if cache_exists(CACHE_DIR):
        print(f"发现缓存 {CACHE_DIR}，是否重建？[y/N] ", end="")
        answer = input().strip().lower()
        if answer != "y":
            print("加载已有缓存...")
            index = load_index(CACHE_DIR)
            if index:
                print(f"✅ 加载成功: {len(index.chunks)} chunks, {index.vectors.shape}")
                print(f"   构建时间: {index.built_at}")
            import sys
            sys.exit(0)
    
    # 构建新索引
    papers = zotero_db.list_papers()
    print(f"从 Zotero 获取了 {len(papers)} 篇论文")
    
    index = build_index(papers)
    
    # 打印最终统计
    print(f"\n{'=' * 60}")
    print("最终统计")
    print('=' * 60)
    print(f"  成功: {index.num_papers_succeeded} 篇")
    print(f"  失败: {index.num_papers_failed} 篇")
    print(f"  总 chunks: {len(index.chunks)}")
    print(f"  向量 shape: {index.vectors.shape}")
    
    # 保存到缓存
    save_index(index, CACHE_DIR)
    
    # 打印 level 分布
    from collections import Counter
    level_counts = Counter(c.level for c in index.chunks)
    print(f"\nChunk level 分布:")
    for level, count in level_counts.most_common():
        print(f"  {level:<12} {count}")