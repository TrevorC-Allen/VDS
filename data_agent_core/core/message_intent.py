"""Conversation-level intent guards for VDS workbench messages."""

from __future__ import annotations


def classify_workbench_message(question: str, *, has_dataset: bool) -> str:
    """Classify a workbench message before choosing chat vs analysis flow.

    This is intentionally conservative: targeted analytical questions continue
    to the normal planner/executor chain, while greetings/meta questions and
    broad dataset overview prompts are handled before they can be misread as a
    row-count or detail lookup task.
    """

    if not has_dataset:
        return "chat"
    if is_casual_or_meta_chat(question):
        return "chat"
    if is_dataset_overview_question(question):
        return "dataset_overview"
    return "analysis"


def is_casual_or_meta_chat(question: str) -> bool:
    """Return True for ordinary assistant conversation, not data analysis."""

    text = _normalize(question)
    if not text:
        return True
    compact = text.replace(" ", "")
    exact_or_short = {
        "你好",
        "您好",
        "hello",
        "hi",
        "hey",
        "在吗",
        "你是谁",
        "你是什么",
        "你是什么模型",
        "你叫什么",
        "介绍一下你",
        "help",
        "帮助",
    }
    if compact in exact_or_short:
        return True
    return any(
        token in compact
        for token in (
            "你是什么模型",
            "你是哪个模型",
            "什么大模型",
            "底层模型",
            "你能做什么",
            "怎么用",
            "如何使用",
            "使用说明",
            "功能介绍",
            "你的功能",
        )
    )


def is_dataset_overview_question(question: str) -> bool:
    """Return True for broad "look at this data" style overview requests."""

    text = _normalize(question)
    if not text:
        return False
    compact = text.replace(" ", "")
    if any(token in compact for token in _SPECIFIC_ANALYSIS_TOKENS):
        return False
    if any(phrase in compact for phrase in _GENERIC_OVERVIEW_PHRASES):
        return True
    has_overview_signal = any(token in compact for token in _OVERVIEW_TOKENS) or any(token in text for token in _EN_OVERVIEW_TOKENS)
    has_data_subject = any(token in compact for token in _DATA_SUBJECT_TOKENS) or any(token in text for token in _EN_DATA_SUBJECT_TOKENS)
    return has_overview_signal and has_data_subject


def _normalize(question: str) -> str:
    return str(question or "").strip().lower()


_GENERIC_OVERVIEW_PHRASES = (
    "看一下这个数据",
    "看下这个数据",
    "看看这个数据",
    "看一下这份数据",
    "看下这份数据",
    "看看这份数据",
    "看一下这个表",
    "看下这个表",
    "看看这个表",
    "看一下这个文件",
    "看下这个文件",
    "看看这个文件",
    "分析一下这个数据",
    "分析下这个数据",
    "分析一下这个表",
    "分析一下这个文件",
    "这个数据怎么样",
    "这个表怎么样",
    "这个文件怎么样",
    "数据概览",
    "数据总览",
)

_OVERVIEW_TOKENS = (
    "整体",
    "总体",
    "概览",
    "总览",
    "情况",
    "看一下",
    "看下",
    "看看",
    "分析一下",
    "分析下",
)

_DATA_SUBJECT_TOKENS = (
    "数据",
    "表",
    "文件",
    "销售",
    "收入",
    "订单",
    "订阅",
    "业务",
    "经营",
)

_EN_OVERVIEW_TOKENS = (
    "overview",
    "summary",
    "summarize",
    "overall",
    "look at",
    "look over",
)

_EN_DATA_SUBJECT_TOKENS = (
    "data",
    "dataset",
    "table",
    "file",
    "sales",
    "revenue",
    "business",
)

_SPECIFIC_ANALYSIS_TOKENS = (
    "哪个",
    "哪一个",
    "最高",
    "最低",
    "最大",
    "最小",
    "top",
    "排名",
    "多少",
    "几",
    "占比",
    "比例",
    "增长",
    "下降",
    "环比",
    "同比",
    "对比",
    "比较",
    "趋势",
    "按",
    "分组",
    "筛选",
    "列出",
    "为空",
    "空值",
    "缺失",
    "重复",
    "异常",
    "质量",
)
