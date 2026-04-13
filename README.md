# ZoteroChat

> 基于个人 Zotero 文献库的 AI 论文问答系统。将本地学术 PDF 转化为可检索的知识库,通过 LangGraph Agent + 两阶段语义检索,支持跨论文问答、方法对比、分类筛选等学术研究场景。

## 技术亮点

- **自研两阶段检索管线**:分层配额召回(Bi-Encoder)+ Cross-Encoder 精排 + 多样性重排,解决段落数量优势淹没摘要的经典 RAG 问题
- **三级分层切块策略**:将 PDF 切分为 document / section / paragraph 三个粒度,不同粒度分别参与检索和展示,兼顾宏观概览与细节定位
- **无外部向量数据库**:Index 直接存为 Numpy 矩阵 + JSON,零运维依赖,本地完整运行
- **LangGraph 工具调用 Agent**:8 个语义工具,LLM 根据问题意图自动路由;对话历史通过 SQLite checkpointer 跨会话持久化
- **Zotero 元数据深度集成**:chunk 级别保留 Zotero 的 collection 和 tag 信息,支持按分类/标签过滤检索
- **容错索引构建**:单篇 PDF 解析失败不中断整体流程,失败信息单独记录,成功率可追踪

## 功能概览

- 用自然语言在几十到几百篇论文中做跨论文检索
- 按论文标题关键词直接获取摘要,无需向量检索
- 按 Zotero Collection 或 Tag 限定检索范围,减少噪声
- 多论文对比分析(自动调用多次工具组织回答)
- 多轮对话,历史跨会话持久化,重启后可继续
- 中文提问,中文回答(论文本身为英文)

## Demo

### 启动

```
============================================================
  ZoteroChat - 基于 Zotero 的论文问答助手
============================================================

加载索引...
✅ 索引加载成功
   - 论文数: 86
   - Chunks: 12917
   - 构建时间: 2026-04-13 19:19

构建 agent...
✅ Agent 就绪

本次对话 ID: cli_07994f75
输入 'exit' / 'quit' / 'q' 退出
输入 'new' 开始新对话(生成新的 thread_id)
============================================================
```

### 示例 1:多论文对比(展示多工具自动协作)

```
你: WDTM-CL 和 MST++ 这两篇有什么区别?

助手: 基于两篇论文的摘要信息,我来为您对比分析 WDTM-CL (2025) 和 MST++ (2022) 的主要区别:

## 核心区别总结

| 维度 | WDTM-CL (2025) | MST++ (2022) |
|------|---------------|--------------|
| 发表年份 | 2025年 | 2022年 |
| 核心创新 | 小波分解 + 双注意力机制 + 对比学习 | 多阶段光谱注意力 + U型结构 |
| 计算效率 | 重点优化:使用小波分解降低计算复杂度 | 未特别强调计算效率优化 |
| 注意力机制 | 双注意力:同时捕获非局部空间相似性和全局光谱相关性 | 光谱注意力:基于HSI空间稀疏但光谱自相似的特点 |
| 损失函数 | 对比损失:patch-wise 对比学习 | 传统重建损失 |
| 性能表现 | 在多个基准数据集上达到 SOTA | 在 NTIRE 2022 光谱重建挑战赛中获得第一名 |

## 详细分析

1. 技术演进关系:MST++ (2022) 是较早的 Transformer 在光谱重建中的应用,
   WDTM-CL (2025) 是后续改进,引入小波分解优化效率,并增加对比学习提升质量。

2. 解决的核心问题不同:MST++ 主要解决 CNN 难以捕获长距离依赖的问题;
   WDTM-CL 主要解决 Transformer 计算效率低、未充分利用全局上下文的问题。

3. 方法学差异:MST++ 采用多阶段渐进式重建,WDTM-CL 采用小波域处理。

总结:WDTM-CL 可以看作是 MST++ 的演进版本,通过小波分解解决了计算效率问题,
并通过对比学习进一步提升了重建质量。

   (本轮调用工具: list_papers, get_paper_abstract, get_paper_abstract)
```

**亮点**:Agent 一个问题自动调用了 3 次工具——先确认两篇论文都在库里,然后分别拿摘要,最后基于摘要内容做对比分析。整个过程用户不需要手动指定每一步。

### 示例 2:结构化数据 + LLM 增值(展示 list_tags)

```
你: 我 Zotero 里有哪些 tag?

助手: 你的 Zotero 文献库中共有 12 个标签,按论文数量排序如下:

## 主要学科标签
1. Computer Science - Computer Vision and Pattern Recognition (18篇)
2. Computer Science - Machine Learning (6篇)
3. Computer Science - Artificial Intelligence (5篇)
4. Electrical Engineering and Systems Science - Image and Video Processing (4篇)
5. Computer Science - Computation and Language (2篇)

## 技术方法标签
6. Convolutional neural network (1篇)
7. Transformer (1篇)
8. Cross-dimension interaction (1篇)

## 应用领域标签
9. Hyperspectral image classification (1篇)
10. Remote sensing (1篇)

## 管理标签
11. ⛔ No DOI found (2篇)
12. Statistics - Machine Learning (1篇)

从标签分布可以看出,你的文献库主要关注计算机视觉、机器学习和人工智能领域。
其中计算机视觉方向的论文最多(18篇),占主导地位。

   (本轮调用工具: list_tags)
```

**亮点**:工具只返回扁平的 tag 列表,LLM 自动按"主要学科 / 技术方法 / 应用领域 / 管理标签"做了语义分组——这是工具做不到的增值。

### 示例 3:范围限定检索(展示 search_by_tag 的自主纠正能力)

```
你: 在 Computer Vision and Pattern Recognition 这个 tag 里找 transformer 相关的论文

助手: 在 "Computer Science - Computer Vision and Pattern Recognition" 标签下,
我找到了 2 篇 transformer 相关的论文:

## 1. Restormer: efficient transformer for high-resolution image restoration (2022)
- 作者: Syed Waqas Zamir, Aditya Arora, Salman Khan 等
- Collection: 图像复原
- 核心内容: 提出了用于高分辨率图像复原的高效 Transformer 模型,引入多 D 卷积头
  转置注意力(MDTA)模块,通过跨通道应用自注意力来隐式建模全局上下文。

## 2. SpecTr: spectral transformer for hyperspectral pathology image segmentation (2021)
- 作者: Boxiang Yun, Yan Wang, Jieneng Chen 等
- Collection: 图像分割
- 核心内容: 提出用于高光谱病理图像分割的谱 Transformer,基于纯注意力机制,
  引入稀疏性 Transformer 使用稀疏注意力机制。

   (本轮调用工具: list_tags, search_by_tag)
```

**亮点**:用户输入的 tag 名不完整("Computer Vision..." 实际全名是 "Computer Science - Computer Vision..."),Agent 主动先调 `list_tags` 查到完整名称,再用完整名调 `search_by_tag`。这种"自主纠正用户输入"的能力是单步工具调用做不到的。

### CLI 内置命令

| 命令 | 说明 |
|------|------|
| `new` | 开始新对话,生成新 thread_id,清空上下文 |
| `exit` / `quit` / `q` | 退出程序 |

## 系统架构

```
用户输入(CLI)
    ↓
LangGraph Agent(DeepSeek LLM + 8 个工具)
    ↓
检索层(分层配额召回 → Cross-Encoder 精排 → 多样性重排)
    ↓
索引(Chunk 列表 + Numpy 向量矩阵,缓存在 data/cache/)
    ↓
数据源(Zotero SQLite DB + PDF 文件)
```

### 核心模块

| 模块 | 路径 | 职责 |
|------|------|------|
| Zotero 数据访问 | `src/zotero/db.py` | 只读访问 Zotero SQLite,获取论文、Collection、Tag |
| PDF 解析 | `src/parser/paper_parser.py` | PyMuPDF 提取文本,识别章节标题,清理排版噪声 |
| 分层切块 | `src/indexing/chunker.py` | 三级切块:document / section / paragraph |
| 索引构建 | `src/indexing/builder.py` | 串联解析 → 切块 → Embedding → 保存 |
| 缓存读写 | `src/indexing/cache.py` | Index 序列化为 `metadata.json` + `vectors.npy` |
| 检索器 | `src/retrieval/retriever.py` | 分层配额召回 + bge-reranker 精排 + 多样性重排 |
| Agent 图 | `src/agent/graph.py` | LangGraph 状态机,管理工具调用循环与对话历史 |
| 工具定义 | `src/agent/tools.py` | 8 个暴露给 LLM 的工具函数 |
| CLI 入口 | `cli.py` | 加载索引、构建 Agent、运行多轮对话循环 |

## 检索原理

单纯向量检索存在"段落数量优势"问题:同一篇论文的段落切块数量远多于摘要,导致检索结果被段落主导,摘要和章节级信息被淹没。本项目采用三步方案解决:

**第一步:分层配额召回(Bi-Encoder)**

将所有 Chunk 按粒度分层,分别独立召回后合并:

| 层级 | 内容 | 配额 |
|------|------|------|
| document | 论文摘要 | 20% |
| section | 章节正文 | 30% |
| paragraph | 段落 | 50% |

某层名额不足时,自动流转给下一层,确保总召回数稳定。

**第二步:Cross-Encoder 精排**

用 `BAAI/bge-reranker-base` 对召回候选逐对打分,精度高于双塔模型,适合最终排序。

**第三步:多样性重排**

优先保证每个粒度层各有至少一个最优结果进入最终 top-5,再按分数补全,兼顾覆盖面与相关度。这一步特别重要——reranker 容易给摘要打低分(因为摘要不含具体技术词),但摘要恰恰是"这篇论文讲什么"这类宏观问题最需要的上下文。

## Design Decisions

### 为什么直接读 Zotero SQLite 而不是用 Zotero Web API?

Zotero 云端同步的本质是把 PDF 和元数据推到本地。一旦同步完成,本地 SQLite 就是数据的完整副本。直接读本地 SQLite 的优势:

- **速度快**:跳过网络延迟,查询 100 篇论文的元数据只需几毫秒
- **不依赖网络**:离线也能使用
- **无 API 限流**:不受 Zotero 免费账户 10 req/s 的 rate limit

代价是跨设备使用需要各自运行 builder 一次。但 Zotero 云同步会保证各设备本地数据一致,这个成本可接受。

### 为什么不用 LangChain 的 RAG 高层抽象?

LangChain 的 `RetrievalQA` 等高层抽象隐藏了太多细节:分层策略、检索参数、重排逻辑都被封装在黑盒里。对于本项目要做的"分层配额召回 + 多样性重排"这类自定义逻辑,LangChain 抽象反而是障碍。

因此检索层完全自己实现,只在 Agent 层使用 LangGraph 管理工具调用循环——LangGraph 够薄,恰好覆盖"while 循环 + 状态持久化"这部分样板代码,不干涉检索逻辑。

### 为什么 chunk 里直接冗余存储 Zotero 元数据?

每个 chunk 直接带 `collections`、`tags`、`authors` 等字段,而不是只存 `paper_key` 然后查询时 JOIN。这是"读多写少"场景的典型优化:

- **写**:索引构建一次,冗余字段只多占很少内存(Python 字符串 interned)
- **读**:每次检索都要过滤元数据,直接在 chunk 上判断 O(N),比查数据库快 10-100 倍

特别是 `search_in_collection` 和 `search_by_tag` 这类工具,直接对 chunks 做 list comprehension 过滤,不需要额外的索引层。

### 为什么选 DeepSeek 而不是 OpenAI?

- **成本**:约 10 倍便宜,对学术项目足够了
- **中文能力**:中文问答质量优秀,适合中文用户的自然提问
- **OpenAI 兼容**:API 协议完全兼容,切换到其他模型只需改一行代码

## 快速开始

### 1. 安装依赖

```bash
pip install langgraph langchain-openai sentence-transformers pymupdf pydantic python-dotenv numpy langgraph-checkpoint-sqlite
```

### 2. 配置环境变量

在项目根目录创建 `.env`:

```env
DEEPSEEK_API_KEY=sk-...       # DeepSeek API Key
ZOTERO_PATH=E:/ZoteroFiles    # Zotero 数据目录(含 zotero.sqlite 和 storage/)

# 可选:LangSmith 追踪
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_...
LANGCHAIN_PROJECT=zotero_chat
```

`ZOTERO_PATH` 默认位置:Windows `C:/Users/<用户名>/Zotero`,macOS `~/Zotero`。

### 3. 构建索引

```bash
python -m src.indexing.builder
```

首次运行需下载模型文件(Embedding 模型约 100MB,Reranker 约 400MB)。构建完成后索引缓存到本地,后续启动直接加载。

国内用户如遇 HuggingFace 下载超时,设置环境变量:

```bash
# Windows
set HF_ENDPOINT=https://hf-mirror.com

# Linux/Mac
export HF_ENDPOINT=https://hf-mirror.com
```

### 4. 启动

```bash
python cli.py
```

## Agent 工具

### 检索类工具

| 工具 | 触发场景 | 说明 |
|------|----------|------|
| `search_paper(query)` | 具体方法、实验细节、跨论文查询 | 全库语义检索,返回 top-5 相关段落 |
| `search_in_collection(collection, query)` | "在 XX collection 里找 YY" | 限定 collection 范围的语义检索 |
| `search_by_tag(tag, query)` | "在 XX tag 里找 YY" | 限定 tag 范围的语义检索 |

### 摘要类工具

| 工具 | 触发场景 | 说明 |
|------|----------|------|
| `get_paper_abstract(paper_name)` | "XX 论文讲了什么" | 按标题关键词直接查摘要,跳过向量检索 |

### 列表类工具

| 工具 | 触发场景 | 说明 |
|------|----------|------|
| `list_papers()` | "有哪些论文" | 全部论文列表,按 Collection 分组 |
| `list_collections()` | "有哪些分类" | 所有 Collection 及论文数量 |
| `list_tags()` | "有哪些标签" | 所有 Tag 及论文数量 |
| `get_papers_in_collection(collection)` | "XX collection 里有哪些论文" | 列出某分类下的所有论文(比 list_papers 更精确) |

## 技术栈

| 组件 | 选型 |
|------|------|
| LLM | DeepSeek(兼容 OpenAI SDK) |
| Agent 框架 | LangGraph |
| 嵌入模型 | `sentence-transformers/all-MiniLM-L6-v2`(384 维) |
| 精排模型 | `BAAI/bge-reranker-base` |
| PDF 解析 | PyMuPDF(fitz) |
| 数据验证 | Pydantic V2 |
| 向量存储 | Numpy 本地文件(无需向量数据库) |
| 对话持久化 | SQLite(LangGraph checkpointer) |
| Zotero 数据 | 直接读取 Zotero SQLite,只读模式 |

## Known Limitations

- **PDF 解析依赖启发式规则**:章节识别基于正则匹配,在约 27% 的论文上失败(主要是扫描版 PDF 和非标准格式期刊)。失败时走 full_text 兜底切分,论文依然可被检索,但章节级语义信息会丢失。Abstract 提取也有 fallback 策略,使用前 1500 字符兜底。

- **纯中文论文支持较弱**:使用 `all-MiniLM-L6-v2` 作为 embedding 模型,主要面向英文。对纯中文论文的语义理解精度较低。计划未来替换为多语言模型如 `BAAI/bge-small-zh`。

- **增量更新未实现**:当前为全量重建,Zotero 新增/删除论文后需手动重跑 builder。对个人规模(几十到几百篇)体验良好(全量构建约 3-5 分钟),但生产场景需要增量更新机制。

- **单机内存限制**:向量索引全量加载到内存,~10 万 chunks 规模以内无压力,再大需要外部向量数据库(FAISS/Qdrant)。

- **不支持 OCR**:扫描版 PDF 提取出的文本可能为空或乱码,这些论文虽不会导致 builder 崩溃,但实际上无法被检索到有效内容。

## Project Status

**当前版本**:0.1.0 (MVP)

**已完成**:
- ✅ Zotero SQLite 数据访问层
- ✅ 层次化 PDF 解析与 chunking
- ✅ 两阶段语义检索(召回 + 精排 + 多样性重排)
- ✅ LangGraph Agent with 8 tools
- ✅ 多轮对话 + 会话持久化
- ✅ LangSmith 可观测性集成

**Roadmap**:
- ⬜ 增量索引更新(监控 Zotero 变更)
- ⬜ Web UI(目前只有 CLI)
- ⬜ 多语言 embedding(支持中文论文)
- ⬜ PDF 结构识别升级(基于字体大小而非正则)
- ⬜ 笔记关联(把 Zotero 笔记一起索引)

## Author

**Lov1song** — [github.com/Lov1song](https://github.com/Lov1song)