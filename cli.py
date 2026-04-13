"""
ZoteroChat CLI 入口

功能：
- 启动时加载 Zotero 索引（从 data/cache/）
- 注入 index 到 tools 模块
- 构建 LangGraph 图（带 SQLite checkpointer）
- 多轮对话循环

对话历史持久化到 data/checkpoints/conversations.db
重启 CLI 后可以用同一个 thread_id 继续之前的对话
"""
from pathlib import Path
from uuid import uuid4

from langchain_core.messages import HumanMessage

from src.indexing.cache import load_index
from src.agent.tools import set_index
from src.agent.graph import build_graph


def main():
    # ==================== 加载索引 ====================
    print("=" * 60)
    print("  ZoteroChat - 基于 Zotero 的论文问答助手")
    print("=" * 60)
    
    print("\n加载索引...")
    cache_dir = Path("data/cache")
    index = load_index(cache_dir)
    
    if index is None:
        print("❌ 没有找到索引，请先运行：")
        print("   python -m src.indexing.builder")
        return
    
    print(f"✅ 索引加载成功")
    print(f"   - 论文数: {index.num_papers_succeeded}")
    print(f"   - Chunks: {len(index.chunks)}")
    print(f"   - 构建时间: {index.built_at.strftime('%Y-%m-%d %H:%M')}")
    
    # 注入 index 到工具模块
    set_index(index)
    
    # ==================== 构建 Graph ====================
    print("\n构建 agent...")
    checkpoint_db = Path("data/checkpoints/conversations.db")
    graph = build_graph(checkpoint_db_path=checkpoint_db)
    print(f"✅ Agent 就绪\n")
    
    # ==================== 生成 thread_id ====================
    thread_id = f"cli_{uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": thread_id}}
    print(f"本次对话 ID: {thread_id}")
    print("输入 'exit' / 'quit' / 'q' 退出")
    print("输入 'new' 开始新对话（生成新的 thread_id）")
    print("=" * 60)
    
    # ==================== 对话循环 ====================
    while True:
        try:
            user_input = input("\n你: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n再见！")
            break
        
        if not user_input:
            continue
        
        if user_input.lower() in ("exit", "quit", "q"):
            print("再见！")
            break
        
        if user_input.lower() == "new":
            thread_id = f"cli_{uuid4().hex[:8]}"
            config = {"configurable": {"thread_id": thread_id}}
            print(f"✨ 新对话已开始，thread_id: {thread_id}")
            continue
        
        # 调用 graph
        try:
            result = graph.invoke(
                {"messages": [HumanMessage(content=user_input)]},
                config=config,
            )
        except Exception as e:
            print(f"\n❌ 调用失败: {type(e).__name__}: {e}")
            continue
        
        # 打印最终答复
        final_message = result["messages"][-1]
        print(f"\n助手: {final_message.content}")
        
        # 打印工具调用轨迹（仅本轮新增的消息）
        # 这能帮你看到 agent 调用了哪些工具
        new_messages = result["messages"]
        # 找到本轮用户输入之后的所有消息
        tool_calls_made = []
        for msg in new_messages:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    tool_calls_made.append(tc["name"])
        
        if tool_calls_made:
            print(f"\n   (本轮调用工具: {', '.join(tool_calls_made)})")


if __name__ == "__main__":
    main()