"""
Zotero 数据结构定义

用 Pydantic 模型定义返回类型，这样：
1. 类型清晰，IDE 有自动补全
2. 字段验证（如果 Zotero 数据异常会立刻报错）
3. 可以很容易序列化成 JSON（将来做 Web API 时免费获得）
"""
from pathlib import Path
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field

#paper 结构信息
class Paper(BaseModel):
    key: str = Field(description="Zotero item key，全局唯一")
    item_id: int = Field(description="SQLite 内部 itemID")
    title: str = Field(description="论文标题")
    item_type: str = Field(description="类型，如 conferencePaper / journalArticle / preprint")
    
    # 文件相关
    pdf_path: Path = Field(description="PDF 文件的绝对路径")
    pdf_filename: str = Field(description="PDF 文件名")
    
    # 时间戳
    date_added: datetime = Field(description="加入 Zotero 的时间")
    date_modified: datetime = Field(description="最后修改时间")
    
    # 元数据（可能为空）
    authors: list[str] = Field(default_factory=list, description="作者列表")
    year: Optional[int] = Field(default=None, description="发表年份")
    abstract: Optional[str] = Field(default=None, description="摘要（Zotero 里可能有）")
    
    # 组织信息
    collections: list[str] = Field(default_factory=list, description="所属 collection 的名字列表")
    tags: list[str] = Field(default_factory=list, description="标签列表")

    class Config:
        # 允许 Path 类型（Pydantic 默认要求字符串）
        arbitrary_types_allowed = True


class Collection(BaseModel):
    """一个 Zotero collection（分类文件夹）"""
    
    key: str
    collection_id: int
    name: str
    parent_key: Optional[str] = Field(default=None, description="父 collection 的 key，顶级为 None")
    paper_count: int = Field(default=0, description="这个 collection 下的论文数量")


class Tag(BaseModel):
    """一个 Zotero tag（标签）"""
    
    tag_id: int
    name: str
    paper_count: int = Field(default=0, description="打了这个 tag 的论文数量")