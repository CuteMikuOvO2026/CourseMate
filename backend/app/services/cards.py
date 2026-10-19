"""从课程文本块生成可追溯的问答复习卡。"""

from __future__ import annotations

import re
from dataclasses import dataclass

SENTENCE_RE = re.compile(r"(?<=[。！？!?；;])\s*|\n+")

DEFINITION_RE = re.compile(
    r"(?:^|[，。；：、\s])"
    r"(?P<term>[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9.+#\-]{1,11}?)\s*"
    r"(?:是|指|称为|用于|负责|包括|表示)"
)

SUFFIX_TERM_RE = re.compile(
    r"(?P<term>[\u4e00-\u9fff]{1,5}"
    r"(?:层|协议|握手|连接|算法|模型|系统|方法|过程|机制|技术|数据|地址|端口|"
    r"报文|服务|函数|变量|结构|接口|标准|指标|公式|定理|定义|特征|类型|阶段|"
    r"步骤|要求|报告|实验|作业|网络|传输|路由|进程|线程|数据库))"
)

ACRONYM_RE = re.compile(r"(?<![A-Za-z0-9])[A-Z][A-Z0-9.+#-]{1,7}(?![A-Za-z0-9])")

STOP_TERMS = {
    "这个",
    "那个",
    "这些",
    "那些",
    "什么",
    "怎么",
    "如何",
    "可以",
    "需要",
    "应该",
    "通过",
    "使用",
    "进行",
    "包括",
    "负责",
    "用于",
    "表示",
    "称为",
    "建立",
    "确认",
    "提供",
    "实现",
    "支持",
    "包含",
    "具有",
    "相关",
    "其他",
    "其中",
    "以及",
    "因为",
    "所以",
    "但是",
    "如果",
    "一个",
    "一种",
    "这种",
    "我们",
    "你们",
    "他们",
    "它们",
    "时间",
    "内容",
    "问题",
    "答案",
    "方法",
    "方式",
    "情况",
}

STOP_CHARS = set(
    "的了和与在是为对把被将从到用以及或而其这那哪什么怎样吗呢吧啊也还很更最会能要个些时后前里外内"
)

BAD_PREFIXES = (
    "这个",
    "那个",
    "这些",
    "那些",
    "什么",
    "怎么",
    "如何",
    "通过",
    "使用",
    "进行",
    "用于",
    "包括",
    "负责",
    "表示",
    "称为",
    "建立",
    "确认",
    "提供",
    "实现",
    "支持",
    "包含",
    "具有",
    "相关",
    "其他",
    "其中",
    "以及",
    "因为",
    "所以",
    "但是",
    "如果",
    "一个",
    "一种",
    "这种",
    "我们",
    "你们",
    "他们",
    "它们",
    "在",
    "对",
    "把",
    "被",
    "将",
    "从",
    "到",
    "以",
    "及",
    "或",
    "而",
    "其",
    "这",
    "那",
    "哪",
    "什",
    "怎",
    "为",
    "是",
    "的",
    "了",
    "和",
    "与",
    "个",
    "些",
)


@dataclass(frozen=True)
class CardDraft:
    front: str
    back: str
    source_chunk_ids: list[str]


def split_sentences(text: str) -> list[str]:
    parts = [re.sub(r"\s+", " ", item).strip() for item in SENTENCE_RE.split(text)]
    return [item for item in parts if len(item) >= 10]


def _is_valid_term(term: str) -> bool:
    term = term.strip()
    if not 2 <= len(term) <= 10:
        return False
    if term.isdigit():
        return False
    if term in STOP_TERMS:
        return False
    if all(char in STOP_CHARS for char in term):
        return False
    if "的" in term or "是" in term or term.startswith(BAD_PREFIXES):
        return False
    return True


def extract_terms(sentence: str) -> list[str]:
    """按定义句式、领域后缀和高频缩写提取候选术语，按可信度排序。"""
    raw: list[str] = []
    raw.extend(match.group("term") for match in DEFINITION_RE.finditer(sentence))
    raw.extend(match.group("term") for match in SUFFIX_TERM_RE.finditer(sentence))
    raw.extend(match.group(0) for match in ACRONYM_RE.finditer(sentence))

    terms: list[str] = []
    for term in raw:
        term = term.strip("，,。.；;：:、（）()《》\"'“”")
        if _is_valid_term(term) and term not in terms:
            terms.append(term)
    return terms


def build_card_drafts(chunks) -> list[CardDraft]:
    """从有序 chunks 生成卡片草稿；同一术语只保留首次出现的句子。"""
    drafts: list[CardDraft] = []
    seen_fronts: set[str] = set()

    for chunk in chunks:
        for sentence in split_sentences(chunk.text):
            terms = extract_terms(sentence)
            if not terms:
                continue
            term = max(terms, key=lambda item: (len(item), sentence.find(item)))
            front = f"什么是「{term}」？"
            if front in seen_fronts:
                continue
            seen_fronts.add(front)
            drafts.append(
                CardDraft(front=front, back=sentence, source_chunk_ids=[chunk.id])
            )
    return drafts
