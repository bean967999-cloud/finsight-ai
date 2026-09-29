# FinSight AI — 企业级架构说明

## 1. 为什么不用“纯多智能体堆砌”

本项目采用 **一个可控的 LangGraph Orchestrator + 多个确定性 Tool/Domain Service**。

原因：

- 金融场景要求可复现、可审计。
- SQL、VaR、CVaR、回撤、财务指标计算不应该交给 LLM 自由生成。
- Agent 负责“判断该用什么工具、按什么顺序、如何整合证据”。
- Tool 负责“确定性执行”。
- Verifier 负责“检查引用、数字和数据来源”。

## 2. 目标架构

```text
┌─────────────────────────────────────────────────────────┐
│                 React + TypeScript UI                   │
│      投研问答 / 单次执行轨迹 / 风险看板 / Eval 看板       │
└───────────────────────┬─────────────────────────────────┘
                        │ HTTPS / SSE
┌───────────────────────▼─────────────────────────────────┐
│                     FastAPI API                         │
│ Auth / RBAC / Rate Limit / Request ID / Validation      │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│                 LangGraph Orchestrator                  │
│ Intent → Plan → Tools → Evidence Fusion → Verify → Ans  │
│ Checkpoint / Retry / HITL / Trace                       │
└──────────┬──────────────────┬──────────────────┬─────────┘
           │                  │                  │
      RAG Tool           SQL/Data Tool       Risk Engine
           │                  │                  │
 MinerU → Chunk      Text-to-SQL Guard     NumPy/Pandas
 BGE-M3              PostgreSQL             VaR/CVaR
 Dense+Sparse        Read-only Role         Drawdown
 Milvus Hybrid       Timeout/Limit          Volatility
 Rerank              Audit                  Correlation
           │                  │                  │
           └──────────────────┴──────────────────┘
                              │
                    Evidence / Provenance
                              │
                  Citation + Numeric Verifier
                              │
┌─────────────────────────────▼───────────────────────────┐
│ Observability / Governance                              │
│ Trace / Token / Latency / Error / Eval / Audit / Metrics│
└─────────────────────────────────────────────────────────┘
```

## 3. 模块边界

### 3.1 API 层
只处理：
- 身份
- 请求校验
- 统一错误
- API Contract
- 流式响应
- Request ID

不在路由函数里直接写业务逻辑。

### 3.2 Agent 层
只处理：
- 意图识别
- 计划
- 工具路由
- 状态流转
- 重试
- Human-in-the-Loop
- 最终回答编排

### 3.3 Domain Service 层
可独立测试：
- RiskEngine
- FinancialDataService
- RetrievalService
- SQLQueryService
- EvidenceService

### 3.4 Infrastructure 层
- PostgreSQL
- Milvus
- Redis
- Object Storage
- LLM Provider
- Embedding Provider
- Tushare Provider

Domain 不直接依赖某一家外部供应商。

## 4. Agent Graph

最终图：

```text
START
  ↓
normalize_request
  ↓
classify_intent
  ↓
build_plan
  ↓
┌───────────────────────────────────────┐
│ conditional / parallel tool execution │
├───────────┬──────────────┬────────────┤
│ rag_search│ sql_query    │ risk_calc  │
└─────┬─────┴──────┬───────┴─────┬──────┘
      └────────────┴──────────────┘
                    ↓
              fuse_evidence
                    ↓
              verify_numbers
                    ↓
             verify_citations
                    ↓
      compliance / confidence gate
              ↙             ↘
        enough evidence    insufficient
              ↓                ↓
        synthesize        safe refusal
              ↓                ↓
             END              END
```

## 5. 金融数学能力如何真正进入项目

不是只在 README 里写“金融数学”。

核心确定性指标：

- simple/log return
- annualized volatility
- rolling volatility
- max drawdown
- historical VaR
- parametric VaR
- CVaR / Expected Shortfall
- Sharpe ratio
- covariance / correlation matrix
- portfolio volatility
- marginal/component risk contribution
- beta
- stress scenario

第二阶段可加入：

- Monte Carlo VaR
- factor exposure
- simple mean-variance optimization

## 6. RAG 设计

```text
PDF / 年报 / 公告 / 监管文档
        ↓
MinerU
        ↓
结构化 Markdown + metadata
        ↓
Financial Chunker
        ↓
BGE-M3
   ↙           ↘
dense         sparse
   ↘           ↙
  Milvus Hybrid Search
        ↓
RRF / Weighted Fusion
        ↓
Cross Encoder Rerank
        ↓
Top Evidence
```

Chunk metadata 至少保留：

- document_id
- company
- stock_code
- report_type
- report_period
- page
- section
- source_url
- checksum
- chunk_version

## 7. SQL 安全不是 Prompt 安全

完整防线：

1. Pydantic Structured Output 生成 SQL Plan。
2. sqlglot AST 解析。
3. 只允许 SELECT / CTE。
4. schema/table allowlist。
5. 自动 LIMIT。
6. PostgreSQL `statement_timeout`。
7. read-only DB user。
8. 租户/用户数据范围过滤。
9. SQL 与结果 Audit。
10. 敏感导出进入 HITL。

## 8. Evidence Contract

最终答案中的每个核心结论应绑定 Evidence：

```json
{
  "claim": "公司近三年净资产收益率下降",
  "evidence": [
    {
      "type": "sql",
      "dataset": "financial_indicators",
      "rows": ["2024", "2025", "2026"]
    },
    {
      "type": "document",
      "document_id": "annual_report_xxx",
      "page": 88,
      "section": "Management Discussion"
    }
  ]
}
```

## 9. 企业级评估

### RAG
- Recall@K
- MRR / nDCG（可选）
- citation correctness
- faithfulness
- refusal correctness

### Agent
- intent accuracy
- tool selection accuracy
- tool argument correctness
- workflow completion rate
- retry rate

### 数值
- risk metric unit tests
- SQL result consistency
- LLM answer vs tool result consistency

### 工程
- P50/P95 latency
- token cost
- tool error rate
- API error rate
- cache hit rate

## 10. 企业级不是一定上 Kubernetes

20 天版本部署：

```text
Nginx
  ↓
FastAPI
  ├── PostgreSQL
  ├── Redis
  ├── Milvus
  └── Worker
```

全部 Docker Compose 部署到 CVM。

Kubernetes 作为“未来规模化演进方案”写进架构说明，不在 20 天里为了简历强行堆进去。
