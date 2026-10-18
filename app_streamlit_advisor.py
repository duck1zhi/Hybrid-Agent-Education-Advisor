#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
教培咨询规划助手 - Streamlit 可视化界面

左侧输入单个问题，后台调用「1-Hybrid Agent-教培机构咨询规划助手.py」的
run_education_advisor，在主区展示处理过程与最终回答。
"""

from __future__ import annotations

import importlib.util
import io
import sys
import time
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import streamlit as st

# ---------------------------------------------------------------------------
# 页面基础配置
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="教培咨询规划助手",
    layout="wide",
    initial_sidebar_state="expanded",
)

SCRIPT_DIR = Path(__file__).resolve().parent
AGENT_FILE = SCRIPT_DIR / "1-Hybrid Agent-教培机构咨询规划助手.py"

# 快捷测试问题（按类别折叠；点击后直接触发生成）
QUICK_QUESTION_GROUPS = {
    "查课报价": [
        "Python数据分析班多少钱，每周什么时候上课，还剩几个名额？",
        "大模型应用开发班和AI智能体实战班的价格、上课时间和剩余名额分别是多少？",
        "Python入门班、Python数据分析班和大模型应用开发班有什么区别，我该先上哪个？",
    ],
    "限时折扣": [
        "限时优惠活动期间报 Python入门班能打几折？现价大约多少？",
        "入门班结业后续报 Python数据分析班，学费按什么折扣算？",
        "限时活动期间续报进阶，能不能折上折？大概相当于几折？",
        "续报进阶会送哪三门课？限时活动期间续报能否同时享受折扣和赠课？",
        "零基础先限时报入门班，再续报大模型应用开发班，费用和福利怎么算？",
        "零基础一次性报 Python入门班加任意一门进阶课，能不能折上折？送不送三门课？",
        "零基础一次性报整条路径A或路径B，学费怎么算？有没有赠课？",
    ],
    "学习规划": [
        "请结合我的学员信息，帮我规划接下来的学习路径和课程组合。",
        "请结合我的预算和已学课程，评估下一步该怎么选课、如何衔接。",
        "请结合我的情况，评估机器学习项目班和AI智能体实战班，并给出学习节奏建议。",
    ],
}

STUDENT_OPTIONS = {
    "student1": "零基础学员（预算约10000元）",
    "student2": "入门学员（已完成Python入门，预算约18000元）",
    "student3": "资深学员（入门+数据分析已完成，大模型进行中）",
}


def _now_tag() -> str:
    return datetime.now().strftime("%H:%M:%S")


def load_advisor_module(force_reload: bool = False):
    """
    动态加载助手脚本。按文件修改时间自动热加载，避免 Streamlit 一直用旧模块
    （否则新增「报班活动查询」后界面仍答「资料库没有限时优惠」）。
    """
    if not AGENT_FILE.exists():
        raise FileNotFoundError(f"未找到助手脚本: {AGENT_FILE}")

    mtime = AGENT_FILE.stat().st_mtime_ns
    mod_name = "hybrid_education_advisor"
    cached_mtime = st.session_state.get("_advisor_mtime")
    cached_mod = st.session_state.get("_advisor_module")

    need_reload = (
        force_reload
        or cached_mod is None
        or cached_mtime != mtime
        or not hasattr(cached_mod, "query_promo_activity")
    )
    if not need_reload:
        return cached_mod

    # 清掉旧模块，确保重新 exec 最新源码
    if mod_name in sys.modules:
        del sys.modules[mod_name]

    spec = importlib.util.spec_from_file_location(mod_name, str(AGENT_FILE))
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)

    st.session_state._advisor_module = module
    st.session_state._advisor_mtime = mtime
    return module


def run_advisor(
    user_query: str,
    student_id: str,
) -> Tuple[Dict[str, Any], str, float]:
    """
    调用助手问询功能，并捕获控制台日志用于界面展示。
    返回: (结果字典, 日志文本, 耗时秒)
    """
    module = load_advisor_module()
    buf = io.StringIO()
    t0 = time.perf_counter()
    with redirect_stdout(buf):
        print(f"[{_now_tag()}] 收到用户问题，开始调用 Hybrid Agent...")
        print(f"[{_now_tag()}] 助手模块已加载 query_promo_activity={hasattr(module, 'query_promo_activity')}")
        print(f"[{_now_tag()}] student_id={student_id}")
        print(f"[{_now_tag()}] 正在执行 LangGraph 工作流（评估 → 反应式/深思熟虑）...")
        result = module.run_education_advisor(
            user_query=user_query,
            student_id=student_id,
        )
        mode = result.get("processing_mode", "未知")
        qtype = result.get("query_type", "未知")
        print(f"[{_now_tag()}] 处理模式: {mode} | 查询类型: {qtype}")
        if result.get("error"):
            print(f"[{_now_tag()}] 执行出现错误: {result.get('error')}")
        else:
            print(f"[{_now_tag()}] 回答生成完成")
    elapsed = time.perf_counter() - t0
    return result, buf.getvalue(), elapsed


# ---------------------------------------------------------------------------
# 样式：参考截图（渐变顶栏、红按钮、日志终端、答案卡片）
# ---------------------------------------------------------------------------
st.markdown(
    """
<style>
    /* 侧边栏 */
    [data-testid="stSidebar"] {
        background: #f7f8fa;
        border-right: 1px solid #e6e8eb;
    }
    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3 {
        color: #1f2937;
    }
    /* 主区背景 */
    .stApp {
        background: #f3f4f6;
    }
    /* 渐变顶栏 */
    .hero-banner {
        background: linear-gradient(90deg, #7c3aed 0%, #a855f7 45%, #ec4899 100%);
        border-radius: 14px;
        padding: 1.6rem 1.8rem;
        color: #fff;
        margin-bottom: 1.1rem;
        box-shadow: 0 8px 24px rgba(124, 58, 237, 0.25);
    }
    .hero-banner h1 {
        margin: 0 0 0.35rem 0;
        font-size: 1.75rem;
        font-weight: 700;
        letter-spacing: 0.02em;
    }
    .hero-banner p {
        margin: 0;
        opacity: 0.92;
        font-size: 0.95rem;
    }
    /* 分区卡片 */
    .section-card {
        background: #fff;
        border: 1px solid #e5e7eb;
        border-radius: 12px;
        padding: 1rem 1.1rem 1.15rem;
        margin-bottom: 1rem;
        box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    }
    .section-title {
        font-size: 1.05rem;
        font-weight: 700;
        color: #111827;
        margin: 0 0 0.75rem 0;
        padding-bottom: 0.45rem;
        border-bottom: 1px solid #eee;
    }
    /* 终端日志 */
    .log-console {
        background: #1e1e1e;
        color: #d4d4d4;
        font-family: Consolas, "Courier New", monospace;
        font-size: 0.82rem;
        line-height: 1.55;
        border-radius: 10px;
        padding: 0.9rem 1rem;
        max-height: 280px;
        overflow-y: auto;
        white-space: pre-wrap;
        word-break: break-word;
    }
    /* 答案区 */
    .answer-box {
        background: #f9fafb;
        border: 1px solid #e5e7eb;
        border-radius: 10px;
        padding: 1rem 1.1rem;
        line-height: 1.7;
        color: #111827;
        white-space: pre-wrap;
    }
    .meta-green {
        background: #ecfdf5;
        border: 1px solid #a7f3d0;
        border-radius: 10px;
        padding: 0.75rem 0.95rem;
        color: #065f46;
        margin-top: 0.75rem;
        font-size: 0.92rem;
    }
    .meta-blue {
        background: #eff6ff;
        border: 1px solid #bfdbfe;
        border-radius: 10px;
        padding: 0.75rem 0.95rem;
        color: #1e3a8a;
        margin-top: 0.75rem;
        font-size: 0.92rem;
    }
    /* 红色主按钮（生成答案） */
    div.stButton > button[kind="primary"] {
        background: #e11d48 !important;
        color: #fff !important;
        border: none !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
        height: 2.6rem;
    }
    div.stButton > button[kind="primary"]:hover {
        background: #be123c !important;
        color: #fff !important;
        border: none !important;
    }
    /* 侧边栏快捷问题：浅色描边按钮 */
    [data-testid="stSidebar"] div.stButton > button[kind="secondary"] {
        background: #fff !important;
        color: #374151 !important;
        border: 1px solid #d1d5db !important;
        font-weight: 500 !important;
        height: auto !important;
        min-height: 2.4rem;
        white-space: normal !important;
        text-align: left !important;
        padding: 0.45rem 0.7rem !important;
    }
    [data-testid="stSidebar"] div.stButton > button[kind="secondary"]:hover {
        border-color: #e11d48 !important;
        color: #be123c !important;
        background: #fff1f2 !important;
    }
</style>
""",
    unsafe_allow_html=True,
)


def init_state() -> None:
    defaults = {
        "query_text": "",
        "last_result": None,
        "last_log": "",
        "last_elapsed": 0.0,
        "last_query": "",
        "has_run": False,
        "auto_run": False,
        "student_id": "student1",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _fill_and_auto_run(question: str) -> None:
    """on_click：填入问题并标记本轮自动生成答案。"""
    st.session_state.query_text = question
    st.session_state.auto_run = True


def render_sidebar() -> Tuple[str, str, bool]:
    """渲染侧边栏，返回 (问题, student_id, 是否点击生成)。"""
    with st.sidebar:
        st.markdown("### 查询设置")
        # 与快捷问题共用 session_state.query_text（仅用 key，不用 value 双写）
        st.text_area(
            "请输入您的问题",
            height=120,
            placeholder="例如：Python数据分析班多少钱，还剩几个名额？",
            label_visibility="collapsed",
            key="query_text",
        )

        student_id = st.selectbox(
            "学员画像（规划类问题建议选择）",
            options=list(STUDENT_OPTIONS.keys()),
            format_func=lambda x: STUDENT_OPTIONS[x],
            key="student_id",
        )

        clicked = st.button("生成答案", type="primary", use_container_width=True)

        st.markdown("---")
        st.markdown("### 快捷测试问题")
        st.caption("点击快捷问题后直接开始生成。")

        # 分类折叠：默认展开「限时折扣」，其余收起
        for group_name, questions in QUICK_QUESTION_GROUPS.items():
            expanded = group_name == "限时折扣"
            with st.expander(group_name, expanded=expanded):
                for i, q in enumerate(questions):
                    st.button(
                        q,
                        key=f"quick_{group_name}_{i}",
                        use_container_width=True,
                        on_click=_fill_and_auto_run,
                        args=(q,),
                    )

        st.markdown("---")
        if st.button("重新加载助手模块", use_container_width=True):
            load_advisor_module(force_reload=True)
            st.success("已重新加载最新助手脚本（含报班活动查询）")
        st.caption("后台调用：1-Hybrid Agent-教培机构咨询规划助手.py")
        st.caption("资料库事实驱动 · LangGraph 混合智能体")

    query = (st.session_state.get("query_text") or "").strip()
    auto_run = bool(st.session_state.pop("auto_run", False))
    return query, student_id, (clicked or auto_run)


def render_hero() -> None:
    st.markdown(
        """
        <div class="hero-banner">
          <h1>教培机构咨询规划助手</h1>
          <p>Hybrid Agent · 反应式查课 + 深思熟虑规划 · 资料库 Excel 驱动</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def mode_label(mode: Optional[str]) -> str:
    if mode == "reactive":
        return "反应式（快速查课 / 事实问答）"
    if mode == "deliberative":
        return "深思熟虑（个性化学习规划）"
    return mode or "未知"


def render_process_log(log_text: str, elapsed: float) -> None:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown(
        f'<div class="section-title">实时处理过程'
        f'<span style="float:right;font-weight:500;color:#6b7280;font-size:0.85rem;">'
        f'耗时 {elapsed:.2f}s</span></div>',
        unsafe_allow_html=True,
    )
    safe = (log_text or "等待提问…").replace("<", "&lt;").replace(">", "&gt;")
    st.markdown(f'<div class="log-console">{safe}</div>', unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


def render_details(result: Dict[str, Any]) -> None:
    """展示中间信息：模式、学情装配等（对应参考图的检索汇总区）。"""
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">处理详情汇总</div>', unsafe_allow_html=True)

    with st.expander(
        f"协调层判定 | 模式: {result.get('processing_mode', '-')} | "
        f"类型: {result.get('query_type', '-')}",
        expanded=True,
    ):
        st.write(
            {
                "processing_mode": result.get("processing_mode"),
                "query_type": result.get("query_type"),
                "current_phase": result.get("current_phase"),
                "error": result.get("error"),
            }
        )

    course_data = result.get("course_data")
    if course_data:
        with st.expander("深思熟虑 · 已装配课程资料库事实", expanded=False):
            st.json(course_data)

    analysis = result.get("analysis_results")
    if analysis:
        with st.expander("深思熟虑 · 分析结果", expanded=False):
            st.json(analysis)

    profile = result.get("student_profile")
    if profile:
        with st.expander("当前学员画像", expanded=False):
            st.json(profile)

    st.markdown("</div>", unsafe_allow_html=True)


def render_answer(result: Dict[str, Any], query: str) -> None:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">最终答案</div>', unsafe_allow_html=True)

    answer = result.get("final_response") or "未能生成响应"
    safe_answer = str(answer).replace("<", "&lt;").replace(">", "&gt;")
    st.markdown(f'<div class="answer-box">{safe_answer}</div>', unsafe_allow_html=True)

    mode = mode_label(result.get("processing_mode"))
    st.markdown(
        f'<div class="meta-green"><strong>处理摘要：</strong>'
        f'问题已通过 Hybrid Agent 完成应答；当前采用「{mode}」。'
        f"</div>",
        unsafe_allow_html=True,
    )

    steps = [
        "1. 协调层评估问题类型，选择 reactive 或 deliberative",
        "2. 反应式路径：按需调用班次 / 内容 / 排课资料库工具后作答",
        "3. 深思熟虑路径：装配资料库事实 → 分析 → 生成学习规划",
        "4. 将最终自然语言回答返回界面展示",
    ]
    # 按实际模式裁剪说明
    if result.get("processing_mode") == "reactive":
        steps = [
            "1. 协调层判定为反应式处理（事实查询为主）",
            "2. ReAct 决策是否调用课程班次 / 内容 / 排课工具",
            "3. 严格依据资料库返回原文组织回答",
            "4. 输出最终答案给用户",
        ]
    elif result.get("processing_mode") == "deliberative":
        steps = [
            "1. 协调层判定为深思熟虑处理（需个性化规划）",
            "2. 从资料库装配课程与学情事实",
            "3. 结合学员画像做差距分析与路径推荐",
            "4. 生成可执行的学习 / 续费规划回答",
        ]

    st.markdown(
        '<div class="meta-blue"><strong>处理步骤：</strong><br>'
        + "<br>".join(steps)
        + f"<br><br><strong>用户原问：</strong>{query}"
        + "</div>",
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)


def main() -> None:
    init_state()
    query, student_id, clicked = render_sidebar()
    render_hero()

    if clicked:
        if not query:
            st.warning("请先输入问题，或点击左侧快捷测试问题。")
        else:
            with st.spinner("智能体处理中，请稍候…"):
                try:
                    result, log_text, elapsed = run_advisor(query, student_id)
                    st.session_state.last_result = result
                    st.session_state.last_log = log_text
                    st.session_state.last_elapsed = elapsed
                    st.session_state.last_query = query
                    st.session_state.has_run = True
                except Exception as e:
                    st.session_state.has_run = True
                    st.session_state.last_result = {
                        "final_response": f"调用失败: {e}",
                        "error": str(e),
                        "processing_mode": "unknown",
                    }
                    st.session_state.last_log = f"[{_now_tag()}] 异常: {e}"
                    st.session_state.last_elapsed = 0.0
                    st.session_state.last_query = query

    if not st.session_state.has_run:
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">使用说明</div>', unsafe_allow_html=True)
        st.markdown(
            """
1. 在左侧输入**单个问题**，或展开快捷分类后**点选测试问题**（点选后会直接生成）  
2. 如需个性化规划，可选择对应**学员画像**  
3. 也可手动点击红色 **生成答案**  
4. 下方将展示：实时处理日志、详情汇总、最终答案  

请确认已设置环境变量 `DASHSCOPE_API_KEY`（通义）；可选 `LANGFUSE_*` 用于追踪。
            """
        )
        st.markdown("</div>", unsafe_allow_html=True)
        return

    result = st.session_state.last_result or {}
    render_process_log(st.session_state.last_log, st.session_state.last_elapsed)

    col_left, col_right = st.columns([1, 1], gap="medium")
    with col_left:
        render_details(result)
    with col_right:
        render_answer(result, st.session_state.last_query)


if __name__ == "__main__":
    main()
