# GridLens — AI 开发交接

更新日期：2026-10-12（Pacific/Auckland）。这是现有应用的接手入口，
不是从零创建项目的提示词，也不表示完整 MVP 已经实现。

## 1. 先确认工作位置

实际应用根目录（在这里安装、运行测试和改代码）：

```text
/Users/lei/.codex/.chatgpt-projects/g-p-6ac1cd20bc708191b9fcf5adf2a61b2b/gridlens
```

根目录内还有一个 `gridlens/`，那是 Python package。不要把应用放到它里面，
不要再创建 `gridlens/gridlens/gridlens` 项目。父目录是 Seen Ventures 的资料工作区，
父目录 `sources/` 为只读同步资料，不能改动。

阅读顺序：根 `AGENTS.md` → 本文 → `tasks.json` → 对应任务卡和开发规格相关章节。
产品范围查 `00_PRD.md`；实际历史证据查 `progress.md`。
如果文档状态与代码不符，先记录差异，再修正记录，不能假设模块已经存在。

## 2. 当前完成状态

36 项任务中 **24 项 done，4 项 awaiting_input，8 项 todo**。T01–T20、T22–T24、T33 已完成并通过离线验证；
T34/T35/T36/T21 离线完成、等待本人真实登录及其后的会话/目录/生成验证。当前没有遗留的失败检查。

| 已完成 | 当前能力 | 主要文件 |
| --- | --- | --- |
| T01 | 独立本地 Git 项目、Python 3.12 环境、可安装包、锁文件和启动器 | `pyproject.toml`、`requirements.lock`、`run.sh`、`README.md` |
| T02 | 严格 DTO、配置隔离、错误和 provider 协议 | `gridlens/config.py`、`contracts.py`、`errors.py` |
| T03 | 全部初始表/约束、原子迁移、短事务、基础 repository | `gridlens/db.py`、`migrations/001_initial.sql`、`repositories/` |
| T04 | 合成 HTML/PDF、确定性 fake、故障场景与测试环境 | `gridlens/providers/fakes.py`、`tests/fixtures/`、`tests/conftest.py` |
| T05 | Discover / Review / Knowledge Base / Ask & Gaps 导航与空状态 | `app.py`、`gridlens/bootstrap.py`、`gridlens/ui/` |
| T06 | Tavily Search API 适配、稳定错误映射与离线 HTTP 合约测试 | `gridlens/providers/tavily.py`、`tests/unit/test_tavily.py` |
| T07 | 三次调用预算、URL 去重排序、SearchRun/Hit/Source 持久化与操作幂等 | `gridlens/services/discovery.py`、`repositories/sources.py` |
| T08 | Discover 搜索/错误/空状态、候选选择、手动 pending lead 与 Review 交接 | `gridlens/ui/discover.py`、`ui/review.py` |
| T09 | 公开 URL/DNS/重定向边界、流式大小/超时限制与 HTML/PDF 获取 | `gridlens/documents/fetch.py` |
| T10 | HTML 正文清理、标题路径、稳定段落定位及解析限制警告 | `gridlens/documents/html.py` |
| T11 | 可终止子进程中的 PDF 逐页提取、页码定位与稳定格式错误 | `gridlens/documents/pdf.py` |
| T12 | HTML/PDF 不可变原文与段落快照、语义 hash、去重和原子失败清理 | `gridlens/documents/snapshots.py` |
| T13 | 审核 hash/正文校验、approve/reject/revoke/reopen 状态机与事务事件 | `gridlens/services/review.py` |
| T14 | Review 页面：捕获、正文预览、元数据修正、hash 绑定/过期提示、Approve/Reject/Revoke/Reopen 与历史 | `gridlens/ui/review.py`、`providers/fakes.py` |
| T16 | 固定 revision 的本地 BGE embedding（仅本地加载、长度预检、16 批、归一化/维度校验）与显式 `prepare-model` | `gridlens/providers/local_embeddings.py`、`cli.py` |
| T15 | 按页/章节装箱、长段 offset 窗口的确定性 token 分块，index_fingerprint 与 chunk_id | `gridlens/documents/chunking.py` |
| T17 | 本地持久 Chroma：按 fingerprint 的 cosine 集合、显式向量、白名单查询、按版本删除、配置不符报错 | `gridlens/providers/chroma_store.py` |
| T18 | 入库流水线：处理锁、分块、批量 embedding/upsert、ID 集合核对、发布前复查审核、单事务替换 Active；Review 批准后入库与重试 | `gridlens/services/ingestion.py`、`bootstrap.py`、`ui/review.py` |
| T19 | Knowledge Base：三种状态分列、Searchable 仅来自 SQLite、真实阶段/计数、Retry/Revoke | `gridlens/ui/knowledge_base.py` |
| T20 | 仅限批准版本的检索：SQLite 资格 + 已审核元数据筛选、白名单 Top-10、越界丢弃、相邻重叠去重、5 块/4000 tokens、返回前复查 | `gridlens/services/retrieval.py`、迁移 002 |
| T34（awaiting_input） | loopback PKCE 登录、callback/state/nonce/JWKS/issued-ID 校验，全部通过才保存；`gridlens login` | `gridlens/auth/oauth.py`、`cli.py` |
| T35（awaiting_input） | 串行刷新（fcntl 锁、旋转 token 完整替换）、账户选择 epoch 隔离、撤销后清除 tokens 保留注册；`gridlens logout` | `gridlens/auth/sessions.py` |
| T36（awaiting_input） | 侧栏账户/模型选择：账户专属目录（/v1/models，visibility=list）、每次选择只请求一次、换账户清空、plan 权限提示、重新授权/退出/Usage | `gridlens/auth/catalog.py`、`ui/account.py` |
| T21（awaiting_input） | 订阅授权流式回答：字段白名单、证据作数据、schema/prompt-JSON 严格校验、SSE 至 completed、额度/资格/失效错误独立 | `gridlens/providers/chatgpt_oauth.py`、`prompts/answer_v1.txt` |
| T22 | 问答服务：最多两次生成（格式/引用修复一次）、逐字引用校验、发布前复查资格、服务端引用元数据、单事务保存、operation_key 重放 | `gridlens/services/answers.py`、`citations.py` |
| T23 | Ask 页面：问题/地区/类型、已保存记录渲染（rerun 不调用模型）、fact/inference、引用展开（摘录/页码或段落/原链接）、历史与来源状态复查 | `gridlens/ui/ask.py` |
| T24 | 知识缺口：规范 gap_key、open 唯一合并、QA 同事务保存、仅用户关闭（resolve 需说明）、失败不产生缺口 | `gridlens/services/gaps.py` |
| T33 | 稳定 host ID、按注册隔离的受保护原子凭证存储 | `gridlens/auth/host.py`、`credentials.py` |

所有其他任务待实施，包括：真实搜索联调、抓取/解析服务、批准/拒绝操作、
embedding/Chroma、RAG/引用服务、缺口管理/导出、OAuth、模型目录和评估。
Discover 搜索在 fixture 模式可用，live 模式需本地 Tavily key。Review 可捕获、人工审核并在批准后入库（fixture：合成文档 + fake embedding + 持久 Chroma；
live：需先 prepare-model）；
Knowledge Base 与 Ask 已接通（fixture 可完整使用；live 生成需登录与选择模型）。凭证存储实现不等于 OAuth 登录已实现。

## 3. 已验证的基线

本次交接再次执行检查，结果如下：

| 命令 | 结果 |
| --- | --- |
| `.venv/bin/python -m pytest -q` | 298 passed，8 deselected（live/local_model），13s |
| `.venv/bin/ruff check .` | All checks passed |
| `.venv/bin/ruff format --check .` | 92 files already formatted |
| `.venv/bin/python -m pip check` | No broken requirements found |
| `.venv/bin/python -m gridlens.cli doctor` | fixture；搜索 key 未配置；oauth_login live_cli_only_not_verified；模型 prepared `5c38ec7c405e` |
| `.venv/bin/python -m pytest -m local_model -q` | 4 passed（禁网；需本机已 prepare-model；含 live 装配端到端入库） |

Python 3.12.14、Streamlit 1.65.0、Pydantic 2.14.0；完整版本看锁文件。
基础阶段还验证了干净环境安装 wheel、包内迁移资源加载和四页真实浏览器导航。
这些历史检查本次未重复执行，不能写成本次重新安装或浏览器验证。

没有执行真实搜索、真实 ChatGPT 授权/生成、本地 BGE 推理或人工研究验收。
没有真实研究语料、已批准资料、gold 答案或人工分数。合成 JWT/JWKS 和 PDF
只是 fixture，不是真实用户凭证或研究依据。

## 4. 仓库与运行状态

- `origin`：`https://github.com/lynnjeans/gridlens.git`。
- 本地分支：`master`；T13–T20 与 T34–T36、T21（离线实现）已按用户要求提交并推送到 `origin/master`
  （用户指示“Auto, go to the end”：每个任务完成后自动提交推送）。
  后续 Git 操作前先检查 `git status` 与 `git log origin/master..`。
- 没有 PR 或部署。其他电脑可以从 GitHub 仓库 clone 当前实现；输出目录中的
  源码交接 ZIP 仍可用于离线交接。
- 同机已有 `.venv`：从应用根目录运行 `./run.sh`，默认地址
  `http://127.0.0.1:8501`，只绑定本机。已有预览进程可能占用端口，
  启动前检查；不要无依据结束其他进程。也可指定新的本地端口。
- 换机器用 Python 3.12 按根 README 安装。系统默认 Python 曾是 3.9.6，
  不要直接使用它运行本项目。虚拟环境不可作为跨机器安装包。

源码交接 ZIP 包含代码、文档、锁文件和合成测试资料；不含 `.git`、`.venv`、
`.env`、数据库、运行结果或真实凭证，因此不含 Git 历史或远端配置。
GitHub 地址和分支信息已在本文明确记录。解压后复用已有应用目录，
避免覆盖另一份更新的 checkout。

## 5. 下一项工作：T25（T34–T36、T21 真实验证待用户）

T06–T08 的“搜索候选来源并保存”里程碑已经完成：

1. **T06 Tavily adapter 已完成**：离线 HTTP 合约 9 项通过；真实 smoke 因无 key 为 not_run。
2. **T07 discovery service 已完成**：离线单元/集成测试 11 项通过，三次预算、去重、partial/failed 和持久幂等已验证。
3. **T08 Discover UI 已完成**：表单、状态、rerun 幂等、手动来源和 Review 选择通过 UI 测试。

T09–T14 的获取、解析、不可变快照、审核状态机和 Review 页面已完成。
T34 OAuth 登录离线已完成，等待用户本人运行 `APP_MODE=live .venv/bin/python -m gridlens.cli login` 完成真实登录并确认 plan scope
（只记录脱敏结果，AI 不代为登录）。T19、T20 已完成，T35/T36 离线完成。T21 离线完成，T22–T24 完成。下一项 T25 缺口列表与补充搜索入口
（离线可实现，真实验证依赖 T34 登录）。关键路径：T34 → T35 → T36 → T21 → T22。
T18 接好后在 Review 批准成功处触发一次入库。
T34 可以从已完成的 T33/T04 接续实现 OAuth，但不与 discovery 的共享文件
进行未经安排的并发编辑。本交接不要求或启动多代理。

其他重要顺序：**T16 → T15**（真实 tokenizer 先准备）、
**T34 → T35 → T36 → T21**（会话/账户模型选择先于生成），随后 T22/T23。
以 tasks.json 的完整依赖图为准，不能单纯按任务数字执行。

## 6. 实现时容易误判的地方

- `bootstrap.py` 每次渲染构建 container（只读 manifest，不加载模型、不打开 Chroma）。
  fixture 向量存储是 `data/fixture/chroma` 的持久 Chroma；live 仅在 prepare-model 后
  建立 embeddings/vectors/ingestion，answers 仍为 `None`。
- 搜索运行记录已实现。文档版本、问答等表虽已存在，repository 仍只有基础方法；
  CLI prepare-model 已实现；evaluate 与处理锁尚未实现，需要在对应任务添加。
- 若新增缓存，保持 OAuth/search secrets 不进入 UI session/cache keys；
  审核和检索资格不能因缓存而过期。以后对 fake 向量状态的生命周期作显式设计。
- core/dev/auth/embeddings 依赖已安装并锁定（sentence-transformers 6.1.0、torch 2.14.1）；
  `vectors` extra（chromadb 1.5.9）已安装并锁定；Chroma 默认 ONNX 模型不得使用或下载。模型缓存在 git 忽略的 `models/`，
  新机器需运行 `gridlens prepare-model`（下载约 134 MB）后才能跑 local_model 检查。
  `models/gridlens-model.json` 记录 revision `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a`。
- 本地 BGE 默认英文 384 维、350/50 分块；按其实际 tokenizer 计数，
  固定 revision、query prefix/normalization，禁止静默截断或自动下载。
- ChatGPT 调用方案已在开发规格中约定，尚无真实账户验证；接入时重新查官方文档，
  不硬编码旧模型、不使用私有端点、不将 API 平台能力自动套到订阅路由。
- 凭证存储使用 POSIX 权限与 fcntl，已验证 macOS，Windows 尚不支持。
- 不自动批准真实来源；generation 的 failed/incomplete/断流不能成为可信答案
  或知识缺口。引用与资格检查必须位于服务端。

## 7. 可复制的接手提示词

```text
请接手已有 GridLens 项目，完成 T25 缺口列表与补充搜索入口（T34–T36、T21 等待用户真实登录）。
先读取根 AGENTS.md、docs/HANDOFF.md、docs/tasks.json 和对应任务卡，
再检查真实代码及开发规格相关章节。
T01–T20、T22–T24、T33 已完成，请复用现有项目，不再初始化，不用空远端覆盖本地代码。
按依赖顺序实现并验证，保持 fixture/live 隔离、有限调用预算和 UI rerun 幂等。
抓取与解析先用离线 HTTP/DNS fixture 完成；真实任意网站不作为单元验收条件。
不要索要聊天中的密钥，不自动批准资料，不虚构研究评估，不增加 P1。
记录真实修改和验证结果，同步 tasks.json、任务卡、progress.md 和 HANDOFF.md。
本次工作范围是搜索里程碑，不包含推送远端、部署或消息发送。
```

接手者只有收到用户的实际开发指示后才执行提示词。完成任务后更新交接摘要，
不要让后续 AI 再从已经完成的里程碑开始。

## 8. 用户长期约定：每个功能后自动同步文档

每完成一个功能或任务，在汇报完成或进入下一功能之前，自动同步
`tasks.json`、对应任务卡、`progress.md` 和本交接文档，无需等用户再次提醒。
写明实际状态、修改文件、验证结果、未运行检查、限制与下一任务。
未完成、等待输入或验证失败也要记录实际状态和原因，不能提前标为 done。
接口、行为或安装方式变化时同时更新开发规格和根 README。
当前工作区仍有输出文档镜像与交接 ZIP 时一并刷新，不纳入环境、运行数据或真实凭证。
这是开发过程中的同步规则，不是定时任务，也不授权自动推送 GitHub。
