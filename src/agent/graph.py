"""
ZoteroChat Agent 的 LangGraph StateGraph 定义

架构：
    START → call_model → [tool_calls?] → tools → call_model → ... → END

组件：
- StateGraph(MessagesState): 标准的消息式 state
- ToolNode: 自动执行工具调用
- SqliteSaver: 对话历史持久化
- LangSmith: 通过 .env 的 LANGCHAIN_* 环境变量自动启用 tracing
"""
import os
import sqlite3
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.sqlite import SqliteSaver

from src.agent.tools import ALL_TOOLS
from src.agent.prompts import SYSTEM_PROMPT

load_dotenv()


# ==================== LLM 初始化 ====================
# 用 DeepSeek API（兼容 OpenAI SDK）
llm = ChatOpenAI(
    model="deepseek-chat",
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
    temperature=0,
)

# 绑定工具到 LLM
# 这一步相当于"告诉 LLM 它有哪些工具可以调用"
llm_with_tools = llm.bind_tools(ALL_TOOLS)


# ==================== 节点函数 ====================

def call_model(state: MessagesState):
    """
    调用 LLM 节点。
    
    关键：state["messages"] 里可能没有 system message（因为 checkpointer 恢复的对话
    也只存 human/ai/tool 消息），所以我们每次都在调用 LLM 前手动拼上 system prompt。
    这样 system prompt 永远是最新的，也不会被保存到 checkpoint 污染历史。
    """
    messages = state["messages"]
    
    # 如果消息列表开头没有 SystemMessage，加上
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + messages
    
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}


def should_continue(state: MessagesState) -> str:
    """
    判断是否需要调工具。
    
    规则：最后一条消息是 AI message 且有 tool_calls → 去 tools 节点
          否则 → END（返回最终答案给用户）
    """
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return END


# ==================== 图构建 ====================

def build_graph(checkpoint_db_path: Optional[Path] = None):
    """
    构建并编译 LangGraph。
    
    Args:
        checkpoint_db_path: SQLite 数据库路径。如果为 None，用 MemorySaver（重启丢失）
    
    Returns:
        编译好的 graph
    """
    # 创建图
    workflow = StateGraph(MessagesState)
    
    # 添加节点
    workflow.add_node("agent", call_model)
    workflow.add_node("tools", ToolNode(ALL_TOOLS))
    
    # 添加边
    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            END: END,
        }
    )
    workflow.add_edge("tools", "agent")
    
    # 选择 checkpointer
    if checkpoint_db_path is not None:
        # SQLite 持久化
        checkpoint_db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(checkpoint_db_path), check_same_thread=False)
        checkpointer = SqliteSaver(conn)
    else:
        # 内存版（进程重启丢失）
        from langgraph.checkpoint.memory import MemorySaver
        checkpointer = MemorySaver()
    
    # 编译
    return workflow.compile(checkpointer=checkpointer)