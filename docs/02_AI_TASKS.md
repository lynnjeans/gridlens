# GridLens AI 开发任务清单

版本：1.1 | 日期：2026-10-11 | 36 个 P0 任务 | 14 项已完成（T01–T13、T33），22 项待实施。

本地 Streamlit 网页；ChatGPT OAuth 订阅生成；本地 BGE embedding。T01–T32 保留编号，新增 T33–T36 处理授权；按依赖执行，不按编号机械执行。路径均相对于现有应用根目录；基础阶段已经实现，当前交接入口见 HANDOFF.md。

`tasks.json` 是机器主清单；修改任务/状态同步本阅读版。实际证据写入应用 docs/progress.md；离线、真实服务与人工验证分开。

## 任务总览

| ID | 任务 | 建议日程 | 前置任务 | 类别 | 状态 |
| --- | --- | --- | --- | --- | --- |
| T01 | 初始化独立仓库与可安装项目 | D1 | 无 | implementation | done |
| T02 | 定义配置、DTO、错误码和端口接口 | D1 | T01 | implementation | done |
| T03 | 建立 SQLite schema 和基础 repository | D1 | T02 | implementation | done |
| T04 | 建立合成资料与 Fake Providers | D1 | T02 | implementation | done |
| T05 | 建立四页 UI 导航与依赖组装 | D1 | T02, T04 | implementation | done |
| T06 | 实现 Tavily 搜索适配器 | D2 | T02, T04 | implementation | done |
| T07 | 实现搜索编排、排序与去重保存 | D2 | T03, T06 | implementation | done |
| T08 | 接通 Discover 页面 | D2 | T05, T07 | implementation | done |
| T09 | 实现有边界的公开 URL 获取 | D3 | T02, T04 | implementation | done |
| T10 | 实现 HTML 正文与段落定位 | D3 | T02, T04 | implementation | done |
| T11 | 实现 PDF 提取与页码定位 | D3 | T02, T04 | implementation | done |
| T12 | 保存可审核的不可变文档快照 | D3 | T03, T09, T10, T11 | implementation | done |
| T13 | 实现审核状态机与即时撤销 | D3 | T03, T12 | implementation | done |
| T14 | 接通 Review 页面 | D3 | T05, T13 | implementation | todo |
| T15 | 实现确定性 token 分块 | D4 | T02, T12, T16 | implementation | todo |
| T16 | 实现本地 embedding 与模型准备 | D4 | T02, T04 | implementation | todo |
| T17 | 实现 Chroma 向量存储适配器 | D4 | T02, T03, T04 | implementation | todo |
| T18 | 实现入库流水线与原子发布 | D4 | T13, T14, T15, T16, T17 | implementation | todo |
| T19 | 接通 Knowledge Base 页面 | D6 | T05, T18 | implementation | todo |
| T20 | 实现仅限批准版本的检索 | D5 | T18 | implementation | todo |
| T21 | 实现订阅授权的流式回答 Provider | D5 | T02, T04, T35, T36 | implementation | todo |
| T22 | 实现问答服务、引用校验与保存 | D5 | T20, T21 | implementation | todo |
| T23 | 接通 Ask 与引用查看 | D5 | T05, T22 | implementation | todo |
| T24 | 实现知识缺口规则、保存与去重 | D7 | T03, T22 | implementation | todo |
| T25 | 接通缺口列表与补充搜索入口 | D7 | T08, T23, T24 | implementation | todo |
| T26 | 补齐刷新版本与历史引用状态 | D6 | T19, T23 | implementation | todo |
| T27 | 实现 Markdown research log 导出 | D8 | T24, T26 | implementation | todo |
| T28 | 实现中断恢复、调用限额与运行记录 | D8 | T18, T22 | implementation | todo |
| T29 | 建立 15 题与评估运行工具 | D8 | T22, T24 | implementation | todo |
| T30 | 执行完整闭环与可信性回归 | D9 | T14, T19, T23, T25, T26, T27, T28, T29, T36 | implementation | todo |
| T31 | 完成真实语料与人工评估验收 | D9 | T06, T16, T21, T29, T30 | human_gated_acceptance | todo |
| T32 | 整理运行说明、限制和 demo 交付 | D10 | T30, T31 | delivery | todo |
| T33 | 建立本机注册与受保护凭证存储 | D1 | T02 | implementation | done |
| T34 | 实现OAuth登录和callback校验 | D2 | T33, T04 | implementation | todo |
| T35 | 实现刷新、账户切换与退出 | D4 | T34 | implementation | todo |
| T36 | 接通账户侧栏和可用模型目录 | D4 | T05, T35 | implementation | todo |

## 使用规则

- 每次一项或用户明确授权的里程碑；以依赖和真实代码为准。
- 不自动批准真实来源，不虚构人工评分，不把fixture当live验收。
- API key只用于独立搜索服务；ChatGPT凭证通过官方OAuth，不粘贴到聊天或任务记录。
- 本地模型初次下载显式进行，常规运行/离线测试不隐式联网。
- 合成凭证用于mock；真实OAuth/模型调用的检查需实际执行并脱敏记证据。
- 文件范围可因共享契约而合理补充，同时同步消费者和文档。

## T01 — 初始化独立仓库与可安装项目

**优先级/状态：** P0 / done
**日程/类别：** D1 / implementation
**依赖：** 无
**PRD 对应：** AC-10
**所需输入：** 目标应用目录；若未指定，使用工作区下独立 gridlens 目录并在记录中说明。

**目标：** 建立可继续开发的独立本地项目，不在 ChatGPT 同步 sources 目录里写应用。

### 文件范围

- `pyproject.toml`
- `requirements.lock`
- `.gitignore`
- `.env.example`
- `README.md`
- `gridlens/__init__.py`
- `docs/`

### 实现步骤

1. 检查指定工作目录和现有 Git 状态；若已有实现先复用，避免嵌套仓库。
2. 建立 Python 3.12 环境、最小 package、开发依赖与可重复安装的锁文件。
3. 复制开发文档和 PRD 到 docs；忽略 .env、data、artifacts、.venv，保留 .env.example。
4. 为本地模型、OAuth/JWT 校验与 Responses streaming 选择兼容依赖并锁定；忽略凭证与模型缓存，不把 tokens 放入 .env.example。

### 完成条件

- 全新环境可按 README 安装并 import gridlens。
- 无真实密钥、数据库或运行快照被纳入 Git；原 PRD 与 sources 未被改写。
- 本地 Git 状态可检查；远端仓库不是本任务完成前提。

### 验证要求

- 执行 import、依赖一致性和 Ruff 配置检查。
- 人工检查 git status 与忽略规则；不为 README 或空 package 写单元测试。

### 范围外

- 不创建/推送 GitHub 仓库，除非用户已给出目标及授权。
- 不实现业务页面或先安装全部无关框架。

**验证状态：** offline=passed, live=not_required, human=not_required

**执行证据：** docs/progress.md；离线验证已通过，真实授权/研究验收未执行。

## T02 — 定义配置、DTO、错误码和端口接口

**优先级/状态：** P0 / done
**日程/类别：** D1 / implementation
**依赖：** T01
**PRD 对应：** AC-03, AC-05, AC-09
**所需输入：** 无需外部凭证；使用合成 fixture。

**目标：** 使后续任务共同使用明确输入输出和配置，不各自发明数据结构。

### 文件范围

- `gridlens/config.py`
- `gridlens/contracts.py`
- `gridlens/errors.py`
- `.env.example`
- `tests/unit/test_contracts.py`

### 实现步骤

1. 按开发规格定义状态枚举、SearchHitDTO、ParsedSegment、Locator、ChunkDTO、AnswerDraft 和端口 Protocol。
2. 实现 fixture/live 配置隔离、限额校验和按功能检查缺失密钥。
3. 固定 AppError 格式、JSON extra=forbid 和 nullable 字段。
4. 新增 AccountSummary/AuthState/ModelChoice 与 CredentialStore/SessionProvider 接口；embedding role、revision、归一化和 tokenizer 配置按规格固定，错误区分授权、额度、缓存与证据不足。

### 完成条件

- 缺少真实密钥仍可加载 fixture 配置。
- overlap>=chunk size、负限额、未知状态和额外模型字段会被拒绝。
- AnswerDraft 的 answered/partial/insufficient 与 claims/missing_evidence 关系可校验。

### 验证要求

- 契约边界测试：非法枚举、空字段、状态组合、配置模式。
- Ruff；不要测试 Pydantic 自身的普通字段赋值。

### 范围外

- 不实现外部 API 或数据库。
- 不选用未明确配置的生成模型。

**验证状态：** offline=passed, live=not_required, human=not_required

**执行证据：** docs/progress.md；离线验证已通过，真实授权/研究验收未执行。

## T03 — 建立 SQLite schema 和基础 repository

**优先级/状态：** P0 / done
**日程/类别：** D1 / implementation
**依赖：** T02
**PRD 对应：** AC-04, AC-09, AC-10
**所需输入：** 无需外部凭证；使用合成 fixture。

**目标：** 实现规格中的实体、约束、迁移和可靠持久化，提供后续 repository 方法的基础。

### 文件范围

- `gridlens/db.py`
- `gridlens/migrations/001_initial.sql`
- `gridlens/repositories/`
- `gridlens/cli.py`
- `tests/integration/test_db.py`

### 实现步骤

1. 创建全部最小表、外键、状态 CHECK 和 unique/partial indexes；EvaluationRecord 留文件存储。
2. 实现连接生命周期、显式事务、init-db、migration version 记录和常用读写。
3. 添加 eligibility 查询入口，方法通过事务或注入连接组合；不在 repository 内联网。

### 完成条件

- 初始化重复执行不丢数据；关闭后重开仍有记录。
- 同来源不能同时有两个 Active；open gap key 不重复；失效外键被拒绝。
- 失败事务回滚；参数化输入不能改变 SQL 结构。

### 验证要求

- 临时 SQLite 中验证唯一约束、FK、rollback 和重启读取。
- init-db 冒烟；测试只用临时目录。

### 范围外

- 不使用删库重建代替迁移。
- 不在此实现所有未来 UI 查询的抽象层。

**验证状态：** offline=passed, live=not_required, human=not_required

**执行证据：** docs/progress.md；离线验证已通过，真实授权/研究验收未执行。

## T04 — 建立合成资料与 Fake Providers

**优先级/状态：** P0 / done
**日程/类别：** D1 / implementation
**依赖：** T02
**PRD 对应：** AC-03, AC-09, AC-10
**所需输入：** 无需外部凭证；使用合成 fixture。

**目标：** 为所有后续任务提供可复现、默认不出网的输入。

### 文件范围

- `gridlens/providers/fakes.py`
- `tests/conftest.py`
- `tests/fixtures/`
- `tests/unit/test_fakes.py`

### 实现步骤

1. 准备合成 HTML、两页文本 PDF、扫描/损坏 PDF、重复 URL、新旧版本和来源指令干扰样本。
2. 实现确定性搜索、embedding、回答 fake；支持超时、429、无效引用、截断等故障开关。
3. 所有样本写 synthetic 标记；测试默认阻断网络。
4. 补充 OAuth state/nonce/JWKS/issued-ID、refresh rotation、model catalog、SSE completed/failed/incomplete/断流合成 mocks，不记录真实 token。

### 完成条件

- 相同输入产生相同 fake 输出；可准确触发指定故障。
- 每个 PDF 的预期页数、可读文本和定位记录在 fixture manifest。
- fixtures 与 live 存储隔离，不冒用真实出版机构。

### 验证要求

- fixture manifest 校验及 fake 输出契约检查。
- 一次意外外部请求被测试环境拒绝。

### 范围外

- 不把 fake 成功算作真实搜索或模型联调。
- 不构建通用模拟服务平台。

**验证状态：** offline=passed, live=not_required, human=not_required

**执行证据：** docs/progress.md；离线验证已通过，真实授权/研究验收未执行。

## T05 — 建立四页 UI 导航与依赖组装

**优先级/状态：** P0 / done
**日程/类别：** D1 / implementation
**依赖：** T02, T04
**PRD 对应：** AC-09, AC-10
**所需输入：** 无需外部凭证；使用合成 fixture。

**目标：** 建立可启动的应用入口，四个页面共用同一服务配置。

### 文件范围

- `app.py`
- `gridlens/bootstrap.py`
- `gridlens/ui/`
- `tests/ui/test_navigation.py`

### 实现步骤

1. 用 st.navigation/st.Page 建 Discover、Review、Knowledge Base、Ask & Gaps 页面。
2. 实现 fixture/live 模式标识、页面选择和公共错误/状态组件。
3. 只保存 UI session state；未完成模块显示空状态，不伪装成已经可用。

### 完成条件

- 四页可切换，刷新不调用搜索或模型。
- 缺少凭证时应用仍可启动；真实功能有明确配置提示。
- 页面不直接调用供应商 SDK 或写审核状态。

### 验证要求

- 启动并逐页人工检查或使用 AppTest。
- 检查 bootstrap 可注入 fake provider。

### 范围外

- 不做视觉精修、登录或 dashboard。

**验证状态：** offline=passed, live=not_required, human=not_required

**执行证据：** docs/progress.md；离线验证已通过，真实授权/研究验收未执行。

## T06 — 实现 Tavily 搜索适配器

**优先级/状态：** P0 / done
**日程/类别：** D2 / implementation
**依赖：** T02, T04
**PRD 对应：** AC-01
**所需输入：** 离线实现无需密钥；真实 smoke 需要 TAVILY_API_KEY。

**目标：** 把一个真实搜索 API 映射成统一候选结构。

### 文件范围

- `gridlens/providers/tavily.py`
- `tests/unit/test_tavily.py`
- `tests/live/test_search_provider.py`

### 实现步骤

1. 按规格配置 basic/general 和禁用生成答案、raw content、自动参数。
2. 映射 title/url/content/rank；未知 publisher/date 为 null；保留必要 provider metadata。
3. 将 401/429/5xx/timeout 转稳定错误；适配器不自行无限重试。

### 完成条件

- 请求参数与结果映射可通过 mock HTTP 校验。
- 空结果为成功空列表；服务错误不是空结果。
- 单次调用不隐式获取正文、不产生自动答案。

### 验证要求

- HTTP 契约测试覆盖成功、空列表、畸形记录、认证失败和限流。
- 有凭证时一次显式 live smoke；否则记录尚未运行。

### 范围外

- 不实现第二家搜索服务。
- 不自动购买配额。

**验证状态：** offline=passed, live=not_run, human=not_required

**执行证据：** `tests/unit/test_tavily.py` 9 项通过；覆盖正式请求参数、字段映射、空/畸形结果、HTTP/timeout 错误和无隐式重试。Ruff 通过。真实 Tavily smoke 因未配置 key 未运行。

## T07 — 实现搜索编排、排序与去重保存

**优先级/状态：** P0 / done
**日程/类别：** D2 / implementation
**依赖：** T03, T06
**PRD 对应：** AC-01, AC-09
**所需输入：** 无需外部凭证；使用合成 fixture。

**目标：** 用户一次操作得到最多十条真实候选，并能追踪搜索过程。

### 文件范围

- `gridlens/services/discovery.py`
- `gridlens/repositories/research.py`
- `tests/unit/test_discovery.py`
- `tests/integration/test_search_runs.py`

### 实现步骤

1. 用规则生成最多三条保留问题含义的搜索 query。
2. 规范 URL、合并重复、稳定排序、最多保留十条，保存 Source/SearchHit/SearchRun。
3. 所有调用含重试共计最多三次，支持 partial/failed，使用 operation_key 防重复提交。

### 完成条件

- 相同提交 key 重放不再次调用 provider。
- 功能参数被保留，跟踪参数可去除；同一结果在单次搜索不重复出现。
- 部分服务失败保留成功结果与原因；未知日期不伪造。

### 验证要求

- 重复 URL、有效 query 参数、少结果、多结果与部分失败测试。
- 验证三次总调用预算和持久化字段。

### 范围外

- 不做 LLM 搜索词规划或全网爬虫。

**验证状态：** offline=passed, live=not_required, human=not_required

**执行证据：** discovery 单元与 search run 集成测试共 11 项通过；覆盖三次查询预算、功能参数保留、追踪参数清理、重复 URL、稳定排序、十条上限、partial/failed、持久化及 operation_key 跨服务重放。

## T08 — 接通 Discover 页面

**优先级/状态：** P0 / done
**日程/类别：** D2 / implementation
**依赖：** T05, T07
**PRD 对应：** AC-01, AC-02
**所需输入：** 无需外部凭证；使用合成 fixture。

**目标：** 用户可输入主题、启动搜索、打开候选并手动添加 URL。

### 文件范围

- `gridlens/ui/discover.py`
- `gridlens/ui/common.py`
- `tests/ui/test_discover.py`

### 实现步骤

1. 实现表单、地区/类型筛选、loading 和错误提示。
2. 候选显示标题、机构、日期、摘要依据、相关性理由、原始链接。
3. 手动 URL 经服务保存为待审核线索；选择候选把 source_id 带到 Review。

### 完成条件

- 一次 Search 提交仅触发一次 operation。
- 无结果、partial、failed、缺凭证显示不同状态。
- 手动来源不自动批准、抓取或入库。

### 验证要求

- fixture 模式操作主路径与错误路径。
- 检查 rerun 不重复搜索及输入校验。

### 范围外

- 不做批量审核或复杂筛选器。

**验证状态：** offline=passed, live=not_required, human=not_required

**执行证据：** Discover 与导航 UI 测试 10 项通过；覆盖搜索/刷新幂等、候选展示与选择、Review 接收来源、手动 pending lead、输入/缺 key 错误和 empty/partial/failed 状态。完整回归 67 passed、1 live deselected；Ruff/format/pip check 通过。

## T09 — 实现有边界的公开 URL 获取

**优先级/状态：** P0 / done
**日程/类别：** D3 / implementation
**依赖：** T02, T04
**PRD 对应：** AC-02, AC-03, AC-09
**所需输入：** 无需外部凭证；使用合成 fixture。

**目标：** 取得可审核的原始 HTML/PDF，限制网络目标和资源消耗。

### 文件范围

- `gridlens/documents/fetch.py`
- `tests/unit/test_fetch.py`

### 实现步骤

1. 校验 URL、DNS 结果、scheme/port/userinfo；拒绝私网和保留地址。
2. 手动处理最多三跳 redirect，每一跳重新检查；设置总超时和流式体积上限。
3. 记录 final URL、content type、抓取时间和 raw SHA256；响应错误统一映射。

### 完成条件

- localhost、IPv4/IPv6 私网、私网重定向均不继续请求。
- 超大或解压后超限数据中止；超时有明确信息。
- 正常公开 HTML/PDF 可返回受限 bytes 和 metadata。

### 验证要求

- 用 HTTP mock 与 DNS stub 检查每跳目标、大小和超时。
- 不依赖实时任意网站验证本单元任务。

### 范围外

- 不绕过登录、执行网页脚本或承诺生产级 DNS 对抗隔离。

**验证状态：** offline=passed, live=not_required, human=not_required

**执行证据：** `tests/unit/test_fetch.py` 24 项通过；覆盖 URL/DNS/端口/IPv4/IPv6 私网、每跳 redirect、三跳上限、HTML/PDF、压缩后与流式大小、总 timeout 和 HTTP 错误。完整回归 91 passed、1 live deselected；Ruff/format 通过。

## T10 — 实现 HTML 正文与段落定位

**优先级/状态：** P0 / done
**日程/类别：** D3 / implementation
**依赖：** T02, T04
**PRD 对应：** AC-02, AC-03, AC-06
**所需输入：** 无需外部凭证；使用合成 fixture。

**目标：** 从 HTML 得到可审核、可引用的正文段落。

### 文件范围

- `gridlens/documents/html.py`
- `tests/unit/test_html_parser.py`

### 实现步骤

1. 优先 main/article，回退内容段落；去除脚本、导航、样式。
2. 保存标题路径、稳定 paragraph_index 和正文；保留数字、单位、条件与 Unicode。
3. 返回提取警告，正文为空报错；不把网页指令当成程序指令。

### 完成条件

- 两种布局 fixture 均可得到预期正文而不含导航噪声。
- 每个片段能映射章节/段落；同输入解析结果确定。
- 不支持内容有警告，不能返回搜索摘要假装正文。

### 验证要求

- 正文完整性、标题和段落定位、空正文用例。
- 包含恶意指令文字时仅保留为文本。

### 范围外

- 不做浏览器渲染、OCR 或完整表格重建。

**验证状态：** offline=passed, live=not_required, human=not_required

**执行证据：** `tests/unit/test_html_parser.py` 5 项通过；覆盖 main/article/body fallback、噪声移除、标题路径、段落定位、Unicode/数字、表格警告、空正文和指令干扰。完整回归 96 passed、1 live deselected；Ruff/format 通过。

## T11 — 实现 PDF 提取与页码定位

**优先级/状态：** P0 / done
**日程/类别：** D3 / implementation
**依赖：** T02, T04
**PRD 对应：** AC-03, AC-06, AC-09
**所需输入：** 无需外部凭证；使用合成 fixture。

**目标：** 支持文本 PDF，并明确拒绝或标注不能可靠解析的内容。

### 文件范围

- `gridlens/documents/pdf.py`
- `tests/unit/test_pdf_parser.py`

### 实现步骤

1. 用 pypdf 逐页提取；file_page 从 1 开始，不等同于印刷页码。
2. 限制页数和解析耗时；用可终止子进程隔离异常解析。
3. 空文本、扫描件、损坏/加密文件给稳定错误；复杂布局记录限制。

### 完成条件

- 两页 fixture 的文本和对应 file_page 准确。
- 扫描件不被判为成功正文；超限和损坏文件不会卡死主应用。
- 解析不重新编号或合并丢失页面来源。

### 验证要求

- 文本 PDF、扫描 PDF、损坏 PDF、页数超限测试。
- 超时用受控解析 stub 验证，不依赖真实卡死文件。

### 范围外

- 不加 OCR，不声称自动保证复杂表格正确。

**验证状态：** offline=passed, live=not_required, human=not_required

**执行证据：** `tests/unit/test_pdf_parser.py` 6 项通过；覆盖两页文本/file_page、确定性、扫描件、损坏/加密 PDF、页数限制和可终止超时子进程。完整回归 102 passed、1 live deselected；Ruff/format/pip check 通过。

## T12 — 保存可审核的不可变文档快照

**优先级/状态：** P0 / done
**日程/类别：** D3 / implementation
**依赖：** T03, T09, T10, T11
**PRD 对应：** AC-02, AC-03, AC-09
**所需输入：** 无需外部凭证；使用合成 fixture。

**目标：** 把原始抓取和解析正文绑定成有稳定 hash 的版本。

### 文件范围

- `gridlens/documents/snapshots.py`
- `gridlens/repositories/sources.py`
- `tests/integration/test_snapshots.py`

### 实现步骤

1. 实现 capture 流程、类型分发、受控路径及 temp file → atomic rename。
2. 按规范算法计算 snapshot_sha256，保存 metadata、segments 和 extraction notes。
3. 同来源同快照复用版本；不同快照 Candidate/Pending；未取到正文只保留失败线索。

### 完成条件

- 重复 capture 不多建版本；仅抓取时间变化不影响快照 hash。
- 影响引用的 metadata 变化形成不同审核快照。
- 目录路径不接受用户文件名拼接；失败不产生可批准的半文件。

### 验证要求

- 重抓去重、内容变化、元数据变化和写文件失败测试。
- 验证原文文件、数据库记录和 hash 一致。

### 范围外

- 不做 embedding，也不修改已批准快照。

**验证状态：** offline=passed, live=not_required, human=not_required

**执行证据：** `tests/integration/test_snapshots.py` 6 项通过；覆盖 HTML/PDF 分发、文件/DB/hash 一致、时间/导航无关去重、正文/审核元数据变化、原子写失败清理和抓取失败线索。完整回归 108 passed、1 live deselected；Ruff/format/pip check 通过。

## T13 — 实现审核状态机与即时撤销

**优先级/状态：** P0 / done
**日程/类别：** D3 / implementation
**依赖：** T03, T12
**PRD 对应：** AC-02, AC-04, AC-09
**所需输入：** 无需外部凭证；使用合成 fixture。

**目标：** 用服务端规则控制来源资格，并保存人工决定。

### 文件范围

- `gridlens/services/review.py`
- `gridlens/repositories/sources.py`
- `tests/integration/test_review.py`

### 实现步骤

1. 实现 approve/reject/reopen/revoke，校验允许状态、预览 expected_hash 和正文；reopen 清空批准 hash 并重置 Candidate/Not started。
2. 批准保存 approved_snapshot_sha256；拒绝需 reason；事件与状态同事务提交。
3. 撤销即时改变 SQLite 资格；后续索引清理可独立失败。

### 完成条件

- 没有可读正文、hash 过期、非法状态不能批准。
- 重复相同操作幂等；重新开启后必须再人工批准并重新入库，不能继承旧 Ready 资格。
- 撤销提交后 eligibility 查询立即排除该来源。

### 验证要求

- 完整合法状态转移与关键非法转移测试。
- 事务失败 rollback、重复批准、撤销后资格与重新开启后重新入库检查。

### 范围外

- 不自动批准真实来源，不伪造 reviewer。

**验证状态：** offline=passed, live=not_required, human=not_required

**执行证据：** `tests/integration/test_review.py` 6 项通过；覆盖 approve/reject/revoke/reopen、hash/正文完整性、原因/审核人、幂等、非法状态、即时资格排除和事务回滚。完整回归 114 passed、1 live deselected；Ruff/format/pip check 通过。

## T14 — 接通 Review 页面

**优先级/状态：** P0 / done
**日程/类别：** D3 / implementation
**依赖：** T05, T13
**PRD 对应：** AC-02
**所需输入：** 无需外部凭证；使用合成 fixture。

**目标：** 用户可查看对应正文和版本，然后明确批准或拒绝。

### 文件范围

- `gridlens/ui/review.py`、`gridlens/ui/common.py`
- `gridlens/services/review.py`（`load_snapshot`、`update_metadata`）、`gridlens/repositories/research.py`（审核历史）
- `gridlens/contracts.py`（`MetadataCorrection`）、`gridlens/bootstrap.py`、`gridlens/providers/fakes.py`（`FakeDocumentFetcher`）
- `tests/ui/test_review_page.py`（原定 `tests/ui/test_review.py` 与集成测试同名冲突）

### 实现步骤

1. 展示候选列表、正文预览、元数据修正、提取限制和原链接。
2. 保存待审核字段后更新快照 hash；动作绑定用户当前看到的 hash。
3. 批准成功后显示已批准状态；入库服务接好后再触发一次入库，错误不改成人工拒绝。

### 完成条件

- Reject 无理由无法提交；不可读正文不能批准。
- 预览过期时要求重新查看，不批准后台已经改变的内容。
- 刷新页面不重复审核或创建事件。

### 验证要求

- AppTest 或人工 fixture 流程：approve/reject/stale/unreadable。
- 检查 reviewer 标签与用户输入准确保存。

### 范围外

- 不批量审核，不增加登录系统。

**验证状态：** offline=passed, live=not_required, human=not_required

**执行证据：** `tests/ui/test_review_page.py` 8 项 AppTest 通过：capture/预览/approve、reviewer 必填、reject 原因必填且原文保存、stale 预览需重新加载、不可读快照禁止批准、空文档不建版本、元数据修正改 hash 并绑定批准、revoke/reopen、rerun 不重复事件。`tests/integration/test_review.py` 7 项通过（含元数据修正）。完整回归 123 passed、1 live deselected；Ruff/format/pip check 通过。未执行真实浏览器手动检查；批准后入库触发待 T18。

## T15 — 实现确定性 token 分块

**优先级/状态：** P0 / done
**日程/类别：** D4 / implementation
**依赖：** T02, T12, T16
**PRD 对应：** AC-03, AC-04, AC-06
**所需输入：** 无需外部凭证；使用合成 fixture。

**目标：** 将已审核正文切成带稳定定位的可重建片段。

### 文件范围

- `gridlens/documents/chunking.py`
- `gridlens/contracts.py`（ChunkDTO 字段、Tokenizer 协议）、`gridlens/providers/local_embeddings.py`（identity/token_offsets）、`gridlens/providers/fakes.py`（FakeTokenizer）
- `tests/unit/test_chunking.py`、`tests/local_model/test_local_chunking_smoke.py`

### 实现步骤

1. 使用固定本地 embedding tokenizer 按页/段落组合，长段落 token 窗口分割；初始 350/50，含标题/special tokens 不超512。
2. 计算 index_fingerprint、text hash 和确定性 chunk_id。
3. 保留 locator 与 segment IDs；不跨页、跨文档或跨版本。

### 完成条件

- 所有块在预算内、没有空块，正文覆盖满足 overlap 规则。
- 同输入同配置 IDs 一致；模型/切分配置变化 fingerprint 改变。
- 长 Unicode 段落仍可溯源，文件页序不丢失。
- 模型/tokenizer revision、query prefix 和 normalization 变化也会改变 fingerprint；检索问题超长时拒绝而不 truncate。

### 验证要求

- 短文、长段、跨页、中文/英文 token 边界和确定性测试。
- 验证拼接/overlap 不遗漏非空原文段落。

### 范围外

- 不调研高级语义 chunker，不用字符数冒充 token 数。

**验证状态：** offline=passed, local_model=passed, live=not_required, human=not_required

**执行证据：** `tests/unit/test_chunking.py` 14 项通过（短文、长段窗口与 overlap、跨页/章节、中英文、覆盖、确定性与 fingerprint 变化、非法配置）。禁网真实 BGE tokenizer（350/50）smoke 1 项通过：15 块、最大 350 tokens、全部成功 embedding。完整回归 154 passed、4 deselected；Ruff/format/pip check 通过。尚未接入入库（T18）。

## T16 — 实现本地 embedding 与模型准备

**优先级/状态：** P0 / done
**日程/类别：** D4 / implementation
**依赖：** T02, T04
**PRD 对应：** AC-03, AC-04
**所需输入：** 离线 mock 无凭证；实际模型 smoke 需首次下载的固定本地模型缓存，无 ChatGPT 登录或平台 key。

**目标：** 用固定本地缓存模型生成文档和查询向量，正常推理不出网。

### 文件范围

- `gridlens/providers/local_embeddings.py`
- `gridlens/cli.py`（`prepare-model`、doctor 模型状态）、`gridlens/config.py`（`LOCAL_MODEL_DIR`）
- `pyproject.toml`（`embeddings`/`vectors` extra）、`requirements.lock`、`.env.example`
- `tests/unit/test_embeddings.py`
- `tests/local_model/test_local_embeddings_smoke.py`（原定文件名与单元测试同名冲突）

### 实现步骤

1. 提供显式 prepare-model 步骤，下载 BAAI/bge-small-en-v1.5，记录实际 revision 和 tokenizer revision；运行时 local_files_only=true、trust_remote_code=false。
2. CPU 归一化推理384维，最多16项一批；document/query role 采用同一权重和不同 prefix 策略；长度先检查。
3. 校验数量、维度、有限数值和顺序，返回本地耗时/token count，不伪造 API usage。

### 完成条件

- 缺缓存、输入过长、维度错误或空文本不返回成功批次；绝不静默下载/截断/换模型。
- 固定配置同输入输出可复现；fixture 与实际本地模型隔离。
- 文档和问题 fingerprint 一致，query prefix 不污染原文引用。

### 验证要求

- 离线 mock 验证缓存缺失、role、长度、有限数值和批次顺序。
- 模型显式准备后在禁网环境做真实本地 smoke，记录实际384维与revision；此检查不等于 ChatGPT live 验证。

### 范围外

- 不使用私有 backend-api、浏览器 cookies 或共享他人的 tokens；不部署公网。

**验证状态：** offline=passed, local_model=passed, live=not_required, human=not_required

**执行证据：** `tests/unit/test_embeddings.py` 17 项通过（缓存缺失、role/prefix、长度、有限数值、批次顺序、维度、本地-only loader、prepare-model）。经用户批准下载 sentence-transformers 6.1.0 依赖并锁定，`gridlens prepare-model` 下载 bge-small-en-v1.5（10 文件 134.4 MB）revision `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a`。禁网 `pytest -m local_model` 2 项通过：384 维、512 tokens、归一化、可复现、超长拒绝。完整回归 140 passed、3 deselected；Ruff/format/pip check 通过。provider 尚未接入入库（T18）。

## T17 — 实现 Chroma 向量存储适配器

**优先级/状态：** P0 / done
**日程/类别：** D4 / implementation
**依赖：** T02, T03, T04
**PRD 对应：** AC-03, AC-04, AC-09
**所需输入：** 无需外部凭证；使用合成 fixture。

**目标：** 提供可持久化、可白名单查询且幂等的向量存储。

### 文件范围

- `gridlens/providers/chroma_store.py`
- `tests/integration/test_vector_store.py`
- `pyproject.toml`/`requirements.lock`（vectors extra：chromadb 1.5.9）

### 实现步骤

1. 以 fingerprint 创建/打开本地集合，显式关闭默认 embedding function。
2. 实现 upsert/query/stored_ids/delete_version，传入显式 embeddings。
3. query 强制要求非空 eligible_version_ids，空集直接空结果，禁止退化为全库检索。

### 完成条件

- 同 ID upsert 不增加重复记录；重开后仍能检索。
- 查询只返回白名单版本；配置 mismatch 明确报错。
- metadata 不携带假定审核资格，返回正文以数据库为准。

### 验证要求

- 用临时真实 Chroma 和合成向量验证持久化、过滤、删除。
- 检查没有调用外部模型或下载默认 embedding。

### 范围外

- 不使用 Chroma Cloud，不开发多租户。

**验证状态：** offline=passed, live=not_required, human=not_required

**执行证据：** 经用户批准安装 chromadb 1.5.9（38 个新依赖，既有锁定不变）。`tests/integration/test_vector_store.py` 9 项通过（临时真实 Chroma、禁网）：幂等 upsert、重开持久化、cosine、白名单过滤、空白名单返回空、按版本删除、仅标识 metadata、配置不符报错、非法写入、懒加载；默认 embedding function 禁止调用，未生成 ~/.cache/chroma。完整回归 163 passed、4 deselected；Ruff/format/pip check 通过。尚未接入入库（T18）。

## T18 — 实现入库流水线与原子发布

**优先级/状态：** P0 / done
**日程/类别：** D4 / implementation
**依赖：** T13, T14, T15, T16, T17
**PRD 对应：** AC-03, AC-04, AC-09
**所需输入：** 无需外部凭证；使用合成 fixture。

**目标：** 只有完整处理完成且仍获批准的版本才成为 Ready/Active。

### 文件范围

- `gridlens/services/ingestion.py`、`gridlens/contracts.py`（IngestionResult）、`gridlens/bootstrap.py`
- `gridlens/ui/review.py`（批准后入库、Retry indexing）
- `tests/integration/test_ingestion.py`、`tests/ui/test_review_page.py`、`tests/local_model/test_local_ingestion_smoke.py`
- 未修改 `gridlens/repositories/sources.py`（入库 SQL 集中在服务的短事务内）

### 实现步骤

1. 校验批准 hash，建立运行锁，分块、存 chunk、分批 embedding/upsert，记录阶段。
2. 校验预期 ID 集合等于实际索引集合；发布前再检查审批。
3. SQLite 单事务替换旧 Active、标记 Ready 和运行 completed；失败保留旧版本可用。

### 完成条件

- 中途 embedding/索引失败时新版本不能被检索。
- 重试同版本无重复 chunk/vector；Ready 重复处理 no-op。
- 处理过程中撤销不能发布；两个 tab 的重复操作不启动双任务。

### 验证要求

- 故障注入到每个阶段，检查旧版本和发布事务。
- 验证 count 相同但 IDs 不同也不能通过完整性检查。

### 范围外

- 不引入任务队列；不靠删除整库解决失败。

**验证状态：** offline=passed, local_model=passed, live=not_required, human=not_required

**执行证据：** `tests/integration/test_ingestion.py` 10 项通过（各阶段故障注入、count 相同 ID 不同、撤销阻止发布、双 tab、旧 Active 保留与替换、发布事务回滚）。Review UI 新增 3 项通过。禁网真实 BGE + Chroma live 装配 smoke 通过（2 块发布、白名单检索命中）。完整回归 176 passed、5 deselected；Ruff/format/pip check 通过。遗留 processing 运行回收属于 T28。

## T19 — 接通 Knowledge Base 页面

**优先级/状态：** P0 / done
**日程/类别：** D6 / implementation
**依赖：** T05, T18
**PRD 对应：** AC-03, AC-09
**所需输入：** 无需外部凭证；使用合成 fixture。

**目标：** 展示真正可用的资料，以及处理阶段和恢复操作。

### 文件范围

- `gridlens/ui/knowledge_base.py`、`gridlens/ui/common.py`（共用 index_version）、`gridlens/ui/review.py`
- `gridlens/repositories/research.py`（latest_ingestion_runs）
- `tests/ui/test_knowledge_base.py`

### 实现步骤

1. 列表显示三种状态、版本、地区/类型与入库限制。
2. 实现详情、Retry、Revoke；按钮调用服务而非直接改数据库。
3. 显示真实阶段与数量，Approved 未 Ready 明确区分。

### 完成条件

- Failed 的批准资料可以 retry，但不能被标成可问答。
- 撤销后列表与查询资格一致。
- 处理中的操作禁用重复提交，页面状态可刷新。

### 验证要求

- fixture 数据覆盖所有状态，人工检查主要交互。
- 验证 Retry 和 Revoke 的调用参数与 operation_key。

### 范围外

- 不开发统计 dashboard 或批处理队列。

**验证状态：** offline=passed, live=not_required, human=not_run（人工浏览器检查未执行）

**执行证据：** `tests/ui/test_knowledge_base.py` 5 项 AppTest 通过（全部状态、Searchable 仅来自 SQLite 资格、失败 Retry 的 kb-retry- operation_key、处理中禁用与真实阶段/计数、Revoke 需 reviewer 且与检索资格一致、rerun 不重复、空库）。完整回归 213 passed、6 deselected。未执行人工浏览器检查；Refresh 属于 T26。

## T20 — 实现仅限批准版本的检索

**优先级/状态：** P0 / done
**日程/类别：** D5 / implementation
**依赖：** T18
**PRD 对应：** AC-04, AC-05, AC-09
**所需输入：** 无需外部凭证；使用合成 fixture。

**目标：** 为生成模型提供有资格、有限量、可定位的正文上下文。

### 文件范围

- `gridlens/services/retrieval.py`、`gridlens/contracts.py`（RetrievalFilters）、`gridlens/bootstrap.py`
- `gridlens/repositories/research.py`（chunks_by_ids；eligible 谓词已在此，未改 sources.py）
- `gridlens/migrations/002_chunk_segments.sql`、`gridlens/db.py`（按序迁移）、`gridlens/services/ingestion.py`（写入 segment IDs）
- `tests/integration/test_retrieval.py`、`tests/integration/test_db.py`

### 实现步骤

1. 按 reviewed metadata 和唯一 eligible 谓词筛选地区/类型。
2. 问题 embedding、Top-10 白名单检索、数据库读取正文、相邻块去重、最多五块/4000 tokens。
3. 空库不调用向量或生成服务；越界 ID 丢弃并记录；返回前再检查资格。

### 完成条件

- Pending/Rejected/Revoked/Failed/Superseded 永不出现在上下文。
- NZ 查询的地区筛选与 GLOBAL 规则符合规格，UNKNOWN 默认排除。
- 即便向量库留有旧记录，也不会因空过滤或缓存绕过限制。

### 验证要求

- 混合状态语料和故意返回越界 ID 的 provider 测试。
- 验证空库、状态中途变化、上下文预算和地区错配诊断。

### 范围外

- 不实现 reranker、混合检索或所谓可信度百分比。

**验证状态：** offline=passed, local_model=passed, live=not_required, human=not_required

**执行证据：** `tests/integration/test_retrieval.py` 9 项通过（混合状态且留有旧向量、地区/类型规则与诊断、空库与全排除不调用模型、越界 ID 丢弃、中途撤销复查、5 块与 token 预算、相邻重叠去重、正文取自 SQLite）。迁移 002 与 v1 升级测试通过。禁网真实 BGE + Chroma 检索 smoke 通过。完整回归 208 passed、6 deselected；Ruff/format/pip check 通过。

## T21 — 实现订阅授权的流式回答 Provider

**优先级/状态：** P0 / awaiting_input（离线完成，真实 smoke 需登录与计划用量）
**日程/类别：** D5 / implementation
**依赖：** T02, T04, T35, T36
**PRD 对应：** AC-05, AC-06
**所需输入：** 离线实现无凭证；真实smoke需合资格ChatGPT账户、本人OAuth plan授权、可用额度与所选catalog模型。

**目标：** 使用选中账户订阅授权生成 AnswerDraft，仅在完整流和校验成功后返回。

### 文件范围

- `gridlens/providers/chatgpt_oauth.py`
- `gridlens/prompts/answer_v1.txt`
- `tests/unit/test_answer_provider.py`
- `tests/live/test_live_answer_provider.py`（原定文件名与单元测试同名冲突）
- `pyproject.toml`（打包 prompts/*.txt）

### 实现步骤

1. 从 SessionProvider 取得当前账户 token，与该账户 catalog slug 一起调用公开 Responses endpoint；store=false、stream=true、input数组、instructions/developer，关闭 SDK 隐式重试。
2. 遵循规格3.3请求字段白名单；不发送 system message、max_output_tokens、temperature、metadata、历史ID或工具。
3. 缓冲SSE到completed，处理failed/incomplete/断流与额度错误；记录脱敏request ID和可用usage。
4. 对实际所选模型验证 schema 能力；支持则schema，不支持记录prompt-JSON模式，两者均严格Pydantic校验，不接受自由文本。

### 完成条件

- 未获plan权限、无模型、失效或额度耗尽有独立错误；不自动转平台收费调用。
- 流未completed或schema失败不返回可信答案；无额外URL/page字段。
- 证据只作数据，不允许文档指令改变行为，引用校验仍在T22。

### 验证要求

- mock验证请求字段及SSE完整/终止/额度错误在流开始后到达的场景。
- 用户授权后用合成证据做真实smoke，记录slug、output mode和terminal event，不能用mock替代。

### 范围外

- 不使用私有 backend-api、浏览器 cookies 或共享他人的 tokens；不部署公网。

**验证状态：** offline=passed, live=not_run, human=not_required

**执行证据：** 已核对官方 inference/限制/错误文档。`tests/unit/test_answer_provider.py` 21 项通过（请求字段白名单、证据仅作数据、schema→prompt-JSON 单次回退、未 completed/额度/资格/畸形流不返回答案、自由文本与额外字段被拒、错误映射不重试、无权限或换账户不请求）。完整回归 266 passed、8 deselected。**未运行真实 smoke**：需 `APP_MODE=live GRIDLENS_LIVE_ANSWER=1 .venv/bin/python -m pytest -m live -k live_answer -s`。

## T22 — 实现问答服务、引用校验与保存

**优先级/状态：** P0 / done
**日程/类别：** D5 / implementation
**依赖：** T20, T21
**PRD 对应：** AC-05, AC-06, AC-09
**所需输入：** 无需外部凭证；使用合成 fixture。

**目标：** 把检索、生成、引用验证和 QA 保存连成可信的一次操作。

### 文件范围

- `gridlens/services/answers.py`
- `gridlens/services/citations.py`
- `gridlens/contracts.py`（AnswerProvider repair 参数、AnswerEnvelope.missing_evidence）、`gridlens/bootstrap.py`
- `gridlens/providers/fakes.py`、`gridlens/providers/chatgpt_oauth.py`（repair 说明）
- `tests/integration/test_answers.py`（QA 写入集中在服务事务内，未改 repositories/qa.py）

### 实现步骤

1. 读取上下文，生成 draft；对每项引用验证 ID 属于上下文、quote 为原文子串、来源仍有效。
2. 服务端生成链接/页码/编号；从 claims 渲染，不增加无引用 summary。
3. 总生成尝试最多两次；成功同事务保存 QA/citations；为后续缺口服务保留事务扩展点。

### 完成条件

- 虚构 ID、错误 quote、失效来源均不能发布正常答案。
- operation_key 重放不重复收费；错误保存 failure，不伪装成 insufficient。
- 空库直接 completed/insufficient；历史引用锁定实际版本。

### 验证要求

- 伪造引用、来源中途撤销、格式修复一次后失败、空库测试。
- 检查 QA/citation 保存失败时整笔回滚。

### 范围外

- 不在问答时自动联网补证据。
- 不声称程序已验证语义蕴含。

**验证状态：** offline=passed, live=not_required, human=not_required

**执行证据：** `tests/integration/test_answers.py` 15 项通过（伪造引用与错误 quote、修复一次、provider 失败不伪装 insufficient、中途撤销 stale_context、空库 insufficient 不调用模型、operation_key 重放、保存失败整笔回滚、历史引用锁定版本）。完整回归 281 passed、8 deselected。引用校验不等于语义蕴含验证。

## T23 — 接通 Ask 与引用查看

**优先级/状态：** P0 / done
**日程/类别：** D5 / implementation
**依赖：** T05, T22
**PRD 对应：** AC-05, AC-06
**所需输入：** 无需外部凭证；使用合成 fixture。

**目标：** 用户能提问并核查每个论断的原文证据。

### 文件范围

- `gridlens/ui/ask.py`
- （未改 `gridlens/ui/common.py`；账户状态复用 T36 的 `ui/account.selected_model`）
- `tests/ui/test_ask.py`

### 实现步骤

1. 实现问题表单、地区/类型、回答结构和历史列表。
2. 显示 fact/inference、partial/insufficient、限制和 citation 展开区。
3. 错误、缺凭证、空库分别显示；每次读历史数据重新检查来源状态。
4. 集成账户侧栏与登录/权限/额度/断流状态；仅显示最终已验证答案，进度与回答分开。

### 完成条件

- 点击引用可看到正确短摘录、文件页序或章节段落、原始链接。
- 重新渲染页面不会重新请求模型。
- 界面不把检索距离当置信度，不隐藏证据不足。

### 验证要求

- fixture 模式正常、partial、insufficient、failure 四条 UI 路径。
- 检查引用与对应 claim 的映射。

### 范围外

- 不实现多轮聊天或视觉动画。

**验证状态：** offline=passed, live=not_run（依赖 T34/T36/T21）, human=not_run

**执行证据：** `tests/ui/test_ask.py` 6 项 AppTest 通过（partial 引用映射与展开区、answered、insufficient、provider 失败、撤销后历史提示、rerun 不再调用模型、输入校验）。完整回归 287 passed、8 deselected。未运行 live 真实提问与人工浏览器检查。

## T24 — 实现知识缺口规则、保存与去重

**优先级/状态：** P0 / done
**日程/类别：** D7 / implementation
**依赖：** T03, T22
**PRD 对应：** AC-07, AC-09
**所需输入：** 无需外部凭证；使用合成 fixture。

**目标：** 将回答中的证据不足转成可操作、可复查的研究记录。

### 文件范围

- `gridlens/services/gaps.py`、`gridlens/bootstrap.py`（接入 AnswerService.gap_writer）
- `tests/integration/test_gaps.py`
- （未改 `services/answers.py` 与 `repositories/qa.py`：T22 已预留事务扩展点）

### 实现步骤

1. 实现无上下文规则和已校验 draft 的六种缺口类型。
2. 按规范 question/filters/reason/subquestion 建 gap_key，open 唯一，关闭后可再次生成新 open。
3. 将自动 gap 保存接入 QA/citations 同一事务；编辑/关闭需明确用户动作。

### 完成条件

- 相同 open 缺口合并；数字、否定词或地域不同的问题不误合并。
- 服务故障不产生领域缺口；每条有效草稿有 scope 和建议词。
- resolved 需要 resolution_note，不能由模型自动设定。

### 验证要求

- 去重、close/reopen、关键语义保留、事务 rollback 测试。
- 空库、地区不匹配及模型误报可 dismiss 的案例。

### 范围外

- 不扫描全库推断整个行业没有答案。

**验证状态：** offline=passed, live=not_required, human=not_required

**执行证据：** `tests/integration/test_gaps.py` 11 项通过（去重与关键语义保留、scope 参与 key、地区不匹配与 partial 草稿、服务失败不产生缺口、resolve 需说明与关闭后新建、dismiss/reopen、编辑唯一性、事务回滚）。完整回归 298 passed、8 deselected。

## T25 — 接通缺口列表与补充搜索入口

**优先级/状态：** P0 / done
**日程/类别：** D7 / implementation
**依赖：** T08, T23, T24
**PRD 对应：** AC-07
**所需输入：** 无需外部凭证；使用合成 fixture。

**目标：** 让用户检查缺口、编辑原因并启动下一轮研究。

### 文件范围

- `gridlens/ui/ask.py`
- `gridlens/ui/discover.py`
- `tests/ui/test_gaps_page.py`（原定文件名与集成测试同名冲突）

### 实现步骤

1. Ask & Gaps 加列表、详情、编辑、Resolved/Dismissed 与备注。
2. 显示问题范围、已有证据、缺少证据和建议 query。
3. 选择建议词只跳转并填入 Discover，点击 Search 后才发起搜索。

### 完成条件

- 不会因查看缺口自动发搜索请求。
- 重复问题看到同一 open 记录；关闭状态可追踪。
- 不使用“行业无研究”等超出当前知识库的措辞。

### 验证要求

- 编辑/关闭/跳转主流程和空列表检查。
- 验证未点击 Search 时 provider 调用数不变。

### 范围外

- 不自动发邮件或联系专家。

**验证状态：** offline=passed, live=not_required, human=not_run

**执行证据：** `tests/ui/test_gaps_page.py` 4 项 AppTest 通过（空列表、详情与措辞、建议词仅预填 Discover 且 provider 调用数为 0、同一 open 缺口、编辑/resolve 需说明/dismiss/reopen）。完整回归 302 passed、8 deselected。用户需自行点击 Discover 导航；未执行人工浏览器检查。

## T26 — 补齐刷新版本与历史引用状态

**优先级/状态：** P0 / done
**日程/类别：** D6 / implementation
**依赖：** T19, T23
**PRD 对应：** AC-02, AC-06, AC-09
**所需输入：** 无需外部凭证；使用合成 fixture。

**目标：** 让资料更新不覆盖旧证据，撤销后历史答案也能正确解释。

### 文件范围

- `gridlens/ui/knowledge_base.py`（Refresh、待审核更新标记、修正元数据）、`gridlens/ui/review.py`、`gridlens/ui/ask.py`、`gridlens/ui/common.py`
- `gridlens/services/review.py`（revise_metadata）、`gridlens/services/citations.py`（source_statuses）、`gridlens/services/ingestion.py`（purge_vectors）
- `gridlens/documents/snapshots.py`、`gridlens/repositories/sources.py`（沿用已审核元数据）
- `tests/integration/test_version_lifecycle.py`、`tests/integration/test_snapshots.py`、`tests/ui/test_knowledge_base.py`

### 实现步骤

1. 接通手动 Refresh：同 hash no-op、新 hash Candidate/Pending。
2. 显示存在待审核更新；新版本发布前旧版本继续有效，发布后旧版 Superseded。
3. 历史 QA 动态标记 revoked/superseded，引用依然对应原快照；撤销向量删除失败仍排除检索。

### 完成条件

- 新内容不能继承旧批准；已批准元数据修正也重新审核。
- 旧答案文本、quote 和定位不被新版本替换。
- 撤销不自动恢复另一旧版本，也不依赖物理向量删除成功。

### 验证要求

- 完整 v1→v2→revoke 生命周期回归。
- 模拟清理失败和批准后修改 hash，确保资格不泄漏。

### 范围外

- 不做自动监测更新或可视化 diff。

**验证状态：** offline=passed, live=not_required, human=not_required

**执行证据：** `tests/integration/test_version_lifecycle.py` 3 项（v1→v2→revoke 全周期、清理失败、批准后修正与 hash 篡改）与 KB Refresh UI 测试通过。行为变更：刷新沿用已审核元数据，T12 测试相应更新。完整回归 306 passed、8 deselected。

## T27 — 实现 Markdown research log 导出

**优先级/状态：** P0 / done
**日程/类别：** D8 / implementation
**依赖：** T24, T26
**PRD 对应：** AC-08
**所需输入：** 无需外部凭证；使用合成 fixture。

**目标：** 将可追溯研究记录导出供团队整理笔记。

### 文件范围

- `gridlens/services/export.py`
- `gridlens/ui/knowledge_base.py`
- `tests/integration/test_export.py`

### 实现步骤

1. 支持选择来源/问答/缺口，导出 UTF-8 Markdown、时间、模式和审核备注。
2. 当前有效证据与待审核线索分区；撤销来源不导出正文摘录，历史版本明确标注。
3. 转义用户文本，URL 仅 HTTP(S)，排除本地路径、密钥和 provider 原始请求。

### 完成条件

- 中文和特殊 Markdown 字符不会破坏文档结构。
- 每条引用指向对应元数据，状态与当前数据库一致。
- Pending/Rejected 正文、被撤销摘录与密钥不出现在输出。

### 验证要求

- 用包含状态变化和恶意 Markdown 的 fixture 验证导出边界。
- 人工打开一次导出文件，核查可读性。

### 范围外

- 不自动生成未经核实的 research note 结论。

**验证状态：** offline=passed, live=not_required, human=not_run（人工打开导出文件未执行）

**执行证据：** `tests/integration/test_export.py` 6 项通过（恶意 Markdown/HTML、Pending/Rejected 正文、撤销 quote 与仅依赖撤销来源的 claim 省略、superseded 标注、状态随数据库、非 HTTP(S) URL、中文 UTF-8）。AI 阅读过样例导出；人工打开检查未执行。完整回归 312 passed、8 deselected。

## T28 — 实现中断恢复、调用限额与运行记录

**优先级/状态：** P0 / done
**日程/类别：** D8 / implementation
**依赖：** T18, T22
**PRD 对应：** AC-09, AC-10
**所需输入：** 无需外部凭证；使用合成 fixture。

**目标：** 重启后能够解释失败、保留有效数据，并避免隐形重复调用。

### 文件范围

- `gridlens/services/recovery.py`、`gridlens/runlocks.py`、`gridlens/oplog.py`
- `gridlens/bootstrap.py`、`gridlens/cli.py`（recover、doctor）、`app.py`（会话级恢复与日志脱敏）
- `gridlens/services/ingestion.py`、`discovery.py`、`answers.py`（运行锁与操作日志）
- `tests/integration/test_recovery.py`（未改 `config.py`：锁与日志位于 data_dir）

### 实现步骤

1. 启动识别已退出 owner 的 processing runs，转 Interrupted/Failed 并释放过期锁。
2. 统一计量 stage/耗时/调用次数/usage；有限重试预算包含 SDK 内部行为。
3. 增加本地 doctor 检查配置和存储，默认不出网，不打印密钥。
4. 日志脱敏OAuth tokens、id_token_hint授权URL及callback code；错误计量区分本地推理、搜索配额与ChatGPT计划用量，未知剩余额度不推算。

### 完成条件

- 中断任务不冒充 Ready，用户可重试；活跃进程锁不被错误回收。
- 已有效来源、历史问答重启后仍在。
- 日志无密钥或整篇正文，模型重试不会超过两次总调用。

### 验证要求

- 模拟崩溃/重启/仍活跃 owner、重复 operation 和 429 链式失败。
- 检查 doctor 输出与日志脱敏。

### 范围外

- 不加监控平台、自动清库或无人值守重跑。

**验证状态：** offline=passed, live=not_required, human=not_required

**执行证据：** `tests/integration/test_recovery.py` 8 项通过（崩溃恢复与重试、存活子进程持锁不被回收、搜索中断、重启后数据保留、429 链式预算、日志无正文与脱敏、doctor 无密钥）。完整回归 320 passed、8 deselected。

## T29 — 建立 15 题与评估运行工具

**优先级/状态：** P0 / done
**日程/类别：** D8 / implementation
**依赖：** T22, T24
**PRD 对应：** AC-05, AC-06, AC-07, AC-10
**所需输入：** 无需外部凭证；使用合成 fixture。

**目标：** 把 PRD 题库和评分方法变成可重复运行、不会制造假通过的工具。

### 文件范围

- `evals/questions.json`
- `evals/gold.json`
- `gridlens/cli.py`
- `gridlens/evaluation.py`
- `tests/unit/test_evaluation.py`

### 实现步骤

1. 原样整理 R01–R15，正式评估仅 R01–R12，保存 split 和预期行为。
2. gold 为人工填充的证据段落/要点；报告要求 corpus fingerprint、model、prompt、分子分母和失败项。
3. 实现 evaluate 命令，fixture 输出显著标记；领域正确性与引用语义支持率留人工评分。

### 完成条件

- 未填写 gold 或评审分数时报告 incomplete/awaiting_input，不输出 pass。
- R01–R08 和 R09–R12 分组统计，指标与 PRD 一致。
- 自动引用定位率不被误用为语义支持率。

### 验证要求

- 评分边界、缺失评分、分母为零、7/8与4/4门槛检查。
- fixture evaluate 可运行并明确不能用于真实验收。

### 范围外

- 不由 AI 填造真实 gold 或人工评审者。

**验证状态：** offline=passed, live=not_required, human=not_required（gold 与评分属于 T31，由人工填写）

**执行证据：** 题库原样提取并与 PRD 逐条比对；gold 为空白人工模板。`tests/unit/test_evaluation.py` 14 项通过（门槛 7/8、4/4、100%、90%，缺失评分与分母为零为 awaiting_input，自动定位≠语义支持，fixture 永不验收）。本机 fixture evaluate/evaluate-score 实跑：全部 awaiting_input。完整回归 334 passed、8 deselected。

## T30 — 执行完整闭环与可信性回归

**优先级/状态：** P0 / todo
**日程/类别：** D9 / implementation
**依赖：** T14, T19, T23, T25, T26, T27, T28, T29, T36
**PRD 对应：** AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10
**所需输入：** 无需外部凭证；使用合成 fixture。

**目标：** 证明已实现模块组合后仍符合审核隔离和引用规则。

### 文件范围

- `tests/integration/test_workflow.py`
- `tests/integration/test_trust_boundaries.py`
- `docs/progress.md`
- `artifacts/test-results/`

### 实现步骤

1. 从搜索候选到审核、入库、问答、缺口和导出执行一条合成端到端路径。
2. 覆盖 Pending/Rejected/Revoked/Failed 泄漏、来源指令干扰、伪造引用、索引部分失败和更新历史。
3. 运行现有相关测试及质量检查；发现问题在对应服务修复并回归。

### 完成条件

- 合成测试全部通过，关键身份/状态过滤直接检查上下文，而非只看最终回答没有某句话。
- 测试没有使用 live credentials，运行结果与 fake 使用情况可复现。
- 未修复的 P0 缺陷阻止本任务 done。

### 验证要求

- 全套非 live pytest 与 Ruff。
- 人工 UI 主流程检查一次，结果留档。
- 回归授权拒绝、账户切换、刷新竞争/失效、退出/撤销网络失败、SSE失败/断流和额度耗尽，检查不泄露凭证或保存半截答案。

### 范围外

- 不把通过合成测试写成真实研究质量通过。

**验证状态：** offline=not_run, live=not_required, human=not_required

**执行证据：** 尚无；完成开发后填写实际结果。

## T31 — 完成真实语料与人工评估验收

**优先级/状态：** P0 / todo
**日程/类别：** D9 / human_gated_acceptance
**依赖：** T06, T16, T21, T29, T30
**PRD 对应：** AC-01, AC-03, AC-05, AC-06, AC-07, AC-10
**所需输入：** 真实搜索key、合资格ChatGPT本人OAuth plan授权/可用额度、固定本地模型缓存、至少10份人工批准资料、gold参考与人工评分。

**目标：** 用真实公开资料与人工评分验证 PRD 目标，明确代码完成与研究验收的区别。

### 文件范围

- `artifacts/evals/`
- `artifacts/research-log.md`
- `evals/gold.json`
- `docs/progress.md`

### 实现步骤

1. 收集三次真实查询结果；人工审核至少十份资料、覆盖三类并成功入库，记录 source/version IDs。
2. 由人填写或确认 R01–R12 gold，运行冻结配置问答，逐项检查论断和引用。
3. 输出实际发现相关性、7/8回答/检索、4/4不足处理、引用率和至少三条有效缺口；记录失败。

### 完成条件

- 真实请求、已批准来源、人工评审身份与评分均可核查，fixture 不计入指标。
- 达到开发规格第12.3节门槛；不够样本或未达标就注明未通过。
- 缺凭证、未批准语料或未评分时状态 awaiting_input；AI 不替人批准来源。

### 验证要求

- 运行显式 live evaluation，并人工核对全部引用支持关系。
- 记录用量、耗时、失败案例和语料/模型/提示词配置。
- 记录登录模型slug与实际output mode、本地embedding revision及禁网推理结果；验证额度失败不会计为知识缺口或成功问答。

### 范围外

- 不为凑足数量伪造日期、文档、审核记录或评分。
- 不自动购买账户或发送评估结果给他人。

**验证状态：** offline=not_run, live=not_run, human=not_run

**执行证据：** 尚无；完成开发后填写实际结果。

## T32 — 整理运行说明、限制和 demo 交付

**优先级/状态：** P0 / todo
**日程/类别：** D10 / delivery
**依赖：** T30, T31
**PRD 对应：** AC-10
**所需输入：** T31真实验收结果；若未通过，可先准备文档，但最终交付状态必须反映未通过。

**目标：** 把已经验证的应用交给下一位使用者，并明确完成范围。

### 文件范围

- `README.md`
- `docs/DEMO.md`
- `docs/KNOWN_LIMITATIONS.md`
- `docs/progress.md`
- `.env.example`

### 实现步骤

1. 按全新环境演练安装、配置、初始化、启动和评估；记录实际版本。
2. 按 PRD 编写6–8分钟 demo：搜索、审核、入库、引用、缺口、导出、实际结果。
3. 记录限制、未达标项、下一步和数据备份方式；回放材料标时间/版本。
4. 说明本地网页启动、显式模型下载、Continue with ChatGPT/权限与Usage、token刷新/退出、资格限制和搜索独立费用；演示前验证授权与模型缓存。

### 完成条件

- 按说明可启动并重复演示；没有真实密钥进入交付。
- 文档区分代码测试、真实联调和人工验收结果。
- 只有全部P0满足且T31通过，才能宣称MVP验收通过。

### 验证要求

- 干净环境安装/启动一次；核对 demo 与真实界面。
- 检查任务证据、遗留问题与PRD验收编号对应。

### 范围外

- 不发布公网、不推送远端或通知外部人员，除非已有相应用户授权。

**验证状态：** offline=not_run, live=not_required, human=not_required

**执行证据：** 尚无；完成开发后填写实际结果。

## T33 — 建立本机注册与受保护凭证存储

**优先级/状态：** P0 / done
**日程/类别：** D1 / implementation
**依赖：** T02
**PRD 对应：** AC-09, AC-10
**所需输入：** 无需真实账户；合成tokens与临时配置目录。

**目标：** 稳定保存本机host标识和账户注册，不把凭证混入研究数据。

### 文件范围

- `gridlens/auth/host.py`
- `gridlens/auth/credentials.py`
- `tests/unit/test_credentials.py`

### 实现步骤

1. 创建并持久化稳定opaque ext_agent_host_id；使用用户配置目录。
2. 按issued client ID+已验证subject分别保存credential records，Unix 0700/0600，原子写入完整token set。
3. 返回仅含脱敏labels的AccountSummary，读写限制到受控文件路径；无token日志/导出。

### 完成条件

- 重启host ID不变，账户同email不同注册不覆盖。
- 写入失败不会破坏旧token set；fixture用临时目录。
- 研究SQLite、Git、UI/browser state和export均不含tokens。

### 验证要求

- 临时目录权限、原子失败、并行读与账户隔离测试。
- 检查敏感值不进入日志/摘要。

### 范围外

- 不使用私有 backend-api、浏览器 cookies 或共享他人的 tokens；不部署公网。

**验证状态：** offline=passed, live=not_required, human=not_required

**执行证据：** docs/progress.md；离线验证已通过，真实授权/研究验收未执行。

## T34 — 实现OAuth登录和callback校验

**优先级/状态：** P0 / awaiting_input（离线完成，等待本人真实登录）
**日程/类别：** D2 / implementation
**依赖：** T33, T04
**PRD 对应：** AC-09, AC-10
**所需输入：** mock无账户；真实联调需本人在官方浏览器页面完成登录与授权。

**目标：** 完成本机PKCE登录，验证身份与计划权限再激活账户。

### 文件范围

- `gridlens/auth/oauth.py`
- `gridlens/cli.py`（`login`，仅 live 模式）
- `tests/unit/test_oauth.py`
- `tests/live/test_login.py`

### 实现步骤

1. 先启动127.0.0.1 listener；每次state/nonce/verifier随机，S256；pending attempt设置到期和单次消费。
2. 按规格3.3发起新注册或返回登录；callback state先验证，用issued ID交换code，exact redirect URI不变。
3. 使用官方OIDC discovery/JWKS与JWT库验签，检查issuer/audience/expiry/nonce，返回登录检查原subject；检查token response granted scopes。
4. 拒绝授权、错误或missing issued ID不替换当前账户；只在全部通过时保存凭证。

### 完成条件

- 错误state、nonce、签名、scope、issued-ID错配、重复callback和过期attempt都被拒绝。
- 首次dynamic_agent_client不能被保存为实际client ID。
- callback timeout关闭listener并允许新attempt，tokens不进入页面或日志。

### 验证要求

- mock各callback/JWKS/交换失败场景；系统浏览器打开与listener生命周期冒烟。
- 本人在合资格账户做真实登录，确认plan授权；仅记脱敏证据。

### 范围外

- 不使用私有 backend-api、浏览器 cookies 或共享他人的 tokens；不部署公网。

**验证状态：** offline=passed, live=not_run, human=not_required

**执行证据：** 已核对官方 sign-in/token/errors 文档与 OIDC discovery。`tests/unit/test_oauth.py` 22 项通过（错误 state/nonce/签名/aud/iss/过期、scope、issued-ID 错配、重复与过期 callback、拒绝授权与交换失败不保存、返回登录身份核对、loopback listener 成功/超时关闭）。完整回归 198 passed、6 deselected。按官方指引，缺少 plan scope 时保留登录但禁用 plan usage。**未运行真实登录**：需本人执行 `APP_MODE=live .venv/bin/python -m gridlens.cli login` 或 `APP_MODE=live GRIDLENS_LIVE_LOGIN=1 .venv/bin/python -m pytest -m live -k login -s`，只记录脱敏结果。

## T35 — 实现刷新、账户切换与退出

**优先级/状态：** P0 / awaiting_input（离线完成，真实验证需 T34 登录）
**日程/类别：** D4 / implementation
**依赖：** T34
**PRD 对应：** AC-09, AC-10
**所需输入：** 离线实现合成会话；真实联调需T34本人授权。

**目标：** 稳定维护订阅会话，失败时停止请求，退出后清除凭证。

### 文件范围

- `gridlens/auth/sessions.py`、`gridlens/auth/credentials.py`（clear_tokens keep_id_token）
- `gridlens/cli.py`（`logout --account`）
- `tests/unit/test_sessions.py`
- `tests/live/test_live_sessions.py`（原定文件名与单元测试同名冲突）

### 实现步骤

1. 串行刷新选中session，refresh grant使用issued ID/resource；完整原子替换旋转token set。
2. 刷新invalid_grant提示重新授权；不覆盖其他账户。切换前校验目标注册，取消/隔离旧账户正在执行的结果。
3. 退出停止请求，discovery取得revocation endpoint，有限重试撤销refresh token，清除local access/refresh/ID tokens，保留client/host映射。

### 完成条件

- 两个刷新不竞用旧refresh token，失败不发布不完整token set。
- 切换账户没有token/client/catalog混用，退出后不能继续请求。
- 远端撤销未确认明确提示；本地tokens仍清除，保留注册可再次登录。

### 验证要求

- 旋转token竞争、invalid_grant、账户隔离和logout网络失败mock。
- 授权账户验证刷新/退出，证据不含tokens。

### 范围外

- 不使用私有 backend-api、浏览器 cookies 或共享他人的 tokens；不部署公网。

**验证状态：** offline=passed, live=not_run, human=not_required

**执行证据：** 已核对官方 sessions/errors 文档。`tests/unit/test_sessions.py` 19 项通过（旋转 token 并发、终止错误、账户隔离与切换、临时失败保留凭证、撤销重试/未确认仍清除、discovery 异常不发送 token）。完整回归 232 passed、7 deselected。**未运行真实刷新/退出**：需 T34 登录后执行 `APP_MODE=live GRIDLENS_LIVE_SESSION=1 .venv/bin/python -m pytest -m live -k live_sessions -s`。

## T36 — 接通账户侧栏和可用模型目录

**优先级/状态：** P0 / awaiting_input（离线完成，真实目录需 T34 登录）
**日程/类别：** D4 / implementation
**依赖：** T05, T35
**PRD 对应：** AC-09, AC-10
**所需输入：** mock无账户；真实catalog需要T35可用OAuth会话。

**目标：** 用户能看见当前授权账户并选择该账户真实可用模型。

### 文件范围

- `gridlens/auth/catalog.py`
- `gridlens/ui/account.py`
- `gridlens/ui/common.py`、`gridlens/bootstrap.py`（oauth/sessions/catalog 装配）
- `tests/unit/test_catalog.py`
- `tests/ui/test_account.py`

### 实现步骤

1. OAuth Bearer GET /v1/models，解析models/visibility=list/slug/display_name，缓存绑定账户且支持刷新。
2. 侧栏Continue with ChatGPT、账户picker、模型picker、重新授权、退出与Usage链接；不展示tokens。
3. 换账户失效旧catalog/模型选择；错误和plan permission状态清晰，不影响已保存研究资料查看。

### 完成条件

- 不硬编码模型或把另一账户模型用于当前请求；空catalog要求重选/稍后刷新。
- 未授权/额度不足不生成live答案，fixture仍可启动。
- Streamlit rerun不重复注册、登录或模型请求；callback通过服务通信不写浏览器token。

### 验证要求

- 目录字段/空目录/账户切换与UI连接状态mock。
- 真实账户读取catalog并完成一次选择，记录脱敏结果。

### 范围外

- 不使用私有 backend-api、浏览器 cookies 或共享他人的 tokens；不部署公网。

**验证状态：** offline=passed, live=not_run, human=not_required

**执行证据：** 已核对官方 models 文档。`tests/unit/test_catalog.py` 8 项、`tests/ui/test_account.py` 5 项通过（字段/空目录/错误映射、账户切换清空并隔离、rerun 不重复请求、plan scope 缺失、退出）。完整回归 245 passed、7 deselected。**未运行真实目录读取**：需 T34 登录后在 live 侧栏完成一次选择。
