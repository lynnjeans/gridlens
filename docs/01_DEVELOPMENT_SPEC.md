# GridLens 开发规格

版本：1.1 | 日期：2026-10-11 | 状态：基础阶段已实现，后续功能待实施 | 项目名称：GridLens（暂用名）

## 1. 文档用途与范围

本文件将 `00_PRD.md` 转成实现约定；`02_AI_TASKS.md` 将实现拆成 36 个任务；`03_AI_EXECUTION_GUIDE.md` 定义如何逐个交给 AI 开发。应用现已建立独立本地仓库，T01–T20、T22–T30、T33 完成，T21、T34–T36 离线完成待真实登录，T31–T32 待用户验收；会话、生成和问答等后续功能仍待实施。实际证据见 progress.md，真实服务与研究评估尚未执行。

产品范围遵循 PRD：公开来源自动发现 → 人工审核 → 文本型 HTML/PDF 入库 → 已批准资料检索 → 带引用问答 → 知识缺口与 Markdown 导出。默认 NZ、英文资料、单操作者、本地运行。保留 PRD 的 FR-01–FR-10、AC-01–AC-10 和 R01–R15 编号。

范围外：pandapower/OpenDSS、容量计算、OCR、复杂表格/GIS、多用户权限、生产部署、自动批准资料、问答时自动联网、后台持续研究。P1 功能不进入本次任务清单。

### 1.1 本文补充的工程决策

以下为开发默认值，不是用户已经选定的供应商或已经验证的性能。现有项目如已采用等效方案，先记录差异，优先复用，不重建整个系统。

| 决策 | 默认方案 | 理由 |
| --- | --- | --- |
| 运行时 | Python 3.12；项目内 `.venv` | 固定一个基线，减少 AI 自行切换环境 |
| UI | Streamlit，四页导航 | 与 PRD 一致，首版无需独立 HTTP 后端 |
| 数据校验 | Pydantic v2 | 统一服务参数、返回值与模型输出 |
| 元数据 | Python `sqlite3` + 编号 SQL migration | 数据量小，显式事务即可；不引入 ORM |
| 原文 | 本地不可变快照目录 | 审核和引用固定到实际读取内容 |
| 向量库 | Chroma PersistentClient | 本地验证；业务正文仍从 SQLite/快照读取 |
| 搜索适配器 | Tavily Search（建议默认，可替换） | 首版实现一个真实 provider，与业务逻辑隔离 |
| 生成适配器 | ChatGPT OAuth + OpenAI SDK Responses 流式调用 | 使用用户批准的订阅用量；UI 不直接持有 tokens |
| embedding 默认 | SentenceTransformers + `BAAI/bge-small-en-v1.5`，384 维，本地 CPU | 固定 revision 与归一化配置；英文首版 |
| 生成模型 | 登录后读取账户 catalog，由用户选择 model slug | schema 能力需联调；保持严格本地输出校验 |
| 抓取与解析 | HTTPX、BeautifulSoup4、pypdf | 只覆盖可公开读取的 HTML 与文本型 PDF |
| token 切分 | embedding 模型对应 HuggingFace tokenizer | 350 tokens + 50 overlap，验证完整输入不超过模型上限 |
| 质量工具 | pytest、Ruff；可选 Streamlit AppTest | 检查业务边界，不做全量 UI 截图框架 |
| 依赖管理 | `pyproject.toml` + 一份已解析的 `requirements.lock` | T01 在实际环境确定兼容版本并锁定，不写未经安装验证的版本号 |

本次用户已选择 ChatGPT 订阅授权 + 本地 embedding。生成调用遵循官方 plan usage 路由，不能照搬平台 key 的完整参数集合；具体契约见 3.3–3.4 节。账户资格及模型输出能力以真实联调为准。

## 2. 架构与目录约定

```text
Streamlit pages
       ↓
Application services：discover / capture / review / ingest / ask / gaps / export
       ↓                         ↓
SQLite repositories       Provider interfaces
       ↓                         ↓
Snapshots + metadata      Tavily / ChatGPT OAuth Responses / local embeddings / Chroma / HTTP fetcher
```

UI 只负责收集输入、调用服务和显示结果。状态变更、检索资格、引用校验在服务层执行，不能仅通过禁用按钮实现。同步、串行处理即可；不加消息队列、微服务或 Agent 框架。

以下为**应用仓库内的相对路径约定**。基础模块已实现，其余按任务逐步创建；当前文件与未实现服务以 HANDOFF.md 为准。

```text
gridlens/
  app.py
  pyproject.toml
  requirements.lock
  .env.example
  .gitignore
  README.md
  docs/                       # 本文档包、PRD、执行记录
  gridlens/
    config.py                 # 所有配置和限额
    contracts.py              # DTO、枚举、端口接口
    errors.py                 # 稳定错误码
    bootstrap.py              # 组装真实/fixture 依赖
    db.py
    migrations/001_initial.sql
    repositories/             # sources.py, research.py, qa.py
    providers/                # tavily.py, chatgpt_oauth.py, local_embeddings.py, chroma_store.py, fakes.py
    auth/                     # host.py, credentials.py, oauth.py, sessions.py, catalog.py
    documents/                # fetch.py, html.py, pdf.py, snapshots.py, chunking.py
    services/                 # discovery.py, review.py, ingestion.py, retrieval.py,
                              # answers.py, citations.py, gaps.py, export.py, recovery.py
    ui/                       # discover.py, review.py, knowledge_base.py, ask.py, common.py, account.py
    prompts/answer_v1.txt
    cli.py
  tests/
    unit/
    integration/
    ui/
    live/                     # 默认不运行，需要显式选择
    fixtures/                 # 合成测试材料，不能充当真实研究来源
  evals/
    questions.json
    gold.json                 # 人工补充后才可验收
  data/                       # Git 忽略：SQLite、快照、Chroma
  artifacts/                  # Git 忽略：运行、评估和导出结果
```

`gridlens` 使用普通 Python package；T01 配置 editable 安装，不把整个应用硬塞进 `app.py`。三个 repository 文件可按任务逐步添加方法，初期不为每张表建立抽象基类。

## 3. 配置、启动和执行模式

### 3.1 配置契约

| 环境变量 | 默认/要求 | 行为 |
| --- | --- | --- |
| `APP_MODE` | `fixture` 或 `live`，默认 `fixture` | 两套数据目录完全分离；页面始终显示模式 |
| `DATA_DIR` | `./data/{APP_MODE}` | 路径必须落入项目指定数据目录，不从文档输入取得 |
| `TAVILY_API_KEY` | live 搜索必填 | 缺失时只禁用真实搜索，不阻止离线开发 |
| `AUTH_DIR` | 用户配置目录下 GridLens 子目录 | tokens 使用受保护的本地存储，禁止落入仓库/研究数据库 |
| `CHATGPT_MODEL_SLUG` | 可选首选项，须匹配当前账户目录 | 实际选择绑定账户；不可用时要求重选 |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | 模型变化要求新索引配置 |
| `EMBEDDING_DIMENSIONS` | `384` | 实际返回维度必须匹配 |
| `EMBEDDING_REVISION / LOCAL_MODEL_DIR` | 下载时解析并锁定实际 revision / 受控缓存目录 | 不编造 revision；正常运行禁止自动下载 |
| `EMBEDDING_DEVICE / NORMALIZE_EMBEDDINGS` | `cpu / true` | query prefix、tokenizer revision 一并写入 fingerprint |
| `MAX_SEARCH_CALLS` | `3` | 一次搜索操作的总网络调用上限，包含重试 |
| `MAX_SEARCH_RESULTS` | `10` | 合并、去重后显示上限 |
| `MAX_DOCUMENT_BYTES` | `20971520` | 解压后的响应正文也检查大小 |
| `MAX_PDF_PAGES` | `200` | 超限拒绝解析 |
| `CHUNK_TOKENS / CHUNK_OVERLAP` | `350 / 50` | 要求 `0 <= overlap < size` |
| `RETRIEVAL_TOP_K / CONTEXT_TOP_K` | `10 / 5` | 最多进入生成上下文 5 个块 |
| `MAX_CONTEXT_TOKENS` | `4000` | 正文片段总预算，给系统提示和输出另留空间 |
| `MAX_GENERATION_ATTEMPTS` | `2` | 包含网络重试和无效引用重试的总次数 |
| `FETCH_TIMEOUT_SECONDS` | `20` | 连接/读取超时，并设置整体截止时间 |
| `MODEL_TIMEOUT_SECONDS` | `60` | 超时归为服务错误；30 秒仅为 PRD 优化目标 |

Fixture 模式只能用明确标注的合成资料与可预测 fake providers；不调用网络，不写 live 索引。Live 模式服务失败绝不自动降级成 fake 答案。测试默认禁止出网；小型 fake embeddings 维度与 live 分开配置，不共用集合。

### 3.2 完成相应任务后应支持的命令

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install -e . --no-deps
python -m gridlens.cli init-db
python -m streamlit run app.py --server.address 127.0.0.1
python -m pytest -m "not live and not local_model"
python -m ruff check .
python -m ruff format --check .
python -m gridlens.cli evaluate --cases evals/questions.json --mode fixture
```

真实本地模型 smoke 标记 local_model，默认检查排除它；显式准备缓存后执行该组并记录结果，跳过不能算实际模型验证成功。CLI evaluate live 从受保护存储读选中账户会话，无有效授权则明确失败。

这些是目标运行接口，不表示当前已经可以执行。`requirements.lock` 要包含开发/测试依赖；生成方法和使用的工具版本写入 README。实际真实评估通过显式 `--mode live` 运行，需要账户配置、已审核语料和人工评分。

### 3.3 ChatGPT 订阅授权与调用契约（P0）

首版为本地个人研究应用，采用官方 Sign in with ChatGPT 的 ChatGPT plan usage 流程。是否允许使用取决于账户资格、授权和可用额度；不把“登录成功”当作“已获模型权限”。公网托管或付费产品不在此授权假设内。[官方说明](https://developers.openai.com/siwc/token-sharing-open-source)

登录实现按以下固定边界拆分为 T33–T36：

1. T33 持久化本机 `ext_agent_host_id`，注册记录按已验证身份和 issued client ID 分开保存。使用受保护的用户配置目录，Unix 目录 0700、凭证文件 0600，原子替换；不写研究 SQLite、浏览器存储、Git、导出或日志。保留 access/refresh/ID tokens、scope、expiry、client ID；UI 只取得脱敏账户摘要。
2. T34 先启动 `127.0.0.1` loopback listener，再打开官方 authorize 页面。每次生成 PKCE S256、state、nonce；首次使用 `dynamic_agent_client` 和 `agent_name_hint=GridLens`，返回后保存 issued client ID。交换 code 使用实际 issued ID、相同 redirect URI、verifier 和 resource；不需要 client secret。验证 state、JWKS 签名、issuer、audience、expiry、nonce，返回登录核对原账户身份；错误 callback 或过期/重放 attempt 不更新当前账户。验证授权范围包含 plan usage 权限，拒绝授权保持当前账户不变。（2026-10-11 按官方 errors-and-recovery 修订：token 响应缺少 `chatgpt.tokens.use.direct` 时保留登录、标记 plan usage 未授权并提示重新授权，不发起推理。JWKS：`https://auth.openai.com/.well-known/jwks.json`，来自 issuer discovery；实现见 `gridlens/auth/oauth.py`，CLI `gridlens login` 仅 live 模式。）[注册与登录](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)
3. T35 过期前串行刷新；替换完整 token set，避免旋转 refresh token 竞争。invalid_grant 停止生成并要求重新授权。退出先停止请求，按 discovery 文档的 revocation endpoint 尝试撤销 refresh token，再清除本地 tokens，保留 client/host 映射。无法确认远端撤销时清除本地凭证并明确提示用户可到 ChatGPT Settings 断开。切换账户不混用身份、client ID 或 token。（实现 2026-10-12：`gridlens/auth/sessions.py`，过期前 5 分钟刷新，按注册 fcntl 串行；终止性刷新错误清除 tokens 仅保留 ID token 作 hint；临时失败保留凭证；撤销端点必须属于 issuer，最多 3 次退避重试；账户选择以 `active.json` epoch 隔离旧结果；CLI `gridlens logout`。）[会话管理](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions)
4. T36 获取选中账户 `GET https://api.openai.com/v1/models`；解析 `models` 数组，只显示 `visibility=list` 项，显示 display_name、请求传 slug。换账户清空旧选择并刷新 catalog。显示 Continue with ChatGPT、已连接账户、模型选择、重新授权、退出和 [ChatGPT Usage](https://chatgpt.com/settings/usage) 链接；无需增加第五个研究页面。（实现 2026-10-12：`gridlens/auth/catalog.py`、`gridlens/ui/account.py`；目录按账户选择缓存在 session state、不含 token；`selected_model()` 只返回当前账户目录中的模型。）[模型目录](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)

Authorize endpoint：`https://auth.openai.com/api/accounts/authorize`。Token endpoint：`https://auth.openai.com/api/accounts/oauth/token`。请求 identity scopes `openid profile email`，plan scopes `offline_access resource.invoke chatgpt.tokens.use.direct`，resource `https://api.openai.com/v1`。listener 固定 `/auth/callback`，端口可用时选择；同一 attempt 的 authorize 与 exchange URI 必须完全相同，不能把 host 换成 localhost。使用已安装 JWT/OIDC 库验证，不手写密码学。

T21 的 HTTP 生成请求必须满足：

- `POST https://api.openai.com/v1/responses`，使用选中账户的 OAuth Bearer token；SDK 的 api_key 参数承载该 token，不是平台 API key。
- 每次 `store=false`、`stream=true`、`input` 为数组；提示使用 `instructions` 或 developer message，证据作为用户数据。禁止显式 system message、历史 response ID、后台执行和工具。
- 不发送本路由不支持的 `max_output_tokens`、`temperature`、`top_p`、`metadata`、`conversation` 等字段；编码时按 preview limitations 做请求字段白名单。用应用上下文预算、超时和响应缓冲上限约束资源；超限为失败，不能截断后当答案。
- SSE 缓冲直到 `response.completed`；failed/incomplete/断流都不是成功。随后 Pydantic 校验 AnswerDraft、引用校验和输出前来源资格校验，全部成功才保存/展示可信答案。进度可以展示，未验证正文不能进入 research log。
- 首次真实联调测试所选模型的 JSON schema 能力；支持时使用兼容的 `text.format` schema。若不支持，明确记录为 prompt-JSON + 同等严格本地校验模式；两种模式均不得接受自由文本或绕过引用校验。记录实际 output mode，不承诺所有账户模型均支持同一 schema 参数。
- 权限未开通、过期/被撤销、模型不可用和计划额度耗尽独立显示；额度错误即停止，绝不无限重试或自动换成收费平台调用。用量有返回则记入 QA usage，未返回为未知，不推算“剩余百分比”。
- 实现（2026-10-12，`gridlens/providers/chatgpt_oauth.py`）：原生 httpx、顶层字段白名单 `model/instructions/input/store/stream/text`；官方 2026-10-12 文档未说明 `text.format` 与 usage 字段，故 output mode `auto` 先 strict json_schema，流开始前因 `text.*` 参数被拒时回退一次 `prompt_json_validated`；错误码 USAGE_LIMITED、PLAN_PERMISSION_MISSING、AUTH_EXPIRED、MODEL_UNAVAILABLE、STREAM_INCOMPLETE、OUTPUT_INVALID、PROVIDER_TIMEOUT、PROVIDER_UNAVAILABLE、GENERATION_FAILED、GENERATION_TOO_LARGE。

上述端点/参数与事件行为依据 [模型调用](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)、[预览限制](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)、[错误与恢复](https://developers.openai.com/siwc/token-sharing-open-source/errors-and-recovery)，核对日期 2026-10-11。它们不是本应用已经完成的登录或可用性测试。

### 3.4 本地 embedding 与模型准备

默认 SentenceTransformers + `BAAI/bge-small-en-v1.5`，CPU 推理、384 维、归一化向量。初次显式下载后记录实际 revision，正常运行使用固定本地缓存、`local_files_only=true`、`trust_remote_code=false`；缺缓存报 `LOCAL_MODEL_MISSING`，不悄悄联网下载。实现：`gridlens prepare-model` 是唯一下载入口，只取 SentenceTransformers 所需文件到 `LOCAL_MODEL_DIR`（默认 git 忽略的 `models/`），要求解析为 40 位 commit，并写 `gridlens-model.json` 清单（revision、tokenizer revision、维度、512 上限、prefix）；运行时按本地快照路径加载。query 使用模型卡指令 `Represent this sentence for searching relevant passages: `，文档无 prefix。依赖：`embeddings` extra 为 `sentence-transformers>=6.1,<7`（2026-10-11 锁定 6.1.0），Chroma 在 `vectors` extra。2026-10-11 实际准备 revision `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a`。测试分 fake 与真实本地模型 smoke；后者不需要 ChatGPT 登录或平台 key。[模型卡](https://huggingface.co/BAAI/bge-small-en-v1.5)、[SentenceTransformers](https://sbert.net/docs/sentence_transformer/usage/usage.html)

该默认模型面向英文，最大输入 512 tokens；分块采用其 tokenizer 的 350/50 起始值，计入标题、special tokens 后验证长度。问题使用模型建议的 retrieval query prefix，文档不用；prefix 与归一化策略固定到 fingerprint。长问题不得静默 truncate，提示缩短问题。中文备注可用，中文检索质量不属于首版验收。

Embedding 与生成独立：本地检索不消耗 ChatGPT 订阅额度；生成会消耗获授权的计划用量，搜索服务另有配额/费用。没有 ChatGPT 登录时仍可搜索、审核、入库和查看来源，但不能生成 live 答案。

## 4. 数据与状态契约

### 4.1 公共规则

- ID 使用 UUID 字符串；chunk ID 使用确定性 hash。时间存 UTC ISO-8601，界面按 Pacific/Auckland 显示。缺失日期用 null，不用发现时间代替。
- SQLite 每个连接执行 `PRAGMA foreign_keys=ON`，事务保持短小；外部 HTTP、解析和模型调用放在事务外。
- JSON 列以有效 JSON TEXT 保存，通过 Pydantic 校验；数据 SQL 参数化，表名/字段名由代码固定。
- Source 表示链接身份；DocumentVersion 表示一次人工审核面对的不可变正文与元数据；Chunk 只属于一个版本和一个索引配置。
- `fixture/live` 在存储根目录隔离；导出与评估均记录模式。

### 4.2 最小表定义

约定 `id` 为 TEXT PRIMARY KEY；`*_id` 是对应实体外键；`*_json` 为 JSON TEXT；计数为 INTEGER；`*_at` 为 TEXT；其余默认 TEXT。除标记 `?` 的字段外均 NOT NULL。迁移脚本为最终可执行 schema，字段含义以本表为准。

| 表 | 必需字段（除 id 外） | 约束/说明 |
| --- | --- | --- |
| `schema_migrations` | `version INTEGER, applied_at` | 此表以 version 为主键，不另设 id |
| `search_runs` | `operation_key, topic, filters_json, queries_json, provider, status, calls_used INTEGER, started_at, finished_at?, error_code?` | operation_key UNIQUE；status=`running/completed/partial/failed` |
| `sources` | `canonical_url, original_url, title, publisher?, source_type, jurisdiction, topics_json, access_status, created_at` | canonical_url UNIQUE；access_status=`unknown/readable/reference_only/failed` |
| `search_hits` | `search_run_id, source_id, rank INTEGER, snippet, relevance_reason, metadata_json` | UNIQUE(search_run_id, source_id)；metadata 标明搜索摘要来源 |
| `document_versions` | `source_id, raw_sha256, snapshot_sha256, raw_path, segments_path, metadata_json, published_at?, fetched_at, extraction_notes_json, review_status, ingestion_status, version_status, approved_snapshot_sha256?, index_fingerprint?, created_at` | UNIQUE(source_id, snapshot_sha256)；批准 hash 必须匹配当前快照 |
| `review_events` | `version_id, action, reviewer_label, reason?, created_at` | 拒绝必须 reason；历史只追加 |
| `ingestion_runs` | `operation_key, version_id, stage, status, attempt INTEGER, expected_chunks INTEGER, indexed_chunks INTEGER, started_at, finished_at?, error_code?` | operation_key UNIQUE；status=`processing/completed/failed` |
| `chunks` | `version_id, index_fingerprint, ordinal INTEGER, text, heading_path_json, locator_json, text_sha256, token_count INTEGER, embedding_model, embedding_dimension INTEGER, source_segment_ids_json`（迁移 002） | UNIQUE(version_id, index_fingerprint, ordinal)；正文可来自已批准快照 |
| `qa_records` | `operation_key, question, filters_json, execution_status, evidence_status?, answer_json?, context_chunk_ids_json, context_version_ids_json, model_id?, output_mode?, account_registration_ref?, prompt_version, index_fingerprint?, created_at, latency_ms INTEGER, usage_json, error_code?` | operation_key UNIQUE；execution_status=`completed/failed/stale_context`；evidence_status=`answered/partial/insufficient` 或 null |
| `citations` | `qa_id, claim_ref, chunk_id, quoted_span, locator_snapshot_json, source_metadata_snapshot_json` | UNIQUE(qa_id, claim_ref, chunk_id)；引用内容不可被新版本覆盖 |
| `knowledge_gaps` | `qa_id, gap_key, question, scope_json, reason_type, missing_evidence, suggested_queries_json, status, resolution_note?, created_at, updated_at` | status=`open/resolved/dismissed`；仅 open 的 gap_key 唯一 |
| `app_state` | `key, value_json` | 此表以 key 为主键，不另设 id；保存当前 index_fingerprint 与 processing lock owner 等轻量配置 |

AuthRegistration 不建研究数据库表：受保护凭证目录保存注册/会话，app_state 最多保存脱敏选中账户引用。QA 的 account_registration_ref 使用不含 email 的 opaque ID，output_mode 记录 schema 或 prompt_json_validated。

EvaluationRecord 按 PRD 允许的方式保存在 `artifacts/evals/` 的 JSON/CSV，不新增评估数据库。API 用量记录在 search run、ingestion stage 日志和 QA usage 中，日志禁止正文全量和密钥。

建议写入的索引：

```sql
CREATE UNIQUE INDEX one_active_version_per_source
ON document_versions(source_id) WHERE version_status = 'active';

CREATE UNIQUE INDEX one_open_gap_per_key
ON knowledge_gaps(gap_key) WHERE status = 'open';

CREATE INDEX eligible_versions
ON document_versions(review_status, ingestion_status, version_status);

CREATE INDEX chunks_for_version
ON chunks(version_id, index_fingerprint);
```

### 4.3 三种状态分别管理

| 状态 | 取值 | 允许变化 |
| --- | --- | --- |
| Review | `pending/approved/rejected/revoked` | pending → approved/rejected；approved → revoked；rejected/revoked → pending（人工重新开启，之后重新批准） |
| Ingestion | `not_started/processing/ready/failed` | not_started/failed → processing → ready/failed；ready 同配置重复请求为 no-op |
| Version | `candidate/active/superseded` | candidate → active；active → superseded；仅 Ready 的获批版本可以成为 active |

**对 PRD 的工程细化**：新增 `candidate` 表示尚未发布的新版本，消除“待审核版本也叫 active”的歧义，不增加产品功能。Superseded 版本不在 MVP 里直接重新激活；新批准资料不会自动恢复其他被撤销版本。

唯一检索资格谓词：

```text
eligible(v) = review_status == approved
           AND ingestion_status == ready
           AND version_status == active
           AND approved_snapshot_sha256 == snapshot_sha256
           AND index_fingerprint == current_index_fingerprint
```

审核字段只能通过 ReviewService 修改；查询资格只以 SQLite 为准。`approved`、`ready` 和 `active` 任一条件不满足，均不能进入模型上下文。

重新开启 Rejected/Revoked 版本时，清空 `approved_snapshot_sha256`，将 ingestion 重置为 `not_started`、version 重置为 `candidate`；再次批准后必须重新完成入库校验。这样即使撤销时向量已经删除，也不会因旧的 Ready 状态直接恢复查询资格。Superseded 版本不允许通过 Reopen 绕过新版本发布流程。

### 4.4 快照身份

`raw_sha256` 记录抓取字节。`snapshot_sha256` 根据确定性序列化后的 `{segments, reviewed_metadata, parser_version}` 计算；reviewed_metadata 包含会影响引用或适用性的标题、发布方、日期、地区和类型，不包含抓取时间等每次变化字段。

同一 URL、相同快照重复获取只更新访问记录，不增加版本。仅抓取时间或无关 HTML 导航变化不应产生新的审核对象。不同 URL 的相同正文提示可能重复，优先原始发布方，但不自动混并不同发布机构。

Pending 元数据修正后重新计算 snapshot hash；Approved 之后正文、影响引用的元数据和 hash 不可原地修改。需要修正时建立新 Candidate 并重新审核。批准保存 `approved_snapshot_sha256`，入库前再次比对。

## 5. 服务与 Provider 接口

以下是内部 Python 调用，不是 REST API。搜索、入库和问答接受 UI 生成并在本次提交重用的 `operation_key`；重复提交返回已存在结果。其他写操作通过唯一键、快照 hash 和条件状态更新保证幂等；重复批准不重复追加事件。查询无副作用。

| 服务方法 | 输入 | 输出/副作用 |
| --- | --- | --- |
| `discover(request, operation_key)` | topic 3–500 字符、region、source_types | SearchRunDetail；最多 3 次搜索调用、10 条唯一候选 |
| `add_source(url)` | 公开 HTTP(S) URL | SourceDetail；不批准、不入库 |
| `capture(source_id)` | 候选来源 ID | VersionPreview 或 FetchError；获取并保存待审核快照 |
| `review(version_id, action, reason, reviewer, expected_hash)` | action=approve/reject/reopen/revoke | 更新状态并追加事件；approve 要求正文存在且 hash 匹配 |
| `ingest(version_id, operation_key)` | 已批准版本 | IngestionResult；完整索引校验通过后发布 Ready/Active |
| `retrieve(question, filters)` | question 3–2000 字符、地区/类型 | RetrievalContext；最多 5 块和检索诊断 |
| `ask(question, filters, operation_key)` | 同上 | AnswerEnvelope；验证引用后一次性保存 QA + citations |
| `list_gaps / update_gap / dismiss_gap` | gap ID、编辑字段、状态、备注 | 缺口记录；模型不得代替人工标记 resolved |
| `export_log(selection)` | 选定 source/QA/gap IDs | UTF-8 Markdown；按当前审核资格处理内容 |
| `recover_interrupted_runs()` | 启动时显式调用 | 中断任务转 Failed，可人工重试；不自动重复收费调用 |

Provider 最小接口：

```python
class SearchProvider(Protocol):
    def search(self, query: str, limit: int) -> list[SearchHitDTO]: ...


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str], role: Literal["document", "query"]) -> EmbeddingBatch: ...


class AnswerProvider(Protocol):
    def generate(self, question: str, context: RetrievalContext) -> AnswerDraft: ...


class VectorStore(Protocol):
    def upsert(self, chunks: list[ChunkDTO], vectors: list[list[float]]) -> None: ...
    def query(
        self, vector: list[float], eligible_version_ids: list[str], k: int
    ) -> list[VectorHit]: ...
    def stored_ids(self, version_id: str) -> set[str]: ...
    def delete_version(self, version_id: str) -> None: ...
```

协议代码是契约示意；实现时 DTO 定义都放在 `contracts.py`，服务不 import 具体 provider。

### 5.1 核心 DTO 字段

| DTO | 字段 |
| --- | --- |
| `AccountSummary / AuthState / ModelChoice` | 脱敏 registration ID、显示标签、connected/needs_login/permission_missing/usage_limited、slug/display_name；不含 tokens |
| `SearchHitDTO` | title、url、snippet、provider_rank、publisher?、published_at?、source_type=`unknown`、jurisdiction=`unknown`、metadata_evidence |
| `ParsedSegment` | segment_id、text、heading_path、locator、warnings |
| `Locator` | kind=`pdf/html`；PDF 用 file_page ≥1；HTML 用 section_title?、paragraph_index ≥1；印刷页码可为空 |
| `ChunkDTO` | chunk_id、version_id、ordinal、text（原文精确子串，引用目标）、text_sha256、embedding_text（标题上下文 + text，实际模型输入）、heading_path、token_count（embedding_text 含 special tokens）、source_segment_ids、locator、index_fingerprint |
| `EmbeddingBatch` | vectors、model_id、revision、dimensions、role、local_token_count、latency_ms；不含 API 计费 usage，vectors 与 inputs 一一对应且均为有限数字 |
| `VectorHit` | chunk_id、distance；distance 不展示为可信度 |
| `RetrievalContext` | chunks、eligible_version_ids、filters、index_fingerprint、diagnostics |
| `AnswerEnvelope` | qa_id、execution_status、evidence_status?、claims、limitations、citations、gaps、error?、mode |
| `AppError` | code、safe_message、retryable、operation_id；内部 exception 不直接显示 |

## 6. 发现、抓取与审核实现规则

### 6.1 搜索

规则模板最多生成 3 个查询，优先保留用户原问题并扩展 data centre/data center、grid connection/interconnection；无需为 query expansion 额外调用 LLM。地区默认 NZ，来源类型是检索提示及人工标签，不把猜测分类视为已验证元数据。

Tavily 使用 `topic=general`、`search_depth=basic`、`max_results=10`、`auto_parameters=false`、`include_answer=false`、`include_raw_content=false`。应用合并排序去重至 10 条，搜索摘要仅为候选描述。映射 provider 字段时，发布方与日期无证据则 null；域名可显示，但不能冒充机构名称。[Tavily Search API](https://docs.tavily.com/documentation/api-reference/endpoint/search)

搜索总预算 3 次请求；部分查询成功则 `partial` 并保留结果与失败原因，全部失败为 `failed`。HTTP 429/5xx/超时可在预算内重试，400/401/403 不盲目重试。实际使用次数和 provider usage 有则保存，无则为未知。

URL 规范化只统一 scheme/host 大小写、移除 fragment 和已知跟踪参数；保留功能性 query，不随意排序重复参数、不删除路径末尾斜杠。不猜测 canonical 标签的真实性，重定向后的 URL 另存于快照元数据。

### 6.2 抓取与解析

- 校验 HTTP(S)、合法主机、无 userinfo；拒绝 localhost、私网、loopback、link-local、保留地址和不允许端口。域名解析出的全部地址均检查；每次重定向再次校验，最多 3 跳，不开启无检查的自动 follow。
- 流式获取并限制响应字节、解压后大小、请求总耗时；仅接受 HTML/PDF，结合 MIME 与 PDF 文件头判断。不执行 JavaScript，不解析脚本内的指令。
- 本地单操作者部署是边界；DNS 重绑定等强对抗隔离不以 URL 校验完成度作保证，未来公网部署应另做出站网络控制。
- HTML 去掉 script/style/nav 等非正文节点，优先 main/article，再回退正文段落；正文和章节定位一起保存。提取为空返回错误，不能拿搜索摘要代替。
- PDF 按文件页序提取正文，保存 file_page；无可提取文字为 `UNSUPPORTED_SCAN`。识别到复杂表格而无法保证列关系的部分不当作完整结构化证据；保存限制提示。
- 解析过程设置有限耗时，PDF 解析使用可终止子进程；异常不会卡死 UI。原始 PDF 和解析结果都保留，不重排页码。

pypdf 不执行 OCR，扫描图像和复杂排版可能无法得到可用文本；这正是本 MVP 的格式限制。[pypdf 文本提取说明](https://pypdf.readthedocs.io/en/stable/user/extract-text.html)

### 6.3 审核

待审核页面显示来源元数据、正文、解析限制、hash 对应版本和原始链接。Approve 要求非空正文、可支持的文档类型和最新预览 hash；Reject 要求 reason。审核服务不调用 embedding，也不联网生成批准结论。

Pending 元数据修正通过 `ReviewService.update_metadata(version_id, expected_hash, MetadataCorrection)` 重算 hash；页面记录审核者打开时的 hash，与当前不一致时禁用批准并要求重新加载。fixture 模式的 capture 使用合成 `FakeDocumentFetcher`，不访问真实网站。

Approve 成功后 UI 可自动发起一次同步入库操作；失败只改 ingestion，不撤销人的审核。再次渲染页面不能重复触发批准或入库。需要 retry 时使用新的 operation_key，版本仍保持同一个。

## 7. 分块、向量与发布事务

### 7.1 分块的确定性

先按 ParsedSegment 的页/章节边界切，再在段落间装箱至 350 tokens。单个长段落才切 token 窗口，overlap 50；不跨 PDF 页、文档或版本。每块保存对应 segment IDs 与 locator；尾块为空则不产生记录，标题与正文的组织规则固定到 chunker_version。实现（`segment-pack-v1`）：按 PDF 页或 HTML heading_path 分组，整段以空行拼接装箱；embedding_text = `标题路径（" > " 连接）+ 空行 + text`，计数含 special tokens 不超 CHUNK_TOKENS；长段按 tokenizer 字符 offset 切窗，text 为原文精确子串；标题上下文超过预算一半时只从 embedding 输入省略。Tokenizer 协议：`count_tokens(texts)`、`token_offsets(text)`。

`index_fingerprint = SHA256(canonical_json(model_id, model_revision, dimensions, tokenizer_revision, query_prefix_policy, normalization, chunker_version, size, overlap))`；`chunk_id = SHA256(version_id + index_fingerprint + ordinal + text_sha256)`。以规范 JSON 编码、固定字段顺序/分隔规则计算，避免字符串拼接歧义。配置改变时拒绝继续写旧集合，返回 `INDEX_CONFIG_MISMATCH`；MVP 不实现自动跨模型迁移，也不静默删除原索引。

### 7.2 向量适配器

embedding 以最多 16 个块一批在本地推理；空字符串先过滤，长度含 special tokens 先校验，数量、revision、维度、有限数值全部校验。文档 role=document、问题 role=query，不静默截断输入。写入 Chroma 使用确定性 IDs 和 upsert。显式传入 embeddings/query_embeddings，关闭默认 embedding function，使用 cosine 与归一化向量，防止后台使用另一个模型。

集合名绑定 index_fingerprint；metadata 只存 `version_id/source_id/ordinal/index_fingerprint` 等标识，检索结果拿到 chunk ID 后从 SQLite 获取权威正文。Chroma metadata 不是审核权限系统。

实现（chromadb 1.5.9，2026-10-11 核对文档）：`ChromaVectorStore(path, index_fingerprint, dimensions)` 懒打开 `PersistentClient`（`anonymized_telemetry=False`），集合名 `gridlens-` + fingerprint 前 48 位，`configuration={"hnsw": {"space": "cosine"}}`，自定义拒绝嵌入的 embedding function 取代默认 ONNX 模型；集合 metadata 记录 fingerprint 与维度，不符报 `INDEX_CONFIG_MISMATCH`；其余 Chroma 异常映射为 `VECTOR_STORE_FAILED`。

Chroma 本地持久化适合本项目的本地开发场景；`$in` 可用于 version ID 白名单过滤。[Chroma client](https://docs.trychroma.com/reference/python/client)、[Metadata filtering](https://docs.trychroma.com/docs/querying-collections/metadata-filtering)。

### 7.3 入库发布顺序

1. 用短事务取得单文档处理锁，检查 Approved、hash 匹配和配置一致；创建 IngestionRun，ingestion=processing。
2. 从已审核快照读取并切分，保存确定性 chunk 记录。
3. 在事务外调用 embedding 并逐批 upsert；记录阶段与数量，失败留作不可用的部分索引。
4. 比较期望 chunk ID 集合与 Chroma 实际集合；不只检查 count，额外/缺失 ID 都不发布。
5. 再次检查审核 hash 与状态。若中途撤销，结束为 Failed，禁止发布。
6. 在一个 SQLite 事务里：旧 Active → Superseded；当前版本 ingestion=ready、version=active；run=completed。任一步失败全部回滚。
7. 释放处理锁。向量旧记录可以保留，但所有检索必须使用资格白名单。

实现（`gridlens/services/ingestion.py`）：返回 `IngestionResult(status=completed/failed/noop, ingestion_status, version_status, expected_chunks, indexed_chunks, error_code)`；同 operation_key 重放结果；chunk 行用 INSERT OR IGNORE 且核对 ID 集合；失败码包括 `REVIEW_REQUIRED`、`INGESTION_IN_PROGRESS`、`INDEX_CONFIG_MISMATCH`、`CHUNK_MISMATCH`、`INDEX_INCOMPLETE`、`REVIEW_CHANGED`、`INGESTION_FAILED`。fixture 使用 `data/fixture/chroma` 持久索引 + fake embedding；live 仅在 prepare-model 后启用。

SQLite 与 Chroma 不共享事务，使用“向量先写、数据库最后发布”的策略。崩溃留下的向量不会自动有查询资格；相同版本重试 upsert 相同 ID。若数据库发布失败，旧 Active 仍可用。已 Ready 的同配置重复入库直接返回已有结果。

数据库并发写入仍串行；即使是本地，也对同一版本建立条件更新/运行锁，防止两个浏览器 tab 重复触发任务。启动时只能回收确认属于已退出进程的锁，不能把仍存活的操作误判为崩溃。

## 8. 检索与问答契约

### 8.1 检索

1. 从 SQLite 计算 eligible 集合，基于版本中的已审核 metadata 筛选，不能读取 Source 的未审核新标签来改变旧证据适用性。
2. 地区枚举 `NZ/US/GLOBAL/UNKNOWN`。默认 NZ 包含 NZ 和明确标为 GLOBAL 的概念性资料；GLOBAL 不意味着适用于所有国家的规则。UNKNOWN 默认排除，用户可明确选择所有地区。
3. 类型枚举 `policy/technical/paper/industry_report/product/unknown`；不筛选类型时包含全部合格类型，回答保留类型限制。
4. 合格集合为空：不调用 Chroma、不调用生成模型；保存 completed + insufficient 及缺口。若过滤前有批准资料，可用元数据判断地区不匹配，不能读取未批准正文补充解释。
5. embed 问题，使用 version ID 白名单查询 Top-10；拒绝 provider 返回的越界 IDs；从数据库加载块。
6. 保留按相关性排序的块；同文档相邻重叠内容优先取较高项，选最多 5 块且总正文 tokens 不超过 4000。不合并成一个无法定位的新块。
7. 进入 LLM 之前重新计算资格，过滤失效块；全部失效则返回 stale_context 或重新开始一次完整用户操作，不在本次偷偷换成未审核证据。

实现（2026-10-12）：`RetrievalFilters(region=NZ|US|GLOBAL|ALL, source_types=[])`；NZ/US 含 GLOBAL，GLOBAL 仅 GLOBAL，仅 ALL 含 UNKNOWN。诊断字段：approved_versions、eligible_versions、excluded_by_region、excluded_by_type、vector_hits、dropped_out_of_scope、skipped_overlapping、skipped_over_budget、context_tokens、dropped_after_recheck、reason（no_approved_sources / filters_excluded_all / no_relevant_chunks / stale_context）。相邻重叠 = 同版本、ordinal 相邻且共享 segment；segment IDs 存于迁移 002 的 `chunks.source_segment_ids_json`。

默认不设置通用相似度门槛。语义上是否回答了问题由回答模型在给定证据中判断，随后用人工评估验证；距离不是答案正确概率。

### 8.2 AnswerDraft 结构

下面是完整、可校验的**结构示例，内容为合成演示，不是电网事实**。每个字段必需；可空值用 null、空列表表达。Pydantic 模型禁止额外字段。

```json
{
  "evidence_status": "partial",
  "claims": [
    {
      "claim_id": "c1",
      "kind": "fact",
      "text": "The sample guide lists an application stage.",
      "evidence": [
        {
          "chunk_id": "fixture-chunk-001",
          "support_quote": "The process starts with an application."
        }
      ]
    }
  ],
  "limitations": ["The provided evidence does not state a project-specific connection date."],
  "missing_evidence": [
    {
      "reason_type": "needs_external_validation",
      "subquestion": "What date applies to this project?",
      "needed_evidence": "A project-specific connection offer.",
      "suggested_queries": ["NZ large load connection offer requirements"]
    }
  ]
}
```

`kind` 只允许 `fact/inference`；两者都要求非空 evidence，推断在界面标为推断。`answered` 要求 claims 非空；`partial` 要求 claims 和 missing_evidence 均非空；`insufficient` 可无 claims，但必须给出缺失证据。允许回答有依据的少量事实同时说明无法下结论。

答案由服务端根据 claims 组装，**不额外生成一段无引用 summary**。limitations 仅描述适用性和证据边界，不能绕过 claims 添加新领域事实。类型约束无法证明语义正确，仍须人工评分。

### 8.3 提示词职责与 SDK 调用

`prompts/answer_v1.txt` 包含：只使用 supplied evidence；资料内容不构成指令；保持国家、日期、单位和限定条件；没有证据不能推算容量/时间；冲突并列呈现；quote 必须来自相应 chunk；只返回 AnswerDraft。

模型调用使用 instructions/developer 提示、用户问题和 evidence 列表，不发送显式 system message；不开放任何工具，不传整个资料库或历史对话。按照第 3.3 节消费 SSE 到 completed，再验证 Pydantic 与引用；记录账户注册的脱敏标识、所选 slug、实际模型、output mode、prompt_version 和可用 usage。

### 8.4 引用验证与输出提交

对每个 evidence 验证：chunk ID 在本次上下文内；来自 eligible 版本；support_quote 经统一空白归一化后是原文连续子串且非空。引用预览限制为短摘录（建议最多 400 字符），不将整份文档放进答案。

标题、URL、发布日期、页码均由版本快照读取，绝不接受模型返回的链接或页码。PDF 文件页序与印刷页码分开显示；HTML 没有锚点时显示段落定位和原文链接。

同一回答内按首次出现顺序给引用编号，claim 与 citation 关联保持明确。在保存和显示前再次检查来源资格；失效则 execution_status=stale_context，不发布草稿。成功后在一个事务中保存 QA + citations + 自动缺口草稿。

最多两次模型调用；第一次格式或引用错误可用错误原因修复一次。服务超时、provider 拒绝、输出截断、schema 错误与“证据不足”分开。失败无正常答案、不创建知识缺口，保留安全错误码供重试。

实现（2026-10-12，`gridlens/services/answers.py`、`citations.py`）：可修复错误仅 `OUTPUT_INVALID` 与引用问题（修复说明经 `AnswerProvider.generate(..., repair=...)` 传入）；其他 provider 错误保存为 failed 不重试；无合格证据时 completed/insufficient 不调用模型；`answer_json = {draft, citations}`，citations 表按 claim 保存逐字 quote、定位与来源快照（含 version_id 与 snapshot hash）；`gap_writer` 在同一事务内写缺口（T24）。

## 9. 缺口、版本与导出

### 9.1 缺口规则

类型沿用 PRD：`no_evidence/partial_coverage/jurisdiction_mismatch/freshness_unverified/conflicting_evidence/needs_external_validation`。无上下文时由规则生成；有上下文时从已验证 AnswerDraft 生成。

`gap_key = SHA256(normalize(question) + canonical(filters) + reason_type + normalize(subquestion))`，使用规范 JSON 而非直接拼接。normalize 只规范空白和大小写，不删除数字、否定词或地名。源类型筛选按排序后的列表序列化。

同一 open key 更新最新 qa_id、建议词与时间，不重复插入；resolved/dismissed 留历史。若已关闭问题后来再次缺证据，可建立新 open 记录。编辑影响 key 的字段时重新校验唯一性。Resolved 必须由用户明确操作并填写 resolution_note；模型不能自动宣布解决。

实现（2026-10-12，`gridlens/services/gaps.py`）：subquestion 保存在 `scope_json` 以便编辑时重算 key；错误码 GAP_DUPLICATE、GAP_NOT_OPEN、RESOLUTION_NOTE_REQUIRED、GAP_NOT_FOUND。

缺口建议只把文本带入 Discover 输入框；用户点击 Search 才调用搜索。服务错误、损坏索引和配置错误不构成领域知识缺口。

### 9.2 更新、撤销与历史答案

ReviewService 在最早实现时就支持 revoke 并即时改变资格；后续 T26 补齐手动刷新、新快照、版本提示和历史答案状态。

Refresh 抓取新快照，相同 hash 为 no-op；不同 hash 建 Candidate。旧版本在新版本 Ready 之前继续有效，UI 显示待审核更新；新版本 Ready 发布过程按第 7.3 节执行。

Revoke 先提交 SQLite，再尝试删除向量，删除失败也不允许再次检索。历史 QA 不改写原文；每次读取历史回答计算来源是否 revoked/superseded，展示状态标签。历史答案不作为新问题检索内容。

实现（2026-10-12）：重新抓取沿用最近版本的已审核元数据（REVIEWED_LABEL_KEYS），未审核 Source 标签变化不产生新版本；已批准版本的元数据修正经 `ReviewService.revise_metadata` 生成新 pending 版本（同原文与段落文件、新 hash）；`IngestionService.purge_vectors` 尽力删除撤销版本向量；`citations.source_statuses` 读取时计算 current/superseded/revoked/not_current。

### 9.3 Markdown 导出

导出包含 UTC/显示时区时间、运行模式、来源目录及人工审核备注、所选问答及引用、开放缺口。不自动输出 research note 结论。

当前有效来源可以带短引用；历史已撤销答案单独标注并省略已撤销来源正文摘录，只保留链接、标题和状态；不混为当前有效证据。历史已被替代但未撤销的版本可保留原引用并标明 superseded。Pending/Rejected 只可作为显式选择的待审核线索列表，不导出正文。

实现（2026-10-12，`gridlens/services/export.py`）：仅依赖撤销/非当前来源的 claim 文本同样省略（claim 可能复现来源原文）；`<`/`>`/`&` 以实体输出，Markdown 标点以反斜杠转义。

Markdown 中转义用户输入，禁用原始 HTML 执行；URL 只允许已验证 HTTP(S)，不导出本地数据绝对路径、密钥或完整 provider 请求。

## 10. 四页 UI 的可实现要求

Streamlit 入口使用 `st.navigation` 与 `st.Page`，页面函数由容器传入服务。官方 API 支持文件或 callable 页面。[Streamlit navigation](https://docs.streamlit.io/develop/api-reference/navigation/st.navigation)

| 页面 | 布局及组件 | 验证与交互 |
| --- | --- | --- |
| Discover | 顶部主题表单；地区/类型；Search；候选卡片；手动 URL 输入 | 空输入报错；展示 publisher unknown/date unknown；显示 partial/failed；点击查看跳到 Review |
| Review | 左侧候选列表，右侧元数据表单与正文展开区；Approve/Reject/Reopen | Approve 前 hash 检查；Reject reason 必填；不可读来源禁止批准；界面刷新不重复提交 |
| Knowledge Base | 来源、版本、审核/入库状态表格；详情与 Retry/Revoke/Refresh | 三种状态分开展示；不提供一键“全批准”；进度按阶段而非伪造百分比 |
| Ask & Gaps | 问题表单；回答 claims；引用展开；历史；缺口 tab | 空库仍可说明范围不足；错误与 insufficient 不混淆；建议词只填入搜索框 |

四页共用账户侧栏，显示注册标签、授权状态、模型及 Usage；OAuth tokens 不缓存到 UI/session state。

Session state 只保存当前选中 ID、表单输入和 operation_key，不保存权威审核资格。可缓存 provider 客户端；SQLite 连接按操作创建，避免把一个默认线程限制连接跨线程共享。页面每次渲染重新读取状态，历史答案同样检查来源状态。

### 10.1 授权与本地模型错误

`AUTH_REQUIRED`、`PLAN_PERMISSION_MISSING`、`AUTH_EXPIRED`、`USAGE_LIMITED`、`MODEL_UNAVAILABLE`、`STREAM_INCOMPLETE`、`LOCAL_MODEL_MISSING`、`EMBEDDING_INPUT_TOO_LONG` 分别处理。认证失败可在明确安全的情况下刷新一次；流式生成开始后的失败不假定未消耗用量。额度不足不重试。错误不会被标成“知识缺口”，也不会将未完成输出持久化为成功问答。授权状态和来源审核状态完全独立。

## 11. 错误、重试与恢复

| 错误码 | 应用行为 | 自动重试 |
| --- | --- | --- |
| `CONFIG_MISSING` | 提示缺少哪个配置项，不显示密钥内容 | 否 |
| `INVALID_INPUT / INVALID_URL / URL_BLOCKED` | 显示输入问题，不开始外部请求 | 否 |
| `FETCH_FAILED / FETCH_TIMEOUT` | 保留来源线索，允许 Retry | 用户触发 |
| `DOCUMENT_TOO_LARGE / UNSUPPORTED_FORMAT / UNSUPPORTED_SCAN / EMPTY_DOCUMENT` | 标记原因，不批准为可问答文档 | 否 |
| `PREVIEW_STALE / REVIEW_REQUIRED` | 重新打开预览/人工审核 | 否 |
| `RATE_LIMITED / PROVIDER_TIMEOUT / PROVIDER_UNAVAILABLE` | 记录服务故障，使用统一调用预算 | 预算内至多一次 |
| `INDEX_CONFIG_MISMATCH / INDEX_INCOMPLETE` | 不发布版本、不生成依赖残缺索引的答案 | 不静默修复 |
| `INGESTION_INTERRUPTED` | Failed，保留快照、运行记录，允许人工重试 | 否 |
| `MODEL_REFUSAL / OUTPUT_INCOMPLETE / ANSWER_INVALID / CITATION_INVALID` | 不发布无效答案；模型拒绝单独显示 | schema/citation 错误预算内一次；拒绝不循环尝试 |
| `STALE_CONTEXT` | 提示来源状态变化，重新提问 | 否 |

所有第三方 SDK 的自动重试关闭或明确纳入服务统一预算，不能出现“服务重试 2 次 × SDK 重试 3 次”的隐形调用。日志至少包括 operation ID、stage、耗时、错误码和可用 usage，不记录密钥及全量正文。

实现（2026-10-12）：运行期间持有 `data/<mode>/locks` 下的 fcntl 文件锁，恢复以非阻塞加锁判定 owner 已退出（`INGESTION_INTERRUPTED` / `SEARCH_INTERRUPTED`）；操作日志 `data/<mode>/logs/operations.jsonl` 仅含计量字段并脱敏；`gridlens recover`、`gridlens doctor`。

重启恢复只标记确定已中断的 processing runs；不得清空已审核语料。数据库迁移只前进、不通过删库绕过错误。开发测试必须用临时数据目录。

## 12. 测试与验收映射

### 12.1 三层证据

| 层 | 可自动完成 | 不代表什么 |
| --- | --- | --- |
| 单元/合成集成测试 | 状态、去重、错误、引用 ID、越权检索、重启、导出 | 不证明真实搜索相关性或答案领域正确性 |
| 真实服务联调 | 真实搜索、本地实际模型推理、OAuth 流式生成；记录 revision/model/provider/request IDs（脱敏） | 不证明资料已获人工批准或问答质量达标 |
| 人工研究验收 | 来源批准、gold 参考段落、论断正确性、引用支持率和缺口价值 | 不能由 AI 的自评分冒充人工评审 |

关键 fixture：可读 HTML、两页文本 PDF、扫描 PDF、损坏 PDF、空正文、重复 URL、带参数 URL、重定向私网 URL、包含指令干扰文字的文档、Pending/Rejected/Revoked/Failed 版本、同来源新旧版本、含数字或地区差异的问题。全部标记 synthetic，不能加入 live research corpus。

### 12.2 需求追踪

| PRD | 实现任务 | 主要验证 |
| --- | --- | --- |
| FR-01 / AC-01 | T06–T08 | 合并去重、调用预算、真实搜索相关性由 T31 评分 |
| FR-02 / AC-02 | T09–T14 | 可读快照、hash 绑定、审批状态、拒绝原因 |
| FR-03 / AC-03 | T10–T12、T15–T19 | HTML/PDF、失败不 Ready、幂等重试 |
| FR-04 / AC-04 | T15–T20 | 版本白名单、模型一致、未审核隔离 |
| FR-05 / AC-05 | T21–T23、T29、T31 | 结构化回答、12 题正式评估 |
| FR-06 / AC-06 | T22–T23、T26、T31 | 引用有效、语义支持、历史版本定位 |
| FR-07 / AC-07 | T24–T25 | 缺口范围、去重、人工关闭；至少 3 条有效缺口 |
| FR-08 / AC-08 | T27 | 导出、转义、来源资格、无密钥/未审核正文 |
| FR-09 / AC-09 | T03、T13、T18、T26、T28、T30 | 事务、撤销、重启、版本与运行故障 |
| FR-10 / AC-10 | T29–T36 | 评估数据、可信性回归、真实验收、运行说明与 demo |

### 12.3 PRD 量化门槛

真实发现：3 个查询各前 10 条，共 30 条（跨查询可重复），相关 ≥70%；不足样本如实标记未达标。至少 10 份不同 Ready 文档、3 类核心资料。R01–R08 至少 7 题得 2 分，检索至少 7/8 命中参考依据；R09–R12 全部正确表达证据不足。引用覆盖 100%、支持率 ≥90%、定位 100%，关键工程/规则/时间结论无依据数量为 0。未批准内容泄漏 0；人工确认有效缺口 ≥3。

语义引用支持率按“获得引用支持的论断 / 已引用论断”计数，不能用“链接能打开”代替。报告分子、分母、评分者、语料版本、模型、提示词和失败案例。gold 未填写则 `awaiting_input`，不是 pass。

## 13. 两周实施顺序

| 日期 | 任务 | 可演示成果 |
| --- | --- | --- |
| D1 | T01–T05、T33；确认订阅资格，准备本地模型缓存 | 本地骨架、数据契约、四页空壳、fixture 环境 |
| D2 | T06–T08、T34；开始真实搜索样本和登录授权 spike | 搜索问题得到真实候选 |
| D3 | T09–T14；人工阅读与审核 | 获取原文、批准/拒绝可用 |
| D4 | 先 T16，再 T15、T17–T18；T35–T36 | 获批文档分块入库，失败不会进入查询 |
| D5 | T20–T23；冻结 12 题及参考要点 | 第一条“搜索到带引用回答”路径 |
| D6 | T19、T26；人工将语料扩到至少 10 份 | KB 状态、更新、撤销与历史引用 |
| D7 | T24–T25 | 缺口记录与后续搜索入口 |
| D8 | T27–T29 | 导出、故障恢复、评估工具；功能冻结 |
| D9 | T30–T31 | 完整边界回归及真实人工评估 |
| D10 | T32 | 交付包、运行说明、6–8 分钟 demo |

这是两周目标安排；新增授权工作使 D2/D4 成为主要排期风险。D1–D2 先确认真实订阅资格与最小生成调用，失败则记录阻碍，继续离线部分；不把 fixture 算作真实授权成功。保持 P1 冻结，如授权接入超时必须报告工期偏差。任务大小以一个可独立验证的改动为准，不保证每项固定耗时；如果任务无法在一次审查中理解，按同一编号拆成 A/B 两个子步骤并更新依赖。

## 14. 技术参考与变更管理

官方技术文档查阅于 2026-10-11。参数、结构、限额和排期属于本项目设计，并非供应商承诺。实现时安装兼容版本、锁定依赖并执行小型契约测试。

- [Python sqlite3](https://docs.python.org/3/library/sqlite3.html)：连接与事务行为；项目固定 Python 3.12，编码时使用相应版本文档。
- [Streamlit navigation](https://docs.streamlit.io/develop/api-reference/navigation/st.navigation)：四页导航。
- [Tavily Search](https://docs.tavily.com/documentation/api-reference/endpoint/search)：搜索请求和结果字段。
- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)：受约束输出与异常处理。
- [Sign in with ChatGPT](https://developers.openai.com/siwc/token-sharing-open-source)：本地应用订阅授权；具体子页面见第 3.3 节。
- [BGE model card](https://huggingface.co/BAAI/bge-small-en-v1.5)：英文模型、384 维、512 tokens、query/document 策略。
- [Chroma client](https://docs.trychroma.com/reference/python/client) 与 [metadata filtering](https://docs.trychroma.com/docs/querying-collections/metadata-filtering)：本地索引和查询白名单。
- [pypdf text extraction](https://pypdf.readthedocs.io/en/stable/user/extract-text.html)：文本提取边界。

变更产品范围需记录对 PRD 和验收的影响；正常实现细节由开发者在任务内决定。接口或字段发生变化时同步修改 contracts、本文、任务数据和相关测试；不能让下一张任务卡依赖不存在的方法。
