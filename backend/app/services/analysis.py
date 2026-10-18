"""中文/英文混合文本的分词器。

不引入外部分词模型：中文按相邻二字组切分，英文/数字按词切分，
再过滤高频虚词，兼顾检索召回与离线确定性。
"""

from __future__ import annotations

import re
import unicodedata

LATIN_RE = re.compile(r"[a-z0-9]+(?:[._+\-][a-z0-9]+)*")
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")

STOPWORDS = {
    # 中文虚词 / 疑问词
    "的", "了", "和", "与", "在", "是", "有", "对", "中", "上", "下", "就", "都",
    "而", "及", "或", "为", "以", "于", "之", "其", "这", "那", "哪", "什", "么",
    "怎", "样", "吗", "呢", "吧", "啊", "也", "还", "很", "更", "最", "会", "能",
    "要", "把", "被", "让", "给", "从", "到", "向", "用", "个", "些", "时", "后",
    "前", "里", "外", "内", "我", "你", "他", "她", "它", "们", "请", "问", "说",
    "一个", "一下", "我们", "你们", "他们", "这个", "那个", "哪些", "什么", "怎么",
    "如何", "是否", "可以", "的话", "以及", "因为", "所以", "但是", "如果", "就是",
    "还是", "或者", "关于", "进行", "需要", "应该", "可能", "没有", "不是",
    # 英文停用词
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "at", "is", "are",
    "was", "were", "be", "been", "it", "this", "that", "these", "those", "for",
    "with", "as", "by", "from", "what", "which", "how", "why", "when", "who",
    "can", "could", "should", "would", "do", "does", "did", "not", "no", "yes",
    "we", "you", "they", "he", "she", "i", "my", "your", "our", "their", "there",
    "here", "about", "into", "than", "then", "also", "such", "only", "just",
}

STOP_BIGRAMS = {
    "什么", "怎么", "如何", "哪些", "是否", "可以", "这个", "那个", "一个", "一下",
    "我们", "你们", "他们", "的话", "以及", "因为", "所以", "但是", "如果", "就是",
    "还是", "或者", "关于", "进行", "需要", "应该", "可能", "没有", "不是", "么是",
}


def tokenize(text: str) -> list[str]:
    """返回用于检索的词元列表（保留重复，供 BM25 计算词频）。"""
    if not text:
        return []
    normalized = unicodedata.normalize("NFKC", text).lower()
    tokens: list[str] = []

    for match in LATIN_RE.finditer(normalized):
        token = match.group()
        if len(token) >= 2 and token not in STOPWORDS:
            tokens.append(token)

    for match in CJK_RE.finditer(normalized):
        run = match.group()
        if len(run) == 1:
            if run not in STOPWORDS:
                tokens.append(run)
            continue
        for index in range(len(run) - 1):
            bigram = run[index : index + 2]
            if bigram in STOP_BIGRAMS:
                continue
            if run[index] in STOPWORDS and run[index + 1] in STOPWORDS:
                continue
            tokens.append(bigram)

    return tokens
