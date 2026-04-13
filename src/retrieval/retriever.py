"""
两阶段检索：分层配额召回 + Cross-Encoder 精排 + 多样性重排

职责：接收 query，从 chunks 里返回最相关的 top_k 个。
不负责构建索引（那是 indexing/builder.py 的职责）。
"""
import numpy as np
from sentence_transformers import SentenceTransformer, CrossEncoder

from src.indexing.schema import Chunk


# ==================== 模型加载（模块级）====================
# 只在 import 时加载一次，避免每次调用都重新加载模型
# 注意：这些模型大概占 500MB 内存
embedder = SentenceTransformer('all-MiniLM-L6-v2')
reranker = CrossEncoder('BAAI/bge-reranker-base', max_length=512)


# ==================== 多样性重排 ====================
def diverse_top_k(candidates: list[Chunk],
                  scores,
                  final_k: int = 3) -> list[tuple[Chunk, float]]:
    """
    从候选池里选 top_k，保证不同 level 的多样性。
    
    策略：
    1. 第一轮：每个出现过的 level 各取最高分的 1 个（保证多样性）
    2. 第二轮：按纯分数继续填满 final_k（保证质量）
    """
    sorted_pairs = sorted(
        zip(candidates, scores),
        key=lambda x: x[1],
        reverse=True
    )
    
    chosen: list[tuple[Chunk, float]] = []
    chosen_ids: set[tuple[str, int]] = set()   # (paper_key, chunk_id) 组合作为唯一 ID
    levels_seen: set[str] = set()
    
    # 第一轮：每个 level 挑最高分的一个
    for c, s in sorted_pairs:
        if c.level not in levels_seen:
            chosen.append((c, s))
            chosen_ids.add((c.paper_key, c.chunk_id))
            levels_seen.add(c.level)
            if len(chosen) >= final_k:
                return chosen
    
    # 第二轮：按分数继续填
    for c, s in sorted_pairs:
        uid = (c.paper_key, c.chunk_id)
        if uid in chosen_ids:
            continue
        chosen.append((c, s))
        chosen_ids.add(uid)
        if len(chosen) >= final_k:
            return chosen
    
    return chosen


# ==================== 主检索函数 ====================
def search_with_rerank(query: str,
                        chunks: list[Chunk],
                        vectors: np.ndarray,
                        recall_k: int = 40,
                        final_k: int = 5) -> list[tuple[Chunk, float]]:
    """
    两阶段检索：分层配额召回 + reranker 精排 + 多样性重排
    
    Args:
        query: 查询字符串
        chunks: 所有 chunk 的列表（来自 Index.chunks）
        vectors: 对应的 embedding 矩阵（来自 Index.vectors）
        recall_k: 第一阶段召回数量（越大越全，但精排成本越高）
        final_k: 最终返回数量
    
    Returns:
        [(chunk, rerank_score), ...] 按相关度降序
    """
    # ===== 第一阶段：Embedding 召回 =====
    query_vector = embedder.encode(
        [query], normalize_embeddings=True
    ).astype(np.float32)
    scores = np.dot(query_vector, vectors.T).squeeze()
    
    # 按 level 分组
    level_groups: dict[str, list[tuple[int, float]]] = {
        "document": [],
        "section": [],
        "paragraph": [],
    }
    for i, c in enumerate(chunks):
        if c.level in level_groups:
            level_groups[c.level].append((i, float(scores[i])))
    
    # 每组按分数降序排
    for level in level_groups:
        level_groups[level].sort(key=lambda x: x[1], reverse=True)
    
    # 分配配额：document 20% / section 30% / paragraph 50%
    # 理由见 Paper Assistant 时期的决策：防止 paragraph 数量优势挤占 document 和 section
    quotas = {
        "document": max(1, int(recall_k * 0.2)),
        "section": max(1, int(recall_k * 0.3)),
        "paragraph": max(1, int(recall_k * 0.5)),
    }
    
    # 第一轮：每层按配额取
    recall_ids: list[int] = []
    leftover = 0   # 某层没用完的配额流转给下一层
    
    for level in ["document", "section", "paragraph"]:
        available = level_groups[level]
        quota = quotas[level] + leftover
        take = min(quota, len(available))
        recall_ids.extend([idx for idx, _ in available[:take]])
        leftover = quota - take
    
    # 兜底：如果三层加起来都不够 recall_k，从全局 top 补
    if leftover > 0:
        all_sorted = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        existing = set(recall_ids)
        for idx, _ in all_sorted:
            if idx not in existing:
                recall_ids.append(idx)
                leftover -= 1
                if leftover <= 0:
                    break
    
    candidates = [chunks[i] for i in recall_ids]
    
    # ===== 第二阶段：Reranker 精排 =====
    pairs = [(query, c.text) for c in candidates]
    rerank_scores = reranker.predict(pairs)
    
    # ===== 第三步：多样性重排 =====
    return diverse_top_k(candidates, rerank_scores, final_k=final_k)