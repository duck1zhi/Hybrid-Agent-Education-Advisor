#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
DeepEval + Langfuse 评估脚本 - 教培机构咨询规划助手

对「1-Hybrid Agent-教培机构咨询规划助手.py」：
1. 用 DeepEval 指标打分（相关性 / 幻觉 / 学员匹配 / 课程事实）
2. 在 Langfuse 创建数据集，并在 Experiments 中展示评估结果

安装依赖：
    pip install deepeval langfuse langchain-openai

运行方式：
    python .\\3-deepeval_education_advisor.py

环境变量：
    LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_BASE_URL
    DEEPSEEK_API_KEY（DeepEval 评判模型）
    DASHSCOPE_API_KEY（教培助手通义）
可选：
    DEEPSEEK_MODEL=deepseek-flash
查看结果：http://localhost:3000 → Datasets / Experiments
"""

import os
import sys
import time
import importlib.util
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable

from deepeval.test_case import LLMTestCase, LLMTestCaseParams
from deepeval.metrics import (
    AnswerRelevancyMetric,
    HallucinationMetric,
    GEval,
)
from deepeval.models import DeepSeekModel
from langfuse import Langfuse, Evaluation

# ==================== Langfuse 环境配置 ====================
os.environ["LANGCHAIN_TRACING_V2"] = "false"

LANGFUSE_PUBLIC_KEY = (os.getenv("LANGFUSE_PUBLIC_KEY") or "").strip()
LANGFUSE_SECRET_KEY = (os.getenv("LANGFUSE_SECRET_KEY") or "").strip()
LANGFUSE_BASE_URL = (os.getenv("LANGFUSE_BASE_URL") or "http://localhost:3000").strip().rstrip("/")
LANGFUSE_ENABLED = bool(LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY)

if LANGFUSE_PUBLIC_KEY:
    os.environ["LANGFUSE_PUBLIC_KEY"] = LANGFUSE_PUBLIC_KEY
if LANGFUSE_SECRET_KEY:
    os.environ["LANGFUSE_SECRET_KEY"] = LANGFUSE_SECRET_KEY
os.environ["LANGFUSE_BASE_URL"] = LANGFUSE_BASE_URL
os.environ["LANGFUSE_HOST"] = LANGFUSE_BASE_URL

# ==================== DeepSeek 评估模型配置 ====================
DEEPSEEK_API_KEY = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
DEEPSEEK_MODEL = (os.getenv("DEEPSEEK_MODEL") or "deepseek-flash").strip()

SCRIPT_DIR = Path(__file__).resolve().parent
AGENT_FILE = SCRIPT_DIR / "1-Hybrid Agent-教培机构咨询规划助手.py"
DATASET_NAME = "education-advisor-deepeval-dataset"

# ==================== 导入教培助手 ====================
if not AGENT_FILE.exists():
    raise FileNotFoundError(f"未找到教培助手脚本: {AGENT_FILE}")

spec = importlib.util.spec_from_file_location(
    "hybrid_education_advisor",
    str(AGENT_FILE),
)
hybrid_module = importlib.util.module_from_spec(spec)
sys.modules["hybrid_education_advisor"] = hybrid_module
spec.loader.exec_module(hybrid_module)

from hybrid_education_advisor import (  # noqa: E402
    run_education_advisor,
    SAMPLE_STUDENT_PROFILES,
    query_course_schedule,
    query_course_content,
)

# Langfuse 客户端
client = None
if LANGFUSE_ENABLED:
    client = Langfuse(
        public_key=LANGFUSE_PUBLIC_KEY,
        secret_key=LANGFUSE_SECRET_KEY,
        base_url=LANGFUSE_BASE_URL,
    )
    try:
        if client.auth_check():
            print(f"[Langfuse] 客户端已初始化，地址: {LANGFUSE_BASE_URL}")
        else:
            print("[Langfuse] 警告: auth_check 未通过，请检查密钥与 BASE_URL")
    except Exception as e:
        print(f"[Langfuse] 鉴权检查异常: {e}")

# ==================== 测试用例定义 ====================

REACTIVE_TEST_CASES = [
    {
        "user_query": "Python数据分析班多少钱，每周什么时候上课，还剩几个名额？",
        "student_id": "student1",
        "context": [
            "Python数据分析班提供价格、上课时间与剩余名额信息",
            "具体数字以资料库查询结果为准",
        ],
    },
    {
        "user_query": "大模型应用开发课的内容有哪些？",
        "student_id": "student2",
        "context": [
            "大模型应用开发班提供课程大纲与主题说明",
            "内容细节以资料库查询结果为准",
        ],
    },
    {
        "user_query": "Python入门班、Python数据分析班和大模型应用开发班有什么区别，我该先上哪个？",
        "student_id": "student1",
        "context": [
            "三门课在价格、先修条件、课时上有差异",
            "学习路径建议应结合学员基础",
        ],
    },
]

DELIBERATIVE_TEST_CASES = [
    {
        "user_query": "请结合我的学员信息，帮我规划接下来的学习路径和课程组合。",
        "student_id": "student1",
        "context": [
            "学员为零基础，目标转行，预算约10000元",
            "需要结合课程价格与先修条件给出学习路径",
        ],
    },
    {
        "user_query": "请结合我的预算和已学课程，评估下一步该怎么选课、如何衔接。",
        "student_id": "student2",
        "context": [
            "学员已完成Python入门班，预算约18000元",
            "需评估数据分析班与大模型班的衔接、预算与可行性",
        ],
    },
    {
        "user_query": "请结合我的情况，评估机器学习项目班和AI智能体实战班，并给出学习节奏建议。",
        "student_id": "student3",
        "context": [
            "学员已完成Python入门班与Python数据分析班，大模型应用开发班进行中，预算约10000元",
            "需结合预算与在学情况安排机器学习与智能体节奏",
        ],
    },
]

ALL_TEST_CASES = REACTIVE_TEST_CASES + DELIBERATIVE_TEST_CASES

# 延迟初始化，避免无密钥时导入即失败
_EVAL_MODEL: Optional[DeepSeekModel] = None


def get_eval_model() -> DeepSeekModel:
    """构建 DeepEval 评估用 DeepSeek 模型。"""
    global _EVAL_MODEL
    if _EVAL_MODEL is not None:
        return _EVAL_MODEL
    if not DEEPSEEK_API_KEY:
        raise ValueError("未设置 DEEPSEEK_API_KEY")
    _EVAL_MODEL = DeepSeekModel(
        model=DEEPSEEK_MODEL,
        api_key=DEEPSEEK_API_KEY,
        temperature=0,
    )
    return _EVAL_MODEL


# ==================== 辅助函数 ====================

def build_student_context(student_id: str) -> List[str]:
    """把学员画像转成评估上下文片段"""
    profile = SAMPLE_STUDENT_PROFILES.get(student_id, {})
    courses = profile.get("current_courses") or {}
    if courses:
        course_desc = "；".join(f"{k}（{v}）" for k, v in courses.items())
    else:
        course_desc = "尚未学习任何课程"
    return [
        f"学员基础: {profile.get('current_level', '未知')}",
        f"学习目标: {profile.get('learning_goal', '未知')}",
        f"预算: {profile.get('budget', '未知')}元",
        f"在学情况: {course_desc}",
    ]


def _get_item_input(item: Any) -> Dict[str, Any]:
    """从 experiment item / DatasetItem / 字典中安全取出 input"""
    try:
        if hasattr(item, "input") and item.input is not None:
            value = item.input
            return value if isinstance(value, dict) else {"raw": value}
        if isinstance(item, dict):
            if "input" in item:
                value = item["input"]
                return value if isinstance(value, dict) else {"raw": value}
            if "inputs" in item:
                value = item["inputs"]
                return value if isinstance(value, dict) else {"raw": value}
            if "user_query" in item:
                return item
    except Exception:
        pass
    return {}


def _normalize_input(raw_input: Any) -> Dict[str, Any]:
    if isinstance(raw_input, dict):
        return raw_input
    return {}


def _augment_context_from_kb(user_query: str, base_ctx: List[str]) -> List[str]:
    """
    用资料库工具原文扩充评判上下文。
    避免助手正确引用班次/名额/大纲时，因用例 context 过短被误判为编造。
    """
    ctx = list(base_ctx)
    q = (user_query or "").strip()
    if not q:
        return ctx
    try:
        seats_text = query_course_schedule(q)
        if seats_text:
            ctx.append("【资料库班次与名额原文】\n" + seats_text[:6000])
    except Exception as e:
        ctx.append(f"【资料库班次查询失败】{e}")
    # 内容/区别类问题再补大纲
    content_keys = ("内容", "大纲", "学什么", "区别", "先上", "主题")
    if any(k in q for k in content_keys):
        try:
            content_text = query_course_content(q)
            if content_text:
                ctx.append("【资料库课程内容原文】\n" + content_text[:6000])
        except Exception as e:
            ctx.append(f"【资料库内容查询失败】{e}")
    return ctx


def build_llm_test_case(input_data: Dict[str, Any], output: Any) -> LLMTestCase:
    """把 Langfuse 用例输出转成 DeepEval LLMTestCase"""
    user_query = input_data.get("user_query") or input_data.get("input") or ""
    student_id = input_data.get("student_id", "student1") or "student1"
    base_ctx = list(input_data.get("context") or [])
    ctx = base_ctx + build_student_context(student_id)
    ctx = _augment_context_from_kb(str(user_query), ctx)

    actual_output = ""
    if isinstance(output, dict):
        actual_output = output.get("final_response") or ""
    elif isinstance(output, str):
        actual_output = output

    return LLMTestCase(
        input=user_query,
        actual_output=actual_output or "",
        context=ctx,
        retrieval_context=ctx,
    )


def _score_from_metric(metric_name: str, metric: Any) -> Evaluation:
    """把 DeepEval metric 结果转成 Langfuse Evaluation"""
    score = getattr(metric, "score", None)
    reason = getattr(metric, "reason", "") or ""
    success = None
    try:
        success = metric.is_successful()
    except Exception:
        pass
    comment = reason
    if success is not None:
        comment = f"success={success}; {reason}".strip("; ")
    value = float(score) if score is not None else 0.0
    return Evaluation(name=metric_name, value=value, comment=comment[:2000])


# ==================== Langfuse 数据集 ====================

def create_test_dataset(dataset_name: str = DATASET_NAME) -> Optional[str]:
    """创建或复用 Langfuse DeepEval 测试数据集"""
    if not client:
        print("错误: Langfuse 客户端未初始化")
        return None

    try:
        try:
            dataset = client.get_dataset(dataset_name)
            item_count = len(getattr(dataset, "items", []) or [])
            print(f"[Langfuse] 数据集已存在: {dataset_name}")
            print(f"  现有测试用例数量: {item_count}")
            if item_count > 0:
                return dataset_name
            print("  数据集为空，将添加测试用例...")
        except Exception:
            print("[Langfuse] 数据集不存在，正在创建...")
            client.create_dataset(
                name=dataset_name,
                description="教培助手 DeepEval 评估数据集（相关性/幻觉/学员匹配/课程事实）",
                metadata={"source": "3-deepeval_education_advisor.py", "evaluator": "deepeval"},
            )
            print(f"[Langfuse] 数据集已创建: {dataset_name}")

        print("[Langfuse] 正在添加测试用例...")
        added_count = 0
        n_reactive = len(REACTIVE_TEST_CASES)
        for i, case in enumerate(ALL_TEST_CASES):
            item_id = f"deepeval-edu-case-{i + 1:02d}"
            case_type = "reactive" if i < n_reactive else "deliberative"
            payload = {
                "user_query": case["user_query"],
                "student_id": case["student_id"],
                "context": case["context"],
            }
            try:
                client.create_dataset_item(
                    dataset_name=dataset_name,
                    id=item_id,
                    input=payload,
                    expected_output={"context": case["context"]},
                    metadata={
                        "case_index": i + 1,
                        "case_type": case_type,
                        "evaluator": "deepeval",
                    },
                )
                added_count += 1
            except Exception as e:
                error_msg = str(e).lower()
                if "already exists" in error_msg or "duplicate" in error_msg:
                    continue
                print(f"  警告: 添加测试用例 {i + 1} 失败: {e}")

        dataset = client.get_dataset(dataset_name)
        item_count = len(getattr(dataset, "items", []) or [])
        print(f"[Langfuse] 测试数据集准备完成: {dataset_name}")
        print(f"  总测试用例数量: {item_count}")
        if added_count > 0:
            print(f"  本次新增: {added_count} 个测试用例")
        return dataset_name
    except Exception as e:
        print(f"创建测试数据集失败: {e}")
        import traceback
        traceback.print_exc()
        return None


# ==================== Experiment 任务与 DeepEval 评估器 ====================

# 每题耗时统计：助手推理 + DeepEval 打分
_CASE_TIMINGS: List[Dict[str, Any]] = []
_CASE_TIMING_INDEX: Dict[str, int] = {}
_EXPERIMENT_WALL_SECONDS: float = 0.0


def _reset_timing_stats() -> None:
    """清空本轮 Experiment 的耗时记录。"""
    global _CASE_TIMINGS, _CASE_TIMING_INDEX, _EXPERIMENT_WALL_SECONDS
    _CASE_TIMINGS = []
    _CASE_TIMING_INDEX = {}
    _EXPERIMENT_WALL_SECONDS = 0.0


def _timing_key_from_input(raw_input: Any) -> str:
    data = _normalize_input(raw_input)
    return str(data.get("user_query") or data.get("input") or raw_input or "")


def _ensure_case_timing(user_query: str, student_id: str = "") -> Dict[str, Any]:
    """按问题拿到或创建一条耗时记录。"""
    key = str(user_query or "")
    if key in _CASE_TIMING_INDEX:
        return _CASE_TIMINGS[_CASE_TIMING_INDEX[key]]
    record = {
        "index": len(_CASE_TIMINGS) + 1,
        "user_query": key,
        "student_id": student_id or "",
        "task_seconds": 0.0,
        "eval_seconds": 0.0,
    }
    _CASE_TIMING_INDEX[key] = len(_CASE_TIMINGS)
    _CASE_TIMINGS.append(record)
    return record


def _wrap_evaluator_with_timing(evaluator_fn: Callable) -> Callable:
    """包装评估器，累计该题的 DeepEval 打分耗时。"""

    def timed_evaluator(
        *,
        input: Any = None,
        output: Any = None,
        expected_output: Any = None,
        metadata: Any = None,
        **kwargs,
    ) -> Evaluation:
        key = _timing_key_from_input(input)
        record = _ensure_case_timing(key)
        t0 = time.perf_counter()
        result = evaluator_fn(
            input=input,
            output=output,
            expected_output=expected_output,
            metadata=metadata,
            **kwargs,
        )
        record["eval_seconds"] += time.perf_counter() - t0
        return result

    timed_evaluator.__name__ = getattr(evaluator_fn, "__name__", "timed_evaluator")
    return timed_evaluator


def _print_timing_stats() -> None:
    """打印每题耗时与总评估时间。"""
    print()
    print("=" * 60)
    print("评估耗时统计")
    print("=" * 60)
    if not _CASE_TIMINGS:
        print("（本轮无逐题耗时记录）")
        print(f"Experiment 墙钟总时间: {_EXPERIMENT_WALL_SECONDS:.2f} 秒")
        return

    sum_task = 0.0
    sum_eval = 0.0
    for rec in _CASE_TIMINGS:
        task_s = float(rec.get("task_seconds") or 0.0)
        eval_s = float(rec.get("eval_seconds") or 0.0)
        case_s = task_s + eval_s
        sum_task += task_s
        sum_eval += eval_s
        q = str(rec.get("user_query") or "")
        q_show = q if len(q) <= 40 else q[:40] + "..."
        sid = rec.get("student_id") or "-"
        print(
            f"  用例{rec.get('index')}: {case_s:.2f}s "
            f"(助手 {task_s:.2f}s + 打分 {eval_s:.2f}s) | {sid} | {q_show}"
        )

    sum_case = sum_task + sum_eval
    print("-" * 60)
    print(f"  各题合计（助手+打分）: {sum_case:.2f} 秒")
    print(f"    其中助手推理合计: {sum_task:.2f} 秒")
    print(f"    其中 DeepEval 打分合计: {sum_eval:.2f} 秒")
    print(f"  Experiment 墙钟总时间: {_EXPERIMENT_WALL_SECONDS:.2f} 秒")
    print("=" * 60)


def _run_advisor_task(*, item, **kwargs) -> Dict[str, Any]:
    """Experiment 任务：调用教培助手（并记录该题助手耗时）"""
    try:
        example_inputs = _get_item_input(item)
        user_query = example_inputs.get("user_query", "")
        student_id = example_inputs.get("student_id", "student1") or "student1"

        if not user_query or not str(user_query).strip():
            return {
                "error": "用户查询为空",
                "final_response": "用户查询为空，无法处理",
                "processing_mode": "unknown",
                "query_type": "unknown",
            }

        print(f"[任务] {str(user_query)[:50]}...")
        record = _ensure_case_timing(str(user_query), student_id=student_id)
        t0 = time.perf_counter()
        result = run_education_advisor(user_query=user_query, student_id=student_id)
        record["task_seconds"] += time.perf_counter() - t0
        print(
            f"[耗时] 用例{record['index']} 助手推理 "
            f"{record['task_seconds']:.2f}s | {str(user_query)[:40]}..."
        )
        return {
            "final_response": result.get("final_response", ""),
            "processing_mode": result.get("processing_mode", "unknown"),
            "query_type": result.get("query_type", "unknown"),
            "error": result.get("error"),
            "student_id": student_id,
        }
    except Exception as e:
        return {
            "error": str(e),
            "final_response": f"执行错误: {str(e)}",
            "processing_mode": "unknown",
            "query_type": "unknown",
        }


def answer_relevancy_evaluator(
    *,
    input: Any = None,
    output: Any = None,
    expected_output: Any = None,
    metadata: Any = None,
    **kwargs,
) -> Evaluation:
    """DeepEval AnswerRelevancy → Langfuse Score"""
    try:
        model = get_eval_model()
        tc = build_llm_test_case(_normalize_input(input), output)
        metric = AnswerRelevancyMetric(
            threshold=0.6,
            model=model,
            include_reason=True,
            async_mode=False,
        )
        metric.measure(tc)
        return _score_from_metric("AnswerRelevancy", metric)
    except Exception as e:
        return Evaluation(name="AnswerRelevancy", value=0.0, comment=f"评估失败: {e}")


def hallucination_evaluator(
    *,
    input: Any = None,
    output: Any = None,
    expected_output: Any = None,
    metadata: Any = None,
    **kwargs,
) -> Evaluation:
    """DeepEval Hallucination → Langfuse Score（分越高幻觉越多）"""
    try:
        model = get_eval_model()
        tc = build_llm_test_case(_normalize_input(input), output)
        metric = HallucinationMetric(
            threshold=0.5,
            model=model,
            include_reason=True,
            async_mode=False,
        )
        metric.measure(tc)
        return _score_from_metric("Hallucination", metric)
    except Exception as e:
        return Evaluation(name="Hallucination", value=0.0, comment=f"评估失败: {e}")


def student_fit_evaluator(
    *,
    input: Any = None,
    output: Any = None,
    expected_output: Any = None,
    metadata: Any = None,
    **kwargs,
) -> Evaluation:
    """DeepEval GEval StudentFit → Langfuse Score"""
    try:
        model = get_eval_model()
        tc = build_llm_test_case(_normalize_input(input), output)
        metric = GEval(
            name="StudentFitConsideration",
            criteria=(
                "评估课程建议是否结合了学员的已学课程、学习目标与预算约束，"
                "且不承诺就业或收入结果；不以周学时或长短期标签为必要依据"
            ),
            evaluation_params=[
                LLMTestCaseParams.INPUT,
                LLMTestCaseParams.ACTUAL_OUTPUT,
            ],
            evaluation_steps=[
                "检查回答是否考虑学员学籍（零基础/已完成入门等）与学习目标",
                "检查是否结合预算约束核算课程组合（如适用）",
                "判断建议是否个性化，而非空泛推销",
                "确认没有承诺就业、考证通过或收入结果",
            ],
            threshold=0.5,
            model=model,
            async_mode=False,
        )
        metric.measure(tc)
        return _score_from_metric("StudentFitConsideration", metric)
    except Exception as e:
        return Evaluation(name="StudentFitConsideration", value=0.0, comment=f"评估失败: {e}")


def course_fact_evaluator(
    *,
    input: Any = None,
    output: Any = None,
    expected_output: Any = None,
    metadata: Any = None,
    **kwargs,
) -> Evaluation:
    """DeepEval GEval CourseFact → Langfuse Score"""
    try:
        model = get_eval_model()
        tc = build_llm_test_case(_normalize_input(input), output)
        metric = GEval(
            name="CourseFactGrounding",
            criteria=(
                "宽松评估：回答中的课程事实是否大体合理、无明显胡编。"
                "用例 context 只是简要提示，回答可包含更细的价格/时间/名额/大纲，"
                "只要与检索上下文（含资料库原文）不矛盾即可给高分。"
                "仅当出现明显矛盾，或编造完全不存在的课程时才大幅扣分。"
            ),
            evaluation_params=[
                LLMTestCaseParams.INPUT,
                LLMTestCaseParams.ACTUAL_OUTPUT,
                LLMTestCaseParams.RETRIEVAL_CONTEXT,
            ],
            evaluation_steps=[
                "用例 context 可能很短，不要要求回答只能复述这些短句",
                "若检索上下文含资料库原文，以原文为准核对关键事实",
                "细节比用例摘要更丰富但能在资料库原文中找到依据时，视为正确，不扣分",
                "仅惩罚：与上下文明显矛盾，或编造完全不存在的课程/离谱价格",
            ],
            threshold=0.5,
            model=model,
            async_mode=False,
        )
        metric.measure(tc)
        return _score_from_metric("CourseFactGrounding", metric)
    except Exception as e:
        return Evaluation(name="CourseFactGrounding", value=0.0, comment=f"评估失败: {e}")


def run_langfuse_experiment(
    dataset_name: str,
    experiment_name: Optional[str] = None,
) -> Any:
    """在 Langfuse 数据集上跑 Experiment，评估器用 DeepEval 指标"""
    if not client:
        print("错误: Langfuse 客户端未初始化")
        return None

    if not experiment_name:
        experiment_name = f"deepeval-edu-eval-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    base_evaluators = [
        answer_relevancy_evaluator,
        hallucination_evaluator,
        student_fit_evaluator,
        course_fact_evaluator,
    ]
    evaluators = [_wrap_evaluator_with_timing(fn) for fn in base_evaluators]

    try:
        dataset = client.get_dataset(dataset_name)
        item_count = len(getattr(dataset, "items", []) or [])
        print("[Langfuse] 开始 DeepEval Experiment...")
        print(f"  实验名称: {experiment_name}")
        print(f"  数据集: {dataset_name}")
        print(f"  测试用例数量: {item_count}")
        print(f"  评估器: {[getattr(e, '__name__', str(e)) for e in evaluators]}")
        print(f"  评判模型: {DEEPSEEK_MODEL}")
        print()

        _reset_timing_stats()
        wall_t0 = time.perf_counter()
        if hasattr(dataset, "run_experiment"):
            results = dataset.run_experiment(
                name=experiment_name,
                description="教培助手 DeepEval 指标评估（Langfuse Experiments）",
                task=_run_advisor_task,
                evaluators=evaluators,
                max_concurrency=1,
            )
        else:
            results = client.run_experiment(
                name=experiment_name,
                description="教培助手 DeepEval 指标评估（Langfuse Experiments）",
                data=list(getattr(dataset, "items", []) or []),
                task=_run_advisor_task,
                evaluators=evaluators,
                max_concurrency=1,
            )
        global _EXPERIMENT_WALL_SECONDS
        _EXPERIMENT_WALL_SECONDS = time.perf_counter() - wall_t0

        client.flush()
        print()
        print("[Langfuse] Experiment 完成")
        _print_timing_stats()
        return results
    except Exception as e:
        print(f"运行 Experiment 失败: {e}")
        import traceback
        traceback.print_exc()
        if client:
            client.flush()
        return None


def _print_experiment_summary(results: Any, experiment_name: str, dataset_name: str) -> None:
    print()
    print("=" * 60)
    print("评估完成")
    print("=" * 60)
    print(f"实验名称: {experiment_name}")
    print(f"数据集: {dataset_name}")
    print(f"查看地址: {LANGFUSE_BASE_URL}")
    if _EXPERIMENT_WALL_SECONDS > 0:
        print(f"Experiment 墙钟总时间: {_EXPERIMENT_WALL_SECONDS:.2f} 秒")
    print()
    if results is not None and hasattr(results, "format"):
        try:
            print("评估结果摘要:")
            print(results.format())
            print()
        except Exception as e:
            print(f"格式化结果时出错（可忽略，请到 UI 查看）: {e}")
            print()
    print("在 Langfuse 界面中:")
    print(f"  1. Datasets → {dataset_name}")
    print(f"  2. Experiments / Runs → {experiment_name}")
    print("  3. 查看 Scores: AnswerRelevancy / Hallucination / StudentFitConsideration / CourseFactGrounding")


# ==================== 入口 ====================

if __name__ == "__main__":
    print("=" * 60)
    print("DeepEval + Langfuse 教培助手评估")
    print("=" * 60)
    print(f"助手脚本: {AGENT_FILE.name}")
    print()

    if not LANGFUSE_ENABLED or not client:
        print("[错误] 请设置 Langfuse 环境变量:")
        print("  LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_BASE_URL")
        exit(1)

    if not DEEPSEEK_API_KEY:
        print("[错误] 请设置 DEEPSEEK_API_KEY（DeepEval 评判模型）")
        print("官网: https://platform.deepseek.com")
        exit(1)

    if not os.getenv("DASHSCOPE_API_KEY"):
        print("[错误] 请设置 DASHSCOPE_API_KEY（教培助手）")
        exit(1)

    print(f"[配置] DeepSeek 评判模型: {DEEPSEEK_MODEL}")
    print(f"[配置] Langfuse: {LANGFUSE_BASE_URL}")
    print()

    print("步骤 1: 准备 Langfuse 数据集...")
    print("-" * 60)
    created = create_test_dataset(DATASET_NAME)
    if not created:
        print("数据集准备失败")
        exit(1)

    try:
        dataset = client.get_dataset(DATASET_NAME)
        item_count = len(getattr(dataset, "items", []) or [])
        if item_count == 0:
            print("数据集为空，无法运行评估")
            exit(1)
    except Exception as e:
        print(f"无法验证数据集: {e}")
        exit(1)

    print()
    print("步骤 2: 运行 Experiment（助手推理 + DeepEval 打分）...")
    print("-" * 60)
    experiment_name = f"deepeval-edu-eval-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    print(f"实验名称: {experiment_name}")
    print(f"用例数量: {item_count}")
    print("开始运行，请耐心等待...")
    print()

    try:
        results = run_langfuse_experiment(DATASET_NAME, experiment_name)
        if results is not None:
            _print_experiment_summary(results, experiment_name, DATASET_NAME)
        else:
            print("Experiment 未返回结果，请到 Langfuse UI 查看")
            print(f"  {LANGFUSE_BASE_URL}")
    except Exception as e:
        print(f"评估失败: {e}")
        if client:
            client.flush()
        exit(1)
    finally:
        if client:
            client.flush()
