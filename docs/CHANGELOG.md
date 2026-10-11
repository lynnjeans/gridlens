# GridLens 文档变更记录

## v1.1 — 2026-10-11

按用户决定同步为本地浏览器网页 + ChatGPT 订阅 OAuth + 本地 embedding。

- PRD、开发规格、任务卡、机器任务清单和执行指南保持一致；原始 PRD 输出同步更新。
- 新增 T33 本机注册/凭证、T34 OAuth 登录、T35 会话刷新/退出、T36 账户侧栏/模型目录；总计36任务，全部待实施。
- T16 改为本地 SentenceTransformers/BGE；T15依赖T16的tokenizer；T21依赖T35/T36，使用OAuth流式Responses。
- 本地模型默认384维，输入上限512 tokens，起始分块350/50；固定revision、query prefix策略与归一化，索引fingerprint随配置变化。
- 生成等待completed事件并验证schema/引用；未完成流、权限/额度错误不能作为答案或知识缺口。模型schema能力需要真实联调验证。
- 密钥与OAuth凭证独立于研究库/日志/导出；退出尝试撤销后清除本地token。搜索服务独立费用，ChatGPT计划仍受额度限制。
- 两周计划加入授权工作和早期资格验证；主要排期风险在D2/D4，保持P1冻结。产品范围、研究题库和语义验收门槛不变。

当时的 v1.1 修订只更新文档，尚未开发应用、创建GitHub仓库、下载模型、进行OAuth授权或运行真实评估。技术依据链接见开发规格3.3–3.4节；实现时仍需安装/契约与真实账户验证。

## 基础阶段实现 — 2026-10-11

T01–T05、T33 完成，42项离线测试通过；四页本地浏览器导航已验证。依赖分阶段安装：core/dev/auth 已锁定，models extra 在实际接入时锁定；凭证存储首版使用POSIX权限/锁，Windows尚未支持。真实搜索、OAuth、embedding和研究验收尚未执行，详见progress.md。

## AI 交接同步 — 2026-10-11

新增根 AGENTS.md 和 HANDOFF.md，统一下一任务为 T06–T08，修正执行指南仍从T01开始的旧提示。同步 Git origin/master/尚未commit与push 状态；重新验证42项离线测试及质量检查。任务状态不变：6 done、30 todo。输出文档包与源码交接包已更新，不包含环境、运行数据或真实凭证。

## 来源发现里程碑 — 2026-10-11

完成 T06–T08：新增 Tavily HTTP 适配器、三次调用上限的搜索编排、URL 规范化/去重、SearchRun/Hit/Source 持久化、Discover 页面和手动 pending lead。候选可选择并在 Review 页显示；未抓取、批准或入库。完整离线回归 67 passed、1 live deselected；Ruff、格式和依赖检查通过。未配置 Tavily key，真实搜索 smoke 未运行。下一里程碑为 T09–T14 文档抓取与人工审核。

完成 T09：新增带公网 DNS/端口/重定向复检、流式与解压后大小限制、总超时、HTML/PDF 类型检查的文档抓取器。24 项定向测试通过；完整回归 91 passed、1 live deselected。测试未访问任意实时网站。

完成 T10：新增确定性 HTML 正文提取、标题路径和段落定位，清理导航/脚本，body fallback 与表格限制显式告警，空正文稳定失败。5 项定向测试通过；完整回归 96 passed、1 live deselected。

完成 T11：PDF 在可终止子进程中逐页提取，保存一基 file_page，限制页数和耗时；扫描、损坏、加密与超限文件稳定失败，并明确复杂布局限制。6 项定向测试通过；完整回归 102 passed、1 live deselected。

完成 T12：抓取结果按类型解析并以语义段落、审核元数据和解析器版本生成稳定 snapshot hash；原文/段落原子写入受控目录，相同身份复用，不同内容或元数据生成 Pending/Candidate，失败清理半文件。6 项定向测试通过；完整回归 108 passed、1 live deselected。

完成 T13：实现带预览/原文完整性校验的 approve、必填原因 reject、即时失去资格的 revoke 和清除旧入库状态的 reopen；事件与状态同事务，重复操作幂等。6 项定向测试通过；完整回归 114 passed、1 live deselected。

## 首次 GitHub 发布 — 2026-10-11

按用户明确要求，将当前 T01–T10、T33 实现、测试和同步文档提交并推送至现有 `lynnjeans/gridlens` 仓库的 `master`。推送前确认远端无分支、运行数据与凭证路径被忽略，未发现真实密钥。未创建 PR 或部署。

完成 T14：Review 页面接通捕获、正文预览、元数据修正（重算 hash）、hash 绑定与过期重新加载、Approve/Reject/Revoke/Reopen 和审核历史；fixture 模式使用合成文档获取器。8 项 AppTest 与 7 项审核集成测试通过；完整回归 123 passed、1 live deselected。批准后入库待 T18。

完成 T16：固定 revision 的本地 bge-small-en-v1.5 embedding（仅本地加载、长度预检、16 批、归一化与维度校验）和显式 `prepare-model`；`models` extra 拆为 `embeddings`/`vectors`，锁定 sentence-transformers 6.1.0。17 项单元测试与 2 项禁网真实模型 smoke 通过（revision `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a`）；完整回归 140 passed、3 deselected。

完成 T15：确定性 token 分块（按页/章节装箱、长段按 tokenizer offset 切窗、原文精确子串、index_fingerprint/chunk_id）；ChunkDTO 增加 ordinal、text_sha256、embedding_text、heading_path。14 项单元测试与真实 BGE tokenizer 禁网 smoke 通过；完整回归 154 passed、4 deselected。

完成 T17：本地持久 Chroma 向量存储适配器（按 fingerprint 的 cosine 集合、显式向量、拒绝默认 embedding function、白名单查询、按版本删除、配置不符报错）；锁定 chromadb 1.5.9。9 项真实临时 Chroma 集成测试通过；完整回归 163 passed、4 deselected。

完成 T18：入库流水线与原子发布（处理锁、分块、批量 embedding/upsert、ID 集合核对、发布前复查审核、单事务替换旧 Active，失败保留批准与旧版本）；Review 批准后入库一次并可重试；fixture 改用持久 Chroma。10 项故障注入集成测试、3 项 UI 测试与禁网真实模型端到端 smoke 通过；完整回归 176 passed、5 deselected。

T34 离线完成（awaiting_input）：loopback PKCE 登录与 callback/state/nonce/JWKS/issued-ID 校验，全部通过才保存凭证；`gridlens login`（仅 live）。按官方指引，缺少 plan scope 时保留登录但禁用 plan usage。22 项 OAuth 测试通过；完整回归 198 passed、6 deselected。真实登录待用户本人执行。

完成 T20（2026-10-12）：仅限批准版本的检索（SQLite 资格 + 已审核元数据地区/类型规则、白名单 Top-10、越界 ID 丢弃、相邻重叠去重、5 块/4000 tokens、返回前复查）；迁移 002 增加 chunk segment IDs，迁移执行器按序应用。9 项检索集成测试、v1 升级测试与禁网真实模型检索 smoke 通过；完整回归 208 passed、6 deselected。

完成 T19（2026-10-12）：Knowledge Base 页面（三种状态分列、Searchable 仅来自 SQLite 资格、真实阶段/计数、经服务的 Retry/Revoke）。5 项 AppTest 通过；完整回归 213 passed、6 deselected；人工浏览器检查未执行。

T35 离线完成（awaiting_input，2026-10-12）：串行刷新与旋转 token 完整替换、账户切换隔离、撤销后清除 tokens 并保留注册；`gridlens logout`。19 项单元测试通过；完整回归 232 passed、7 deselected。真实刷新/退出待 T34 登录后验证。

T36 离线完成（awaiting_input，2026-10-12）：账户专属模型目录与侧栏账户/模型选择、重新授权、退出、Usage 链接。13 项目录与 UI 测试通过；完整回归 245 passed、7 deselected。真实目录读取待 T34 登录后验证。
