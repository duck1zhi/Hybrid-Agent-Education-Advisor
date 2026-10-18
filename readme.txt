================================================================================
Hybrid Agent - 教培机构咨询规划助手及评估
项目说明与脚本逻辑（含 Streamlit 界面与报班活动资料库）
================================================================================

一、项目概述
--------------------------------------------------------------------------------
本项目实现一个「混合智能体（Hybrid Agent）」教培咨询助手，配套 Streamlit
可视化界面，以及两套基于 Langfuse 的评估脚本。核心能力：

  - 反应式：查价格、班次、名额、课程内容、排课时间、限时优惠/续报福利等
  - 深思熟虑：结合学员画像（基础、目标、预算、在学课程）做学习路径规划
  - 资料库驱动：课程与活动硬事实一律来自「资料库」Excel，禁止模型瞎编
  - 可观测：可选接入本地/自建 Langfuse，记录 Trace 与实验评分
  - 可视化：Streamlit 单问题问答界面，快捷题点击后直接生成答案

主要入口：

  1-Hybrid Agent-教培机构咨询规划助手.py
      → 主智能体（CLI 交互；也被评估脚本 / Streamlit 调用）

  app_streamlit_advisor.py
      → Streamlit 界面：输入问题 → 调用 run_education_advisor → 展示回答

  2-langfuse_testing_evaluation_education.py
      → 业务规则评估：处理模式是否正确、回答是否命中期望关键词

  3-deepeval_education_advisor.py
      → 质量评估：DeepEval 打相关性/幻觉/学员匹配/课程事实，结果回写 Langfuse


二、目录结构（与逻辑相关部分）
--------------------------------------------------------------------------------
  1-Hybrid Agent-教培机构咨询规划助手.py   主智能体
  app_streamlit_advisor.py                     Streamlit 可视化问答
  2-langfuse_testing_evaluation_education.py   Langfuse 规则评估
  3-deepeval_education_advisor.py              DeepEval + Langfuse 评估
  requirements.txt
  readme.txt
  langfuse_本地部署总结.html                   Langfuse 部署说明（文档）
  资料库/
    C01_Python入门班_*.xlsx
    C02_Python数据分析班_*.xlsx
    C04_机器学习项目班_*.xlsx
    C05_大模型应用开发班_*.xlsx
    C06_AI智能体实战班_*.xlsx
    各课程剩余名额.xlsx
    报班活动-限时优惠与续报福利说明.xlsx       限时折扣 / 续报赠课 / 打包报名

说明：部分本地 HTML 说明页（如课程路径、报班活动说明页）可能仅保留在本机，
      不纳入 GitHub 仓库；活动规则以资料库 xlsx 为准供智能体检索。


三、环境变量（共用）
--------------------------------------------------------------------------------
助手与评估均通过环境变量读取密钥，代码中不写死真实密钥。

  DASHSCOPE_API_KEY     通义（脚本1 / Streamlit 默认 LLM；脚本3 跑助手时也需要）
  LANGFUSE_PUBLIC_KEY   Langfuse 公钥 pk-lf-...
  LANGFUSE_SECRET_KEY   Langfuse 私钥 sk-lf-...
  LANGFUSE_BASE_URL     本地默认 http://localhost:3000

脚本2 / 脚本3 额外：

  DEEPSEEK_API_KEY      评估用 DeepSeek（脚本2 默认替换助手 LLM；脚本3 作评判模型）
  DEEPSEEK_MODEL        默认 deepseek-flash
  DEEPSEEK_BASE_URL     默认 https://api.deepseek.com（脚本2）
  EVAL_LLM_PROVIDER     脚本2：deepseek（默认）或 tongyi

Windows PowerShell 示例：

  $env:DASHSCOPE_API_KEY="sk-..."
  $env:LANGFUSE_PUBLIC_KEY="pk-lf-..."
  $env:LANGFUSE_SECRET_KEY="sk-lf-..."
  $env:LANGFUSE_BASE_URL="http://localhost:3000"
  $env:DEEPSEEK_API_KEY="sk-..."


================================================================================
脚本1：1-Hybrid Agent-教培机构咨询规划助手.py
================================================================================

【定位】
  面向教培场景的 Hybrid Agent。用 LangGraph 把「协调评估 → 反应式 / 深思熟虑」
  串成一条可追踪工作流；课程与活动事实全部从资料库 Excel 读取。

【依赖模型】
  默认：通义 Tongyi（qwen-turbo-latest），密钥 DASHSCOPE_API_KEY。
  可选：Langfuse CallbackHandler 上报整条执行链。

【状态 EducationAdvisorState】
  输入：user_query、student_profile
  中间：query_type、processing_mode、course_data、analysis_results
  输出：final_response、error、current_phase

【资料库工具层】
  课程元数据 COURSE_KB_META（C01/C02/C04/C05/C06）含关键词，用于匹配用户问题。
  四个对外工具：

    1) 课程班次查询 query_course_schedule
       - 汇总价格、上课时间、讲师、报名条件、开结课
       - 合并「各课程剩余名额.xlsx」中的实时名额（每日一更）

    2) 课程内容查询 query_course_content
       - 读各课「课程内容简介」xlsx：大纲、周次主题、学习产出等

    3) 排课表查询 query_course_timetable
       - 读各课「排课表」xlsx：星期、时段、期次、具体有课日期

    4) 报班活动查询 query_promo_activity
       - 读「报班活动-限时优惠与续报福利说明.xlsx」
       - 覆盖：限时 8.5 折、续报 8 折、折上折约 6.8 折、续报送三门课、
         零基础一次性打包（入门+任意进阶 / 整条路径A/B）折上折并送三门
       - 反应式路径：问折扣/续报/赠课/现价等会强制调用本工具，避免答「资料库没有」

  深思熟虑路径还会调用 assemble_deliberative_course_data：
  装配全部在售课程事实 +（若涉及优惠）报班活动事实 + 学员上下文。

【LangGraph 节点与路由】

  入口 assess（assess_query）
    - LLM + ASSESSMENT_PROMPT，输出 JSON：
        query_type: emergency | informational | analytical
        processing_mode: reactive | deliberative
    - 非法值会回落到 reactive / emergency

  分支（assess 之后）：
    processing_mode == "reactive"  → reactive
    否则                           → collect_data（深思熟虑链路）

  反应式链路：
    reactive（reactive_processing）
      1) ReAct 首轮：决定是否输出 [CALL_TOOL:工具名]
      2) 活动类问题强制补「报班活动查询」（必要时再补班次查询）
      3) 按顺序调用工具，再用 FINAL_ANSWER_PROMPT 严格依据工具原文作答
      4) 若无工具：直接用首轮回答（去掉残留 CALL_TOOL 标记）
    → respond → END

  深思熟虑链路：
    collect_data  → 查库装配 course_data（非模型编造）
    analyze       → ANALYSIS_PROMPT，结合画像 + kb_facts 做 JSON 分析
    recommend     → RECOMMENDATION_PROMPT，生成自然语言学习规划
    → respond → END

【对外入口】
  run_education_advisor(user_query, student_id="student1", student_profile=None)
    - 优先使用传入的自定义画像，否则用 SAMPLE_STUDENT_PROFILES
    - 编译工作流并 invoke；若启用 Langfuse 则挂 CallbackHandler 并 flush

【交互主程序】
  选择示例问题或自定义问题 → 选择示例学员或自定义学员画像 → 打印模式与回答。

【如何运行】
  python ".\1-Hybrid Agent-教培机构咨询规划助手.py"


================================================================================
Streamlit：app_streamlit_advisor.py
================================================================================

【定位】
  可视化单问题问答。左侧输入/快捷题，后台动态加载脚本1并调用
  run_education_advisor，主区展示处理日志、详情汇总与最终答案。

【界面要点】
  - 紫粉渐变顶栏 + 红色「生成答案」按钮（风格参考常见 RAG 控制台）
  - 快捷测试问题按「查课报价 / 限时折扣 / 学习规划」折叠
  - 点击快捷题：填入问题并自动触发生成（无需再点生成按钮）
  - 助手模块按源文件修改时间热加载；可点「重新加载助手模块」强制刷新

【如何运行】
  pip install -r requirements.txt
  $env:DASHSCOPE_API_KEY="sk-..."
  python -m streamlit run app_streamlit_advisor.py


================================================================================
脚本2：2-langfuse_testing_evaluation_education.py
================================================================================

【定位】
  对脚本1做「批量业务评估」：在 Langfuse 建数据集、跑 Experiment，
  检查「走哪条处理模式」以及「回答是否覆盖期望关键词」。

【与脚本1的关系】
  - 用 importlib 动态加载脚本1（文件名含空格与中文）
  - 默认把脚本1 的模块级 llm 替换为 DeepSeek（加速批量评估），
    不修改脚本1 源文件；设 EVAL_LLM_PROVIDER=tongyi 则保持通义
  - 每条用例调用 run_education_advisor

【测试用例构成】
  REACTIVE_TEST_CASES      反应式：价格/名额/内容/对比等，期望 processing_mode=reactive
  DELIBERATIVE_TEST_CASES  规划类：期望 processing_mode=deliberative
  EDGE_CASE_TEST_CASES     边界：空查询、超长查询
  → 合并为 ALL_TEST_CASES，写入数据集 education-advisor-test-dataset

【评估器（规则型，非 LLM 裁判）】
  1) processing_mode_evaluator
     - 比较实际 output.processing_mode 与 expected_output.processing_mode
     - 一致得 1.0，否则 0.0

  2) response_completeness_evaluator
     - 检查 final_response 是否包含 expected_outputs.should_contain 中的关键词
     - 得分 = 命中数 / 期望数
     - 边界用例改为「是否有输出」

【主流程】
  1. 校验 Langfuse（及默认 DeepSeek）环境变量
  2. create_test_dataset：创建或复用数据集并写入用例
  3. run_evaluation：
       task = _run_advisor_task（调助手）
       evaluators = 上述两个评估器
       max_concurrency=1
  4. flush，并提示在 Langfuse UI 查看 Datasets / Experiments

【如何运行】
  python .\2-langfuse_testing_evaluation_education.py

【结果查看】
  LANGFUSE_BASE_URL → Datasets → education-advisor-test-dataset
  → Experiments：Score 含 processing_mode、response_completeness


================================================================================
脚本3：3-deepeval_education_advisor.py
================================================================================

【定位】
  对脚本1做「回答质量」评估：用 DeepEval 指标打分，再通过 Langfuse Experiment
  落库展示。比脚本2更关注语义质量，而不是模式/关键词硬规则。

【与脚本1的关系】
  - 同样动态 import 脚本1
  - 助手侧仍用脚本1 默认通义（需 DASHSCOPE_API_KEY）
  - DeepSeek 仅作为 DeepEval 的评判模型（需 DEEPSEEK_API_KEY）

【测试用例】
  反应式 3 条 + 深思熟虑 3 条（ALL_TEST_CASES）
  每条含 user_query、student_id、简要 context
  数据集名：education-advisor-deepeval-dataset

【评判上下文如何构造】
  build_llm_test_case：
    - 用例自带 context
    - 拼上学员画像片段（基础/目标/预算/在学）
    - _augment_context_from_kb：用资料库工具原文扩充检索上下文
      （避免助手正确引用班次/名额/大纲时，因用例 context 过短被误判幻觉）

【四个 DeepEval → Langfuse 评估器】
  1) AnswerRelevancyMetric（AnswerRelevancy）
     - 回答与问题的相关性，threshold=0.6

  2) HallucinationMetric（Hallucination）
     - 幻觉程度，分越高幻觉越多，threshold=0.5

  3) GEval StudentFitConsideration
     - 是否结合已学课程、目标、预算；不承诺就业/收入

  4) GEval CourseFactGrounding
     - 课程事实是否与资料库/上下文大体一致，宽松打分，
       仅对明显矛盾或编造不存在课程大幅扣分

【耗时统计】
  对每题记录：助手推理耗时、各评估器耗时、Experiment 墙钟总时间，结束后打印汇总。

【主流程】
  1. 校验 Langfuse / DeepSeek / DashScope
  2. create_test_dataset 准备 DeepEval 数据集
  3. run_langfuse_experiment：
       task = _run_advisor_task
       evaluators = 四个指标（外裹计时包装）
  4. flush，提示到 Langfuse 查看 Scores

【如何运行】
  需额外安装：pip install deepeval langfuse langchain-openai
  python .\3-deepeval_education_advisor.py

【结果查看】
  Datasets → education-advisor-deepeval-dataset
  Experiments：AnswerRelevancy / Hallucination /
               StudentFitConsideration / CourseFactGrounding


================================================================================
报班活动资料库要点（报班活动-限时优惠与续报福利说明.xlsx）
================================================================================

  限时优惠活动：报班 8.5 折（含零基础报 C01）
  续报进阶：入门结业后续报 C02/C05/C04/C06 → 8 折
  折上折：限时 + 续报同时满足 → 约 6.8 折
  续报福利：只要续报进阶 → 送三门（原理课 / 录播课 / 大赛样例课）
  零基础一次性打包（同样折上折约 6.8 折 + 送三门）：
    - C01 + 任意一门进阶（C02/C04/C05/C06）
    - 整条路径 A：C01 + C02 + C04
    - 整条路径 B：C01 + C05 + C06
  费用参考见该表「费用参考」「打包报名费用」等工作表。


================================================================================
关系小结
================================================================================

                    ┌─────────────────────────────────┐
                    │ 脚本1  Hybrid Agent 主智能体      │
                    │  LangGraph + 资料库工具 + 通义    │
                    └───────────────┬─────────────────┘
                                    │ run_education_advisor()
          ┌─────────────────────────┼─────────────────────────┐
          ▼                         ▼                         ▼
  ┌─────────────────┐    ┌───────────────────┐    ┌───────────────────┐
  │ Streamlit 界面   │    │ 脚本2 规则评估     │    │ 脚本3 DeepEval    │
  │ 单问题可视化问答 │    │ 模式 / 关键词      │    │ 相关性/幻觉等     │
  └─────────────────┘    └───────────────────┘    └───────────────────┘
                                    │
                                    ▼
                         本地 Langfuse（Datasets / Experiments / Traces）


建议使用顺序：
  1) 先跑脚本1 或 Streamlit，确认查课与限时折扣命中资料库
  2) 再跑脚本2，检查协调层是否选对 reactive / deliberative
  3) 最后跑脚本3，看回答质量与幻觉等细粒度分数


================================================================================
依赖安装
================================================================================
  pip install -r requirements.txt
  （含 streamlit；用于 app_streamlit_advisor.py）

脚本3 额外：
  pip install deepeval langfuse langchain-openai

（Langfuse 本地部署可参考同目录「langfuse_本地部署总结.html」）

GitHub：
  https://github.com/zhiji0925/Hybrid-Agent-Education-Advisor

================================================================================
文件结束
================================================================================
