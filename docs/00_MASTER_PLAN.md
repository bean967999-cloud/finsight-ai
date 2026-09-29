# 00_企业级金融投研与风险决策智能平台_20天总纲

## 一、这次项目重新定位

项目名称：

# FinSight AI
## 企业级金融投研与风险决策智能平台
### Enterprise Financial Research & Risk Intelligence Copilot

这次不再做三个彼此割裂的“小型 AI 项目”。

原来的三个方向仍然有价值：

- 金融智能数据分析 Agent：提供 Text-to-SQL、数据库、安全、日志基础。
- 金融知识库 RAG Agent：提供文档解析、Embedding、Milvus、检索与引用基础。
- 数据分析 / 机器学习 Agent：提醒我们必须把“数学和数据能力”真正做进业务。

但是新的旗舰项目会把它们重新组合成一个企业业务闭环：

> **金融数据 + 金融文档 + 量化风险 + Agentic Workflow + Evidence + Governance + Evaluation**

---

## 二、为什么这个项目更适合我的金融数学背景

如果只做 RAG，我和计算机专业同学相比没有明显专业差异。

如果只做传统量化，又体现不出我正在转向 AI 应用开发。

这个项目的核心差异化是：

### AI 应用工程
- FastAPI
- LangGraph
- Tool Calling
- Structured Output
- MCP
- RAG
- Text-to-SQL

### 数据工程
- PostgreSQL
- 金融行情/财务数据
- 数据 Provider
- 数据缓存
- 元数据
- 幂等入库

### 金融数学
- 收益率
- 年化波动率
- 最大回撤
- VaR
- CVaR / Expected Shortfall
- Sharpe
- Beta
- 相关系数
- 组合风险

### 企业工程
- RBAC
- Audit
- SQL 安全
- Human-in-the-Loop
- Eval
- Observability
- Docker
- CI/CD

这样我在面试时可以把自己定位成：

> “我不是只会调用大模型 API。我能把 LLM 放进真实金融系统，让它连接文档、数据库和确定性风险模型，并对每一步做安全、评估和审计。”

---

## 三、2026 年技术判断

这次不会追“最花哨”的词，而是选已经形成工程价值的方向。

### 1. Agentic Workflow
Agent 不再只是 ReAct 循环。

企业场景真正需要：
- State
- checkpoint
- retry
- interrupt
- resume
- human approval
- tool audit

所以采用 LangGraph。

### 2. MCP
把金融能力做成标准 Tool Server。

最终：
- Web 前端可以调用
- LangGraph 可以调用
- 支持 MCP 的外部 AI Client 也可以调用

### 3. Hybrid RAG
不只 dense vector。

采用：
- BGE-M3 dense
- BGE-M3 sparse / BM25
- Milvus Hybrid Search
- RRF / Weighted fusion
- reranker

### 4. Evidence-first
金融回答不能只“听起来合理”。

最终答案必须能追到：
- SQL 数据
- 风险计算结果
- 财报页码/章节
- 来源
- 时间

### 5. Evals + Observability
企业 AI 项目没有评估，就无法证明升级是否有效。

项目会建立：
- RAG eval
- Agent tool eval
- 数值一致性 eval
- latency / token / error metrics

---

## 四、最终业务场景

核心用户：

- 券商/基金投研人员
- 银行研究人员
- 风险管理人员
- FinTech 分析团队

### 场景 A：上市公司研究

用户：

> 比较招商银行和平安银行近三年的 ROE、营收、净利润变化，并结合年报解释主要原因。

系统：

1. Agent 判断需要结构化数据 + 年报。
2. SQL Tool 查财务指标。
3. RAG Tool 查年报。
4. Evidence Fusion 对齐年份、公司和指标。
5. Verifier 检查数字。
6. 返回结论 + 引用。

### 场景 B：组合风险

用户：

> 这个 5 只股票的组合最近一年风险怎么样？

系统：

1. 拉取价格。
2. RiskEngine 计算。
3. 输出 VaR / CVaR / 回撤 / 波动率 / 相关性。
4. RAG 检索相关风险披露。
5. Agent 解释风险来源。

### 场景 C：监管/公告影响

用户：

> 某监管政策对银行资产质量或资本充足率可能有什么影响？

系统：

1. RAG 检索监管文档。
2. 查相关财务指标。
3. 输出证据化分析。
4. 证据不足时拒绝强行下结论。

---

## 五、系统总架构

```text
React + TypeScript + ECharts
            |
         FastAPI
            |
        LangGraph
            |
   +--------+---------+
   |        |         |
 RAG      SQL      RiskEngine
   |        |         |
Milvus  PostgreSQL   NumPy
   |
BGE-M3
Dense + Sparse
   |
Rerank
            |
       Evidence Layer
            |
   Citation / Numeric Verify
            |
     Structured Answer
```

外围：

```text
JWT / RBAC
Audit Log
Redis
Async Worker
LangSmith / OpenTelemetry
Prometheus
Docker / Nginx
MCP Server
```

---

## 六、最重要的设计原则

### 原则 1：LLM 是编排者，不是计算器

VaR、CVaR、回撤、波动率等全部由 Python 确定性函数计算。

### 原则 2：LLM 不能直接执行 SQL

完整链路：

```text
User
→ LLM SQL Plan
→ SQL
→ sqlglot AST
→ table allowlist
→ readonly DB account
→ timeout
→ limit
→ audit
→ result
```

### 原则 3：所有结论尽可能绑定 Evidence

回答不是：

> “我认为风险上升。”

而是：

> “风险上升，依据 A：近 60 日波动率从 X 升至 Y；依据 B：年报第 N 页披露……。”

### 原则 4：不做没有价值的多 Agent

只有当“角色边界和失败隔离”真的需要时才拆 Agent。

20 天版本优先：
- 一个 Orchestrator
- 多个 Tool
- 明确 Graph

---

## 七、20 天完成量

若从 2026-09-10 开始：

- 结束：2026-09-29
- 普通日：6 小时
- 周末：8~10 小时
- 预计总投入：132~144 小时

阶段：

1. Day 1~4：工程地基 + 金融数据
2. Day 5~8：企业级 RAG
3. Day 9~12：Text-to-SQL + Risk Engine
4. Day 13~16：Agent + 安全 + Eval
5. Day 17~20：MCP + 前端 + 部署 + 面试

详细见项目中的 `docs/20_DAY_PLAN.md`。

---

## 八、Day 1 已经开始，而不是只做 PPT

本次已生成 v0.1 工程骨架。

已经有：

- FastAPI 应用
- `/health`
- `/api/v1/risk/analyze`
- `/api/v1/agent/query`
- `ResearchState`
- LangGraph Graph
- RiskEngine
- SQLGuard
- Pytest
- Docker Postgres
- Redis
- README
- Architecture
- 20 Day Plan
- ADR

### 现在的 Graph

```text
START
  ↓
classify_intent
  ↓
risk? ---------------- no
 ↓                      ↓
calculate_risk        synthesize
 ↓                      ↓
synthesize ------------+
  ↓
 END
```

后续逐步扩展为真正研究 Graph。

---

## 九、项目目录

```text
finsight-ai/
├── src/finsight/
│   ├── api/
│   ├── agents/
│   ├── core/
│   ├── domain/
│   ├── security/
│   ├── services/
│   └── main.py
├── tests/
├── docs/
│   ├── ARCHITECTURE.md
│   ├── 20_DAY_PLAN.md
│   └── adr/
├── scripts/
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
└── README.md
```

---

## 十、我以后读代码时先抓什么

不要第一遍就逐行抠语法。

### 第一遍：看业务链路
请求从哪里进？
数据往哪里走？
最后结果从哪里出？

### 第二遍：看边界
API 为什么不直接算 VaR？
Agent 为什么不直接查数据库？
为什么 RiskEngine 是单独 Service？

### 第三遍：看 State
一个问题经过 Graph 后，State 增加了哪些字段？

### 第四遍：看安全
如果 LLM 生成 DELETE 会发生什么？

### 第五遍：看可测试性
哪个模块可以不用 LLM 就测试？

---

## 十一、面试时最核心的 5 分钟结构

### 第 1 分钟：业务问题

“我做的是金融投研与风险决策智能平台，不是普通 RAG。目标是把上市公司财务数据、年报/监管文档和量化风险计算统一进一个 Agent 工作流。”

### 第 2 分钟：为什么 Agent

“一个问题经常同时需要结构化数据、文档证据和风险计算，所以我使用 LangGraph 做状态化编排，而不是简单链式调用。”

### 第 3 分钟：数据与 RAG

“文档用 MinerU 解析，BGE-M3 生成 dense/sparse 表示，Milvus 做 hybrid retrieval，再 rerank。每个 chunk 保留公司、年份、页码、章节等 metadata。”

### 第 4 分钟：金融数学与安全

“VaR、CVaR、回撤等由确定性 RiskEngine 计算；Text-to-SQL 经过 AST 校验、表白名单、只读账户、超时和行数限制，LLM 不直接碰数据库写权限。”

### 第 5 分钟：企业级

“我还做了 RBAC、Audit、Checkpoint、HITL、Eval、Trace 和 Docker 部署。项目重点不是技术数量，而是让每个 AI 决策都尽量可追踪、可验证、可恢复。”

---

## 十二、最终简历方向

**FinSight AI — 企业级金融投研与风险决策智能平台**

可写成：

- 设计并实现基于 LangGraph 的金融研究 Agent，将财务数据库查询、金融文档 RAG 与量化风险计算统一到状态化工作流中。
- 基于 BGE-M3 + Milvus 构建 dense/sparse hybrid retrieval 与 rerank 链路，并通过来源/页码 metadata 实现证据追踪。
- 构建只读 Text-to-SQL 安全层，采用 AST 校验、表白名单、查询超时、行数限制和审计日志降低 LLM 数据访问风险。
- 实现 VaR/CVaR、最大回撤、波动率、Sharpe、相关性等确定性风险工具，并增加数值一致性验证。
- 建立 RAG / Tool / Agent 评估集及 Trace、Token、Latency、Error 等可观测指标，完成 Docker 化部署与 MCP Tool Server。

注意：
最终简历必须用项目最终真实测得的数据替换泛化描述，例如：
- Recall@K
- P95 latency
- Eval pass rate
- 文档数量
- chunk 数量
- API 测试覆盖
- Agent completion rate

---

## 十三、这 20 天真正要学会的不是“代码量”

项目完成后，我应该能回答：

1. 为什么选 LangGraph 而不是一条 Chain？
2. State 怎么流动？
3. Tool 和 Agent 的边界是什么？
4. 为什么 VaR 不让 LLM 算？
5. 为什么 Hybrid Retrieval 比只做 dense 更适合财报？
6. Rerank 到底解决什么？
7. SQL Prompt 防护为什么不够？
8. 什么是 Evidence Contract？
9. 如何验证最终数字没有被 LLM 改写？
10. 如何做 RAG Eval？
11. 如何做 Agent Tool Eval？
12. Checkpoint 为什么是企业 Agent 的关键能力？
13. Human-in-the-Loop 放在哪里最合理？
14. MCP 在这个项目里解决什么问题？
15. 为什么 20 天版本不直接上微服务/Kubernetes？
16. 数据源挂了怎么办？
17. 模型 API 挂了怎么办？
18. Milvus 检索慢怎么办？
19. 如何降低 Token 成本？
20. 如果并发提高 100 倍，首先拆哪里？

当这 20 个问题能自己讲清楚，这个项目才真正属于我。
