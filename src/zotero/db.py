"""
Zotero SQLite 数据库访问层

职责：提供面向业务的 API 去查询 Zotero 数据，屏蔽 SQL 细节。

核心概念：
- Zotero 里的"一篇论文" = items 表里的一个父 item（非 attachment 类型）
  + itemAttachments 表里关联的 PDF attachment
- 要过滤 deletedItems 表里的已删除条目

这个模块是只读的，不会对 Zotero 数据库做任何修改。
"""
import os
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional
from contextlib import contextmanager
from dotenv import load_dotenv

from src.zotero.schema import Paper, Collection, Tag

load_dotenv()


# ==================== 配置 ====================

ZOTERO_PATH = Path(os.getenv("ZOTERO_PATH", ""))
ZOTERO_DB = ZOTERO_PATH / "zotero.sqlite"
ZOTERO_STORAGE = ZOTERO_PATH / "storage"


# ==================== 连接管理 ====================

@contextmanager
def _connect():
    """上下文管理器：自动打开和关闭数据库连接"""
    uri = f"file:{ZOTERO_DB}?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    try:
        yield conn
    finally:
        conn.close()


# ==================== 内部辅助函数 ====================

def _build_pdf_path(item_key: str, path_field: str) -> Optional[Path]:
    """
    从 Zotero 的 path 字段构造真实的 PDF 文件路径。
    
    Zotero 的 path 字段格式：
    - "storage:filename.pdf" → 存在 storage/{item_key}/filename.pdf
    - 其他格式暂不支持（linked file 等）
    
    返回：
    - Path 对象，如果解析失败或文件不存在则返回 None
    """
    if not path_field or not path_field.startswith("storage:"):
        return None
    
    filename = path_field[len("storage:"):]
    real_path = ZOTERO_STORAGE / item_key / filename
    
    if not real_path.exists():
        return None
    
    return real_path


def _parse_datetime(s: str) -> datetime:
    """解析 Zotero 的时间戳字符串为 datetime"""
    # Zotero 格式如: "2025-10-23 09:15:03"
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


def _get_item_field(conn, item_id: int, field_name: str) -> Optional[str]:
    """
    查询某个 item 的某个字段值。
    
    Zotero 的字段存储是三级间接的：
      items → itemData (itemID + fieldID + valueID)
           → itemDataValues (valueID → value)
           → fields (fieldID → fieldName)
    
    例如要查标题，需要:
    - fields.fieldName='title' 找到 fieldID
    - itemData.itemID=X AND itemData.fieldID=Y 找到 valueID
    - itemDataValues.valueID=Z 拿到真实值
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT idv.value
        FROM itemData id
        JOIN itemDataValues idv ON idv.valueID = id.valueID
        JOIN fields f ON f.fieldID = id.fieldID
        WHERE id.itemID = ? AND f.fieldName = ?
    """, (item_id, field_name))
    row = cursor.fetchone()
    return row[0] if row else None


def _get_item_authors(conn, item_id: int) -> list[str]:
    """
    查询某个 item 的作者列表。
    
    作者存储路径：
      itemCreators (itemID + creatorID + creatorTypeID + orderIndex)
      creators (creatorID → firstName, lastName)
      creatorTypes (creatorTypeID → 'author' / 'editor' / ...)
    
    我们只取 creatorType = 'author' 的。
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.firstName, c.lastName
        FROM itemCreators ic
        JOIN creators c ON c.creatorID = ic.creatorID
        JOIN creatorTypes ct ON ct.creatorTypeID = ic.creatorTypeID
        WHERE ic.itemID = ? AND ct.creatorType = 'author'
        ORDER BY ic.orderIndex
    """, (item_id,))
    
    authors = []
    for first, last in cursor.fetchall():
        # 拼成 "First Last" 或者只有一个的情况
        if first and last:
            authors.append(f"{first} {last}")
        elif last:
            authors.append(last)
        elif first:
            authors.append(first)
    return authors


def _get_item_collections(conn, item_id: int) -> list[str]:
    """查询某个 item 所属的 collection 名字列表"""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.collectionName
        FROM collectionItems ci
        JOIN collections c ON c.collectionID = ci.collectionID
        WHERE ci.itemID = ?
    """, (item_id,))
    return [row[0] for row in cursor.fetchall()]


def _get_item_tags(conn, item_id: int) -> list[str]:
    """查询某个 item 的 tag 名字列表"""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT t.name
        FROM itemTags it
        JOIN tags t ON t.tagID = it.tagID
        WHERE it.itemID = ?
    """, (item_id,))
    return [row[0] for row in cursor.fetchall()]


def _row_to_paper(conn, row: tuple) -> Optional[Paper]:
    """
    把一行 SQL 结果转换成 Paper 对象。
    如果 PDF 文件不存在或缺少关键字段，返回 None。
    
    输入 row 的字段顺序：
    parent_item_id, parent_key, type_name, date_added, date_modified, 
    attachment_key, attachment_path
    """
    (parent_item_id, parent_key, type_name, date_added, date_modified,
     attachment_key, attachment_path) = row
    
    # 构造 PDF 真实路径
    pdf_path = _build_pdf_path(attachment_key, attachment_path)
    if pdf_path is None:
        return None
    
    # 查标题（必须有，没有就跳过）
    title = _get_item_field(conn, parent_item_id, "title")
    if not title:
        return None
    
    # 查其他可选字段
    year_str = _get_item_field(conn, parent_item_id, "date")
    year = None
    if year_str:
        # Zotero 的 date 字段可能是 "2022-06" 或 "2022" 或 "2022-06-15"
        try:
            year = int(year_str[:4])
        except ValueError:
            pass
    
    abstract = _get_item_field(conn, parent_item_id, "abstractNote")
    authors = _get_item_authors(conn, parent_item_id)
    collections = _get_item_collections(conn, parent_item_id)
    tags = _get_item_tags(conn, parent_item_id)
    
    return Paper(
        key=parent_key,
        item_id=parent_item_id,
        title=title,
        item_type=type_name,
        pdf_path=pdf_path,
        pdf_filename=pdf_path.name,
        date_added=_parse_datetime(date_added),
        date_modified=_parse_datetime(date_modified),
        authors=authors,
        year=year,
        abstract=abstract,
        collections=collections,
        tags=tags,
    )


# ==================== 公开 API ====================

def list_papers(collection: Optional[str] = None,
                tag: Optional[str] = None) -> list[Paper]:
    """
    列出所有有 PDF 的论文。
    
    Args:
        collection: 只返回属于这个 collection 的论文
        tag: 只返回打了这个 tag 的论文
    
    Returns:
        Paper 对象列表，按 dateModified 降序
    """
    with _connect() as conn:
        cursor = conn.cursor()
        
        # 核心 SQL：JOIN items（父）和 itemAttachments（子 PDF）
        # 过滤条件：
        # - 只要 PDF 附件
        # - 父 item 不在 deletedItems
        # - 附件不在 deletedItems
        sql = """
            SELECT 
                parent.itemID AS parent_item_id,
                parent.key AS parent_key,
                it.typeName AS type_name,
                parent.dateAdded,
                parent.dateModified,
                att_item.key AS attachment_key,
                a.path AS attachment_path
            FROM itemAttachments a
            JOIN items att_item ON att_item.itemID = a.itemID
            JOIN items parent ON parent.itemID = a.parentItemID
            JOIN itemTypes it ON it.itemTypeID = parent.itemTypeID
            WHERE a.contentType = 'application/pdf'
              AND a.linkMode = 0
              AND parent.itemID NOT IN (SELECT itemID FROM deletedItems)
              AND att_item.itemID NOT IN (SELECT itemID FROM deletedItems)
            ORDER BY parent.dateModified DESC
        """
        
        cursor.execute(sql)
        rows = cursor.fetchall()
        
        papers = []
        for row in rows:
            paper = _row_to_paper(conn, row)
            if paper is None:
                continue
            
            # 应用过滤条件
            if collection and collection not in paper.collections:
                continue
            if tag and tag not in paper.tags:
                continue
            
            papers.append(paper)
        
        return papers


def list_collections() -> list[Collection]:
    """列出所有 collection，带每个 collection 的论文数量"""
    with _connect() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                c.collectionID,
                c.key,
                c.collectionName,
                pc.key AS parent_key,
                COUNT(DISTINCT ci.itemID) AS paper_count
            FROM collections c
            LEFT JOIN collections pc ON pc.collectionID = c.parentCollectionID
            LEFT JOIN collectionItems ci ON ci.collectionID = c.collectionID
            LEFT JOIN items i ON i.itemID = ci.itemID
            LEFT JOIN itemTypes it ON it.itemTypeID = i.itemTypeID
            WHERE (ci.itemID IS NULL
               OR (i.itemID NOT IN (SELECT itemID FROM deletedItems)
                   AND it.typeName != 'attachment'))
            GROUP BY c.collectionID
            ORDER BY c.collectionName
        """)
        return [
            Collection(
                collection_id=row[0],
                key=row[1],
                name=row[2],
                parent_key=row[3],
                paper_count=row[4],
            )
            for row in cursor.fetchall()
        ]


def list_tags() -> list[Tag]:
    """列出所有 tag，带每个 tag 的论文数量"""
    # TODO: 你来写这个
    with _connect() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                t.tagID,
                t.name,
                COUNT(DISTINCT it.itemID) AS paper_count
            FROM tags t
            LEFT JOIN itemTags it ON it.tagID = t.tagID
            LEFT JOIN items i ON i.itemID = it.itemID
            LEFT JOIN itemTypes itp ON itp.itemTypeID = i.itemTypeID
            WHERE (it.itemID IS NULL
               OR (i.itemID NOT IN (SELECT itemID FROM deletedItems)
                   AND itp.typeName != 'attachment'))
            GROUP BY t.tagID
            ORDER BY t.name
        """)
        return [
            Tag(
                tag_id=row[0],
                name=row[1],
                paper_count=row[2],
                )
            for row in cursor.fetchall()
        ]


def get_paper(key: str) -> Optional[Paper]:
    """根据 item key 获取单篇论文"""
    with _connect() as conn:
        cursor = conn.cursor()
        sql = """
            SELECT 
                parent.itemID AS parent_item_id,
                parent.key AS parent_key,
                it.typeName AS type_name,
                parent.dateAdded,
                parent.dateModified,
                att_item.key AS attachment_key,
                a.path AS attachment_path
            FROM itemAttachments a
            JOIN items att_item ON att_item.itemID = a.itemID
            JOIN items parent ON parent.itemID = a.parentItemID
            JOIN itemTypes it ON it.itemTypeID = parent.itemTypeID
            WHERE a.contentType = 'application/pdf'
              AND a.linkMode = 0
              AND parent.itemID NOT IN (SELECT itemID FROM deletedItems)
              AND att_item.itemID NOT IN (SELECT itemID FROM deletedItems)
              AND parent.key = ?
        """
        cursor.execute(sql, (key,))
        row = cursor.fetchone()
        if row is None:
            return None
        return _row_to_paper(conn, row)
        