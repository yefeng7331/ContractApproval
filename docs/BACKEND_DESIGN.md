# 后端设计与 API 契约

## 2026-09-25 F6 待办附件恢复增量

`backend/pending_imports.py` 在获取附件前事务登记任务及 `attachment_attempts`，预留 document_version=1；未取得附件时不创建 document_versions、正文或规则。任务查询/列表允许附件尚不存在，此时 submission 的 filename/format/sha256 为 null。`POST /api/v1/mock-pending/{id}/import` 仍限业务账号，201 表示任务已建立；必须读取 machine_status，超时为 blocked/ATTACHMENT_FETCH_TIMEOUT/admin_retry，而非把 201 当作处理成功。成功路径沿用本地合成附件，未新增真实平台或 F6 待办 ID。

仅管理员 `POST /api/v1/tasks/{id}/retry`，JSON `{"document_version":1}`，优先处理尚未完成的附件获取；同一版本重试并保留历史，正在获取或版本不符为 409。下载成功后沿用原 OCR/规则重试契约。附件尝试数单独持久保存，任务摘要 attempt_count 在进入解析后沿用当前处理阶段计数；附件累计次数以历史接口为准。重复导入仍建立新任务，重试同一任务不会新建任务/文档版本。

仅管理员 `GET /api/v1/tasks/{id}/attachment-attempts` 返回 task_id、初始 document_version=1、attempts（attempt/state/error_code/started_at/finished_at/actor_user_id），不含附件正文、路径、内部租约 token 或原始异常。state 为 running/failed/completed。超时、获取失败、存储失败分别为 ATTACHMENT_FETCH_TIMEOUT、ATTACHMENT_FETCH_FAILED、ATTACHMENT_STORE_FAILED；中断为 ATTACHMENT_FETCH_INTERRUPTED。所有失败可由管理员重试，不自动追加下载。

两分钟租约；启动、服务轮询、历史查询和重试检查过期租约，将中断尝试保存为 failed 并受阻。重启时仍有效的租约等待到期，避免第二连接误抢活跃请求。迟到结果校验 token 对应状态，不覆盖已恢复结果。附件文件守卫覆盖数据库提交；文档登记、解析入队、成功尝试及审计事件同事务，落盘/SQL 失败回滚后记受阻。真实进程硬退出可能留下未引用文件，不自动删除；唯一内部文件名允许后续安全重试。

## 2026-09-25 模拟回写增量

`backend/writeback.py` 持久实现本地评论。仅法务 `GET /api/v1/mock-writeback-targets` 读取现有目标，目前仅 `demo-f1-001`；原业务待办列表权限不变。`POST /api/v1/tasks/{task_id}/mock-writeback` 必填 `{"review_version":1,"mock_approval_id":"demo-f1-001"}`，版本为严格正整数，拒绝额外字段。按 D-26 首次请求绑定上传任务，待办导入沿用目标，之后改目标为 409；不存在目标为 404，未确认版本为 409。请求登记状态为 writing，不表示成功；同键 writing/success 返回已有结果，failed 再次 POST 登记重试。

`GET /api/v1/tasks/{task_id}/mock-writeback?review_version=N` 必须指定确认版本。响应含 task_id/document_version/review_version、mock_approval_id、simulated=true、state、comment_id、completed_at；法务另见 markdown、error、attempts，管理员仅状态/故障/尝试而无 markdown，业务仅本人确认版本最终评论和状态，无错误和尝试。其他业务读取 404，非法律角色 POST 403，未登录 401。目标固定后，读取无需再次指定目标。

`mock_writebacks` 唯一键为任务/确认版本/目标，另约束每任务每审查版本一条；`writeback_attempts` 保存发起人、请求/启动/完成时间及结果。现有服务处理器领取 writing，租约两分钟，过期标记旧尝试 WRITEBACK_INTERRUPTED 并恢复，旧 token 不可覆盖。正常失败为 MOCK_WRITEBACK_FAILED，保持 failed 等法务重试，不自动反复失败重试。评论及成功/尝试/任务当前状态同事务提交；评论从已确认快照生成并转义 Markdown/HTML，仅保留最终风险和意见。历史回写不污染新草稿/新附件的当前状态；不等待报告成功。F6 故障通过测试替换评论生成接入固定合成故障源，正式演示服务不会故意首次失败，也无真实平台请求。

2026-09-25 报告实现：`reports` 以 `(task_id, review_version, format)` 为主键并引用确认快照；保存 state、attempts、error、content BLOB、sha256、generated_at、lease_token/lease_until。确认事务登记两格式，初始化为旧 confirmed 幂等补登记；两分钟租约领取，转换事务外运行，token 条件更新原子发布。SQLite BLOB 为本机演示的简化存储，不返回路径。PDF 复用隔离 LibreOffice；两格式使用同一文本构造器，用户文本不作为 HTML/外部资源执行。

API：GET `/api/v1/tasks/{task_id}/reports/status?review_version=N` 返回 reports 数组，每项 format/state/attempts/generated_at，error 仅法务可见。GET `/reports/{format}?review_version=N` 返回 markdown/pdf 文件，Bearer、no-store；未确认/不存在的确认版本或未 ready 均 409 REPORT_NOT_READY。POST `/reports/{format}/retry` 必填严格正整数 JSON `review_version`，仅法务可将 failed 重排 pending，其他状态 409 REPORT_RETRY_CONFLICT。未登录 401、管理员 403、非本人业务 404。法务确认不受生成失败影响。

## 2026-09-25 法务版本与确认增量

`backend/reviews.py` / `review_versions` 保存任务内递增的审查版本。`PUT /api/v1/tasks/{task_id}/review` 仅法务，必填 `document_version`、`base_review_version`（首次显式 null）、`risks`，可填 `annotation`。每个命中规则恰有一个决策：`rule_id`、`retained`、`risk_level=high/medium/low`、`suggestion_source=rule/model/manual`、`final_suggestion`、`comment`。rule/model 采纳由服务端取原建议，manual 保存编辑文本；保留风险不得缺最终建议，模型缺失不能采纳空建议。来源原文、规则与模型独立冻结，客户端不能改证据或新增未知规则风险。每次保存新增版本并将法务设 in_review、回写设 not_written。

`POST /confirm` 必填 `document_version`、`review_version`、非空 `conclusion`（法务正式结论文本）；机器须 completed、版本须当前，重新核对原件摘要及同版解析/规则/模型来源。事务内保存确认人、时间与快照，再设 confirmed。相同当前版本/结论重复提交返回原快照，不改确认人/时间；不同结论拒绝，须先编辑生成新版本。版本冲突 409/REVIEW_VERSION_CONFLICT，未就绪 409/REVIEW_NOT_READY，证据变化/损坏 409。SQLite BEGIN IMMEDIATE 防止跨连接并发覆盖，失败整体回滚。

`GET /review` 使用可选 document_version/review_version；法务默认当前文档最新审查，业务默认本人最新已确认结果。`GET /risks` 有审查版本时复用此结果，无审查版本时法务仍可读即时规则草稿；`/risks/snapshot` 与 `/model-result` 始终仅法务。业务结果仅含保留风险最终意见及证据，不含机器源快照；业务 `/document` 返回同一确认快照正文，预览及 preview-map 选择对应已确认文档版本。管理员 403、其他业务账号 404，业务显式读取未确认版本 403。

任务摘要新增 `latest_confirmed_version={document_version,review_version}` 和 `risk_level`。当前未确认时等级为 null；`GET /tasks?risk_level=high|medium|low` 只匹配当前已确认正式等级，管理员不得风险筛选。综合等级取保留项最高级，无命中显示“未发现已启用规则风险”，全部不保留显示“未保留风险”，均不自动标低风险。确认快照供下一单元报告生成使用，本轮尚无报告登记/生成和模拟回写；这部分完整契约仍待后续实现。

2026-09-25 扫描 PDF 增量：图片业务已验收。PDF 存在图片或无文本页时整份渲染 OCR，沿用 parse 租约、D-24、摘要校验和重试权限；加密/损坏 PDF 不进入识别。`parsed_documents.extraction_method` 保存 text/ocr（旧库补列），`/document` 对扫描 PDF 返回 ocr 与 extraction_warning。150 DPI、20 页/4000 万像素及中间图大小限制用于本机处理。原 PDF 即预览，直接使用 `/document` 同版归一化 rects；没有 PDF preview-map。图片检测覆盖同页混排的转 OCR 路径，但该版式未做真实识别验证；下文扫描 PDF 未接入为历史。

2026-09-25 图片 OCR 增量（PENDING_ACCEPTANCE）：沿用 parse 租约，`backend/ocr.py` 调用隔离 CPU 子进程，只读已安装模型、不按上传下载。processing_attempts 增加 error_code/error_reason；管理员 `/retry` 对当前版本 blocked/admin_retry 的 OCR 故障重新排队，永久故障要求换附件。图片 PDF 沿用 docx_previews 独立存储及摘要/鉴权。`/document` 增加 extraction_method=ocr 和 warning；preview-map 的 mapping_scope=ocr_line_regions、text_matches=null。D-24 已确认低置信度件整份受阻换件，不发布部分草稿；初始分数阈值 0.9 未标定，不保证无漏字。扫描 PDF 未接入；下文较早能力描述以实施状态为准。

2026-09-25 DOCX 固定预览接入（PENDING_ACCEPTANCE）：`backend/preview_store.py` 使用独立 `docx_previews` 表，按 task_id/document_version 唯一保存 running/ready/failed、180 秒 deadline、原件/解析/PDF/映射摘要及产物路径。默认 worker 对当前已解析 DOCX 生成一次；转换不持有数据库事务，发布前复核同版来源与租约，旧版产物不覆盖新版。过期 running 恢复为 DOCX_PREVIEW_INTERRUPTED，不自动重试，当前无 retry API。预览状态独立，不改写机器审查或已验收解析/规则/模型证据。

`GET /api/v1/tasks/{task_id}/document/preview?document_version=N` 扩展为返回已保存 DOCX PDF；新增同路径 `/preview-map` 返回 DOCX 定位映射（task_id、document_version、persisted、source_sha256、preview_sha256、page_count、normalized_text、text_matches、mapping_scope、paragraphs、clauses、fields）。仅法务；匿名 401、本人业务/管理员 403、其他业务 404；版本不存在 404、非法版本 422。未解析 409 DOCUMENT_NOT_READY；未生成 409 DOCX_PREVIEW_NOT_READY；失败返回保存的 code。读取前验证目录范围、原件/PDF 摘要及同版解析/映射摘要，损坏 409 PREVIEW_EVIDENCE_CHANGED。原 PDF 读取契约不变，preview-map 目前仅用于 DOCX。

定位仅支持严格全文一致且边界完整的段落/条款视觉行；字段子串无精确框时 locatable=false。风险锚点按 document_version/start/end 对应同版映射，不能改写原规则锚点。`/document.preview_available` 表示已登记就绪，最终读取仍须通过完整性检查；DOCX 原 page_count 和段落锚点保留。真实本机 F1/F4 转换及 API 已验证，复杂版式未验证。下方基础组件受阻描述为历史证据。

2026-09-25 DOCX 预览基础组件（PARTIAL）：`backend/docx_preview.convert_docx(content, document_version, executable=...)` 接收本地合成 DOCX，使用已有 LibreOffice 独立 profile 转 PDF，返回 bytes 与来源/产物摘要及段落映射，无数据库/API 副作用。`map_preview` 保留 DOCX 原始字符区间，以去空白全文严格同序和完整 PDF 行框边界作为可定位前提；不符标 DOCX_PREVIEW_TEXT_MISMATCH 或 DOCX_PREVIEW_REGION_UNVERIFIED，不用近似匹配。区域为整段覆盖的完整视觉行，不能用作任意字段的精确框。缺转换器返回 DOCX_PREVIEW_DEPENDENCY_MISSING；不自动安装。当前本机真实转换受阻，转换边界仅模拟验证，服务契约与历史证据均未变。预览持久化/受保护 API/风险和字段映射须在真实固定产物验证后接入。

2026-09-25 验收更新：模型持久作业与读取已获用户验收；真实 F1 由用户本机手动执行，反馈 `{"state": "completed", "code": null}`。下方真实调用受阻属于此前工具审批的历史记录；本轮无接口或流程变更，不新增付费授权，实际费用仍以供应商账单为准。

## 2026-09-25 模型持久作业与读取（离线已验证，真实调用受阻）

`model_jobs` 以 task_id/document_version 为主键，保存 pending/running/completed/blocked/superseded、唯一 call_id/authorization_key、请求摘要、证据摘要、规则版本、规范化结果 JSON 与时间。预留账本和 running 标记在 SQLite 同一事务中提交，嵌套账本使用 SAVEPOINT。180 秒 lease 过期后 blocked、未知费用仍占额；不得自动重新发送。晚到 usage 可结算，但不把已阻塞作业变成完成。旧版结果可留档，不更新新版任务。无命中免费完成；普通有命中作业等待授权，后台不付费。

`GET /api/v1/tasks/{task_id}/model-result?document_version=N`：仅法务；匿名 401、业务本人及管理员 403、其他业务用户 404。版本不存在 404、格式错误 422、未准备 409 MODEL_RESULT_NOT_READY、证据变化 409 MODEL_EVIDENCE_CHANGED、保存内容损坏 409 MODEL_RESULT_INVALID。返回 task_id/document_version、persisted=true、review_version=null、created_at、rule_version_current 和已校验的机器草稿（建议、usage、需法务补充标记）；历史规则过期明确提示，不现场重新调用模型。机器 completed 保持 legal pending。

内部 `python -m backend.model_jobs TASK_ID VERSION` 仅执行 D-15 固定合成 F1 授权，校验原件摘要及路径，从已忽略配置加载密钥，唯一授权跨重启留存；没有公开付费 dispatch/retry API。真实执行工具被自动审批 429 拒绝，命令未执行，需用户本机手动验证；离线成功不等于真实服务可用。自动调度免费分支与故障恢复已接入默认 FastAPI worker；工厂默认仍关闭自动处理供测试使用。

2026-09-25 人工价格核对：用户提供的价格表截图确认 `deepseek-flash` 对应 DeepSeek-V4.1-Flash，人民币高峰缓存未命中输入 2 元/百万 token、输出 8 元/百万 token，与现有 RATES 一致，无需改价。截图是用户提供的官方页面核查材料，不是助手实时访问或账号账单证据；不使用时段折扣。用户已提供官方 V4 tokenizer 压缩包及 CDN 链接，并按 D-21 接受本地模板估算与固定预留方案，不再要求证明线上绝对输入上界。

## 2026-09-25 模型费用预检与私有 HTTP 边界（离线已验证，待验收）

`backend/model_transport.prepare_request(snapshot, tokenizer_path=...)` 复用持久规则草稿校验和 Flash 请求构造，调用 `backend/model_tokens.py` 加载本地已核对摘要的压缩包。只读取 JSON tokenizer 与聊天模板，以现有 tokenizers/Jinja2 沙箱离线计算，不执行示例 Python、不启用 trust_remote_code、不下载。默认资源 `storage/model/deepseek_v4_tokenizer.zip` 被 Git 忽略；缺失、摘要不符或依赖不可用报 MODEL_TOKENIZER_UNAVAILABLE，无规则命中则直接 None、无需加载资源。输入计数是本地模板估算，包含模板角色标记与生成前缀，不保证线上模板/JSON 模式额外开销一致；不使用包内 model_max_length 作为线上上下文限制。

返回 UTF-8 请求体、SHA-256、`estimated_microyuan` 及账本 `quote`。预计超过 100,000 微元报 MODEL_CALL_LIMIT；否则 quote 固定 `reservation_microyuan=100000`，并保留实际估算 `input_tokens`、输出限额 4096、价格及 `input_reference`（本地估算标识、来源 URL、资源 SHA256）。报价不等于持久预留或发送授权。`ModelBudgetStore.reserve` 新增可选 reservation_microyuan/input_reference，保存在原有 quote_json，不改变表结构；预留不得低于估算，重复调用参数含预留额及来源均须一致。原有未传可选参数的报价格式保持兼容。已知 usage 按冻结费率核算，可能超过预留，绝不截断；未知用量仍占用完整 0.10 元。

私有 `_post_json` 仅负责一次 `https://api.deepseek.com/chat/completions` 请求，使用默认 TLS 验证；无自动代理、重定向或重试。30 秒 socket 超时，连接完成后 60 秒请求/读取期限，256 KiB 响应上限；拒绝非 JSON、压缩响应、重复 JSON 键、非法数字、非对象和长度异常。401/403、402、429 分别映射固定凭据/余额/限流错误，其他非200统一失败；连接、超时、解析错误只返回固定脱敏信息，不输出上游正文。DNS 无硬截止保证；未来作业须另行实现租约与恢复。

没有新增公开接口、后台调度或真实调用 CLI。未来调度方必须先校验同版快照、完成本地估算及现价核对、持久预算预留成功后才调用私有传输；失败/未知用量不得自动释放或补发，已知用量按冻结价格结算（即使建议无效）。本轮测试只组合验证组件，不代表持久调度或建议保存已实现。没有让机器进入 completed，也没有授权新的付费次数。真实网络、账户及账单核对仍未验证；这与当前离线功能验收分开记录。

2026-09-24 最新配置：用户已选定 `deepseek-flash`，授权一次合成 F1 真实验证，要求控制额度。调用前仍须完成输入估算及传输边界验证；本次采用预计 0.10 元上限并计入全项目 50 元，超限不发送、失败不自动追加调用。`backend.model_config.load_api_key()` 从项目绝对路径 `secrets/deepseek.ini` 的 `[deepseek] api_key` 读取，支持 UTF-8 BOM，不做变量插值或全局环境设置，配置错误仅报固定信息。真实密钥由用户填写，文件被 Git 忽略且未跟踪；当前加载器未连接 HTTP 传输，不验证账号。以下选型待答复及真实调用未授权为历史状态。

## 模型请求与返回校验（2026-09-24，待功能验收）

`backend/model_advice.py` 无网络、无落库。调用方须先通过 `TaskStore.get_rule_snapshot` / `RuleSnapshotStore.read` 校验来源；组件形状检查不替代原文摘要和锚点核对。`build_request(snapshot, model=...)` 只发送文档版本、证据摘要、规则版本、规则编号、触发原因、必要引文及缺失条款类型，不发送申请人、部门、全文或本地路径。零规则命中返回 None，不表示合同安全。JSON 模式、禁用思考、非流式、输出上限 4096 token；请求上限 100,000 UTF-8 字节，超限 MODEL_INPUT_TOO_LARGE；不是已验证的输入 token 上界。

`validate_response` 要求单个 stop 响应、同版摘要和规则、逐项非空建议，拒绝重复 JSON 键、额外字段、未知/重复规则和截断。模型不提供锚点或等级，建议为独立 source=model、machine_draft、待法务核定。无效内容返回 MODEL_RESPONSE_INVALID 和 requires_legal_supplement=true；合法用量独立保留，未知用量不能当零费用。不改变任务状态，不代表持久化完整机器结果；结构检查不能证明语义或法律正确。

### 官方核查快照

2026-09-24 核对 [人民币价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing)、[英文价格说明](https://api-docs.deepseek.com/quick_start/pricing)、[JSON 模式](https://api-docs.deepseek.com/guides/json_mode)、[思考模式](https://api-docs.deepseek.com/guides/thinking_mode)及 [Chat Completion 契约](https://api-docs.deepseek.com/api/create-chat-completion)。deepseek-flash 对应 DeepSeek-V4.1-Flash，deepseek-v4-pro 对应 DeepSeek-V4-Pro-0813。

| 模型 | 高峰缓存命中输入（元/百万 token） | 高峰未命中输入 | 高峰输出 |
| --- | --- | --- | --- |
| deepseek-flash | 0.04 | 2 | 8 |
| deepseek-v4-pro | 0.30 | 9 | 27 |

低峰为上述一半；高峰为北京时间工作日（不含中国法定节假日）09–12 时、14–18 时。组件使用高峰未命中价格作为保守应用估算快照，不按折扣抵扣，不是供应商账单。已有人民币报价，此快照不另猜美元汇率；真实账号币种/适用条件和费用 UNVERIFIED，真实调用前须重新核对价格及授权。PRICE_REFERENCE 的 checked 日期片段只是本地核查标记，不是官方锚点。两种模型均需显式传入，用户选型待答复，选型不等于付费授权。

独立冒烟 tests.test_model_advice 及预算/自动规则/草稿 API 专项 4/4 通过，响应和 token 用量为合成。HTTP 传输、输入估算、作业/超时/租约、建议持久化及完整机器状态后续接入。

## 自动规则阶段（2026-09-24，待功能验收）

正式服务开启 `auto_process_rules=True`，沿用服务内解析循环；每次扫描当前 `reviewing`、DOCX/PDF 且 `structured_extraction_status=available` 的持久解析结果。`rule_processing_attempts` 以 `(task_id, document_version, attempt)` 为主键保存 `pending/completed/blocked/superseded`、代码、登记/完成时间；补登记使用数据库唯一约束，已经完成或阻塞的不自动重跑。来源为已提交解析记录，启动后可重新扫描，旧版 pending 标 superseded，不生成旧版草稿。

纯本地规则在一个 `BEGIN IMMEDIATE` 事务内完成登记、校验、草稿保存和尝试结果；跨连接写锁保证不重复处理。复用既有同版快照时仍校验内容；来源或规则版本变化不覆盖。中断/SQLite 故障整体回滚，重启后再扫描，未提交的尝试不计数；可捕获处理异常则回滚草稿保存点，提交阻塞记录。此同步短阶段不新增 running 租约；后续网络模型调用必须采用独立租约，不能放入本事务。尝试 `completed` 仅表示规则阶段成功，任务继续 `reviewing`，法务仍 `pending`，不生成审查版本；模型、完整机器结果和法务确认后置。

`POST /api/v1/tasks/{task_id}/retry`：管理员，JSON 必填正整数 `document_version`。仅任务 `blocked/RULE_PROCESSING_FAILED/admin_retry` 且最近同版规则尝试为该暂时故障可重试；事务内追加下一次 pending、任务回 reviewing、保留旧尝试和 `rule_retry_requested` 操作者审计。返回任务/文档版本、stage=rules、attempt、status=pending、machine_status=reviewing。未登录 401、非管理员 403、无任务 404、非法输入 422、错版/重复/非暂时故障 409。解析、模型、预算阻塞的重试暂不支持。证据无效/变化/草稿损坏/规则版本变化为 blocked 并要求 replace_attachment；既有草稿不覆盖。原任务 `attempt_count` 保持解析次数语义，规则次数独立存于上述表。

## 已保存规则草稿读取（2026-09-24）

`GET /api/v1/tasks/{task_id}/risks/snapshot?document_version=1`：仅法务读取；参数可省略，默认当前文档版本，历史文档版本也可显式读取。复用 `/document` 的角色、归属、版本与解析结果校验；权限检查先于快照存在性检查。读取不生成草稿、不运行规则、不修改任何任务状态或审查版本；现有 `/risks` 保持即时计算语义。

返回原保存的草稿以及 `created_at`、`evidence_sha256`、保存时 `rule_version`、与当前规则比较的 `rule_version_current`。规则升级后仍允许读取原草稿，明确标识非当前规则；不自动覆盖。核对原文证据摘要后返回，来源变化拒绝 409/`RULE_EVIDENCE_CHANGED`；损坏 JSON、草稿版本或引文不一致拒绝 409/`RULE_SNAPSHOT_INVALID`。无解析结果 409/`DOCUMENT_NOT_READY`，解析 JSON 损坏 409/`DOCUMENT_EVIDENCE_INVALID`，已解析但未保存 409/`RULE_SNAPSHOT_NOT_READY`；无任务/文档版本 404，非法版本 422。本人业务/管理员 403、其他业务 404、未登录 401。此接口无审查版本选择，返回 `review_version=null`，并非确认结果读取接口。

状态：待用户验收；设计文档，非实现记录。产品行为以 [MVP SPEC](MVP_SPEC.md) 为准，业务顺序见 [核心流程](CORE_FLOW.md)，页面使用方式见 [前端设计](FRONTEND_DESIGN.md)。

## 1. 运行结构

PDF 结构化增量：`backend/pdf_structure.py` 复用字段/条款提取逻辑，用本版 PDF 段落映射条款及风险区域（可跨页），不沿用 F1 的页码。字段保留本版字符区间和源段落页码；局部字段没有独立字符框时 `locatable=false`、`reason=PDF_FIELD_REGION_UNVERIFIED`、`rects=[]`，不得使用整行框冒充精确字段框。`parsed_documents.structured_extraction_status` 新增可迁移列：旧 PDF 标为 `not_implemented`、旧 DOCX 为 `available`；新解析 PDF 与字段/条款原子提交为 `available`，`/risks` 对其开放即时评估。旧 PDF 保留原证据且继续拒绝风险请求，不默默重写历史；当前可通过新建合成任务验证新流程。尚无自动机器审查、PDF 草稿快照或法务确认。

当前增量：正式服务在同一解析循环中依次尝试 DOCX 和 PDF，仍共用全局独占租约、续租、过期恢复及事务提交。PDF 解析使用 `backend/pdf_job.py`，原件摘要一致才处理；`parsed_documents` 增加可空 `page_count`，初始化时保留旧数据并补列。PDF 正文/逐行段落/区域和作业完成状态原子保存，机器进入 `reviewing`，不代表审查完成。`/document` 返回 PDF 页数和 `preview_available=true`（原件预览接口已具备），新增 `structured_extraction_status`：DOCX 为 `available`，PDF 为 `not_implemented`；PDF 字段/条款/缺失列表暂为空，`/risks` 拒绝为 409/`RULE_EVIDENCE_NOT_READY`。加密、损坏、无文本 PDF 分别保留错误代码并要求换附件，OCR 未接入。测试工厂可用 `auto_process_pdf=True` 启用此路径，默认关闭自动处理以供手动单次测试。

一台 Windows 电脑运行一个 FastAPI 服务进程，进程内有一个持久任务处理器；SQLite 存结构化状态，本地文件目录存上传原件、固定预览、OCR/解析产物和报告。前端通过版本化 HTTP API 访问后端。首期不需要独立消息中间件、独立工作进程或真实审批平台连接器。

后端分为六个职责边界：本地身份与权限、任务/模拟待办接入、文档解析与锚点、规则/模型审查、法务复核与版本、报告及模拟回写。可替换的解析/模型组件不得绕开证据、状态或权限检查。最终演示提供一个启动脚本启动本地服务；具体安装命令以另一台约 8 GB 内存 Windows 电脑的验证结果为准。

| 输入类型 | 处理与统一输出 | 关键限制 |
| --- | --- | --- |
| DOCX | 保留原件；以固定转换设置生成 PDF 预览；解析段落并映射到预览页。当前实现正文/段落、显式标题条款及基础字段提取组件，按 Word 正文顺序生成同版 Unicode 字符区间（Python 字符索引）；单次作业校验原件摘要并持久化结果，服务内循环可自动领取 DOCX，尚无固定预览 | 每个锚点最终须指向该文档版本的预览；当前段落、条款及字段页码为空、`locatable=false`、`reason=PREVIEW_NOT_AVAILABLE`、`rects=[]`，不宣称精准定位。条款仅识别明确标题和常见条号；字段仅识别明确标签或首段独立合同标题，重复冲突及缺失值标“未识别”，统一社会信用代码仅做 18 位格式检查，不验证真实性；页眉页脚、批注和浮动文本框尚未覆盖 |
| 文本 PDF | F2 原件已有受保护预览 API；独立 `pdfplumber` 组件提取 NFC 全文、视觉行段落、字符区间、原件页码及归一化段落区域，待用户验收；作业持久化和解析结果 API 尚未接入 | 以原件页序为准，不能拿 F1 的位置套用 F2；仅固定 F2 版式验证，字段/条款/风险精准区域尚未验证 |
| 扫描件 | CPU OCR 生成文字、页、段与坐标；保存对应预览 | 严重模糊或无法核对的内容进入 `blocked` |

pdfplumber 0.11.10 已在 F2 固定样例的独立组件内验证、待用户验收；LibreOffice、PaddleOCR CPU 和 DeepSeek API 仍为待验证候选，不代表目标机兼容性已证实。模型仅处理合成演示合同；调用内容、结果、模型配置及用量关联任务与审查版本，密钥只从运行时环境读取，不写入文档、数据库或日志。

## 2. 持久数据与不变量

PDF 规则快照增量：已有 `rule_draft_snapshots` 允许保存结构化完成、当前版本且机器处于 `reviewing` 的 PDF。规则证据摘要额外包含 PDF 段落和页数（DOCX 摘要兼容旧记录），来源改变或规则版本变化时拒绝覆盖/复用；旧 PDF 的 `not_implemented` 状态不能保存。命令仍是 `backend.rule_snapshot`，不新增 HTTP 写入接口、不更改机器/法务状态；风险读取 API 仍即时评估。自动审查作业、模型和法务确认版本未实现。

| 实体 | 必备关系和字段 | 不变量 |
| --- | --- | --- |
| `User`/`Session` | 本地测试账号、角色、会话、有效期 | 所有读写按服务端身份鉴权；无匿名业务 API |
| `Task` | 申请人、来源、模拟审批单 ID、创建时间、机器状态、阻塞代码/原因、恢复类型 | 一个任务可有多个文档版本；业务经办人只能访问本人任务 |
| `DocumentVersion` | 任务、递增版本、格式、文件摘要/路径、预览路径、提交人/时间 | 重新上传只增版本，原件和旧证据不覆盖 |
| `ParsedDocument`/`Anchor` | 文档版本、规范化全文、字段/条款树、原文片段、起止字符、页、段、页面区域、可定位性及不可定位原因 | 锚点须能在同版全文及预览复核；不可靠时保存原因，不伪造页面区域 |
| `RuleVersion`/`RiskDraft` | 规则来源与版本、命中证据、模型判断/建议、风险等级 | 首期仅启用两条企业商业规则；模型文字不能替换原文证据 |
| `ReviewVersion` | 任务及文档版本、法务编辑、正式结论、状态、确认人/时间 | 确认后不可原位改写；再次编辑创建新版本并重新确认 |
| `ReportArtifact` | 确认版本、格式、`pending/ready/failed`、路径、生成时间、错误和尝试记录 | 两格式独立生成且对应同一确认快照；失败不回退法务确认，重试不读取新草稿；仅 `ready` 可下载 |
| `MockComment`/`WritebackAttempt` | 任务、确认版本、目标模拟单、评论文本/ID、状态、尝试与错误 | `(task_id, confirmed_review_version, mock_approval_id)` 唯一；重试不产生第二条同版评论 |
| `Job`/`AuditEvent`/`CostLedger` | 任务阶段、租约/次数、操作者、时间、调用估算/实际用量 | 状态与日志落库；失败和重启保留可复核记录 |

2026-09-26 A8 增量：`audit_events` 对 F1 人工写操作统一保存 `task_id`、`actor_user_id`、`action`、`document_version`、`created_at`。`review_saved`、`review_confirmed`、`mock_writeback_requested`、`mock_writeback_succeeded`/`mock_writeback_failed` 与对应业务写入共用事务；幂等重读不产生第二事件。解析、模型、报告和回写尝试仍分别由持久作业表保存详细状态；此增量尚未提供审计查询 API，也不等同 A8 全部验收。

2026-09-26 A8 查询增量：`GET /api/v1/tasks/{task_id}/audit-events` 仅管理员可用，支持可选 `document_version>=1`、`limit=1..100`（默认 100）、`offset>=0`；按审计 ID 升序返回 `task_id`、`total`、`items`。每项仅含 `id`、`action`、`document_version`、`created_at`、`actor_username`、`actor_role`。不暴露正文、附件路径、密钥或评论内容；无权限 401/403，缺失任务 404，参数错误 422。该只读接口供 A8 核对，不把机器作业的细节误标为人工审计事件。

SQLite 操作使用事务保护状态转移、审查确认、任务领取及模拟评论唯一约束；文件落盘采用先写临时产物、校验后登记的顺序。清理仅由显式重置触发，不在重启时自动删除任务或证据。

当前 `backend/demo_rules.py` 为独立的 `demo-v2` 商业规则组件：输入同版正文、段落与显式标题条款，输出 `machine_draft`、规则 ID/版本、风险、原文锚点、建议及待法务核定标记；`review_version=null`。已识别的软件权属归供应商且无采购方使用授权时提示风险；到货付全款且验收条款被标记缺失时提示风险，并在草稿中记录 `missing_clause_types`。明确未约定付款前验收条件也会提示；含糊验收和相反约定仍留法务判断。无命中只表示“未发现已启用规则风险”，不证明合同安全。该组件已接入法务即时评估的 `/risks`；另有已验收的手动规则草稿持久化命令，尚无自动审查作业，不会将任务推进至 `completed`，也不调用模型；F1/F4 预览前标注已验收，正式全链路及法务核定仍待完成。

## 3. API 契约

当前增量：`GET /api/v1/tasks/{task_id}/risks` 已实现法务专用的即时规则评估，使用已持久化的同版正文、段落与条款。返回规则组件字段及 `task_id`、`evaluation_mode=on_demand_rules_only`、`persisted=false`；`review_version=null`。不保存草稿、不产生审查版本、不改变机器状态；后续持久审查快照功能完成前，不能将此响应视为可确认版本。权限沿用解析结果接口：本人业务/管理员 403、他人业务 404、未登录 401；未解析 409/`DOCUMENT_NOT_READY`、无此文档版本 404。显式指定任意正整数审查版本返回 404/`REVIEW_VERSION_NOT_FOUND`，非正版本 422；条款证据与正文、段落或版本不符，以及存储 JSON 损坏，均返回 409/`RULE_EVIDENCE_INVALID`，不返回部分草稿。权限校验先于审查版本查询。

统一前缀 `/api/v1`；请求和响应为 JSON，上传、PDF 预览及报告文件除外。`POST /sessions` 返回短期不透明会话令牌与角色，服务端保存有效期及撤销状态；浏览器仅在内存中保存令牌，请求用 `Authorization: Bearer <token>` 携带，刷新页面后须重新登录，退出时撤销。后端按账号、角色和任务归属检查；令牌及明文凭据不写入日志。接口名称及载荷字段在开发前以本文为基线，新增字段不得放松权限或版本约束。

| 接口 | 输入与主要输出 | 允许角色及条件 |
| --- | --- | --- |
| `POST /sessions`、`GET /sessions/current`、`DELETE /sessions/current` | 本地测试账号凭据 → 会话/角色；带令牌查询当前身份；退出撤销会话 | 所有测试角色；查询和退出须有效 Bearer 令牌，失败不暴露密码细节 |
| `GET /tasks`、`GET /tasks/{task_id}` | 三组状态筛选及后续风险筛选 → 列表或任务摘要；三组当前状态及当前文档/审查版本，受阻阶段、原因、尝试次数和恢复类型；有正式结果时另附可见的最新已确认版本对 | 业务只见本人，当前版本确认前不含其草稿/综合等级；法务与管理员按职责见任务。当前已实现三组状态筛选，风险筛选待风险数据实现 |
| `POST /tasks` | `multipart/form-data`：`file`、`department`、`applicant` → `task_id`、文档版本、`pending`；仅合成 DOCX/PDF/PNG/JPEG/TIFF，每份最多 25 MiB；接入时检查文件格式特征和摘要 | 业务经办人；接入和落库已实现，DOCX 由服务内处理器自动解析为 `reviewing` 或 `blocked`，PDF/图片仍保持 `pending` |
| `GET /mock-pending`、`POST /mock-pending/{id}/import` | 固定合成待办列表；当前唯一 ID 为 `demo-f1-001`，列表含 `synthetic=true`、申请信息和附件名；导入创建带 `source=mock_pending`、`mock_approval_id` 的任务和文档版本并返回任务摘要。重复导入创建独立任务；模拟附件超时及其异步受阻仍待处理器实现 | 仅业务经办人；导入与本地上传初始均为 `pending`，DOCX 随后自动处理；F6 超时尚未验证 |
| `POST /tasks/{task_id}/documents` | `multipart/form-data`：新 `file`、必填 `base_document_version` → 新文档版本，当前机器/法务/回写为 `pending/pending/not_written`，阻塞信息和当前尝试次数清空 | 本人业务账号可在当前版本 `blocked/replace_attachment` 或上一文档机器完成且法务已确认后提交修订版；处理中、其他受阻恢复类型或基础版本过期返回 409。旧原件、旧审查版本号、旧版三组状态/阻塞信息和尝试次数留存；接口已实现，允许状态目前仅在受控测试中构造，尚未完成 F5 全链路 |
| `POST /tasks/{task_id}/retry` | 原版本重试请求 → 当前任务状态/尝试次数 | 管理员；仅可重试的暂时性阻塞；预算阻塞需先有用户明确预算调整 |
| `GET /tasks/{task_id}/document` | 当前/指定 `document_version` → 同版解析正文、段落、字段、条款、缺失类型和锚点；已实现的解析阶段返回 `review_version=null`、`page_count=null`、`preview_available=false`，不冒充预览或审查结果 | 本轮仅法务可读；本人业务在确认前 403、其他业务 404、管理员 403；业务在法务确认后的正式结果读取待确认流程实现。无解析结果 409、无此版本 404 |
| `GET /tasks/{task_id}/risks` | 当前已实现同版规则即时草稿，`persisted=false`、`review_version=null`；持久机器/法务风险记录及已确认版本读取待实现 | 当前仅法务可读；本人业务在确认前 403、他人业务 404、管理员 403。后续业务仅可读取本人已确认结果，不得读取机器草稿 |
| `GET /tasks/{task_id}/document/preview` | 当前仅对 PDF 原件提供当前或指定版本的受保护同版字节读取；F2 可作为其自身预览。DOCX/扫描件固定预览和页码/区域锚点待实现；通用 PDF 结构及加密检测待验证 | 与同版 `/document` 相同的服务端鉴权和版本限制；业务仅取本人已确认快照的预览，管理员不可读取；禁止公开静态文件直链 |
| `PUT /tasks/{task_id}/review` | 基础审查版本、风险调整、建议与批注 → 新复核版本 | 法务；基于版本号防覆盖；已确认版编辑形成新版草稿 |
| `POST /tasks/{task_id}/confirm` | 待确认版本、正式结论 → 确认版本/确认人/时间 | 法务；机器须 `completed` 且证据可核对 |
| `GET /tasks/{task_id}/reports/status` | 必填 `review_version` → Markdown/PDF 各自的 `pending/ready/failed`、尝试次数；法务可见错误，业务仅见可用性 | 法务或任务本人业务账号；只允许已确认版本，业务不得枚举未确认版本 |
| `GET /tasks/{task_id}/reports/{format}` | `format=markdown/pdf`、确认版本 → 文件下载 | 法务或任务本人业务账号；只允许已确认版本 |
| `POST /tasks/{task_id}/reports/{format}/retry` | 必填 `review_version` → 同版该格式的新生成状态 | 法务；仅 `failed` 可重试，`pending/ready` 不重复生成 |
| `POST /tasks/{task_id}/mock-writeback` | 确认版本、目标模拟审批单 ID → 写入状态/评论 ID | 法务；同一幂等键重复请求返回已有结果或当前进度 |
| `GET /tasks/{task_id}/mock-writeback` | 确认版本 → 模拟评论、状态、尝试和错误摘要 | 法务、管理员；业务只见本人已确认版本的最终结果 |

`task_id`、文档版本和审查版本在响应中显式返回。`GET /document` 和 `/document/preview` 使用 `document_version` 查询参数；`GET /risks` 使用 `document_version` 和可选的 `review_version`，报告状态、下载与重试使用必填 `review_version`；模拟回写读取使用确认版本。未指定可选版本时，法务取得当前可审版本；业务取得本人最新已确认快照的文档与审查版本，即使已有更新的未确认草稿也不得混入。任务摘要单独给出当前文档/审查版本的三组状态和可见的最新已确认版本对；若当前版本未确认，其综合等级为空，旧确认等级只在标有旧版本的历史结果中出现。风险筛选只依据该角色有权看到的当前正式等级执行，不能通过列表是否命中泄露草稿或把旧版等级当作当前等级。

字段、条款及风险锚点包含 `document_version`、`quote`、`start`、`end`、`page`、`paragraph_index`、`locatable`、`reason` 和 `rects`。`rects` 是同版 PDF 预览的一个或多个 `{page, x, y, width, height}`，页码一起始，坐标以每页左上角为原点并归一化到 0–1，宽高大于零且区域不越界；跨页文本可有多个区域，`page` 是首个区域的页码。`locatable=true` 必须有可复核的非空区域，且引文与同版规范化全文的字符区间一致；无法满足时置 `locatable=false`、提供 `reason`、`rects=[]`，不得让前端猜测高亮位置。业务列表在当前版本未确认时对当前综合等级返回空值，而不是把机器草稿或旧版结论伪装为当前结果。任务受阻时返回 `recovery_action`：`replace_attachment`、`admin_retry`、`budget_decision` 或 `none`，与阻塞代码及角色一致；预算调整本身不是前端自助动作。所有版本化写入需要客户端提交当前基础版本，避免并发法务操作静默覆盖。

错误响应统一包含 `code`、`message`、`retryable`；相关请求附 `task_id` 和当前状态。认证失败为 401、越权为 403、目标不存在为 404、状态或版本冲突为 409、附件超限为 413、不支持的文件扩展名为 415、附件内容或输入无法受理为 422；异步解析/模型失败由任务 `blocked` 和结构化原因表达，不能将 HTTP 接收成功当作审查完成。预览、报告或回写对未确认版本返回 409，越权仍返回 403。报告生成中或失败时，文件 GET 返回 409/`REPORT_NOT_READY`，不返回空文件；失败原因在报告状态接口按角色过滤。PDF 预览和报告须用 Bearer 凭据请求且只针对允许版本，不能暴露本地文件路径或公开静态直链；报告预览与下载使用同一确认版本。日志不得记录明文凭据或完整外部请求密钥。

当前已实现的修订附件接口在归属校验通过后，对 `DOCUMENT_VERSION_CONFLICT` 和 `TASK_STATE_CONFLICT` 的 409 响应附 `task_id`、`current_status`；后者包含当前文档/审查版本、机器/法务/回写状态、阻塞代码/原因、恢复动作及尝试次数。401/403/404 不附这些任务信息。附件先写 `.part` 再移至最终路径；如果本次数据库事务失败，清理本次新建文件，已登记旧版原件不受影响。

## 4. 队列、恢复与模型预算

2026-09-24 实施增量：`backend.model_budget.ModelBudgetStore` 为内部预算组件，`TaskStore.initialize` 初始化 `model_budget_entries`。每个 `call_id` 唯一关联任务/文档版本、冻结的模型/价格来源/输入上界/最大输出/人民币费率、预留金额、用量和创建/更新时间。金额为整数微元，费率单位为每百万 token 的微元，费用计算总额向上取整。预算固定全项目 50 元，无调整 API。调用方负责保守 token 上界、官方价格核查与必要汇率缓冲；组件本身不证明价格有效或用户授权付费。

`reserve` 用 `BEGIN IMMEDIATE` 原子核对已估费用和未结预留；仅当前 reviewing 文档可新增记录。足额为 reserved，超额为 rejected，并在同事务把任务设 blocked/BUDGET_LIMIT/budget_decision。相同调用标识和参数返回已有记录且 created=false，不表示可再次发送；参数冲突拒绝。`settle` 按冻结价格和返回用量记应用估算，重复相同用量幂等、不同用量拒绝；超出预留的估算如实记录，不截断。无用量为 unknown，reserved/unknown 均持续占额，重启不释放；后续可信用量可以结算。原始预留及价格仍保留。其他调用结算不自动解锁已受阻任务。

本轮不接入模型作业、HTTP 费用接口或人工核账入口；未来模型处理器还须实现领取/租约、发送与重启恢复策略，不能把一次成功预留视为外部调用恰好一次的保证。未知用量所需人工核实调整尚未实现。本项不改变机器完成、法务或报告状态。

创建任务在同一 SQLite 事务内登记任务、文件引用与待处理阶段作业；同一 FastAPI 服务内的处理器按任务领取并写入阶段、尝试次数和租约。仅允许一个活动处理器实例；启动时扫描未完成租约，将已提交但中断的解析/审查任务恢复为可重试状态，并检查产物版本，避免重复覆盖。解析暂时故障与模型超时可按原版本重试；加密、空文、严重模糊等需新附件的失败不得盲目重试。法务确认以事务固定审查快照，并登记 Markdown/PDF 各自的待生成任务；生成结果或错误分别落库。报告失败由法务按确认版本和格式重试，服务重启可恢复未完成的生成任务；法务确认和模拟回写通过单独事务处理，不依赖机器任务租约。

当前队列基础已将接入/换版与 `parse` 作业登记放在同一事务；已有 `processing_jobs`、`processing_attempts`，原子领取时同时写入 `parsing` 和尝试次数，只有一个未过期租约能处于活动状态。服务启动时恢复已过期租约，保留旧尝试；旧版本换版后作业终止。`backend.main:app` 启动服务内 `DocxWorker`，约每 0.5 秒轮询现有 DOCX 作业；手动运行 `python -X utf8 -m backend.docx_job` 仍可单次领取。处理器核对文件摘要和有效租约，将同版正文、段落、字段和条款存入 `parsed_documents`；成功后任务进入 `reviewing`（审查尚未执行），空文/原件异常进入 `blocked/replace_attachment`。旧版或过期令牌不能写入结果；结果、尝试和任务状态在同一事务内提交，尝试记录缺失或中途写入失败时整体回滚。独占租约被占用时，单次处理命令返回 `busy`；处理期间每 20 秒续租，默认租约 60 秒，续租失败时最终提交仍由租约校验拒绝。服务停止时等待当前 DOCX 作业完成。旧 `processing_attempts` 表会迁移以记录完成/受阻状态并保留旧尝试。F2 PDF 原件受保护预览 API 已实现；本轮独立 PDF 文本与段落区域提取组件待验收，但尚无 PDF 作业及解析结果 API。DOCX/扫描件固定预览、OCR 和审查阶段作业尚未实现；PDF/图片接入仍停留 `pending`。

当前增量提供 `backend.rule_snapshot` 手动命令：对已解析且状态为 `reviewing` 的当前 DOCX 版本，在事务内把两条已启用商业规则的草稿保存到 `rule_draft_snapshots`，唯一键为 `(task_id, document_version)`；同时保存 `demo-v2` 规则版本与正文/条款来源证据摘要。重复执行不覆盖；错版、未就绪或证据损坏不创建记录，来源证据事后变化返回 `RULE_EVIDENCE_CHANGED`，已存规则版本不同返回 `RULE_VERSION_CHANGED`，均不覆盖既有结果。该表只是一份规则草稿，不是完整机器审查或法务确认快照；不会生成 `review_version`、变更机器状态，也尚未由 `/risks` API 读取。自动审查队列、模型判断、失败恢复与法务确认仍按设计待实现。

每次 DeepSeek 调用前，按当前官方价格配置、输入估算、最大输出 token 和汇率缓冲预留预计费用；`已估费用 + 未结预留 + 本次预留 > 50 元` 时拒绝新调用，任务设 `blocked/BUDGET_LIMIT`，已解析数据保留。调用后以返回用量更新项目估算账本；超时或用量未知保留可核对的预留记录，待人工核实后调整。只有用户明确调整预算并记录新额度，才解除预算阻塞。应用估算不能保证供应商最终账单恰好不超过 50 元；实际金额须对照 DeepSeek 账单，若需严格外部上限，应另行配置供应商侧限额或专用余额（能力待核实）。

模型请求仅包含完成当前风险建议所需的合成条款、规则版本和证据上下文。返回内容要校验结构、引用的原文锚点及规则。依赖超时进入 `blocked` 待重试；若规则证据完整、但模型建议无效或缺失，可产出带“需法务补充建议”标记的机器草稿供法务处理；证据本身不足时仍 `blocked`，不得伪造锚点或正式结论。规则判定和模型生成分别存储，固定样例可用受控响应测试，但 A8 还需真实一次 F1 调用。

## 5. 后端阶段验收证据

通过 API 脚本或人工请求验证 F1–F6 和 [MVP SPEC 的 A1–A8](MVP_SPEC.md#6-固定样例与验收)中后端列：字段/锚点逐项对照标注；三角色逐接口权限拒绝；确认前不可下载；新文档与新审查版本的当前状态不混入旧确认快照；版本冲突、重启恢复、预算阻塞；首次回写失败与重复请求只留一条同版评论；Markdown/PDF 与确认快照一致，单格式报告失败后可在同版重试且不回退确认。记录运行电脑、依赖版本、真实模型调用、估算与账单核对状态。前端双向联动和另一台 Windows 电脑验收留到前端阶段。
