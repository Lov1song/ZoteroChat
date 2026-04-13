"""
Zotero SQLite 探索器

职责：读取 Zotero 数据库的结构和样本数据，帮助理解 Zotero 内部存储格式。
这是一个一次性的诊断脚本，不对数据库做任何修改。

运行方式：
    python -m src.zotero.explorer

前提：
    - .env 里配置了 ZOTERO_PATH
    - Zotero 客户端最好关闭（虽然我们用只读模式，但关闭最保险）
"""
import os
import sqlite3
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


# ==================== 配置 ====================

ZOTERO_PATH = os.getenv("ZOTERO_PATH")
if not ZOTERO_PATH:
    raise RuntimeError("请在 .env 里配置 ZOTERO_PATH")

ZOTERO_DB = Path(ZOTERO_PATH) / "zotero.sqlite"
ZOTERO_STORAGE = Path(ZOTERO_PATH) / "storage"


# ==================== 数据库连接 ====================

def connect_readonly():
    """
    用只读模式连接 Zotero SQLite。
    关键参数：
    - mode=ro: 只读
    - immutable=1: 告诉 SQLite 这个文件不会被修改，绕过锁检查
                   即使 Zotero 客户端开着也能读
    """
    uri = f"file:{ZOTERO_DB}?mode=ro&immutable=1"
    return sqlite3.connect(uri, uri=True)


# ==================== 探索函数 ====================

def explore_tables(conn):
    """列出所有表"""
    print("\n" + "=" * 70)
    print("【所有表】")
    print("=" * 70)

    cursor = conn.cursor()
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table'
        ORDER BY name
    """)
    tables = [row[0] for row in cursor.fetchall()]

    print(f"共 {len(tables)} 个表\n")
    # 分两列打印，好看一点
    for i in range(0, len(tables), 2):
        left = tables[i]
        right = tables[i + 1] if i + 1 < len(tables) else ""
        print(f"  {left:<35} {right}")

    return tables


def explore_table_schema(conn, table_name):
    """打印指定表的字段结构"""
    print(f"\n--- 表: {table_name} ---")
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = cursor.fetchall()
    # PRAGMA table_info 返回: (cid, name, type, notnull, dflt_value, pk)
    for col in columns:
        pk_mark = " [PK]" if col[5] else ""
        nullable = "" if col[3] else " (nullable)"
        print(f"  {col[1]:<25} {col[2]:<15}{pk_mark}{nullable}")


def explore_data_counts(conn):
    """统计关键表的数据量"""
    print("\n" + "=" * 70)
    print("【数据规模】")
    print("=" * 70)

    key_tables = [
        "items",
        "itemAttachments",
        "collections",
        "collectionItems",
        "itemTags",
        "tags",
        "creators",
        "itemCreators",
        "deletedItems",  # 被删除的条目
    ]

    cursor = conn.cursor()
    for table in key_tables:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            print(f"  {table:<25} {count}")
        except sqlite3.OperationalError:
            print(f"  {table:<25} (表不存在)")


def explore_item_samples(conn, limit=5):
    """看看前 N 个 item 长什么样"""
    print("\n" + "=" * 70)
    print(f"【前 {limit} 个 item 示例】")
    print("=" * 70)

    cursor = conn.cursor()

    # items 表的基础字段
    cursor.execute(f"""
        SELECT itemID, key, itemTypeID, dateAdded, dateModified
        FROM items
        ORDER BY itemID
        LIMIT {limit}
    """)

    for row in cursor.fetchall():
        item_id, key, type_id, added, modified = row
        # 根据 itemTypeID 查类型名
        cursor2 = conn.cursor()
        cursor2.execute(
            "SELECT typeName FROM itemTypes WHERE itemTypeID = ?",
            (type_id,)
        )
        type_row = cursor2.fetchone()
        type_name = type_row[0] if type_row else f"未知(id={type_id})"

        print(f"\n  itemID={item_id}")
        print(f"    key          = {key}")
        print(f"    type         = {type_name}")
        print(f"    dateAdded    = {added}")
        print(f"    dateModified = {modified}")


def explore_attachment_samples(conn, limit=10):
    """看看前 N 个 attachment 长什么样"""
    print("\n" + "=" * 70)
    print(f"【前 {limit} 个 attachment 示例】")
    print("=" * 70)

    cursor = conn.cursor()
    cursor.execute(f"""
        SELECT
            a.itemID,
            a.parentItemID,
            a.linkMode,
            a.contentType,
            a.path,
            i.key
        FROM itemAttachments a
        JOIN items i ON i.itemID = a.itemID
        WHERE a.contentType = 'application/pdf'
        ORDER BY a.itemID
        LIMIT {limit}
    """)

    rows = cursor.fetchall()
    if not rows:
        print("  没有找到 PDF 附件！")
        return

    # linkMode 的含义（Zotero 源码里定义的）
    link_mode_names = {
        0: "IMPORTED_FILE",      # 导入的文件（存在 storage/）
        1: "IMPORTED_URL",       # 从 URL 导入（存在 storage/）
        2: "LINKED_FILE",        # 链接到外部文件（只存路径）
        3: "LINKED_URL",         # 链接到 URL（没有本地文件）
    }

    for row in rows:
        item_id, parent_id, link_mode, content_type, path, key = row
        mode_name = link_mode_names.get(link_mode, f"未知({link_mode})")
        print(f"\n  itemID={item_id}, parent={parent_id}")
        print(f"    key          = {key}")
        print(f"    linkMode     = {mode_name}")
        print(f"    contentType  = {content_type}")
        print(f"    path         = {path}")


def find_a_real_pdf(conn):
    """找一个真实的 PDF 文件，验证路径拼接规则"""
    print("\n" + "=" * 70)
    print("【PDF 路径拼接验证】")
    print("=" * 70)

    cursor = conn.cursor()
    cursor.execute("""
        SELECT i.key, a.path
        FROM itemAttachments a
        JOIN items i ON i.itemID = a.itemID
        WHERE a.contentType = 'application/pdf'
          AND a.linkMode = 0
        LIMIT 3
    """)

    for key, path in cursor.fetchall():
        print(f"\n  item key: {key}")
        print(f"  path 字段: {path}")

        # Zotero 的 path 字段格式通常是 "storage:filename.pdf"
        # 我们需要去掉 "storage:" 前缀，然后拼成真实路径
        if path and path.startswith("storage:"):
            filename = path[len("storage:"):]
            real_path = ZOTERO_STORAGE / key / filename
            exists = real_path.exists()
            print(f"  推测真实路径: {real_path}")
            print(f"  文件存在? {'✅ 是' if exists else '❌ 否'}")
        else:
            print(f"  path 格式不是 'storage:xxx'，需要特殊处理")


# ==================== 主函数 ====================

def main():
    print("=" * 70)
    print("  Zotero 探索器")
    print("=" * 70)
    print(f"  数据库路径: {ZOTERO_DB}")
    print(f"  存储目录:   {ZOTERO_STORAGE}")
    print(f"  数据库存在? {'✅' if ZOTERO_DB.exists() else '❌'}")
    print(f"  存储目录存在? {'✅' if ZOTERO_STORAGE.exists() else '❌'}")

    if not ZOTERO_DB.exists():
        print("\n❌ Zotero 数据库文件不存在，请检查 ZOTERO_PATH")
        return

    conn = connect_readonly()

    try:
        # 依次执行各项探索
        tables = explore_tables(conn)

        print("\n" + "=" * 70)
        print("【关键表结构】")
        print("=" * 70)
        key_tables = ["items", "itemAttachments", "itemTypes", "collections",
                      "collectionItems", "itemTags", "tags", "deletedItems"]
        for t in key_tables:
            if t in tables:
                explore_table_schema(conn, t)

        explore_data_counts(conn)
        explore_item_samples(conn)
        explore_attachment_samples(conn)
        find_a_real_pdf(conn)

    finally:
        conn.close()

    print("\n" + "=" * 70)
    print("  探索完成")
    print("=" * 70)


if __name__ == "__main__":
    main()