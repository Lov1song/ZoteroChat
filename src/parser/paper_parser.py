# pdf_test.py
import fitz
import re

def light_clean(text: str) -> str:
    """轻清理：统一换行 + 连字符修复 + 行末断词"""
    # 🔑 第一步：统一换行（解决 Windows \r\n 问题）
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    
    # 连字符替换
    ligature_map = {
        'ﬁ': 'fi', 'ﬂ': 'fl', 'ﬀ': 'ff',
        'ﬃ': 'ffi', 'ﬄ': 'ffl',
    }
    for lig, rep in ligature_map.items():
        text = text.replace(lig, rep)
    
    # 行末断词修复
    text = re.sub(r'(\w+)-\n(\w+)', r'\1\2', text)
    
    return text

def identify_sections(text: str) -> list[dict]:
    """
    识别章节标题。
    
    兼容多种格式：
    - "1\nIntroduction\n"   (数字和标题分两行)
    - "1. Introduction\n"   (同一行，带点)
    - "1 Introduction\n"    (同一行，无点)
    """
    # 三种 pattern 都试，合并结果
    patterns = [
        # Pattern A: 数字和标题分两行 (你原来的)
        re.compile(
            r'\n(\d{1,2})\n([A-Z][A-Za-z][A-Za-z\s]{1,48}[A-Za-z])\n',
            re.MULTILINE
        ),
        # Pattern B: "1. Title" 或 "1 Title" 在同一行
        re.compile(
            r'\n(\d{1,2})\.?\s+([A-Z][A-Za-z][A-Za-z\s]{1,48}[A-Za-z])\n',
            re.MULTILINE
        ),
    ]
    
    # 收集所有候选 match
    all_candidates = []
    for pattern in patterns:
        for m in pattern.finditer(text):
            num = int(m.group(1))
            title = m.group(2).strip()
            all_candidates.append({
                "num": num,
                "title": title,
                "start": m.start(),
                "end": m.end(),
            })
    
    # 按位置排序
    all_candidates.sort(key=lambda x: x["start"])
    
    # 后验过滤：章节号必须从 1 开始且递增
    # 这一步能淘汰掉图表 caption 里的误匹配
    valid = []
    expected_num = 1
    for c in all_candidates:
        if c["num"] == expected_num:
            # 额外的合理性检查：
            # - 标题不能是"Density"、"Ground Truth"这种明显不像章节的词
            # - 标题不能全是单个词（章节标题通常是短语）
            title = c["title"]
            
            # 黑名单：常见的图表/公式里会出现的词
            blacklist = {
                "Density", "Ground", "Truth", "Error", "Loss", "PSNR", 
                "SSIM", "MRAE", "RMSE", "Output", "Input",
            }
            first_word = title.split()[0] if title.split() else ""
            if first_word in blacklist:
                continue
            
            valid.append(c)
            expected_num += 1
    
    # 构造 sections
    sections = []
    for i, c in enumerate(valid):
        start = c["end"]
        end = valid[i + 1]["start"] if i + 1 < len(valid) else len(text)
        content = text[start:end].strip()
        sections.append({
            "number": str(c["num"]),
            "title": c["title"],
            "content": content,
        })
    
    return sections

def remove_references(text: str) -> str:
    """
    移除参考文献。
    
    兼容多种参考文献格式：
    - "References\n1. Paper..."   (LNCS/Springer)
    - "References\n[1] Paper..."  (Elsevier/IEEE)
    - "REFERENCES\n..."           (全大写)
    - "Bibliography\n..."         (部分期刊)
    """
    # 正则说明：
    # - (?:References|REFERENCES|Bibliography): 多种关键词
    # - \s*\n: 关键词后可能有空白再换行
    # - \s*: 换行后可能有空行
    # - (?:\[1\]|1\.?\s): 第一条引用的标志
    #     - \[1\]: [1]
    #     - 1\.?\s: "1. " 或 "1 "
    pattern = re.compile(
        r'\n(?:References|REFERENCES|Bibliography)\s*\n\s*(?:\[1\]|1\.?\s)',
        re.DOTALL
    )
    match = pattern.search(text)
    if match:
        return text[:match.start()]
    return text

def extract_abstract(text: str) -> str:
    """
    提取 Abstract。先尝试结构化提取，失败则用前 1500 字符作为 fallback。
    """
    # ========== 尝试 1：结构化提取 ==========
    abstract_kw = r'A\s?B\s?S\s?T\s?R\s?A\s?C\s?T'
    
    pattern = re.compile(
        r'(?:^|\n)'
        rf'(?:{abstract_kw}|Abstract|abstract)\.?\s*\n'
        r'(.*?)'
        r'\n(?:'
        r'\d+\.?\s*Introduction'
        r'|I\.\s*INTRODUCTION'
        r'|I\s?N\s?T\s?R\s?O\s?D\s?U\s?C\s?T\s?I\s?O\s?N'
        r'|Introduction\n'
        r'|1\s*\n'
        r'|Keywords?\s*[:：]'
        r'|\d+\s+Introduction'
        r')',
        re.DOTALL
    )
    match = pattern.search(text)
    if match:
        abstract = match.group(1).strip()
        if len(abstract) >= 100:
            return abstract
    
    # ========== Fallback：用前 1500 字符 ==========
    # 这覆盖了"找不到明确 Abstract 标识"的情况
    # 前 1500 字符通常包含：标题、作者、单位、Abstract（如果有）
    # 对 agent 回答"这篇论文讲什么"依然有用
    
    # 但要过滤掉明显无用的内容
    # 1. 如果前 1500 字符里根本没有完整的句子（全是短词），说明文本提取失败
    # 2. 做轻度清理（去掉 ScienceDirect / Elsevier 这种 header）
    
    fallback = text[:1500].strip()
    
    # 检查是否有实质内容（至少包含几个完整句子）
    sentence_count = fallback.count('.') + fallback.count('。')
    if sentence_count < 3:
        return ""  # 前 1500 字符没有完整句子，可能是乱码
    
    # 去掉常见的期刊 header
    for noise in [
        "Contents lists available at ScienceDirect",
        "journal homepage:",
        "ARTICLE INFO",
        "A R T I C L E  I N F O",
    ]:
        fallback = fallback.replace(noise, "")
    
    return fallback.strip()

def parse_paper(pdf_path: str) -> dict:
    """
    解析一篇论文，返回结构化信息
    """
    doc = fitz.open(pdf_path)
    
    # 1. 提取所有文本
    raw_text = ""
    for page in doc:
        raw_text += page.get_text() + "\n\n"
    
    # 2. 提取元数据
    metadata = {
        "filename": pdf_path.split("/")[-1].split("\\")[-1],
        "num_pages": len(doc),
    }
    doc.close()
    
    # 3. 清理
    cleaned = light_clean(raw_text)
    
    # 4. 切掉参考文献
    body = remove_references(cleaned)
    
    # 5. 提取 abstract
    abstract = extract_abstract(body)
    
    # 6. 识别章节
    sections = identify_sections(body)
    
    return {
        "metadata": metadata,
        "abstract": abstract,
        "sections": sections,
        "full_text": body,  # 留一份完整文本，万一章节识别失败有兜底
    }
 
if __name__ == "__main__":
    PDF_PATH = "./data/papers/1.2016-Arad_and_Ben_Shahar-Sparse_Recovery_of_Hyperspectral_Signal_from_Natural_RGB_Images.pdf"
    paper = parse_paper(PDF_PATH)

    print(f"文件: {paper['metadata']['filename']}")
    print(f"页数: {paper['metadata']['num_pages']}")

    print(f"\n--- Abstract ({len(paper['abstract'])} 字符) ---")
    print(paper['abstract'][:500])

    print(f"\n--- 识别到 {len(paper['sections'])} 个章节 ---")
    for s in paper['sections']:
        print(f"  [{s['number']}] {s['title']}: {len(s['content'])} 字符")

    print(f"\n--- 正文总长度: {len(paper['full_text'])} 字符 ---")
    print(f"切掉了: {42602 - len(paper['full_text'])} 字符")