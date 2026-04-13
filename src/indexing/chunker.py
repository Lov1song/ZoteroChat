"""
文档chunks的构建逻辑：
{
    "text": "实际 chunk 内容...",
    "level": "document" | "section" | "paragraph",
    "paper_id": "arad_2016",
    "paper_title": "Sparse Recovery of Hyperspectral Signal...",
    "section_number": "3",
    "section_title": "Hyperspectral Prior for Natural Images",
    "chunk_id": 12,
}
"""
import re

def make_chunk(text, level, chunk_id, paper_id, paper_title,
               section_number=None, section_title=None):
    return {
        "text": text,
        "level": level,
        "paper_id": paper_id,
        "paper_title": paper_title,
        "section_number": section_number,
        "section_title": section_title,
        "chunk_id": chunk_id,
    }


def is_junk_paragraph(para: str) -> bool:
    """判断段落是否为垃圾内容（页眉、版权、元信息等）"""
    para_lower = para.lower()

    if 'doi:' in para_lower or 'doi.org' in para_lower:
        return True
    if 'lncs' in para_lower and 'pp.' in para_lower:
        return True
    if 'springer' in para_lower and len(para) < 200:
        return True

    return False


def _split_paragraphs_into_chunks(paragraphs, chunk_id, paper_id, paper_title,
                                   section_number, section_title):
    """
    把一组段落切分成 paragraph 级 chunks。
    共用的段落切分逻辑，Level 3 和兜底方案都调用这个函数。
    返回：(chunks_list, updated_chunk_id)
    """
    chunks = []

    for para in paragraphs:
        para = para.strip()
        if len(para) < 50:
            continue
        if is_junk_paragraph(para):
            continue

        if len(para) < 400:
            chunks.append(make_chunk(
                text=para,
                level="paragraph",
                chunk_id=chunk_id,
                paper_id=paper_id,
                paper_title=paper_title,
                section_number=section_number,
                section_title=section_title,
            ))
            chunk_id += 1

        elif len(para) > 600:
            sentences = re.split(r'(?<=[.!?]) +', para)
            current = ""
            for sent in sentences:
                if len(current) + len(sent) <= 400:
                    current = (current + " " + sent).strip() if current else sent
                else:
                    if current and len(current) >= 50:
                        chunks.append(make_chunk(
                            text=current,
                            level="paragraph",
                            chunk_id=chunk_id,
                            paper_id=paper_id,
                            paper_title=paper_title,
                            section_number=section_number,
                            section_title=section_title,
                        ))
                        chunk_id += 1
                    current = sent
            # 收尾
            if current and len(current) >= 50:
                chunks.append(make_chunk(
                    text=current,
                    level="paragraph",
                    chunk_id=chunk_id,
                    paper_id=paper_id,
                    paper_title=paper_title,
                    section_number=section_number,
                    section_title=section_title,
                ))
                chunk_id += 1

        else:
            # 400-600 之间，整段作为一个 chunk
            chunks.append(make_chunk(
                text=para,
                level="paragraph",
                chunk_id=chunk_id,
                paper_id=paper_id,
                paper_title=paper_title,
                section_number=section_number,
                section_title=section_title,
            ))
            chunk_id += 1

    return chunks, chunk_id


def build_hierarchical_chunks(paper: dict, paper_id: str) -> list[dict]:
    """
    把 parse_paper 的输出转换成层次化 chunks。

    有章节结构时：三层（document + section + paragraph）
    无章节结构时：兜底两层（document + paragraph from full_text）
    """
    chunks = []
    chunk_id = 0
    paper_title = paper["metadata"]["filename"].replace(".pdf", "")

    # ===== Level 1: 文档级（Abstract）=====
    if paper["abstract"]:
        chunks.append(make_chunk(
            text=paper["abstract"],
            level="document",
            chunk_id=chunk_id,
            paper_id=paper_id,
            paper_title=paper_title,
            section_title="Abstract",
        ))
        chunk_id += 1

    sections = paper["sections"]

    if sections:
        # ===== 有章节结构：三层处理 =====

        # Level 2: 章节级
        for section in sections:
            chunks.append(make_chunk(
                text=section["content"],
                level="section",
                chunk_id=chunk_id,
                paper_id=paper_id,
                paper_title=paper_title,
                section_number=section["number"],
                section_title=section["title"],
            ))
            chunk_id += 1

        # Level 3: 段落级
        for section in sections:
            paragraphs = section["content"].split("\n\n")
            para_chunks, chunk_id = _split_paragraphs_into_chunks(
                paragraphs=paragraphs,
                chunk_id=chunk_id,
                paper_id=paper_id,
                paper_title=paper_title,
                section_number=section["number"],
                section_title=section["title"],
            )
            chunks.extend(para_chunks)

    else:
        # ===== 没有章节结构：兜底方案 =====
        full_text = paper.get("full_text", "")
        if full_text:
            paragraphs = full_text.split("\n\n")
            para_chunks, chunk_id = _split_paragraphs_into_chunks(
                paragraphs=paragraphs,
                chunk_id=chunk_id,
                paper_id=paper_id,
                paper_title=paper_title,
                section_number=None,
                section_title="正文",
            )
            chunks.extend(para_chunks)

    return chunks