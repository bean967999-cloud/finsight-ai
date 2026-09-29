# FinSight AI — 20 天实施计划

> 若从 2026-09-10 开始，20 个连续项目日到 2026-09-29。
> 每天基础投入 6 小时；周末建议 8~10 小时。
> 总投入约 132~144 小时。

## Sprint 1：地基与金融数据（Day 1~4）

### Day 1 — 架构冻结 + 可运行骨架
- 仓库结构
- FastAPI
- Settings
- LangGraph State/Graph 骨架
- RiskEngine v0
- SQL Guard v0
- Pytest
- Docker Postgres + Redis
- ADR：为什么模块化单体

验收：
- `/health` 成功
- risk API 成功
- Agent Graph 能 invoke
- 单测通过

### Day 2 — 金融数据模型
- companies
- securities
- market_prices
- financial_statements
- financial_indicators
- data_sources
- import_jobs
- Alembic migration
- Repository pattern
- 数据 Provider 接口

### Day 3 — Tushare / Demo Data Provider
- Provider 抽象
- Tushare API Adapter
- CSV fallback
- 数据落库
- 去重 / upsert
- data freshness
- provider error handling
- 缓存

### Day 4 — 文档与 Milvus 基础设施
- document / chunk metadata schema
- Milvus collection
- object storage abstraction
- ingestion job model
- 文档 checksum
- 幂等入库

## Sprint 2：企业级 RAG（Day 5~8）

### Day 5 — MinerU 文档解析
- PDF → Markdown
- page / section metadata
- table strategy
- parser adapter
- parser test fixtures

### Day 6 — Financial Chunker
- 标题/章节感知切分
- 表格保护
- chunk overlap
- chunk version
- 统计 chunk 分布

### Day 7 — BGE-M3 + Hybrid Retrieval
- dense
- sparse
- Milvus hybrid
- filter by company/report/year
- retrieval trace

### Day 8 — Rerank + Citation
- candidate top-k
- reranker
- final top-n
- citation contract
- evidence API
- RAG golden questions v1

## Sprint 3：结构化问数 + 金融风险（Day 9~12）

### Day 9 — Text-to-SQL
- schema context
- structured SQL plan
- SQL generation
- SQL Guard v1
- table allowlist
- row limit
- timeout
- read-only role

### Day 10 — Financial Analytics
- returns
- volatility
- max drawdown
- VaR/CVaR
- Sharpe
- beta
- correlation
- portfolio risk

### Day 11 — Evidence Fusion
- SQL evidence
- RAG evidence
- risk tool evidence
- provenance
- numeric verification

### Day 12 — Async Job + Redis
- 文档入库异步化
- 报告任务
- job status
- retry / backoff
- idempotency key

## Sprint 4：Agent、治理与评估（Day 13~16）

### Day 13 — LangGraph Research Agent
- intent
- planning
- conditional routing
- parallel tools
- retry
- safe refusal

### Day 14 — Checkpoint + Human-in-the-Loop
- persistent checkpointer
- thread_id
- interrupt
- resume
- 高风险动作审批

### Day 15 — Auth / RBAC / Audit
- user
- role
- workspace
- knowledge-base scope
- audit_event
- request_id
- sensitive operation log

### Day 16 — Eval + Observability
- golden dataset
- retrieval eval
- agent tool eval
- numeric consistency eval
- LangSmith trace
- structured log
- Prometheus metrics
- P95 latency baseline

## Sprint 5：产品化与面试交付（Day 17~20）

### Day 17 — MCP Tool Server
暴露：
- search_financial_documents
- query_financial_data
- calculate_portfolio_risk
- generate_research_brief

目标：
同一套金融能力既能服务 Web，也能被 MCP Client 使用。

### Day 18 — React 企业界面
页面：
1. 智能投研首页
2. 单次 Agent 执行轨迹
3. 文档证据
4. 风险看板
5. Eval 看板
6. Admin / Audit

### Day 19 — 部署 + CI/CD
- Docker image
- Docker Compose
- Nginx
- HTTPS
- GitHub Actions
- pytest / ruff
- startup probe
- backup
- cloud deployment

### Day 20 — 终验 + 简历 + 面试
- E2E demo
- 30~50 条 golden questions
- 架构图
- sequence diagram
- README
- API docs
- 数据字典
- 故障复盘
- 5 分钟 / 15 分钟面试讲解
- 简历 bullets
- Demo 视频脚本

# Scope Freeze

20 天内明确不做：

- 真实自动下单
- 高频交易
- 自研大模型
- 自建分布式向量数据库
- 为了简历强行拆十几个微服务
- 为了“高级”强行上 Kubernetes
- 没有评估数据的“多 Agent 炫技”

# 最终 Demo

用户问题：

> 比较招商银行与平安银行近三年的 ROE、营收和风险变化，结合年报原文给出原因；
> 再对我输入的股票组合计算 95% VaR / CVaR、最大回撤和相关性风险，
> 最后输出一份带证据的风险研究摘要。

系统应展示：

1. Agent 任务计划
2. 调用了哪些工具
3. SQL
4. 风险公式/结果
5. RAG Top-K
6. rerank 后证据
7. 最终引用
8. verifier 结果
9. trace / token / latency
10. 导出研究摘要
