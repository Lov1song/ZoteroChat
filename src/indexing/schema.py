"""
索引层数据结构定义

这里定义两个核心概念：
1. Chunk - 一个可检索的文本片段 + 完整的元数据
2. Index - 一次构建产出的完整索引（chunks + vectors + 构建信息）
"""
from pathlib import Path
from datetime import datetime
from typing import Optional, Literal
import numpy as np
from pydantic import BaseModel, Field, ConfigDict


ChunkLevel = Literal["document", "section", "paragraph"]


class Chunk(BaseModel):
    """
    一个可检索的文本片段。
    
    这个模型合并了两种信息：
    - 文本本身 + 在论文里的位置（来自 chunker.py 的切分结果）
    - Zotero 元数据（标题、作者、collection、tag）
    
    为什么要合并？因为 agent 做"在 Mamba collection 里搜相关论文"这种查询时，
    需要在检索阶段就能看到每个 chunk 的 collection 信息——不能等检索完再去 JOIN。
    """
    
    # ========== chunk 本身 ==========
    text: str = Field(description="chunk 的文本内容")
    level: ChunkLevel = Field(description="chunk 的粒度层级")
    chunk_id: int = Field(description="在同一篇论文内的 chunk 序号")
    
    # ========== 来自哪篇论文 ==========
    paper_key: str = Field(description="Zotero item key，全局唯一的论文标识")
    paper_title: str = Field(description="论文标题")
    
    # ========== 在论文里的位置 ==========
    section_number: Optional[str] = Field(default=None, description="章节编号，如 '3'")
    section_title: Optional[str] = Field(default=None, description="章节标题，如 'Method'")
    
    # ========== Zotero 元数据（关键扩展）==========
    authors: list[str] = Field(default_factory=list, description="作者列表")
    year: Optional[int] = Field(default=None, description="发表年份")
    item_type: Optional[str] = Field(default=None, description="论文类型，如 conferencePaper")
    collections: list[str] = Field(default_factory=list, description="所属 collection 列表")
    tags: list[str] = Field(default_factory=list, description="tag 列表")


class FailedPaper(BaseModel):
    """索引构建失败的论文记录"""
    
    paper_key: str
    paper_title: str
    pdf_path: str
    error_message: str
    error_type: str = Field(description="错误类型，如 ParseError / NoSectionsError")


class Index(BaseModel):
    """
    一次构建产出的完整索引。
    
    包含三部分：
    1. chunks：所有成功解析的 chunk 列表
    2. vectors：对应的 embedding 矩阵
    3. 元数据：构建时间、失败列表、统计信息
    """
    
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    # ========== 核心数据 ==========
    chunks: list[Chunk] = Field(description="所有 chunk 的列表")
    vectors: np.ndarray = Field(description="chunks 对应的 embedding 矩阵，shape=(N, dim)")
    
    # ========== 构建元数据 ==========
    built_at: datetime = Field(description="索引构建时间")
    embedding_model: str = Field(description="使用的 embedding 模型名")
    
    # ========== 统计信息 ==========
    num_papers_succeeded: int = Field(description="成功索引的论文数")
    num_papers_failed: int = Field(description="解析失败的论文数")
    failed_papers: list[FailedPaper] = Field(default_factory=list, description="失败的论文列表")
    
    # ========== 便捷方法 ==========
    def paper_keys(self) -> set[str]:
        """所有成功索引的论文 key 集合"""
        return {c.paper_key for c in self.chunks}