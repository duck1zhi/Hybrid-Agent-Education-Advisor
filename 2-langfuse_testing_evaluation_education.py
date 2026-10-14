#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Langfuse 测试与评估模块 - 教培机构咨询规划助手

对「1-Hybrid Agent-教培机构咨询规划助手.py」做批量评估：
1. 创建/管理测试数据集
2. 运行 Experiments
3. 评估处理模式与关键词完整性
4. 在控制台与 Langfuse UI 查看结果

使用方法（Windows PowerShell）：
  $env:LANGFUSE_PUBLIC_KEY="pk-lf-..."
  $env:LANGFUSE_SECRET_KEY="sk-lf-..."
  $env:LANGFUSE_BASE_URL="http://localhost:3000"
  $env:DASHSCOPE_API_KEY="sk-..."
  $env:DEEPSEEK_API_KEY="sk-..."
  python .\\2-langfuse_testing_evaluation_education.py

可选：
  $env:EVAL_LLM_PROVIDER="tongyi"
  $env:DEEPSEEK_MODEL="deepseek-flash"
  $env:DEEPSEEK_BASE_URL="https://api.deepseek.com"

结果：http://localhost:3000 → Datasets / Experiments
"""

import os
import sys
import importlib.util
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

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

# ==================== 评估用 LLM：默认 DeepSeek 加速 ====================
DEEPSEEK_API_KEY = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
DEEPSEEK_BASE_URL = (os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com").strip().rstrip("/")
DEEPSEEK_MODEL = (os.getenv("DEEPSEEK_MODEL") or "deepseek-flash").strip()
# deepseek（默认）| tongyi
EVAL_LLM_PROVIDER = (os.getenv("EVAL_LLM_PROVIDER") or "deepseek").strip().lower()

SCRIPT_DIR = Path(__file__).resolve().parent
AGENT_FILE = SCRIPT_DIR / "1-Hybrid Agent-教培机构咨询规划助手.py"


def _build_deepseek_llm():
    """构建 DeepSeek Chat 模型（OpenAI 兼容接口）"""
    from langchain_openai import ChatOpenAI

    if not DEEPSEEK_API_KEY:
        raise ValueError("未设置 DEEPSEEK_API_KEY，无法使用 DeepSeek 加速评估")

    return ChatOpenAI(
        model=DEEPSEEK_MODEL,
        api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL,
        temperature=0,
        timeout=60,
        max_retries=2,
    )


# 动态导入教培助手（文件名含空格与中文）
if not AGENT_FILE.exists():
    raise FileNotFoundError(f"未找到教培助手脚本: {AGENT_FILE}")

spec = importlib.util.spec_from_file_location(
    "hybrid_education_advisor",
    str(AGENT_FILE),
)
hybrid_module = importlib.util.module_from_spec(spec)
sys.modules["hybrid_education_advisor"] = hybrid_module
spec.loader.exec_module(hybrid_module)

# 仅在本评估脚本中替换智能体模块级 llm，不修改助手源文件
if EVAL_LLM_PROVIDER in ("deepseek", "ds", "deepseek-flash"):
    try:
        deepseek_llm = _build_deepseek_llm()
        hybrid_module.llm = deepseek_llm
        print(f"[评估LLM] 已切换为 DeepSeek: model={DEEPSEEK_MODEL}, base_url={DEEPSEEK_BASE_URL}")
    except Exception as e:
        print(f"[评估LLM] DeepSeek 切换失败，将继续使用原通义模型: {e}")
else:
    print("[评估LLM] 使用原脚本通义模型 (EVAL_LLM_PROVIDER=tongyi)")

from hybrid_education_advisor import run_education_advisor  # noqa: E402

# Langfuse 客户端初始化
client = None
if not LANGFUSE_ENABLED:
    print("警告: Langfuse 未启用，无法进行测试和评估")
    print("请设置环境变量:")
    print("  - LANGFUSE_PUBLIC_KEY: 项目公钥 pk-lf-...")
    print("  - LANGFUSE_SECRET_KEY: 项目私钥 sk-lf-...")
    print("  - LANGFUSE_BASE_URL: http://localhost:3000（本地默认）")
else:
    client = Langfuse(
        public_key=LANGFUSE_PUBLIC_KEY,
        secret_key=LANGFUSE_SECRET_KEY,
        base_url=LANGFUSE_BASE_URL,
    )
    auth_ok = False
    try:
        auth_ok = bool(client.auth_check())
    except Exception as e:
        print(f"[Langfuse] 鉴权检查异常: {e}")
    if auth_ok:
        print(f"[Langfuse] 客户端已初始化，地址: {LANGFUSE_BASE_URL}")
    else:
        print("[Langfuse] 警告: auth_check 未通过，请检查密钥与 BASE_URL")

# ==================== 测试数据集定义 ====================

# 反应式：班次/价格/名额/课程对比（期望走 reactive）
REACTIVE_TEST_CASES = [
    {
        "inputs": {
            "user_query": "Python数据分析班多少钱，每周什么时候上课，还剩几个名额？",
            "student_id": "student1",
        },
        "expected_outputs": {
            "processing_mode": "reactive",
            "should_contain": ["Python数据分析", "3680", "名额"],
        },
    },
    {
        "inputs": {
            "user_query": "大模型应用开发班和AI智能体实战班的价格、上课时间和剩余名额分别是多少？",
            "student_id": "student1",
        },
        "expected_outputs": {
            "processing_mode": "reactive",
            "should_contain": ["大模型应用开发", "智能体", "名额"],
        },
    },
    {
        "inputs": {
            "user_query": "Python入门班、Python数据分析班和大模型应用开发班有什么区别，我该先上哪个？",
            "student_id": "student1",
        },
        "expected_outputs": {
            "processing_mode": "reactive",
            "should_contain": ["Python入门", "数据分析", "大模型"],
        },
    },
    {
        "inputs": {
            "user_query": "大模型应用开发课的内容有哪些？",
            "student_id": "student2",
        },
        "expected_outputs": {
            "processing_mode": "reactive",
            "should_contain": ["大模型", "周"],
        },
    },
]

# 深思熟虑：个性化学习规划（期望走 deliberative）
DELIBERATIVE_TEST_CASES = [
    {
        "inputs": {
            "user_query": "请结合我的学员信息，帮我规划接下来的学习路径和课程组合。",
            "student_id": "student1",
        },
        "expected_outputs": {
            "processing_mode": "deliberative",
            "should_contain": ["Python", "计划", "预算"],
        },
    },
    {
        "inputs": {
            "user_query": "请结合我的预算和已学课程，评估下一步该怎么选课、如何衔接。",
            "student_id": "student2",
        },
        "expected_outputs": {
            "processing_mode": "deliberative",
            "should_contain": ["数据分析", "大模型", "建议"],
        },
    },
    {
        "inputs": {
            "user_query": "请结合我的情况，评估机器学习项目班和AI智能体实战班，并给出学习节奏建议。",
            "student_id": "student3",
        },
        "expected_outputs": {
            "processing_mode": "deliberative",
            "should_contain": ["机器学习", "智能体", "节奏"],
        },
    },
]

# 边界情况
EDGE_CASE_TEST_CASES = [
    {
        "inputs": {
            "user_query": "",
            "student_id": "student1",
        },
        "expected_outputs": {
            "should_handle_error": True,
        },
    },
    {
        "inputs": {
            "user_query": "这是一个非常长的课程咨询查询" * 80,
            "student_id": "student1",
        },
        "expected_outputs": {
            "should_handle": True,
        },
    },
]

ALL_TEST_CASES = REACTIVE_TEST_CASES + DELIBERATIVE_TEST_CASES + EDGE_CASE_TEST_CASES

# ==================== 辅助函数 ====================

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


def _get_expected_output(expected_output: Any) -> Dict[str, Any]:
    """规范化 expected_output 为字典"""
    if expected_output is None:
        return {}
    if isinstance(expected_output, dict):
        return expected_output
    return {}


def _as_text(value: Any) -> str:
    """把任务输出转成可检索文本"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("final_response", "")) + " " + str(value)
    return str(value)


# ==================== 评估器定义 ====================

def processing_mode_evaluator(
    *,
    input: Any = None,
    output: Any = None,
    expected_output: Any = None,
    metadata: Any = None,
    **kwargs
) -> Evaluation:
    """评估处理模式选择是否正确"""
    expected = _get_expected_output(expected_output)
    expected_mode = expected.get("processing_mode")

    if not expected_mode:
        return Evaluation(
            name="processing_mode",
            value=None,
            comment="未指定期望的处理模式",
        )

    actual_mode = None
    if isinstance(output, dict):
        actual_mode = output.get("processing_mode")

    if actual_mode == expected_mode:
        return Evaluation(
            name="processing_mode",
            value=1.0,
            comment=f"处理模式正确: {actual_mode}",
        )

    return Evaluation(
        name="processing_mode",
        value=0.0,
        comment=f"处理模式不匹配: 期望 {expected_mode}, 实际 {actual_mode}",
    )


def response_completeness_evaluator(
    *,
    input: Any = None,
    output: Any = None,
    expected_output: Any = None,
    metadata: Any = None,
    **kwargs
) -> Evaluation:
    """评估响应完整性（关键词覆盖率）"""
    expected = _get_expected_output(expected_output)
    expected_keywords = expected.get("should_contain", [])

    if not expected_keywords:
        if expected.get("should_handle_error") or expected.get("should_handle"):
            has_output = bool(output)
            return Evaluation(
                name="response_completeness",
                value=1.0 if has_output else 0.0,
                comment="边界用例：已返回结果" if has_output else "边界用例：无结果",
            )
        return Evaluation(
            name="response_completeness",
            value=None,
            comment="未指定期望的关键词",
        )

    response_text = _as_text(output).lower()
    if not response_text.strip():
        return Evaluation(
            name="response_completeness",
            value=0.0,
            comment="无响应输出",
        )

    found_keywords = [kw for kw in expected_keywords if str(kw).lower() in response_text]
    completeness = len(found_keywords) / len(expected_keywords)

    return Evaluation(
        name="response_completeness",
        value=completeness,
        comment=f"找到 {len(found_keywords)}/{len(expected_keywords)} 个期望关键词",
    )


# ==================== 测试运行函数 ====================

def create_test_dataset(dataset_name: str = "education-advisor-test-dataset") -> Optional[str]:
    """创建或复用 Langfuse 测试数据集，并写入用例"""
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
                description="教培咨询规划助手测试数据集：反应式查课、深思熟虑规划、边界情况",
                metadata={"source": "2-langfuse_testing_evaluation_education.py"},
            )
            print(f"[Langfuse] 数据集已创建: {dataset_name}")

        print("[Langfuse] 正在添加测试用例...")
        added_count = 0
        n_reactive = len(REACTIVE_TEST_CASES)
        n_delib = len(DELIBERATIVE_TEST_CASES)
        for i, test_case in enumerate(ALL_TEST_CASES):
            item_id = f"education-advisor-case-{i + 1:02d}"
            if i < n_reactive:
                case_type = "reactive"
            elif i < n_reactive + n_delib:
                case_type = "deliberative"
            else:
                case_type = "edge"
            try:
                client.create_dataset_item(
                    dataset_name=dataset_name,
                    id=item_id,
                    input=test_case["inputs"],
                    expected_output=test_case.get("expected_outputs", {}),
                    metadata={
                        "case_index": i + 1,
                        "case_type": case_type,
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


def _run_advisor_task(*, item, **kwargs) -> Dict[str, Any]:
    """Experiment 任务函数：对单条用例调用教培咨询智能体"""
    try:
        example_inputs = _get_item_input(item)
        user_query = example_inputs.get("user_query", "")
        student_id = example_inputs.get("student_id", "student1") or "student1"

        if not user_query or (isinstance(user_query, str) and not user_query.strip()):
            return {
                "error": "用户查询为空",
                "final_response": "用户查询为空，无法处理",
                "processing_mode": "unknown",
                "query_type": "unknown",
            }

        result = run_education_advisor(
            user_query=user_query,
            student_id=student_id,
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


def run_evaluation(
    dataset_name: str,
    experiment_name: Optional[str] = None,
    evaluators: Optional[List] = None,
) -> Any:
    """在 Langfuse 数据集上运行评估实验"""
    if not client:
        print("错误: Langfuse 客户端未初始化")
        return None

    if not experiment_name:
        experiment_name = f"education-advisor-eval-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    if not evaluators:
        evaluators = [
            processing_mode_evaluator,
            response_completeness_evaluator,
        ]

    try:
        dataset = client.get_dataset(dataset_name)
        item_count = len(getattr(dataset, "items", []) or [])
        print("[Langfuse] 开始评估...")
        print(f"  实验名称: {experiment_name}")
        print(f"  数据集: {dataset_name}")
        print(f"  测试用例数量: {item_count}")
        print(f"  评估器数量: {len(evaluators)}")
        print()

        if hasattr(dataset, "run_experiment"):
            results = dataset.run_experiment(
                name=experiment_name,
                description="教培咨询规划助手 Langfuse 批量评估",
                task=_run_advisor_task,
                evaluators=evaluators,
                max_concurrency=1,
            )
        else:
            results = client.run_experiment(
                name=experiment_name,
                description="教培咨询规划助手 Langfuse 批量评估",
                data=list(getattr(dataset, "items", []) or []),
                task=_run_advisor_task,
                evaluators=evaluators,
                max_concurrency=1,
            )

        client.flush()
        print()
        print("[Langfuse] 评估完成")
        return results
    except Exception as e:
        print(f"运行评估失败: {e}")
        import traceback
        traceback.print_exc()
        if client:
            client.flush()
        return None


def _print_experiment_summary(results: Any, experiment_name: str, dataset_name: str) -> None:
    """打印实验摘要"""
    print()
    print("=" * 60)
    print("评估完成")
    print("=" * 60)
    print()
    print(f"实验名称: {experiment_name}")
    print(f"数据集: {dataset_name}")
    print(f"查看地址: {LANGFUSE_BASE_URL}")
    print()

    if results is not None and hasattr(results, "format"):
        try:
            formatted = results.format()
            print("评估结果摘要:")
            print(formatted)
            print()
        except Exception as e:
            print(f"格式化结果时出错（可忽略，请到 UI 查看）: {e}")
            print()

    print("在 Langfuse 界面中:")
    print("  1. 打开 Datasets，进入数据集:", dataset_name)
    print("  2. 查看 Experiments / Runs，查找:", experiment_name)
    print("  3. 查看每条用例的 Trace、Score（processing_mode / response_completeness）")


# ==================== 主函数 ====================

if __name__ == "__main__":
    print("=" * 60)
    print("Langfuse 测试与评估工具 - 教培机构咨询规划助手")
    print("=" * 60)
    print()
    print(f"助手脚本: {AGENT_FILE.name}")
    print()

    if not LANGFUSE_ENABLED or not client:
        print("错误: Langfuse 未启用，无法进行测试和评估")
        print()
        print("请设置环境变量:")
        print("  - LANGFUSE_PUBLIC_KEY: 项目公钥 pk-lf-...")
        print("  - LANGFUSE_SECRET_KEY: 项目私钥 sk-lf-...")
        print("  - LANGFUSE_BASE_URL: http://localhost:3000")
        exit(1)

    if EVAL_LLM_PROVIDER in ("deepseek", "ds", "deepseek-flash") and not DEEPSEEK_API_KEY:
        print("错误: 评估默认使用 DeepSeek，但未检测到 DEEPSEEK_API_KEY")
        print("请设置 DEEPSEEK_API_KEY，或改用通义: $env:EVAL_LLM_PROVIDER=\"tongyi\"")
        exit(1)

    dataset_name = "education-advisor-test-dataset"

    print("步骤 1: 准备测试数据集...")
    print("-" * 60)
    try:
        created_dataset = create_test_dataset(dataset_name)
        if created_dataset:
            print(f"测试数据集准备完成: {dataset_name}")
        else:
            print("数据集准备失败")
            print()
            print("请检查:")
            print("  1. Langfuse 密钥是否正确")
            print("  2. LANGFUSE_BASE_URL 是否为 http://localhost:3000")
            print("  3. Langfuse 服务是否已启动（docker compose up -d）")
            exit(1)
    except Exception as e:
        print(f"数据集准备失败: {e}")
        exit(1)

    try:
        dataset = client.get_dataset(dataset_name)
        item_count = len(getattr(dataset, "items", []) or [])
        if item_count == 0:
            print("数据集为空，无法运行评估")
            exit(1)
    except Exception as e:
        print(f"无法验证数据集: {e}")
        exit(1)

    print()
    print("步骤 2: 运行测试集评估...")
    print("-" * 60)
    experiment_name = f"education-advisor-eval-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    print(f"实验名称: {experiment_name}")
    print(f"数据集: {dataset_name}")
    print(f"测试用例数量: {item_count}")
    print()
    print("开始运行评估（深思熟虑用例较慢），请耐心等待...")
    print()

    try:
        results = run_evaluation(dataset_name, experiment_name)
        if results is not None:
            _print_experiment_summary(results, experiment_name, dataset_name)
        else:
            print()
            print("评估未返回结果，请到 Langfuse UI 查看实验状态")
            print(f"  {LANGFUSE_BASE_URL}")
    except Exception as e:
        print()
        print("=" * 60)
        print(f"评估失败: {e}")
        print("=" * 60)
        print()
        print("请检查:")
        print("  1. Langfuse 密钥与 BASE_URL")
        print("  2. 数据集是否存在")
        print("  3. DASHSCOPE_API_KEY 是否可用（助手默认通义）；或 DeepSeek 密钥是否可用")
        if client:
            client.flush()
        exit(1)
    finally:
        if client:
            client.flush()
