"""Conversation-level intent guards for VDS workbench messages."""

from __future__ import annotations

import re


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
    if is_dataset_source_question(question):
        return "dataset_source_overview"
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
            "你能干什么",
            "你可以干什么",
            "你能帮我做什么",
            "你能帮我干什么",
            "你可以帮我做什么",
            "我能干什么",
            "我可以干什么",
            "我能问什么",
            "我可以问什么",
            "我该问什么",
            "我能让你做什么",
            "我可以让你做什么",
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
    if _looks_like_explicit_metric_total_question(compact):
        return False
    if _looks_like_grouped_metric_analysis_question(compact):
        return False
    if _looks_like_dataset_content_overview_question(compact):
        return True
    if _looks_like_explicit_business_overview_request(compact):
        return True
    if any(phrase in compact for phrase in _CAPABILITY_OVERVIEW_PHRASES):
        return True
    if any(phrase in compact for phrase in _SHAPE_OVERVIEW_PHRASES):
        return True
    if _looks_like_broad_business_overview_question(compact):
        return True
    if _looks_like_multi_table_overview_question(compact):
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


def _looks_like_explicit_metric_total_question(compact: str) -> bool:
    return any(
        token in compact
        for token in (
            "总订单金额",
            "订单总金额",
            "订单总额",
            "订单金额",
            "总金额",
            "总收入",
            "总利润",
            "客户数量",
            "总客户数",
            "利润率",
            "销售总额",
            "销售总金额",
        )
    ) or bool(re.search(r"客户数(?!据)", compact))


def _looks_like_grouped_metric_analysis_question(compact: str) -> bool:
    grouped_subject = any(token in compact for token in ("各城市", "每个城市", "所有城市", "各区域", "各地区", "各服务线", "各业务线", "各产品", "各客户"))
    metric_subject = any(token in compact for token in ("销售", "订单", "金额", "收入", "营收", "利润", "工单", "票据", "指标"))
    time_scope = bool(re.search(r"(?:20\d{2}年)?\d{1,2}月(?:(?:到|至|-|~|—)\d{1,2}月)?|第[一二三四]季度", compact))
    explicit_overview = any(token in compact for token in ("概览", "总览", "整体概况", "总体概况"))
    strong_calculation = any(
        token in compact
        for token in ("排名", "排行", "最高", "最低", "最多", "最少", "总金额", "总额", "总利润", "销售额", "销售金额", "总销售额", "利润", "工单量", "工单数", "合计", "汇总", "分别", "趋势", "占比", "比例", "是多少", "多少")
    )
    if explicit_overview and not strong_calculation:
        return False
    return grouped_subject and metric_subject and (time_scope or any(token in compact for token in ("情况", "表现", "数据")))


def _looks_like_dataset_content_overview_question(compact: str) -> bool:
    asks_data_content = bool(re.search(r"(?:订单|销售|客户|工单|业务|经营)?数据有哪些", compact))
    if not asks_data_content:
        return False
    entity_targets = ("哪些城市", "哪些客户", "哪些产品", "哪些商品", "哪些服务线", "哪些业务线", "哪些品类")
    metric_targets = ("销售额", "订单金额", "总金额", "总利润", "利润率", "工单量")
    return not any(token in compact for token in (*entity_targets, *metric_targets))


def _looks_like_explicit_business_overview_request(compact: str) -> bool:
    overview_signal = any(token in compact for token in ("介绍一下", "介绍下", "概况", "概览", "总览", "整体概况", "总体概况"))
    if not overview_signal:
        return False
    subject_signal = any(token in compact for token in ("数据", "订单", "客户", "销售", "收入", "利润", "工单", "经营", "业务"))
    if not subject_signal:
        return False
    if any(token in compact for token in _STRONG_SPECIFIC_ANALYSIS_TOKENS):
        return False
    specific_action = any(
        token in compact
        for token in ("哪个", "哪一个", "最高", "最低", "最多", "最少", "排名", "排行", "趋势", "占比", "比例", "对比", "比较", "总金额", "总利润", "总额", "合计", "汇总", "是多少", "多少")
    )
    return not specific_action


def is_dataset_source_question(question: str) -> bool:
    """Return True for questions about uploaded non-tabular/source files."""

    text = _normalize(question)
    if not text:
        return False
    compact = text.replace(" ", "")
    source_subject = any(token in compact for token in _SOURCE_FILE_SUBJECT_TOKENS) or any(
        token in text for token in _EN_SOURCE_FILE_TOKENS
    )
    source_action = any(token in compact for token in _SOURCE_FILE_ACTION_TOKENS) or any(
        token in text for token in _EN_SOURCE_ACTION_TOKENS
    )
    if source_subject and source_action:
        return True
    return any(phrase in compact for phrase in _SOURCE_FILE_PHRASES)


def _looks_like_multi_table_overview_question(compact: str) -> bool:
    """Catch broad multi-file/table browse questions before detail lookup."""

    has_multi_subject = any(token in compact for token in _MULTI_TABLE_SUBJECT_TOKENS)
    if not has_multi_subject:
        return False
    has_overview_action = any(token in compact for token in _MULTI_TABLE_OVERVIEW_ACTION_TOKENS)
    has_specific_analysis = any(token in compact for token in _STRONG_SPECIFIC_ANALYSIS_TOKENS) or any(token in compact for token in _SPECIFIC_ANALYSIS_TOKENS)
    return has_overview_action and not has_specific_analysis


def _looks_like_broad_business_overview_question(compact: str) -> bool:
    """Catch broad business-summary requests even when metric words are present."""

    has_broad_signal = any(token in compact for token in ("整体", "总体", "概览", "总览", "情况", "表现", "看一下", "看看", "分析一下"))
    has_business_subject = any(token in compact for token in ("销售", "利润", "收入", "订单", "业务", "经营"))
    if not (has_broad_signal and has_business_subject):
        return False
    specific_actions = (
        "哪个",
        "哪一个",
        "最高",
        "最低",
        "最大",
        "最小",
        "最多",
        "最少",
        "排名",
        "前",
        "top",
        "多少",
        "数量",
        "客户数量",
        "客户数",
        "总客户数",
        "总金额",
        "总利润",
        "总收入",
        "总额",
        "合计",
        "几",
        "按",
        "各",
        "每",
        "趋势",
        "增长",
        "下降",
        "占比",
        "比例",
        "组成",
        "构成",
        "拆分",
        "来源",
        "质量",
        "异常",
        "缺失",
        "重复",
    )
    return not any(token in compact for token in specific_actions)


def is_cleaning_guidance_question(question: str) -> bool:
    """Return True for cleaning-policy or cleaning-simulation questions."""

    text = _normalize(question)
    if not text:
        return False
    compact = text.replace(" ", "")
    if _looks_like_schema_consistency_question(compact):
        return False
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
        "异常值",
        "样例说明",
        "缺失字段",
        "有缺失",
        "缺失值",
        "填充",
        "保留",
        "影响行数",
        "影响比例",
        "明显异常",
        "数据质量",
        "质量问题",
        "是否存在数据质量",
        "有没有异常",
        "有没有质量问题",
        "范围异常",
        "负值",
        "负数",
        "小于0",
        "小于零",
        "低于0",
        "低于零",
        "无法解析",
        "极端值",
        "离群",
        "winsorize",
    )
    if (
        any(signal in compact for signal in boundary_signals)
        or any(signal in compact for signal in cleaning_signals)
        or _looks_like_data_quality_phrase(compact)
    ):
        return True
    return "异常" in compact and any(token in compact for token in ("规则", "样例", "数量", "占比", "比例"))


def _looks_like_data_quality_phrase(compact: str) -> bool:
    if not any(token in compact for token in ("质量如何", "质量怎么样")):
        return False
    data_subject_terms = (
        "数据",
        "文件",
        "表格",
        "表单",
        "字段",
        "列",
        "dataset",
        "table",
        "file",
        "column",
    )
    return any(token in compact for token in data_subject_terms)


def _looks_like_schema_consistency_question(compact: str) -> bool:
    if "字段是否一致" in compact:
        return True
    return "字段" in compact and any(token in compact for token in ("新增", "类型变化", "字段一致", "字段差异"))


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
    "看一下这几张表",
    "看下这几张表",
    "看看这几张表",
    "看一下这几个表",
    "看下这几个表",
    "看看这几个表",
    "看一下这些表",
    "看下这些表",
    "看看这些表",
    "看一下这几个文件",
    "看下这几个文件",
    "看看这几个文件",
    "看一下这些文件",
    "看下这些文件",
    "看看这些文件",
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
    "能分析哪些数据",
    "分析哪些数据",
    "可以分析哪些数据",
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
    "有什么内容",
    "有哪些内容",
    "包含什么内容",
    "里面有什么内容",
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
    "表有什么内容",
    "表单有什么内容",
    "文件有什么内容",
    "数据有什么内容",
    "这几个表什么意思",
    "这几张表什么意思",
    "这些表什么意思",
    "这几个表单什么意思",
    "这些表单什么意思",
    "这几个表有什么内容",
    "这几张表有什么内容",
    "这些表有什么内容",
    "这几个表单有什么内容",
    "这些表单有什么内容",
    "这几个文件有什么内容",
    "这些文件有什么内容",
    "这几个表讲的什么",
    "这几张表讲的什么",
    "这些表讲的什么",
    "这几个文件讲的什么",
    "这些文件讲的什么",
    "这些表有什么区别",
    "这几个表有什么区别",
    "这几张表有什么区别",
    "这些文件有什么区别",
    "这几个文件有什么区别",
)

_MULTI_TABLE_SUBJECT_TOKENS = (
    "这几个表",
    "这几张表",
    "这些表",
    "这几个表单",
    "这些表单",
    "多个表",
    "多张表",
    "所有表",
    "全部表",
    "两张表",
    "两个表",
    "这几个文件",
    "这些文件",
    "多个文件",
    "所有文件",
    "全部文件",
)

_MULTI_TABLE_OVERVIEW_ACTION_TOKENS = (
    "看一下",
    "看下",
    "看看",
    "讲什么",
    "讲的什么",
    "什么意思",
    "含义",
    "字段",
    "区别",
    "差异",
    "不同",
    "介绍",
    "总结",
    "概览",
    "总览",
    "主要",
    "能分析",
    "分析哪些",
    "哪些数据",
    "内容",
    "有什么内容",
    "有哪些内容",
    "包含什么",
    "里面有什么",
)

_SOURCE_FILE_PHRASES = (
    "还有几个文件是干什么用的",
    "还有几个文件干什么用",
    "还有几个文件是做什么的",
    "其他几个文件是干什么用的",
    "其他几个文件干什么用",
    "其他几个文件是做什么的",
    "说明文件是干什么用的",
    "规则文件是干什么用的",
    "知识文件是干什么用的",
    "manual.md是干什么",
    "fees.json是干什么",
    "merchant_data.json是干什么",
)

_SOURCE_FILE_SUBJECT_TOKENS = (
    "说明文件",
    "规则文件",
    "知识文件",
    "文档",
    "手册",
    "manual",
    "fees",
    "merchant_data",
    "md文件",
    "txt文件",
    "json文件",
    "word",
    "doc文件",
    "doc文档",
    "docx",
    "docm",
    "rtf",
    "odt",
    "pdf",
    "pages",
    "html",
    "还有几个文件",
    "其他几个文件",
    "非表格文件",
    "非数据文件",
)

_SOURCE_FILE_ACTION_TOKENS = (
    "干什么",
    "做什么",
    "用来",
    "用途",
    "用处",
    "讲什么",
    "主要内容",
    "有什么内容",
    "有哪些内容",
    "包含什么",
    "里面有什么",
    "读到",
    "读取",
    "识别",
    "解释",
    "说明",
)

_EN_SOURCE_FILE_TOKENS = (
    "manual",
    "readme",
    "doc",
    "docx",
    "docm",
    "rtf",
    "odt",
    "pdf",
    "pages",
    "html",
    "source file",
    "knowledge file",
    "rule file",
)

_EN_SOURCE_ACTION_TOKENS = (
    "what is",
    "what are",
    "purpose",
    "used for",
    "read",
    "explain",
)

_CAPABILITY_OVERVIEW_PHRASES = (
    "这个数据适合做哪些分析",
    "能分析哪些数据",
    "分析哪些数据",
    "可以分析哪些数据",
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
    "最好",
    "最佳",
    "最优",
    "最差",
    "表现",
    "top",
    "排名",
    "多少",
    "数量",
    "总金额",
    "总利润",
    "总额",
    "合计",
    "总收入",
    "销售额",
    "销售金额",
    "利润",
    "利润率",
    "客户数量",
    "订单数量",
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
    "组成",
    "构成",
    "拆分",
    "下钻",
    "拉动",
    "驱动",
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
    "最好",
    "最佳",
    "最优",
    "最差",
    "表现",
    "top",
    "排名",
    "多少",
    "数量",
    "总金额",
    "总利润",
    "总额",
    "合计",
    "总收入",
    "销售额",
    "销售金额",
    "利润",
    "利润率",
    "客户数量",
    "订单数量",
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
    "组成",
    "构成",
    "拆分",
    "下钻",
    "拉动",
    "驱动",
    "筛选",
    "列出",
    "为空",
    "空值",
    "缺失",
    "重复",
    "异常",
    "质量",
)
