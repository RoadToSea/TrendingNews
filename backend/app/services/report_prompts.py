"""Editorial prompt templates and clean context formatters for AI-generated reports."""

from typing import Any, Dict, List, Optional

REPORT_SYSTEM_PROMPT = (
    "你是资深新闻情报主编与产业分析编辑。请参考 BLUF（结论先行）、ICD 203 分析规范（区分客观事实与分析研判、"
    "如实指明信息缺口）及 Smart Brevity 精炼可读原则，撰写简体中文 Markdown 研判简报。\n\n"
    "必须严格遵守的写作与排版铁律：\n"
    "1. 结论先行与连贯叙事：开篇先给核心结论，正文采用清晰的小标题与紧凑段落（每段 3–5 句）"
    "搭配克制的加粗导语要点，讲清“发生了什么、为何重要、多方视角差异、接下来会怎么走”。\n"
    "2. 严禁使用 Markdown 表格：通篇不得输出任何 `| 列 |` 形式的表格、矩阵或管道符排版。\n"
    "3. 严禁暴露系统内部符号与生硬数字：正文中绝对禁止出现 `event_id`、`news_id`、`ID`、`hot_index`、`velocity`、"
    "`platform_count`、`#1/#2` 排名编号或“火热指数 69.38 / 增速 +25”等内部字段与数值；请将传播情况自然转化为中文描述"
    "（例如“在多个主流平台引发集中讨论”“近期迅速升温”“主要见于技术社区与行业媒体”）。\n"
    "4. 严谨求实与平台温差：重要论断需注明平台或媒体来源，清晰区分已证实事实与推演判断；"
    "注重捕捉大众社交平台热议与权威媒体/专业订阅视角之间的反差；严禁编造未提供的事实、数字或链接。\n"
    "5. 零废话与零表情符号：严禁使用任何 emoji 符号，也不要写“好的，以下是报告”“综上所述”等客套套话，直接输出正文。"
)


def describe_propagation(platform_count: int) -> str:
    """Translate raw platform counts into natural Chinese propagation phrasing."""
    if platform_count >= 5:
        return "全网多平台同步热议，破圈关注度高"
    if platform_count >= 3:
        return "在多个平台形成跨圈层传播"
    if platform_count == 2:
        return "已有跨平台联动讨论"
    return "目前主要集中在单一平台或垂直圈层内讨论"


def describe_momentum(velocity: float, rank: Optional[int] = None) -> str:
    """Translate raw velocity and rank signals into qualitative momentum prose."""
    if velocity >= 50:
        return "关注度短时间内快速拉升"
    if velocity >= 20:
        return "近期讨论热度呈明显上升趋势"
    if rank is not None and rank <= 3:
        return "在对应平台处于前列讨论位置"
    return "保持稳定关注"


def build_daily_overall_prompt(
    title: str,
    events: List[Dict[str, Any]],
    items_by_ev: Dict[int, List[Dict[str, Any]]],
    rising: List[Dict[str, Any]],
) -> str:
    """Build a clean, ID-free daily briefing prompt from top events and rising items."""
    event_blocks: List[str] = []
    for ev in events:
        eid = int(ev["id"])
        spread = describe_propagation(int(ev.get("platform_count") or 1))
        momentum = describe_momentum(float(ev.get("velocity") or 0.0), ev.get("daily_rank"))
        summary = str(ev.get("summary") or "").strip()
        sources = items_by_ev.get(eid, [])[:4]
        source_lines = "；".join(
            f"{str(it.get('platform_name') or '媒体')}《{str(it.get('title') or '').strip()}》"
            for it in sources
            if str(it.get("title") or "").strip()
        )
        lines = [
            f"- **议题**：{str(ev.get('canonical_title') or '').strip()}",
            f"  - 领域与传播：{str(ev.get('domain') or '综合')}（{spread}，{momentum}）",
        ]
        if summary:
            lines.append(f"  - 摘要：{summary}")
        if source_lines:
            lines.append(f"  - 相关报道：{source_lines}")
        event_blocks.append("\n".join(lines))

    rising_lines: List[str] = []
    for it in rising[:12]:
        plat = str(it.get("platform_name") or "平台").strip()
        item_title = str(it.get("title") or "").strip()
        cue = describe_momentum(float(it.get("velocity") or 0.0), it.get("latest_rank"))
        if item_title:
            rising_lines.append(f"- [{plat}] {item_title}（{cue}）")

    events_text = "\n".join(event_blocks) if event_blocks else "暂无汇总议题。"
    rising_text = "\n".join(rising_lines) if rising_lines else "暂无显著快速升温条目。"

    return (
        f"请直接输出一篇题为《# {title}》的每日热点研判简报，严格按以下三部分组织正文（不要使用表格、不要写内部 ID 或指数分数）：\n\n"
        "## 核心研判（今日要览）\n"
        "用 1–2 段精炼文字开门见山总结今日舆论核心主线、最具影响力的公共或产业动向，以及背后反映的共性趋势。\n\n"
        "## 重点议题深度解读\n"
        "按重要性分段剖析今日核心议题（每个重点议题用三级小标题 `### 议题名` 展开自然叙事）：讲清事件脉络与影响，"
        "结合不同平台/媒体的报道视角对比大众情绪与专业声音的差异。\n\n"
        "## 正在升温的苗头与后续观察\n"
        "从快速升温条目中提炼 2–4 个早期信号或演化风向，说明接下来 24–72 小时值得留意的关键变化或验证节点（禁止空话套话）。\n\n"
        f"【参考事实底座 · 重点议题】\n{events_text}\n\n"
        f"【参考事实底座 · 近期升温动态】\n{rising_text}"
    )


def build_domain_trend_prompt(
    title: str,
    domain_name: str,
    events: List[Dict[str, Any]],
    rss: List[Dict[str, Any]],
) -> str:
    """Build a clean, ID-free domain trend briefing prompt."""
    event_blocks: List[str] = []
    for ev in events[:15]:
        spread = describe_propagation(int(ev.get("platform_count") or 1))
        momentum = describe_momentum(float(ev.get("velocity") or 0.0))
        summary = str(ev.get("summary") or "").strip()
        block = f"- **{str(ev.get('canonical_title') or '').strip()}**（{spread}，{momentum}）"
        if summary:
            block += f"\n  - 背景：{summary}"
        event_blocks.append(block)

    rss_blocks: List[str] = []
    for it in rss[:15]:
        feed = str(it.get("platform_name") or "权威媒体").strip()
        item_title = str(it.get("title") or "").strip()
        summary = str(it.get("summary") or "").strip()[:220]
        if item_title:
            line = f"- [{feed}] {item_title}"
            if summary:
                line += f" —— {summary}"
            rss_blocks.append(line)

    events_text = "\n".join(event_blocks) if event_blocks else "当日该领域暂无跨平台汇总事件。"
    rss_text = "\n".join(rss_blocks) if rss_blocks else "近期暂无该领域权威媒体订阅更新。"

    return (
        f"请围绕「{domain_name}」撰写一篇专题趋势简报《# {title}》（全程使用流畅叙事段落与适度要点，禁用 Markdown 表格与任何系统内部编号）：\n\n"
        "## 领域核心判断\n"
        "结论先行，用 3–5 句话概括当前该领域的核心主线、最值得关注的突破或争议，以及总体态势判断。\n\n"
        "## 关键动态与多方视角\n"
        "按重要主题展开分析，将大众讨论热度与权威媒体/专业订阅内容进行交叉印证，指出两者关注的焦点异同。\n\n"
        "## 信息缺口与短期观察点\n"
        "诚实说明当前资料中尚不明朗的信息盲区，并列出短期内最值得跟踪的 2–3 个具体观察线索。\n\n"
        f"【该领域热点动态】\n{events_text}\n\n"
        f"【该领域媒体与官方订阅报道】\n{rss_text}"
    )


def build_item_analysis_prompt(
    events_data: List[Dict[str, Any]],
    news_items: List[Dict[str, Any]],
) -> str:
    """Build a focused narrative prompt for selected events or articles without DB keys."""
    sections: List[str] = []

    if events_data:
        ev_lines: List[str] = []
        for ev in events_data:
            title = str(ev.get("canonical_title") or "").strip()
            domain = str(ev.get("domain") or "综合").strip()
            summary = str(ev.get("summary") or "").strip()
            linked = ev.get("linked_items") or []
            sources = "；".join(
                f"{str(it.get('platform') or '媒体')}《{str(it.get('title') or '').strip()}》"
                for it in linked
                if str(it.get("title") or "").strip()
            )
            block = f"- **主题**：{title}（所属领域：{domain}）"
            if summary:
                block += f"\n  - 概述：{summary}"
            if sources:
                block += f"\n  - 来源报道：{sources}"
            ev_lines.append(block)
        sections.append("【选中的热点议题】\n" + "\n".join(ev_lines))

    if news_items:
        item_lines: List[str] = []
        for it in news_items:
            plat = str(it.get("platform_name") or "来源").strip()
            title = str(it.get("title") or "").strip()
            summary = str(it.get("summary") or "").strip()[:260]
            url = str(it.get("url") or "").strip()
            line = f"- [{plat}] {title}"
            if summary:
                line += f"\n  - 摘要：{summary}"
            if url:
                line += f"\n  - 参考链接：{url}"
            item_lines.append(line)
        sections.append("【选中的具体报道】\n" + "\n".join(item_lines))

    material = "\n\n".join(sections)
    return (
        "请基于以下用户选中的热点素材撰写一篇可读性强的专题深度解读报告（不使用表格、不输出任何内部 ID 或机械打分）：\n\n"
        "## 核心结论与背景\n"
        "先用简明段落说清这件事的核心本质、背景来龙去脉与重要性。\n\n"
        "## 多信源叙事与核心观点\n"
        "梳理不同报道或平台之间的关注重点、立场角度与信息增量，区分确定事实与争议观点。\n\n"
        "## 潜在影响与后续演进\n"
        "推演该事件对相关行业、公众或市场的后续影响，并给出具体的后续验证关注点。\n\n"
        f"{material}"
    )


def build_chat_export_prompt(transcript: str) -> str:
    """Format a conversation transcript into an executive prose-first report prompt."""
    return (
        "请将以下热点研判对话整理为一篇逻辑严密、结论先行的简体中文 Markdown 分析报告。\n"
        "要求：\n"
        "1. 采用小标题与连贯自然段落撰写，禁止使用 Markdown 表格。\n"
        "2. 禁止出现任何内部字段名、数字 ID、机械打分或客套开场白，也不用 emoji。\n"
        "3. 保留对话中已经明确的数据依据、信源出处与核心判断，对尚未核实的推测予以清晰标注。\n\n"
        f"【对话记录】\n{transcript}"
    )
