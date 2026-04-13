"""
索引缓存：保存和加载 Index 对象

核心思路：把 Index 分成两部分存储
- vectors (numpy 数组) → .npy 二进制格式
- 其他所有字段 → JSON

这样做的好处：
1. .npy 是 numpy 原生格式，加载最快
2. JSON 人类可读，debug 时能直接打开看
3. 两个文件独立，方便增量更新（未来如果只重新 embedding，不用动 metadata）
"""
import json
from pathlib import Path
from typing import Optional
import numpy as np

from src.indexing.schema import Index


# 缓存文件名
METADATA_FILENAME = "metadata.json"
VECTORS_FILENAME = "vectors.npy"


def save_index(index: Index, cache_dir: Path) -> None:
    """
    保存索引到磁盘。
    
    会产生两个文件：
    - {cache_dir}/metadata.json  - 除 vectors 外的所有字段
    - {cache_dir}/vectors.npy    - 向量矩阵
    
    Args:
        index: 要保存的 Index 对象
        cache_dir: 缓存目录路径
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    metadata_path = cache_dir / METADATA_FILENAME
    vectors_path = cache_dir / VECTORS_FILENAME
    
    # ========== 保存 vectors ==========
    np.save(vectors_path, index.vectors)
    
    # ========== 保存 metadata ==========
    # 用 Pydantic 的 model_dump() 转成 dict，但排除 vectors 字段
    metadata = index.model_dump(exclude={"vectors"}, mode="json")
    
    # mode="json" 会自动处理 datetime 等类型的序列化
    # 但 Path 对象可能需要额外处理
    # 这里用 default=str 做兜底
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"✅ 索引已保存到 {cache_dir}")
    print(f"   metadata: {metadata_path} ({metadata_path.stat().st_size / 1024:.1f} KB)")
    print(f"   vectors:  {vectors_path} ({vectors_path.stat().st_size / 1024 / 1024:.1f} MB)")


def load_index(cache_dir: Path) -> Optional[Index]:
    """
    从磁盘加载索引。
    
    Args:
        cache_dir: 缓存目录路径
    
    Returns:
        Index 对象；如果文件不存在或损坏，返回 None
    """
    metadata_path = cache_dir / METADATA_FILENAME
    vectors_path = cache_dir / VECTORS_FILENAME
    
    # 检查两个文件都存在
    if not metadata_path.exists() or not vectors_path.exists():
        return None
    
    try:
        # ========== 加载 metadata ==========
        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
        
        # ========== 加载 vectors ==========
        vectors = np.load(vectors_path)
        
        # ========== 组装成 Index ==========
        # 把 vectors 放回 metadata dict，让 Pydantic 重建对象
        metadata["vectors"] = vectors
        
        index = Index(**metadata)
        return index
    
    except Exception as e:
        print(f"⚠️ 加载索引失败: {type(e).__name__}: {e}")
        return None


def cache_exists(cache_dir: Path) -> bool:
    """检查缓存是否存在（两个文件都要有）"""
    return (cache_dir / METADATA_FILENAME).exists() and (cache_dir / VECTORS_FILENAME).exists()