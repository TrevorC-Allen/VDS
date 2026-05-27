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
    if is_cleaning_guidance_question(question):
        return "cleaning_guidance"
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
            "rawprompt",
            "rawtrace",
            "标准答案",
            "外部维表",
            "真实名称",
            "直接说成真实名称",
        )
    ) or ("raw" in compact and any(token in compact for token in ("prompt", "trace", "sql")))


def is_dataset_overview_question(question: str) -> bool:
    """Return True for broad "look at this data" style overview requests."""

    text = _normalize(question)
    if not text:
        return False
    compact = text.replace(" ", "")
    if any(phrase in compact for phrase in _CAPABILITY_OVERVIEW_PHRASES):
        return True
    if any(phrase in compact for phrase in _SHAPE_OVERVIEW_PHRASES):
        return True
    if any(phrase in compact for phrase in _SCHEMA_OVERVIEW_PHRASES) and not any(token in compact for token in _STRONG_SPECIFIC_ANALYSIS_TOKENS):
        return True
    if any(phrase in compact for phrase in _GENERIC_OVERVIEW_PHRASES) and not any(token in compact for token in _STRONG_SPECIFIC_ANALYSIS_TOKENS):
        return True
    if any(token in compact for token in _SPECIFIC_ANALYSIS_TOKENS):
        return False
    has_overview_signal = (
        any(token in compact for token in _OVERVIEW_TOKENS)
        or any(token in compact for token in _SCHEMA_OVERVIEW_TOKENS)
        or any(token in text for token in _EN_OVERVIEW_TOKENS)
    )
    has_data_subject = any(token in compact for token in _DATA_SUBJECT_TOKENS) or any(token in text for token in _EN_DATA_SUBJECT_TOKENS)
    return has_overview_signal and has_data_subject


def is_cleaning_guidance_question(question: str) -> bool:
    """Return True for cleaning-policy or cleaning-simulation questions."""

    text = _normalize(question)
    if not text:
        return False
    compact = text.replace(" ", "")
    boundary_signals = (
        "直接修改原始数据",
        "修改原始数据",
        "覆盖原始",
        "覆盖源文件",
        "用户确认",
        "需要确认",
        "是否确认",
    )
    cleaning_signals = (
        "清洗",
        "删除异常",
        "异常行",
        "异常规则",
        "样例说明",
        "缺失字段",
        "有缺失",
        "缺失值",
        "填充",
        "保留",
        "影响行数",
        "影响比例",
        "数量占比",
        "明显异常",
        "数据质量",
        "范围异常",
        "无法解析",
        "极端值",
        "离群",
        "winsorize",
    )
    if any(signal in compact for signal in boundary_signals) or any(signal in compact for signal in cleaning_signals):
        return True
    return "异常" in compact and any(token in compact for token in ("规则", "样例", "数量", "占比", "比例"))


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
    "看一下这个表单",
    "看下这个表单",
    "看看这个表单",
    "看一下这个数据集",
    "看下这个数据集",
    "看看这个数据集",
    "总结一下这个表",
    "总结一下这个表单",
    "总结一下这张表",
    "总结一下这几张表",
    "总结一下这几个表",
    "总结一下这些表",
    "总结一下这个数据集",
    "介绍一下这个表",
    "介绍一下这个表单",
    "介绍一下这个数据集",
    "看一下这个文件",
    "看下这个文件",
    "看看这个文件",
    "分析一下这个数据",
    "分析下这个数据",
    "分析一下这个表",
    "分析一下这个文件",
    "表单含义",
    "字段含义",
    "主要讲什么",
    "主要内容",
    "数据讲什么",
    "这个数据主要讲什么",
    "这个数据是做什么",
    "这个数据适合做哪些分析",
    "适合做哪些分析",
    "可以做哪些分析",
    "下一步应该分析什么",
    "这个数据正常吗",
    "数据正常吗",
    "这个数据能不能用",
    "能不能用",
    "能不能做趋势",
    "能不能做环比",
    "能不能做同比",
    "能否做趋势",
    "能否做环比",
    "能否做同比",
    "字段是否一致",
    "这些文件有什么区别",
    "哪些字段适合做指标",
    "适合做指标",
    "适合做维度",
    "适合做时间",
    "适合做id",
    "不能直接回答",
    "哪些问题现在不能",
    "主要的分组",
    "主要分组",
    "主要类别",
    "用于对比",
    "用于join",
    "这几个表什么意思",
    "这几张表什么意思",
    "这些表什么意思",
    "这几个文件什么意思",
    "这些文件什么意思",
    "这几个表有什么字段",
    "这些表有什么字段",
    "这个表有什么字段",
    "这张表有什么字段",
    "这个数据怎么样",
    "这个表怎么样",
    "这个文件怎么样",
    "哪里有问题",
    "看看哪里有问题",
    "数据概览",
    "数据总览",
)

_SHAPE_OVERVIEW_PHRASES = (
    "每个文件分别有多少行、多少列",
    "每个文件分别有多少行，多少列",
    "每个文件分别有多少行多少列",
    "每个文件有多少行、多少列",
    "每个文件有多少行，多少列",
    "每个文件有多少行多少列",
    "各个文件有多少行、多少列",
    "各个文件有多少行，多少列",
    "各个文件有多少行多少列",
    "每张表分别有多少行、多少列",
    "每张表分别有多少行，多少列",
    "每张表分别有多少行多少列",
    "每个表分别有多少行、多少列",
    "每个表分别有多少行，多少列",
    "每个表分别有多少行多少列",
    "各个表有多少行、多少列",
    "各个表有多少行，多少列",
    "各个表有多少行多少列",
    "多少行、多少列",
    "多少行，多少列",
    "多少行多少列",
    "行数、列数",
    "行数，列数",
    "行数列数",
    "行列规模",
    "表规模",
    "文件规模",
)

_SCHEMA_OVERVIEW_PHRASES = (
    "有什么字段",
    "有哪些字段",
    "字段是什么",
    "字段含义",
    "主要讲什么",
    "主要内容",
    "数据讲什么",
    "是什么数据",
    "这个数据是做什么",
    "这个数据主要讲什么",
    "这个数据适合做哪些分析",
    "适合做哪些分析",
    "可以做哪些分析",
    "下一步应该分析什么",
    "这个数据正常吗",
    "数据正常吗",
    "这个数据能不能用",
    "能不能用",
    "能不能做趋势",
    "能不能做环比",
    "能不能做同比",
    "能否做趋势",
    "能否做环比",
    "能否做同比",
    "字段是否一致",
    "这些文件有什么区别",
    "哪些字段适合做指标",
    "适合做指标",
    "适合做维度",
    "适合做时间",
    "不能直接回答",
    "哪些问题现在不能",
    "主要的分组",
    "主要分组",
    "主要类别",
    "用于对比",
    "用于join",
    "表什么意思",
    "表单什么意思",
    "文件什么意思",
    "这几个表什么意思",
    "这几张表什么意思",
    "这些表什么意思",
)

_CAPABILITY_OVERVIEW_PHRASES = (
    "这个数据适合做哪些分析",
    "适合做哪些分析",
    "可以做哪些分析",
    "下一步应该分析什么",
    "这个数据正常吗",
    "数据正常吗",
    "这个数据能不能用",
    "能不能用",
    "能不能做趋势",
    "能不能做环比",
    "能不能做同比",
    "能否做趋势",
    "能否做环比",
    "能否做同比",
    "字段是否一致",
)


_SCHEMA_OVERVIEW_TOKENS = (
    "含义",
    "什么意思",
    "讲什么",
    "主要内容",
    "字段",
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
    "总结",
    "介绍",
    "含义",
    "什么意思",
    "字段",
)

_DATA_SUBJECT_TOKENS = (
    "数据",
    "表",
    "表单",
    "数据集",
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

_STRONG_SPECIFIC_ANALYSIS_TOKENS = (
    "哪个",
    "哪一个",
    "最高",
    "最低",
    "最大",
    "最小",
    "top",
    "排名",
    "多少",
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
