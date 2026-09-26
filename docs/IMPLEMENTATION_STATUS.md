# 实施与验收状态

## 2026-09-26 全面验收 A1：接入解析页面核对（PENDING_BROWSER_VERIFICATION）

用户已验收大盘合同名称与金额，按 `MVP_SPEC.md` 第 6 节进入下一项 A1。现有自动证据为上轮 171/171 后端回归中的 F1–F3 上传及模拟待办导入本机 HTTP 链路，以及前端 43/43 逻辑测试和构建；这些不能证明浏览器操作可用。本轮不重复付费 F1 调用，不修改真实业务库。A1 页面检查步骤：在独立数据目录按 README 的 `--process-local --data-root` 方式启动并创建业务、法务、管理员账号；业务在页面分别上传 `samples/f1-software-purchase.docx`、`samples/f2-text-software-purchase.pdf`、`samples/f3-clear-scan.png`，再从模拟待办导入 `demo-f1-001`。确认每项出现任务且状态由待处理进入解析结果；法务在工作台按 `samples/f1_f4_expected.json`、`f2_expected.json`、`f3_expected.json` 核对本版字段、条款、页码及缺失项。F1 预期合同名称“合成软件采购合同（仅供演示，非真实交易）”、金额 `100000`、币种“人民币”；F2/F3 采用各自标注，不能继承 F1 页码。业务在确认前看不到解析字段，管理员无合同内容，其他业务账号不能访问任务；不支持的附件应被拒绝。F1/F2/F3 有规则命中，按需处理模式不会自动发起付费模型调用，机器阶段可能留在 reviewing，不据此判 A1 解析失败。

可单独重跑 A1 本机 HTTP 冒烟：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_local_http_acceptance.LocalHttpAcceptanceTests.test_f1_live_proxy_chain_and_permissions tests.test_local_http_acceptance.LocalHttpAcceptanceTests.test_f2_pdf_live_proxy_pages_review_and_permissions tests.test_local_http_acceptance.LocalHttpAcceptanceTests.test_f3_scan_live_proxy_ocr_regions_review_and_permissions -q`。上轮全量已包含这三项，本轮仅修正验收记录，未重复执行；它们使用临时库、合成账号和受控模型响应，不替代页面核对。

本轮无法执行页面点击：当前环境没有可用浏览器或 Playwright，未取得截图、DOM 或交互结果。A1 页面结果记 `UNVERIFIED`，等待实际浏览器核对后才能判定 A1 前端通过；随后按 A2 双向定位继续。目标 Windows 电脑验证依 D-27 后置。此段是验收执行清单与现有证据边界，不等于用户已经验收 A1。

## 2026-09-26 FE1：大盘合同名称与金额；本机全面验收启动（ACCEPTED）

用户本轮明确回复“验收通过，进行下一项”，本项据此记为 `ACCEPTED`，不把该回复视作全面验收全部通过。业务要求 → 实现：`backend/tasks.py` 从当前文档版本已保存的解析字段提取 `title`、`amount`、`currency`，在任务列表与详情摘要返回 `contract`；法务可看当前版，业务仅当前版法务已确认时可看，管理员无此字段。`frontend/src/model.ts`、`main.tsx` 在大盘和详情展示合同名称与金额，文件名另列；字段或币种不能识别时明示，不用文件名、旧版数据或猜测币种替代。无新增表结构、无真实库迁移或付费调用。

独立冒烟 `tests.test_dashboard_contract` 覆盖解析前后、列表/详情一致、法务确认前后、管理员和其他业务权限、新文档版本隔离；`frontend/tests/dashboard.test.ts` 覆盖展示与缺失值。验证：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_dashboard_contract -q` 1/1 PASS；`node --experimental-strip-types --test frontend/tests/dashboard.test.ts` 6/6 PASS；`npm.cmd --prefix frontend test` 43/43 PASS；`npm.cmd --prefix frontend run build` PASS。测试均使用合成数据和临时库；未动真实业务库。

全面验收按 `MVP_SPEC.md` 第 6 节 A1–A8 与 F1–F6 核对。上轮全量后端回归 `.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -q` 171/171 PASS（588.590 秒），其中 `tests.test_local_http_acceptance` 包含 9 条本机真实 Uvicorn + Vite `/api` 代理的 F1–F6 合成链路、权限、恢复和模拟回写。此为合成数据、受控模型响应及临时库技术证据：A1–A7 的 API/本机 HTTP 路径已覆盖，A8 的 F1 API 与本机 HTTP 路径已覆盖。页面真实点击、原文与风险卡片双向高亮、下载体验均为 `UNVERIFIED`：当前执行环境没有可用浏览器或 Playwright。D-27 已将目标 Windows 电脑验证推迟到本机总体验收之后，不把目标机结果当成本轮完成条件。F1 一次真实 DeepSeek 调用曾由用户手动执行并验收，见下文 2026-09-25 最新验收记录；本轮只读核对默认库中该任务 `model_jobs` 为 `completed`、`code=NULL`，有同一授权键和已保存结果，预算记录为 `settled` 且有 usage；这支持该调用已完成，但供应商账单金额未独立核对。D-21 已替代更早的线上 token 绝对上界阻塞，不能再将其写为当前阻塞。规则与示范条款的专业法务核定仍 `UNVERIFIED`。全面验收已进入执行阶段，尚不能宣布 A1–A8 全部通过。

## 2026-09-26 FE1：大盘创建时间展示（ACCEPTED）

用户本轮明确回复“验收通过”，本项据此记为 `ACCEPTED`。以下保留交付当时的技术证据和限制。

上一项 FE1/FE2 业务类型录入与大盘展示已获用户本轮回复“验收通过，进行下一步”，据此记为 `ACCEPTED`。本轮业务要求 → 实现：`GET /tasks` 已返回任务建立时的 `created_at`，`frontend/src/main.tsx` 在每条任务的列表单元展示“创建：…（本机时间）”，与详情页共用 `frontend/src/model.ts` 的格式化函数；非法或缺失时间显示“时间未记录”，不显示 `Invalid Date`。对管理员同样仅显示任务建立时间，不增加合同内容可见范围。合同名称与金额仍待单独处理，不能从尚未确认的解析结果向业务提前暴露。

独立冒烟 `node --experimental-strip-types --test frontend/tests/dashboard.test.ts` 5/5 PASS（含合法 UTC 时间按本机时区展示及异常值提示）；`npm.cmd --prefix frontend test` 42/42 PASS，`npm.cmd --prefix frontend run build` PASS。已有后端字段未改，未操作真实数据库。浏览器实际列表显示、跨时区人工核对仍 `UNVERIFIED`；本项待用户验收。

## 2026-09-26 FE1/FE2：业务类型录入与大盘展示（ACCEPTED）

用户本轮回复“验收通过，进行下一步”，本项据此记为已验收。以下保留交付时的技术证据与限制。

上一项 FE1 任务列表权限拒绝处理已获用户本轮回复“验收通过，请进行下一项”，据此记为 `ACCEPTED`。本轮业务要求 → 实现：上传合成合同须在前端选择“软件采购”演示类型，`frontend/src/Intake.tsx` / `intake.ts` 写入 multipart；`backend/main.py` / `tasks.py` 验证并保存至任务，模拟待办固定带相同类型；`GET /tasks` 与详情对业务、法务返回 `submission.business_type`，大盘显示业务类型，老任务或旧调用没有该字段时显示“未记录”。管理员继续只见职责范围状态，不返回提交信息。新增 nullable 列兼容旧任务；本轮仅在隔离临时库运行，没有启动或迁移实际业务库。现有 API 客户端未传业务类型仍可创建旧口径任务，新前端要求明确选择。

独立冒烟 `./.venv/Scripts/python.exe -X utf8 -m unittest tests.test_business_type -v` 7/7 PASS（含测试夹具附带的 5 项复核回归；上传/模拟导入成功、列表/详情可见、越权/非法类型拒绝及旧请求兼容）；`npm.cmd --prefix frontend test` 41/41 PASS，`npm.cmd --prefix frontend run build` PASS。均为隔离 API 与逻辑验证；浏览器实际选择、提交及页面显示仍 `UNVERIFIED`。金额、合同名称独立字段及创建时间的大盘展示尚未完成，本项不代表大盘整体符合 MVP。

## 2026-09-26 FE1：任务列表权限拒绝时清理旧视图（ACCEPTED）

用户本轮回复“验收通过，请进行下一项”，本项据此记为已验收。以下保留交付时的技术证据与限制。

上一项 FE6 模拟回写状态轮询故障恢复已获用户回复“验收通过，进行下一项”，据此记为 `ACCEPTED`。本轮业务要求 → 实现：任务列表的只读轮询收到 403 时，`frontend/src/taskPolling.ts` 停止自动重试并通知页面；`frontend/src/main.tsx` 清除缓存任务、详情、上传回执与上次更新时间，隐藏原有任务和操作区，显示无权访问及手动重新读取入口。401 仍退出登录；短暂网络错误仍保留上次任务、提示可能过期并重试。此处理遵守前端设计中 403 不展示缓存内容的约束。

独立冒烟 `node --experimental-strip-types --test frontend/tests/taskPolling.test.ts` 3/3 PASS（合成成功读取→403 触发清理回调并停止轮询；401 与暂时故障路径）；`npm.cmd --prefix frontend test` 41/41 PASS；`npm.cmd --prefix frontend run build` PASS（TypeScript + Vite，54 modules）。权限变化为受控模拟，实际浏览器页面点击、服务端实时撤权场景仍 `UNVERIFIED`；本项待用户验收。

## 2026-09-26 FE6：模拟回写状态轮询故障恢复（ACCEPTED）

用户本轮回复“验收通过，进行下一项”，本项据此记为已验收。以下保留交付时的技术证据与限制。

上一项 FE5 报告状态轮询故障恢复已获用户本轮明确验收。本轮业务要求 → 实现：`frontend/src/writebackPolling.ts` 对同任务、同文档及审查版本的模拟回写状态进行只读 GET 轮询；`writing` 状态读取遇短暂网络、429 或 5xx 故障时保留上次成功状态、提示可能过期并每 5 秒自动重试，恢复后清除提示。401 退出；403、确认版本不一致或成功状态缺少评论 ID 时停止轮询并隐藏旧状态；切换任务、版本或离开页面会取消请求与计时器。`frontend/src/Writeback.tsx` 接入该流程，读取故障期间禁用提交并保留手动刷新入口；回写 POST 仍只由法务人工触发，结果不确定时不会自动重发。仅本地模拟，不连接真实审批平台。

独立冒烟 `node --experimental-strip-types --test frontend/tests/writebackPolling.test.ts` 2/2 PASS（合成结果：写入中→连接失败→成功且未再提交 POST；401、403、错版停止轮询）。`npm.cmd --prefix frontend test` 40/40 PASS；`npm.cmd --prefix frontend run build` PASS（TypeScript + Vite，54 modules）。故障恢复为受控模拟，实际浏览器断连、视觉与点击仍 `UNVERIFIED`；FE6 此增量已由用户验收。

## 2026-09-26 FE5：报告状态轮询故障恢复（ACCEPTED）

用户本轮回复“验收通过，进入下一项”，本项据此记为已验收。以下保留交付时的技术证据与限制。

上一项 FE1/A8 任务列表轮询故障恢复已获用户本轮明确验收。本轮业务要求 → 实现：`frontend/src/reportPolling.ts` 对确认版本的 Markdown/PDF 报告状态继续每 5 秒查询；遇短暂网络、429 或 5xx 故障时保留上次成功状态、提示可能过期并自动重试，恢复后清除提示。401 退出会话；403 等非临时错误、任务 ID 或审查版本不一致时停止轮询并隐藏旧状态；切换任务、版本或离开页面会取消请求与计时器。`frontend/src/Reports.tsx` 接入此流程，读取失败时仍提供手动刷新入口，已就绪文件的后端权限和版本校验保持有效。未接入真实审批平台或付费模型。

独立冒烟 `node --experimental-strip-types --test frontend/tests/reportPolling.test.ts` 2/2 PASS（合成报告：待生成→连接失败→恢复就绪；401、403、版本不一致停止轮询）。`npm.cmd --prefix frontend test` 38/38 PASS；`npm.cmd --prefix frontend run build` PASS（TypeScript + Vite，53 modules）。断连与状态转换为受控模拟，实际浏览器视觉、点击和断连仍 `UNVERIFIED`；FE5 此增量待用户验收。

## 2026-09-26 FE1/A8：任务列表轮询故障恢复（ACCEPTED）

用户本轮回复“验收成功，请进行下一项”，本项据此记为已验收。以下保留交付时的技术证据与限制。

上一项 A8 本机按需处理模式已获用户明确验收。本轮业务要求 → 实现：`frontend/src/taskPolling.ts` 承接已有 5 秒任务轮询，短暂网络/API 故障后继续重试；`frontend/src/main.tsx` 保留上次成功读取的任务及更新时间，显示读取失败与信息可能过期的提示，可手动重读，成功后清除提示。401 会话失效仍退出；无活跃任务时停止轮询，已取消或卸载的轮询不再更新页面。已有任务上的写操作仍由后端逐接口校验版本、状态和权限。

独立冒烟 `node --experimental-strip-types --test frontend/tests/taskPolling.test.ts` 2/2 PASS（合成任务：活跃状态→连接失败→恢复完成；旧任务不清空、重试间隔和 401 退出）。`npm.cmd --prefix frontend run build` PASS（TypeScript + Vite，52 modules）。网络失败为受控模拟，实际浏览器断连、视觉与点击仍 `UNVERIFIED`；A8 总体验收保持 `PARTIAL`。

## 2026-09-26 A8 本机按需处理模式与 F4 页面验收前置链路（ACCEPTED）

用户随后回复“验收通过，进行下一项”，本项记为已验收。以下保留交付时的证据与限制。

用户已明确验收 F6 首次模拟回写失败、重试与去重本机 HTTP 联调。本轮业务要求 → 实现：`scripts/start_local.py --process-local` 显式开启 `backend/local_runtime.py` 已有的解析、规则、模型结果、预览、报告和模拟回写后台处理器，默认查询模式保持原有语义。模型处理器对无规则命中的 F4 自动保存 `MODEL_NOT_REQUIRED`；有风险命中的 F1 仍等待单次单独授权，不发送付费请求。此模式可用隔离 `--data-root` 为 F4 页面验收准备完整的真实本机处理链，尚无浏览器点击证据。

独立冒烟 `tests/test_local_processing_launcher.py` 用临时 SQLite、合成账号和真实 Uvicorn/Vite 代理核对 F4 上传、无命中完成、法务复核确认、两种报告、模拟回写和角色拒绝；另上传 F1 验证两条规则风险已保存而模型结果与提前确认仍被拒绝。`tests/test_local_launcher.py` 核对显式开关启动、端口释放及默认查询模式。技术验证：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_local_processing_launcher -v` 1/1 PASS；`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_local_launcher -q` 3/3 PASS。均使用临时数据与合成账号，无付费模型请求。本机没有可用的 Playwright 或浏览器可执行文件，页面点击与视觉仍 `UNVERIFIED`；A8 总体验收保持 `PARTIAL`。

## 2026-09-26 A7 F6 首次模拟回写失败、重试与去重本机 HTTP 联调（ACCEPTED）

用户本轮回复“验收通过，请进行下一项”，F6 回写失败、重试与去重联调据此记为已验收。以下保留交付时的技术证据与边界。

用户已明确验收 F6 模拟待办附件超时与管理员重试本机 HTTP 联调。本轮业务要求 → 实现与验证：`tests/test_local_http_acceptance.py::test_f6_writeback_failure_live_proxy_retry_dedup_and_permissions` 使用临时 SQLite、合成账号与 F1 固定合同，经真实 Uvicorn 和 Vite `/api` 代理完成法务确认后的模拟回写。确定性内存评论依赖首次失败，接口显示 `failed/MOCK_WRITEBACK_FAILED`、无评论 ID；法务重试后为 `success`，保留失败与成功两次尝试，同版重复提交返回同一评论 ID 且不增加评论或尝试次数。覆盖确认前 409、无效目标 404、非法版本 422、未登录 401、越权 403/404，以及业务账号与管理员读取字段范围。测试不连接真实审批平台或付费模型，内存依赖仅用于注入故障，应用回写状态和尝试记录保存于临时 SQLite。

技术验证：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_local_http_acceptance.LocalHttpAcceptanceTests.test_f6_writeback_failure_live_proxy_retry_dedup_and_permissions -v` 1/1 PASS；`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_local_http_acceptance -q` 9/9 PASS。真实平台写入、浏览器点击仍 `UNVERIFIED`，A8 总体验收仍 `PARTIAL`。

## 2026-09-26 A7 F6 模拟待办附件超时与管理员重试本机 HTTP 联调（ACCEPTED）

用户本轮回复“验收通过，继续下一项”，F6 模拟待办附件超时联调据此记为已验收。以下保留交付时的技术证据与边界。

用户已明确验收 F5 严重模糊扫描件受阻换件本机 HTTP 联调。本轮业务要求 → 实现与验证：`tests/test_local_http_acceptance.py::test_f6_pending_attachment_timeout_live_proxy_admin_retry_and_permissions` 用临时 SQLite、合成账号、确定性首次超时故障源，通过真实 Uvicorn 与 Vite `/api` 代理导入模拟待办。首次获取附件后任务为 `blocked/ATTACHMENT_FETCH_TIMEOUT/admin_retry`，尝试次数 1，无附件摘要、风险等级或可读正文/风险；未取得附件时正文和风险 API 返回 `DOCUMENT_VERSION_NOT_FOUND`（404），提前确认被拒绝。管理员可查看首次失败历史，按原文档版本重试后尝试次数为 2、附件入队；错版、越权、未登录及重复重试被拒绝。随后真实 DOCX 解析和规则作业完成，同版产生两条固定演示风险，首次失败及第二次成功的尝试历史均保留。不请求外部审批平台、付费模型或真实网络超时。

技术验证：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_local_http_acceptance.LocalHttpAcceptanceTests.test_f6_pending_attachment_timeout_live_proxy_admin_retry_and_permissions -v` 1/1 PASS；`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_local_http_acceptance -q` 8/8 PASS（F1–F6 含 F5 三类故障）。此证据限本机 HTTP 和确定性故障注入；真实平台网络超时、浏览器点击仍 `UNVERIFIED`，A8 总体验收仍 `PARTIAL`。

## 2026-09-26 A7 F5 严重模糊扫描件受阻换件本机 HTTP 联调（ACCEPTED）

用户本轮回复“验收通过，请进行下一项”，F5 严重模糊扫描件联调据此记为已验收。以下保留交付时的技术证据与边界。

用户已明确验收 F5 加密 PDF 受阻换件本机 HTTP 联调。本轮业务要求 → 实现与验证：`tests/test_local_http_acceptance.py::test_f5_blurred_scan_live_proxy_block_replacement_and_permissions` 使用临时 SQLite、合成账号及固定严重模糊 PNG，经真实 Uvicorn 与 Vite `/api` 代理上传。真实 CPU OCR 返回 `blocked/OCR_UNREADABLE`，有受阻原因、`replace_attachment` 恢复动作且无风险等级；正文、规则快照及提前确认均被拒绝。管理员可查看 v1 故障记录但不能重试；只有所属业务账号可换传 F3 清晰 PNG 成为 v2，错版及越权换件被拒绝。v2 OCR 成功后可读取新正文，v1 受阻记录保留且旧版无可读正文；不调用付费模型或真实审批平台。

技术验证：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_local_http_acceptance.LocalHttpAcceptanceTests.test_f5_blurred_scan_live_proxy_block_replacement_and_permissions -v` 1/1 PASS；`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_local_http_acceptance -q` 7/7 PASS（F1–F5 三类故障）。此证据限固定合成样例的本机 HTTP 与持久化链路；其他模糊程度、真实业务扫描件、浏览器点击仍 `UNVERIFIED`，A8 总体验收仍 `PARTIAL`。

## 2026-09-26 A7 F5 加密 PDF 受阻换件本机 HTTP 联调（ACCEPTED）

用户本轮回复“验收通过，请继续下一项”，F5 加密 PDF 联调据此记为已验收。以下保留交付时的技术证据与边界。

用户已明确验收 F5 空文 DOCX 受阻换件本机 HTTP 联调。本轮业务要求 → 实现与验证：`tests/test_local_http_acceptance.py::test_f5_encrypted_pdf_live_proxy_block_replacement_and_permissions` 使用临时 SQLite、合成账号和固定 F5 加密 PDF，经真实 Uvicorn 与 Vite `/api` 代理上传。PDF 处理后任务为 `blocked/PDF_ENCRYPTED`，有受阻原因、`replace_attachment` 恢复动作且无风险等级；正文、规则快照及提前确认均被拒绝。管理员可查看 v1 故障记录但不能重试；只有所属业务账号可用有效 F2 文本 PDF 换成 v2，错版及越权换件被拒绝。v2 解析成功后可读取新正文，v1 受阻记录保留且无可读正文；不调用付费模型或真实审批平台。

技术验证：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_local_http_acceptance.LocalHttpAcceptanceTests.test_f5_encrypted_pdf_live_proxy_block_replacement_and_permissions -v` 1/1 PASS；`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_local_http_acceptance -q` 6/6 PASS（F1–F5 空文及加密 PDF）。此证据限 F5 加密 PDF 的本机 HTTP 与持久化链路；严重模糊扫描件的本机 HTTP 联调、浏览器点击仍 `UNVERIFIED`，A8 总体验收仍 `PARTIAL`。

## 2026-09-26 A7 F5 空文 DOCX 受阻换件本机 HTTP 联调（ACCEPTED）

用户本轮回复“上述功能验收通过，请继续下一项”，F5 空文 DOCX 联调据此记为已验收。以下保留交付时的技术证据与边界。

用户已明确验收 F4 修订合同零误报本机 HTTP 联调。本轮业务要求 → 实现与验证：`tests/test_local_http_acceptance.py::test_f5_empty_docx_live_proxy_block_replacement_and_permissions` 使用临时 SQLite、合成账号及固定 F5 空文 DOCX，经真实 Uvicorn 和 Vite `/api` 代理上传。解析后任务为 `blocked/DOCX_EMPTY`，有受阻原因，恢复动作为 `replace_attachment`，无风险等级；正文、规则快照及提前确认均被拒绝。管理员处理记录保留 v1 解析受阻代码；管理员重试被拒绝，只有任务所属业务账号可上传有效 F4 DOCX 形成 v2，过期版本及越权换件被拒绝。v2 解析成功后可读取新正文，旧版受阻记录仍在，旧版正文不可读取。未调用外部模型或真实审批平台。

技术验证：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_local_http_acceptance.LocalHttpAcceptanceTests.test_f5_empty_docx_live_proxy_block_replacement_and_permissions -v` 1/1 PASS；`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_local_http_acceptance -q` 5/5 PASS（F1–F5 空文）。此证据仅覆盖 F5 空文 DOCX 的本机 HTTP 与持久化链路；加密 PDF、严重模糊扫描件的本机 HTTP 联调和浏览器点击仍 `UNVERIFIED`，A8 总体验收仍 `PARTIAL`。

## 2026-09-26 A1–A4 F4 修订合同零误报本机 HTTP 联调（ACCEPTED）

用户本轮回复“验收成功”，F4 据此记为已验收。以下保留交付时的技术证据与边界。

用户已明确验收 F3 清晰扫描件本机 HTTP 联调。本轮业务要求 → 实现与验证：`tests/test_local_http_acceptance.py::test_f4_revised_docx_live_proxy_no_false_risks_and_permissions` 使用临时 SQLite、合成账号与固定 F4 DOCX，经真实 Uvicorn 和 Vite `/api` 代理完成上传、DOCX 解析、同版字段/条款核对、DOCX PDF 预览与区域映射。两条已启用规则均未命中，持久模型作业返回 `MODEL_NOT_REQUIRED`，无需模型请求；法务仍可复核确认，所属业务账号取得同版 Markdown/PDF 报告，报告明确提示“无保留风险；不代表合同不存在其他法律风险”。前端工作台已有“未发现已启用规则风险，不代表法律安全”文案；本轮未做浏览器点击核验。冒烟覆盖草稿未就绪 409、过早确认 409、越权 401/403/404。

技术验证：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_local_http_acceptance.LocalHttpAcceptanceTests.test_f4_revised_docx_live_proxy_no_false_risks_and_permissions -v` 1/1 PASS；整个 `tests.test_local_http_acceptance` 4/4 PASS（F1–F4）。此证据限本机 HTTP 与持久化链路，浏览器实际显示与点击、F5/F6 页面链路仍 `UNVERIFIED`；A8 总体验收仍 `PARTIAL`。

## 2026-09-26 A1–A4 F3 清晰扫描件本机 HTTP 联调（ACCEPTED）

用户本轮回复“验收通过，继续下一项”，F3 据此记为已验收。以下保留交付时的技术证据与边界。

用户已明确验收 F2 文本 PDF 本机 HTTP 联调。本轮业务要求 → 实现与验证：`tests/test_local_http_acceptance.py::test_f3_scan_live_proxy_ocr_regions_review_and_permissions` 使用临时 SQLite、合成账号及固定 F3 PNG，经真实 Uvicorn 和 Vite `/api` 代理上传、执行真实 CPU OCR、建立同版原图区域预览、生成两条高风险规则快照和受控模型响应，再由法务复核确认，所属业务账号读取同版 Markdown/PDF 报告。核对 12 段正文、页码 1、OCR 行区域映射与风险原文锚点；预览为原图生成的 PDF。确认前拒绝预览或确认，越权 401/403/404，错误文档版本 404。测试未调用真实审批平台或付费模型。

技术验证：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_local_http_acceptance.LocalHttpAcceptanceTests.test_f3_scan_live_proxy_ocr_regions_review_and_permissions -v` 1/1 PASS；整个 `tests.test_local_http_acceptance` 3/3 PASS（F1–F3）。此证据限本机 HTTP、持久化及真实 OCR；浏览器真实点击、原文与卡片双向高亮、F4–F6 页面全链路及真实 DeepSeek 调用仍 `UNVERIFIED`；A8 总体验收仍 `PARTIAL`。

## 2026-09-26 A1–A4 F2 文本 PDF 本机 HTTP 联调（ACCEPTED）

用户本轮回复“验收通过，请进行下一项”，F2 据此记为已验收。以下保留交付时的技术证据与边界。

用户已明确验收上一项本机单命令启动。本轮业务要求 → 实现与验证：`tests/test_local_http_acceptance.py::test_f2_pdf_live_proxy_pages_review_and_permissions` 用临时 SQLite、合成账号与固定 F2 文本 PDF，经真实 Uvicorn 和 Vite `/api` 代理完成上传、持久解析、同版规则与受控模型响应、原 PDF 预览、法务复核确认及同版 Markdown/PDF 报告。按固定 F1 同语义标注核对两条高风险、锚点原文与 F2 本版第 2/3 页；确认前拒绝读取、越权 401/403/404、过早确认 409，确认后所属业务账号可读取确认结果，其他业务账号仍不可读取。请求未触达真实审批平台或付费模型。

技术验证：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_local_http_acceptance.LocalHttpAcceptanceTests.test_f2_pdf_live_proxy_pages_review_and_permissions -v` 1/1 PASS；复跑整个 `tests.test_local_http_acceptance` 2/2 PASS，保留 F1 回归。此证据为本机 HTTP 与持久化链路，浏览器真实点击、原文与卡片双向高亮、F3–F6 页面全链路及真实 DeepSeek 调用仍 `UNVERIFIED`；A8 总体验收仍 `PARTIAL`。

## 2026-09-26 A8 本机单命令启动（ACCEPTED）

用户本轮回复“验收成功，继续下一项”，本项据此记为已验收。以下保留交付时的技术证据与边界。

用户已明确验收上一项本机 HTTP 联调。本轮业务要求 → 实现：按 D-04 的 Windows 单机使用方式，新增 `scripts/start_local.py` 同时启动 Uvicorn 与 Vite，`backend/local_runtime.py` 提供仅查询用的应用工厂；可选端口和隔离数据目录，启动前检查依赖和端口，启动后检查前后端及 Vite API 代理的 HTTP 就绪，退出时停止本次启动的两个进程。默认使用项目现有 SQLite 路径；传入 `--data-root` 时只使用指定目录中的 SQLite 与上传目录。入口关闭所有后台作业，因此不会自动解析新上传任务或调用付费模型。

技术验证：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_local_launcher -v` 2/2 PASS，覆盖临时 SQLite 下前后端启动、HTTP 就绪、代理未登录 401、退出释放端口，以及后端端口被占用时拒绝启动且不创建数据。`--smoke` 可独立运行。原 PowerShell 入口在此环境启动时文件消失，无法稳定保留，故改为现有 Python 解释器入口。浏览器真实点击与视觉仍 `UNVERIFIED`：本机未安装 Playwright，已发现的 Edge 在当前执行环境下无界面启动超时，无法把 HTTP 检查记作浏览器验收。F1 真实 DeepSeek 调用、F2–F6 页面全链路和 A8 总体验收仍未完成；A8 保持 `PARTIAL`。

## 2026-09-26 A8 本机前后端 HTTP 联调（ACCEPTED）

用户本轮回复“验收通过，继续下一项”，本项据此记为已验收。以下保留交付时的技术证据与边界。

上一项管理员任务处理记录已获用户明确验收。本轮业务要求 → 实现：`tests/test_local_http_acceptance.py` 在临时 SQLite、合成账号与 F1 DOCX 上启动真实 Uvicorn 和 Vite，所有业务 HTTP 请求均经过 Vite `/api` 代理；核对前端 HTML/脚本资源、登录与角色、上传、解析/规则/受控模型响应、原文与预览、法务草稿和确认、同版 Markdown/PDF、模拟回写、管理员操作与处理记录，以及 401/403/404 和确认前 409。`frontend/vite.config.ts` 增加仅供本机隔离联调覆盖的 `CONTRACT_API_PROXY_TARGET`，默认仍为 `http://127.0.0.1:8010`。测试关闭服务并清理临时数据，不使用真实审批平台或付费模型。

技术验证：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_local_http_acceptance -v` 1/1 PASS（真实本机 HTTP、Vite 代理、受控模型响应）；`npm.cmd --prefix frontend run build` PASS（TypeScript + Vite，51 modules）；`git diff --check` PASS。这证明 HTTP 接入及合成 F1 主链，不证明浏览器点击、双栏高亮/视觉、目标 Windows 电脑、F2–F6 页面全链路或 F1 真实 DeepSeek 调用；A8 总体验收仍为 `PARTIAL`。

## 2026-09-26 A8 增量：管理员任务处理记录（ACCEPTED）

用户随后明确回复“验收通过，继续下一项”，本项记为已验收。

上一项管理员任务操作记录页面已获用户明确验收。本轮业务要求 → 实现：`backend/tasks.py:list_processing_records` 和 `GET /api/v1/tasks/{task_id}/processing-records` 只向管理员按版本、分页提供 F1 解析尝试、规则尝试、模型作业及 Markdown/PDF 报告结果；保留阶段、文档/审查版本、尝试次数、状态、故障代码与已有时间。`frontend/src/ProcessingRecords.tsx` 在管理员任务详情呈现这些元数据，支持版本筛选、翻页、刷新、401 会话失效及错误重读。业务与法务无页面入口且 API 返回 403；不返回合同原文、模型请求/响应、报告内容、密钥或附件路径。人工操作事件仍在相邻操作记录区，机器处理不冒充人工事件。报告表没有完整的开始时间，页面明确显示“未记录”。

技术验证：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_processing_records -q` 1/1 PASS（真实 FastAPI/TestClient、隔离 SQLite、合成 F1 与受控模型响应；核对完整处理阶段、同版/分页、字段白名单、401/403/404/422，断网）；`npm.cmd --prefix frontend test` 34/34 PASS（本项独立请求冒烟 3/3，模拟 Bearer、错任务/版本和 401/403）；`npm.cmd --prefix frontend run build` PASS（TypeScript + Vite，51 modules）。浏览器点击与本机前后端总体验收仍 `UNVERIFIED`；A8 阶段验收仍 `PARTIAL`，无付费调用或正式数据改动。

## 2026-09-26 A8 前端增量：管理员任务操作记录（ACCEPTED）

上一项管理员操作记录查询接口已获用户明确验收；用户随后明确回复“验收成功，进行下一项”，本页面记为已验收。本轮业务要求 → 实现：`frontend/src/AuditEvents.tsx` 仅在管理员任务详情挂载，`frontend/src/audit.ts` 用 Bearer 读取已验收的 `GET /api/v1/tasks/{task_id}/audit-events`；可查看全部或指定文档版本，按服务端 20 条分页，显示时间、动作、版本及操作者。切换任务、版本、页面或刷新时重新读取，核对响应任务 ID 和筛选版本；401 退出会话，403 等错误原样提示并允许手动重读。业务与法务无入口，后端继续按角色拒绝越权。页面不显示合同正文、评论正文或密钥；作业尝试细节仍由原状态记录负责。

技术验证：`node --experimental-strip-types --test frontend/tests/audit.test.ts` 3/3 PASS（模拟 Bearer、准确任务/版本/分页请求、错任务/版本拒绝、403/401）；`npm.cmd --prefix frontend test` 31/31 PASS；`npm.cmd --prefix frontend run build` PASS（TypeScript + Vite，49 modules）；`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_backend_integration.BackendIntegrationTests.test_f1_operation_record_smoke -q` 1/1 PASS（真实 FastAPI/TestClient、临时 SQLite、合成 F1）。浏览器点击及本机前后端总体验收仍 `UNVERIFIED`；A8 全链路阶段验收仍 `PARTIAL`，无付费调用或正式数据改动。

## 2026-09-26 A8 增量：管理员操作记录查询（ACCEPTED）

上一项 F1 人工操作记录已获用户明确验收；用户随后明确回复“验收通过，进行下一项”，本项记为已验收。本轮业务要求 → 实现：新增仅管理员可读的 `GET /api/v1/tasks/{task_id}/audit-events`，按事件 ID 顺序返回任务 ID、总数及操作事件的 ID、动作、文档版本、时间、操作者用户名/角色；可按 `document_version` 过滤，以 `limit`（1–100）和 `offset` 分页。无 Bearer 为 401，业务和法务为 403，不存在任务为 404，无效查询为 422。响应不包含合同正文、原附件路径、密钥、会话 token 或评论正文；只读取现有审计表，不改变业务状态。

技术验证：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_backend_integration.BackendIntegrationTests.test_f1_operation_record_smoke -q` 1/1 PASS（真实 FastAPI/TestClient、临时 SQLite、合成 F1 与受控模型响应；含成功、版本过滤、分页、无凭据、角色拒绝、不存在任务和参数无效）；`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_tasks tests.test_backend_integration -q` 17/17 PASS；`npm.cmd --prefix frontend test` 28/28 PASS。浏览器操作与本机前后端总体验收仍 `UNVERIFIED`。A8 全部操作记录和阶段验收仍 `PARTIAL`；无付费调用、无正式数据改动。

## 2026-09-26 A8 增量：F1 人工操作记录贯通（ACCEPTED）

FE8 已获用户明确验收，本轮推进 A8；用户随后明确回复“验收通过”，本项记为已验收。业务要求 → 实现：F1 从创建任务、法务保存与确认，到模拟回写发起及成功/失败，均在原有 `audit_events` 中记录任务、操作者、文档版本和时间；重复回写及重复确认不新增事件。法务审查、确认和回写状态与对应审计事件在同一 SQLite 事务中提交；解析、模型、报告的作业细节仍由各自持久表保留，该项交付时尚未提供操作记录查询 API。

技术验证：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_backend_integration.BackendIntegrationTests.test_f1_operation_record_smoke -q` 1/1 PASS（真实 FastAPI/TestClient、临时 SQLite、合成 F1 DOCX、受控模型响应且断网保护；核对事件顺序、角色、版本、时间、重复回写和冲突确认）；`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_reviews tests.test_writeback tests.test_backend_integration -q` 13/13 PASS。本机前后端整体流程与浏览器仍 `UNVERIFIED`。A8 全链路操作记录对照、供应商账单和阶段验收仍 `PARTIAL`；未调用付费模型或触碰正式任务。

## 2026-09-26 FE8：管理员受阻恢复页面（ACCEPTED）

FE7 已获用户明确验收，本轮推进 FE8；用户于本轮明确回复“验收通过，进行下一项”，FE8 记为已验收。

业务要求 → 实现：`frontend/src/Recovery.tsx`、`recovery.ts` 在管理员任务详情展示当前版本的故障代码、受阻原因和当前处理阶段尝试次数。仅 `blocked/admin_retry` 显示重试按钮，按展示的 `document_version` 调用既有 `POST /tasks/{id}/retry`；`replace_attachment` 指引业务换件，`budget_decision` 指引预算决策，均不提供管理员重试。模拟待办任务另读 `GET /tasks/{id}/attachment-attempts`，展示附件获取累计尝试的序号、状态、故障代码与时间，并核对任务 ID/版本；不展示原文、附件私有路径或法务编辑区。写请求一次点击仅一次；409 或结果不确定时锁定按钮，手动刷新任务后再核对。后端仍逐接口做管理员权限和版本/状态校验。

技术验证：`node --experimental-strip-types --test frontend/tests/recovery.test.ts` 5/5 PASS（成功、角色/状态禁用、Bearer 与精确版本、409/403、历史版本不一致；网络模拟）；`npm.cmd --prefix frontend test` 28/28 PASS；`npm.cmd --prefix frontend run build` PASS（TypeScript + Vite，47 modules）；`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_pending_imports tests.test_rule_processing tests.test_ocr -q` 12/12 PASS（真实 FastAPI/TestClient、临时库及合成样例，含待办附件恢复、规则/OCR 故障与权限）。实际浏览器点击及本机前后端整体流程仍 `UNVERIFIED`；未调用付费模型或改动演示任务。后端 A8 收口和总体验收仍为后续单元。

## 2026-09-26 FE7：模拟回写页面与状态对接（ACCEPTED）

FE6 已获用户明确验收；用户随后明确回复“验收通过，请进行下一项”，FE7 业务验收通过。以下技术验证边界按交付时记录保留。

业务要求 → 实现：`frontend/src/Writeback.tsx`、`writeback.ts` 在任务详情按确认版本读取本地模拟回写状态。法务可从后端已有模拟审批单选择目标，提交时带审查版本和目标；返回 `writing` 后轮询，只有 `success` 且同版、带评论 ID 才显示成功。失败时法务可对同版同目标重试；请求结果不确定时禁止自动重放，须先刷新核对。业务仅查看本人确认版本的评论与状态，不显示内部错误或尝试；管理员只看当前确认版本的状态/故障与尝试，不显示评论正文且没有提交入口。旧确认版本标明历史。页面明确仅本地保存、未连接真实审批平台；后端继续逐接口鉴权与去重。

技术验证：`node --experimental-strip-types --test frontend/tests/writeback.test.ts` 4/4 PASS（精确版本、Bearer、目标与提交、403/409、成功必有评论 ID；网络为模拟）；`npm.cmd --prefix frontend test` 23/23 PASS；`npm.cmd --prefix frontend run build` PASS（TypeScript + Vite，45 modules）；`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_writeback -q` 4/4 PASS（真实 FastAPI/TestClient、临时库与合成 F1/F6，含权限、失败重试、去重和版本隔离）。实际浏览器点击、异步轮询视觉表现和本机前后端完整流程仍 `UNVERIFIED`；未调用付费模型、未改动演示任务。后端 A8 收口与总体验收仍为后续单元。

## 2026-09-26 FE6：已确认报告查看、下载与失败重试（ACCEPTED）

FE5 已获用户明确验收；用户本轮明确“验收通过，进行下一项”，FE6 业务验收通过。以下技术验证边界按交付时记录保留。

业务要求 → 实现：`frontend/src/Reports.tsx`、`reports.ts` 在业务与法务任务详情显示最近已确认的文档/审查版本；若当前任务已有新文档或新审查草稿，明确标注报告属于历史确认版本。按该确认版本读取 Markdown/PDF 独立生成状态，仅已就绪格式可通过 Bearer 请求预览或下载，Markdown 以纯文本展示，PDF 使用临时 Blob 地址预览。生成中不提供文件操作；失败格式仅法务有重试入口，重试后继续读取状态，写请求不自动重复。业务不显示报告错误代码，管理员无报告入口；后端仍逐接口鉴权、拒绝未就绪和无权访问。

技术验证：`npm.cmd --prefix frontend test` 19/19 PASS（其中 `frontend/tests/reports.test.ts` 可单独运行，模拟成功状态、精确版本与 Bearer 下载、失败重试、409 未就绪和 403 权限）；`npm.cmd --prefix frontend run build` PASS（TypeScript + Vite，43 modules）；`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_reports -q` 4/4 PASS（真实 FastAPI/TestClient、临时库与合成样例，含 Markdown/PDF 产物、角色、历史版本、失败重试）。实际浏览器预览/下载点击、PDF 内嵌显示和本机前后端整体流程仍 `UNVERIFIED`。未调用付费模型、未改动演示任务；模拟回写前端与总体验收仍为后续单元。

## 2026-09-26 FE5：法务复核、保存草稿与正式确认（ACCEPTED）

FE4 已获用户明确验收；用户本轮明确“验收通过，进行下一项”，FE5 业务验收通过。以下技术验证边界按交付时记录保留。

业务要求 → 实现：法务在同版原文与机器草稿工作台中逐项决定保留、等级、规则/模型采纳或人工建议，并填写单项与整体批注；`frontend/src/ReviewEditor.tsx`、`review.ts` 读取当前审查版本，向 `PUT /tasks/{id}/review` 提交完整风险列表、文档版本与基准审查版本，保存后再以指定审查版本及正式结论调用 `POST /tasks/{id}/confirm`。已确认版本继续修改会创建新草稿；保存不等于确认。任务大盘依据后端最新状态刷新。业务与管理员没有编辑入口，后端保持逐接口权限校验。

交互保护：风险修改和未提交正式结论均提示离开；手动刷新、工作台重读、退出及浏览器关闭有丢弃提示，后台轮询在编辑期间不覆盖表单。提交中禁用重复操作；409 冲突锁定提交并要求重读，网络/5xx 不确定结果不自动重试。无同版规则或模型结果时禁止写审查。确认前须有已保存草稿及非空结论；确认动作再次显示版本和不可改写提示。法务依据仍待核定，此流程不代表法务签批。

技术验证：`npm.cmd --prefix frontend test` 16/16 PASS（FE5 独立冒烟 `frontend/tests/review.test.ts` 包括采纳、完整同版请求、确认版本、403 与 409 无自动重试；网络为模拟）；`npm.cmd --prefix frontend run build` PASS（TypeScript + Vite，41 modules）；`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_reviews -q` 5/5 PASS（真实 FastAPI/TestClient、临时库与合成样例，覆盖保存/确认/历史/权限）。实际浏览器编辑、页面跳转提示和端到端确认仍 `UNVERIFIED`；未调用付费模型，未修改演示任务。报告页面与模拟回写前端仍属后续单元。

## 2026-09-26 FE4：法务原文与风险工作台（ACCEPTED）

用户本轮明确“验收成功，进行下一项”；以下技术验证边界按交付时记录保留。

业务要求：法务以本版固定 PDF 对照字段、条款、风险及机器建议，双向定位且不把未核定规则当法律结论。实现：`frontend/src/Workbench.tsx`、`PdfPage.tsx`、`workbench.ts` 接入法务任务详情，带 Bearer 读取本版 `/document`、`/risks/snapshot`、`/model-result`、`/document/preview`，DOCX/图片另读 `/document/preview-map` 并校验 PDF 摘要；PDF.js 分页显示，风险/字段/条款三类高亮分别切换，证据列表跳 PDF，PDF 区域反选证据。同版号、原文 Unicode 摘录、完整段落覆盖与归一化区域校验失败时不画高亮；无可靠区域明确提示。已有模型建议与规则建议分列，只提供复制，不编辑、不确认、不调用模型。仅法务入口，后端逐接口鉴权。

技术验证：`npm.cmd --prefix frontend test` 13/13 PASS，覆盖同版/错版、高亮区域、跨页段落映射、可选草稿缺失、403 权限拒绝（网络模拟）；`npm.cmd --prefix frontend run build` PASS（39 modules，含 TypeScript）；`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_backend_integration.BackendIntegrationTests.test_f1_full_http_chain_and_import -q` 1/1 PASS；`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_frontend_workbench -q` 1/1 PASS（临时库合成 F1/F2，经真实 TestClient 接口、权限检查、固定 PDF.js Node canvas 与 3 处区域核验，F1 1 页/F2 3 页；不含浏览器点击）。未新增依赖、未请求付费模型。实际浏览器双向点击和 F3 固定预览区域视觉核对仍 `UNVERIFIED`，不将脚本冒烟当作 A2 完整端到端验收；法务依据和报告属后续单元。

## 2026-09-26 FE3：业务附件换版（ACCEPTED）

用户本轮明确“验收通过，允许继续”；以下技术验证与当时的手动检查边界保留。

FE2 后补齐接入纠错闭环：MVP 第 3/4 节的新版与旧证据隔离 → `frontend/src/Replacement.tsx`、`intake.ts` 与任务详情入口。仅业务角色、受阻且 replace_attachment 或 completed/confirmed 时展示；提交当前 base_document_version，用户勾选确认新版本后上传。409 要求返回刷新，超时/5xx 不自动重试；成功显示新版本回执并刷新三组状态，旧确认仍标旧版。后端逐接口权限和事务规则沿用已验收实现。

技术验证：`npm.cmd --prefix frontend test` 7/7 PASS（含 multipart、非法文件、待办受阻回执、版本前置条件与无自动重试，网络为模拟）；`npm.cmd --prefix frontend run build` PASS（33 modules）；`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_tasks -q` 13/13 PASS（32.369 秒，隔离临时库与合成附件，含正常换版、角色/本人/状态/版本拒绝及失败回滚）。未新增依赖、模型调用或修改用户任务。

验收边界：自动浏览器此前受审批服务 429 阻塞，当时未绕过；FE3 实际点击与视觉自动检查仍 UNVERIFIED。查询模式新任务保持 pending，不能伪造状态或声称已经解析。

## 2026-09-26 FE2：合同上传与模拟待办导入（ACCEPTED）

用户明确“验收通过，请进下一步”。上一轮已实现 `Intake.tsx`、`intake.ts` 与 multipart 请求支持；仅业务角色入口，25 MiB/格式/申请信息校验，提交锁、取消与不确定结果提示，登记成功保留 task_id 和受阻回执。上一轮隔离 TestClient 实际上传、导入、415 格式拒绝和403角色拒绝通过，构建通过；本轮补落可单独运行的 `frontend/tests/intake.test.ts`，证据见 FE3。用户页面验收与自动浏览器验证分别记录，不将模拟网络描述为端到端点击验证。

## 2026-09-25 FE1：正式登录与任务大盘（ACCEPTED）

用户在测试账号交付后明确“验收通过，请进入下一项”；以下待验收措辞为当时交付记录。

用户已确认 UI v0.5“验收通过，请进行下一项”。本单元在 `frontend/` 实现 React + TypeScript + Vite 登录、服务端角色导航、可见任务大盘、阶段/正式等级筛选、分页与任务进度详情；沿用已确认的深绿侧栏。只接入会话建立/撤销和任务摘要查询，不提交附件、复核、报告或回写，不调用付费模型。

会话仅存内存；刷新需重登；401/到期清空受保护页面，退出请求服务端撤销；撤销请求失败会明确区分本页退出和服务端未确认撤销。读取取消防止旧请求恢复已退出的数据；处理中每 5 秒读取，终态停止、保留手动刷新。概览基于未筛选的全部可见摘要，逐页读取、按 ID 去重后统一更新，不把一页当总量；仅本机演示规模使用此方案。确认版本的空等级不推断为低风险或规则未命中，历史确认不冒充当前结论。管理员无等级筛选、原文或编辑入口。

验证：`npm.cmd test --prefix frontend` 4/4 PASS（Node 逻辑与模拟传输）；`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_frontend_dashboard tests.test_auth tests.test_reviews -q` 13/13 PASS（20.355 秒，真实 FastAPI TestClient、隔离临时库/合成待办、无作业/模型调用）。覆盖登录失败、四账号可见性、分页、未确认等级、管理员字段隔离、退出撤销及历史版本回归。

用户明确“确认安装”后，在 `frontend/` 执行 `npm.cmd install --cache ../storage/npm-cache --no-audit --no-fund` 成功，新增 21 个包，生成锁文件，无全局安装。npm 提示 esbuild postinstall 尚未批准；无需额外开放，实际 TypeScript 检查及 Vite 生产构建已通过（30 modules）。

本机启动验证：8000 实际被 DailyNews 服务占用，初次合同后端绑定失败，代理返回错误项目的 404/405；已将 FE1 代理与启动说明改为 8010，不停止其他项目。`backend.main:create_app --factory` 无自动后台作业启动成功，Vite 5173 启动成功。通过 5173 实际 HTTP 验证首页/TSX 脚本 200、未登录任务查询与合成错误凭据登录均为 JSON 401。成功登录、角色权限与退出证据来自上述隔离 TestClient，不冒充浏览器端到端验证。

剩余验证：浏览器工具的初始状态查询因自动审批服务 429 / exceeded retry limit 未执行；不是安全拒绝，未绕过。浏览器视觉、真实点击、正常账号经前端登录/筛选/退出仍 UNVERIFIED，交由用户按 README 手动验收。FE1 待用户确认，不进入合同接入单元；本轮未调用付费模型。

## 2026-09-25 前端 UI v0.5 交互设计（ACCEPTED）

用户已在该单元交付后明确“验收通过，请进行下一项”。以下为交付时证据；当前正式前端进度见上方 FE1。

用户已验收 F6，并按 D-27 批准前端开发及调整后的验收顺序。首个单元交付 `design/ui-preview/`，基于 `pencil-new.pen` 的深绿/浅底视觉和双栏布局，覆盖三角色、大盘/接入/复核/报告/受阻恢复及关键状态。原型不访问 API、不存凭据、不修改业务数据，实际 React 客户端、PDF.js 和接口联调尚未开始；不能把 UI 预览计为前后端整体通过。

验证：`node --check design/ui-preview/preview.js`、`node design/ui-preview/smoke.cjs` PASS（Node VM 渲染/行为检查，非浏览器）；本机静态入口 HTTP 200，UTF-8 标题正常。浏览器自动打开被审批服务 429 限流阻断，未执行，视觉与真实点击 UNVERIFIED，需用户按 FRONTEND_DESIGN 最新节手动核对。无新增依赖或模型调用。设计验收后逐页面对接真实 API，并收口 A8 操作记录，最后本机总体验收。

## 2026-09-25 F6 待办附件恢复（ACCEPTED）

用户已在本单元交付后明确“验收通过”。以下待验收、后端先整体通过再申请前端的表述为历史，最新顺序以 D-27 为准。

全量回归 `.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -q` 执行 146 项（419.111 秒），首轮 145 通过、1 失败：旧导入测试重新生成 DOCX，ZIP 时间戳导致哈希不稳定。测试现固定实际下载字节，并核对新增的获取开始/导入完成审计序列；生产代码未因该失败修改。修正后 `.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_tasks tests.test_pending_imports -q` **17/17 PASS（52.228 秒）**，覆盖该失败及任务/F6 回归。未重复全量，不记作单次 146/146 PASS。

用户“验收通过，继续补齐”：F3 标题修复记为 ACCEPTED，本轮补齐 F6 下载超时业务。需求 A7/F6 → `backend/pending_imports.py`、`tasks.py`、`main.py`、`docx_worker.py`：先登记任务/尝试，再获取附件；失败保存 blocked/admin_retry，管理员按 v1 重试；文件、文档、解析入队和完成记录原子提交。任务无附件时仍可列表/查询；仅管理员读取附件尝试历史。租约过期持久受阻，双连接竞争与迟到结果不会重复登记或覆盖新结果。启动和服务轮询检查过期租约，不自动重新下载。

技术证据：`tests.test_pending_imports tests.test_smoke -q` **20/20 PASS（29.821 秒）**；新增独立业务冒烟 `tests/test_pending_imports.py` 四项覆盖真实 HTTP 超时/重试/角色、真实 DOCX/规则继续处理、重开数据库/过期租约/旧结果拒绝、双连接并发、存储事务失败回滚及无效附件恢复。固定 F6 故障源通过 HTTP 下载适配器注入，持久 attempt 1 超时、2 返回附件；不是实际外部平台或网络超时验证。仅临时数据库/合成附件，无付费模型调用、依赖安装、正式库或密钥修改。

阶段边界：本功能待用户验收；原 A7 缺口已有专项技术证据，后端阶段仍须收口 A8 操作记录对照、更新整体验收矩阵并请用户验收。之后按 D-25 单独申请前端开发审批。下方为前次集成发现及历史结果，不代表当前 F6 仍未实现。

## 2026-09-25 当前推进

用户“验收通过，进入下一项”：模拟审批评论回写记为 **ACCEPTED**。本轮进入后端集成核验，状态 **PARTIAL / 未通过**，详见 [后端集成验收记录](BACKEND_INTEGRATION_ACCEPTANCE.md)。前端未开始，仍须按 D-25 在后端阶段验收后另行申请审批。

本轮业务要求 → 实现 → 证据：A1/F3 字段提取 → `backend/metadata_extractor.py` 允许标题括号前横向空白、保持原文锚点；`tests/test_metadata_extractor.py` 补充半角/全角空白及非标题反例。`tests/test_backend_integration.py` 新增三个 HTTP 集成测试，覆盖真实 F1–F5 解析、预览、风险、权限、编辑确认、报告、回写和换版。最终 `.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_metadata_extractor tests.test_backend_integration tests.test_writeback tests.test_reports -q` **18/18 PASS（102.926 秒）**。F3 修复为 **PENDING_ACCEPTANCE**，不重开无关已验收功能。

集成阻塞：F6 待办导入下载前未登记持久任务，实际 HTTP 故障注入返回 500、任务增量 0，不能管理员重试或重启恢复；固定样例仍标记 NOT_IMPLEMENTED。F6 回写失败/重试已通过，但不能替代待办超时。A7 FAIL；A8 主链通过，统一操作记录对照仍待收口。真实模型沿用用户此前执行及验收记录，本轮无付费请求，供应商账单仍 UNVERIFIED。仅测试临时数据库/合成附件，未修改正式库、密钥或依赖。

后续顺序：本轮字段修复验收 → 补齐 F6 待办超时持久化与管理员重试 → 后端集成复验及用户阶段验收 → 申请前端开发审批。下方为已验收模拟回写的历史交付证据。

## 2026-09-25 模拟审批评论回写（ACCEPTED）

用户此前按 D-26 确认首次选择已有目标并固定绑定；本轮已明确验收。

业务要求 → 实现：MVP 第 4 节、A6 及 D-26 → `backend/writeback.py` 的 mock_writebacks/writeback_attempts、`tasks.py` 初始化、`main.py` 目标列表与 POST/GET、`docx_worker.py` 自动处理。明确确认版本；事务内绑定目标及登记 writing；后台评论/成功/尝试/当前任务状态原子提交；唯一键保证同版同目标最多一条。失败由法务重试，两分钟租约恢复中断，旧 token 不覆盖；历史版本处理不污染新草稿/附件。法务可见评论和故障，管理员无评论正文，业务仅本人确认结果。Markdown 转义用户文本，不泄露机器草稿；仅本地保存。

验证：`tests.test_writeback tests.test_reviews tests.test_f6_writeback_failure -q` 9/9 PASS（26.317 秒）；补充自动服务与附件隔离后 `tests.test_writeback -q` 4/4 PASS（13.425 秒）。最终 `.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -q` 全量 **138/138 PASS（326.984 秒）**，包含真实本机 OCR 和 LibreOffice；`git diff --check` 退出码 0。临时数据库、合成数据、模拟模型，无付费调用。首轮测试误用 AuthStore 上下文管理器导致测试连接未关闭，已改显式 finally close；新增换版测试遗漏 base_document_version 导致 422，已按真实契约补齐。

证据边界：F6 固定 MockCommentSink 通过替换评论生成注入首次超时，之后走实际持久 API/处理器；并非真实外部回写。自动处理使用真实 TestClient 生命周期，双连接验证并发与重开数据库持久化；事务失败与租约超时采用故障注入。未修改正式库、依赖、密钥或调用外部模型。后端完整 F1–F6/A1–A8 集成验收尚未完成，前端未开始。

后续顺序：模拟回写逐功能验收 → 后端集成验收 → 向用户申请并取得前端开发审批 → 前端实现及接口联调。D-25 覆盖历史自动进入前端的安排。

## 2026-09-25 同版报告（ACCEPTED，以下为当时交付记录）

用户已回复“验收通过”，随后“进行下一项功能”：上轮法务编辑与确认记为 ACCEPTED，本轮仅交付同版 Markdown/PDF 报告，不进入模拟回写或前端。下方法务待验收/报告未实现均为历史记录。

需求 → 实现：MVP 报告与 A5 对应 `backend/reports.py`，`reviews.py` 确认同事务登记、`tasks.py` 初始化与历史确认补登记、`docx_worker.py`/`main.py` 后台及三个鉴权接口。两格式独立 pending/ready/failed、尝试数、安全错误码、生成时间、产物及 SHA256；SQLite BLOB 原子发布，读取核验摘要。仅确认快照参与生成，不读当前草稿；仅列保留风险和最终意见，不暴露模型草稿。未核准法律依据标待法务核定；“模拟回写”标识不改变回写状态。

失败/恢复：单格式失败不撤销确认或影响另一格式；仅法务可重试 failed，pending/ready 为 409。两分钟租约到期可重新领取，旧 token 不可覆盖新产物；重启不抢占有效租约、不重建 ready。历史 confirmed 初始化幂等补任务。未确认/未生成文件为 409 REPORT_NOT_READY；其他业务 404、管理员 403；业务状态不含内部错误。

证据：首轮报告冒烟 3/3 PASS（50.469 秒）；补充旧租约防覆盖后，`tests.test_reports tests.test_reviews -q` **9/9 PASS（74.984 秒）**。完整命令 `.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -q` **134/134 PASS（434.544 秒）**；最后明确报告段落索引从 0 起后，`tests.test_reports -q` **4/4 PASS（47.396 秒）**。临时库、合成合同、模拟模型、真实本机 LibreOffice，全量包含真实 OCR；没有外部模型请求。合成报告一页及 80 行长批注三页均提取核对并逐页目视确认无乱码、裁切或重叠，测试产物 `storage/report-check/`。另以模拟 renderer 验证 FastAPI 生命周期自动领取两格式任务；`git diff --check` 退出码 0。复杂真实合同/目标机仍未验证；未修改正式库、密钥或依赖。

## 2026-09-25 法务编辑与确认（ACCEPTED，以下为当时交付记录）

用户“验收通过，请进入下一功能”：扫描 PDF 接入单元记为 ACCEPTED，原有复杂版式、真实多页及目标机未验证边界保留。按执行清单进入第 4 项，仅交付法务编辑和确认，报告及模拟回写未实现。

需求 → 实现：MVP 第 3–5 节的采纳/编辑版本、最高保留风险等级、正式结论、历史隔离与角色权限，对应 `backend/reviews.py`、`backend/tasks.py`、`backend/main.py`。新增 review_versions 迁移、GET/PUT review、POST confirm；BEGIN IMMEDIATE 与基础版本比较防并发覆盖。确认保存同版原文/规则/模型、来源摘要、最终意见及确认账号/时间；已确认再编辑新增草稿、不覆盖历史。业务仅读本人确认快照/原文/预览；机器快照/模型结果仍仅法务。管理员不得代审或按风险筛选，其他业务账号不可枚举任务。列表当前等级不使用历史结论，risk_level 筛选不暴露草稿。

验证入口：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_reviews -v`。临时 SQLite、合成 F1/F2/F4、模拟有效/无效模型响应，不调用外部模型；覆盖模型/规则采纳与人工编辑、确认幂等/结论冲突、两连接并发、无风险、正文篡改拒绝、事务回滚、历史重读、新文档隔离、三角色 HTTP 拒绝、当前正式等级筛选和确认后原 PDF 预览。首轮 3/3 通过（8.139 秒）；补充项初次因测试 F2 文件名拼写错误失败，已纠正为已有样例 f2-text-software-purchase.pdf，最终结果待下方记录。

最终验证：`.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -q` 全量 **130/130 PASS，271.407 秒**；之后补强有效模型建议原文采纳断言，法务专项再次 **5/5 PASS，19.280 秒**。全量包含真实 CPU OCR，法务专项中的模型响应全部模拟。`git diff --check`（cr-at-eol 口径）退出码 0；仓库已有 LF/CRLF 提示，没有为此改写历史文件。技术验证通过，用户验收仍待确认。

边界：本轮 API 尚不登记或生成 Markdown/PDF 报告、不执行模拟回写；后续须从确认快照生成，不能读取当前草稿。仅基于两条演示规则调整/保留风险，未启用额外法律规则；正式结论为法务提交文本，系统不替代专业法律判断。未启动正式服务、未修改正式数据库、密钥、依赖或 Git 提交。

2026-09-25 最新：用户“验收通过，请继续”，图片 OCR 业务接入记为 ACCEPTED。扫描 PDF 接入 `PENDING_ACCEPTANCE`：`backend/pdf_parser.py` 检出图片或无文本页，`backend/pdf_job.py` 在同一 parse 租约下转 `backend/ocr.py::parse_scanned_pdf`；已安装的 pypdfium2 5.13.0 按 150 DPI 渲染整份 PDF，再复用图片 OCR。最多 20 页、总 4000 万像素、25 MiB 中间图限制；超限受阻换件。parsed_documents 迁移增加 extraction_method，旧记录默认 text，图片接口仍按格式兼容；扫描 PDF 为 ocr 并显示核对提示。原 PDF 即固定预览，不另建 preview-map，坐标直接取同版 `/document`。低分/空页整份受阻，暂时故障管理员重试；发布前再次核验原件摘要及租约。

新增两项测试：真实 F3/F5 转为无文本层 PDF 后分别识别 12 行/受阻；正文区间、同版原件预览、换版、超时重试及零模型预算。混合文本/无文本页、加密不调用 OCR 为实际 PDF 结构配合模拟识别测试。首次验证发现 PdfPage 不支持 with，已改为显式 finally close，复验 2/2 通过（36.532 秒）。补充规则快照和 HTTP 权限/持久读取断言后，全量回归 124/124 通过（265.111 秒）。最后增加同页图片检测：test_text_page_with_image_requests_ocr 与 tests.test_pdf_parser、tests.test_pdf_job 共 4/4 通过（4.563 秒）；本次全量未包含最后新增的该测试，不累计为一次 125 项全量通过。未安装依赖、未修改正式数据、未调用付费模型。

边界：上传 PDF 含任意图片也整份 OCR，避免漏掉同页扫描内容；带图片徽标的文本 PDF 也会转 OCR。复杂版式、旋转/裁剪、真实多页 OCR 与目标机未验证。任一图片或无文本页触发整份 OCR，纯空白页也受阻，不静默略过。工作块 3 尚不记整体完成。

2026-09-25 当前：OCR 隔离基础已 ACCEPTED。用户已按 D-24 确认低置信度件受阻换件，图片业务接入为 `PENDING_ACCEPTANCE`。本次业务规则确认不代替功能验收；下文基础待验收、图片仍 pending 为历史。

业务要求（同版 OCR、定位及受阻恢复）→ `backend/ocr.py`、`scripts/ocr_runtime.py`、jobs/worker/tasks/preview_store/rule_snapshot → `tests/test_ocr.py`。沿用 parse 租约及原子提交，保存同版正文/字段/条款及规则；图片转固定 PDF，行级坐标共享像素方向，字段不冒用整行框。核验原件路径/摘要和发布时租约；暂时错误 admin_retry，永久错误 replace_attachment，尝试记录保存错误码和原因。无新依赖，无本轮付费调用，无正式业务数据操作。

验证：`python -X utf8 -m unittest tests.test_ocr tests.test_pdf_job tests.test_docx_preview_api -v`，9/9 通过，84.370 秒；补充预算零记录断言及返回类型校验后，`python -X utf8 -m unittest discover -s tests -q`，121/121 通过，198.041 秒。F3/F5 真实 CPU 子进程及 HTTP 临时库：12 行、字段、两条规则、预览/映射、读取权限、模糊受阻、换版恢复、重启读取及预览篡改拒绝。超时/管理员重试/旧租约/非法区域/NaN/候选低分策略及两页 TIFF 为模拟测试。

决策已解除：任一行低置信度则整份受阻，要求换清晰件，不发布部分草稿。初始技术阈值 0.9 未经样本标定，不代表漏字检测能力。本轮新增 `test_low_confidence_blocks_without_partial_drafts`，和 `test_invalid_results_and_multipage` 定向运行 2/2 通过（1.712 秒）：0.8999 受阻、正文/规则/预算均无记录、管理员重试被拒、新版 0.9 可解析，仅保存版本 2。识别分数为模拟；上轮全量 121/121 与真实 F3/F5 证据沿用，本轮未再运行全量或付费模型。扫描 PDF、真实 JPEG/TIFF、多页复杂版式及前端尚未验证；工作块 3 仍 PARTIAL。

2026-09-25 最新：D-23 已授权且完成 OCR 隔离安装与真实固定样例验证，`PENDING_ACCEPTANCE`；下方 `BLOCKED_DEPENDENCY` 和等待安装授权为历史。当前交付为可单独运行的 OCR 基础能力，不是整个扫描合同功能；工作块 3 仍 `PARTIAL`。

业务要求（本机 CPU 扫描识别和原图区域）→ `scripts/install_ocr.ps1`、`scripts/requirements-ocr-lock.txt`、`scripts/verify_ocr.py` → 实际 PP-OCRv5 mobile 检测/识别模型运行。独立 Python 3.12.13 位于 `.tools/ocr`，PaddleOCR 3.7.0 / PaddlePaddle 3.3.1 / PaddleX 3.7.2；模型和缓存位于 `storage/ocr`。Windows oneDNN 报错以关闭可选 MKLDNN 加速解决。没有修改主 `.venv`、全局 PATH、已有 Conda 环境或密钥，没有付费调用。

验证命令：`.\.tools\ocr\venv\Scripts\python.exe -X utf8 scripts/verify_ocr.py`，真实复验退出码 0、24.344 秒；F3 共 12 行，11 行逐字一致，标题括号宽度/空格不同，NFKC/忽略空白后 12 行一致。原始结果保留，未用标准答案生成/替换正文。12 框均在图内，与独立原图标注最小交并比 0.764（冒烟门槛 0.65，仅用于此固定样例，不是业务置信度阈值），叠加图已目视检查。F5 严重模糊图返回 0 行。证据：`storage/verification/ocr/` 内两个原始 JSON、`verification-summary.json`、`f3-location-overlay.png`；完整运行日志 `storage/verification/ocr-runtime-verified.log`。`uv pip check --python .tools/ocr/venv/Scripts/python.exe` 使用项目 `UV_CACHE_DIR` 后核对 72 个包兼容；第一次未设置项目缓存的只读检查因用户目录拒绝访问失败，非依赖冲突。隔离运行时与证据的 Git 忽略已核对。

本轮没有改后端业务代码，不重跑既有 118 项回归。图片上传仍保持 pending，OCR 持久作业/同版保存、固定 PDF 预览、字段/条款/规则联动、F5 blocked/换版恢复、扫描 PDF、多页/复杂版式及目标机均未验证。本基础单元验收后继续业务接入，不进入法务编辑。

2026-09-25 用户明确“验收通过，进行下一功能”：上轮 DOCX 固定预览与定位记为 `ACCEPTED`，范围为同版 PDF 生成、独立存储、法务读取和可靠段落/条款定位；118/118 回归为上一轮技术证据，不代表 OCR、复杂版式或前端已验收。

下一单元：F3 清晰扫描件 CPU OCR 与同版坐标，当前 `BLOCKED_DEPENDENCY`。已只读核对项目 `.venv` 为 Python 3.14.6，未安装 paddle/paddleocr/rapidocr/pytesseract/cv2；已有 onnxruntime 1.30.0 与 Pillow 12.3.0，不能单独提供 OCR。现有 Conda 环境 `D:\AICoding\Langchain\conda\envs\langchain1.2` 同为 Python 3.14.6，也没有 paddle/paddleocr/rapidocr；PATH 未找到 tesseract/paddleocr。此为已检查环境的结果，不声称遍历全盘。尚未核实所选 PaddleOCR 版本对 Python 3.14 的支持，不据此断言不兼容。

拟实施范围：先核对 PaddleOCR CPU 官方兼容版本，在项目独立 `.tools/ocr` 环境安装必要运行时，模型与下载缓存放 `storage/ocr`；如现有 Python 不支持，准备项目独立兼容 Python，不改主 `.venv`、全局 PATH 或已有 Conda 环境。真实识别 F3 后核对正文、页码与区域，再接持久队列、固定预览、字段/条款及失败恢复；F5 严重模糊件不能生成虚假结论。禁止以 f3_expected.json 答案代替 OCR 识别结果。准确版本和下载规模须安装前核对，不预报无依据数字。

本轮仅记录验收、依赖核查及具体实施范围，未安装/下载 OCR、未改运行代码、未运行付费模型。D-20 暂缓依赖安装仍有效，D-22 仅授权 LibreOffice；OCR 的依赖与模型准备需单独授权。等待该决定，不把本项记为完成，不跳到法务编辑。

2026-09-25 最新单元：DOCX 固定 PDF 预览与定位 `PENDING_ACCEPTANCE`。D-22 安装阻塞已解除：用户提供 InstallerExitCode=0、InstalledExecutable=`D:\AICoding\Tools\LibreOffice\program\soffice.exe`、InstalledVersion=26.8.0.3；日志 `storage/installers/libreoffice-install-20260925-121055.log`。已核对 App Paths 注册并真实调用转换，不仅依据安装退出码判断可用。

业务要求（同版固定预览与可追溯定位）→ `backend/docx_preview.py`、`backend/preview_store.py`、TaskStore、worker、`GET /document/preview` 和 `/document/preview-map` → `tests/test_docx_preview_api.py`。独立预览表保存原件/解析/产物/映射摘要，以 task_id/document_version 唯一登记；读取验证权限、路径和摘要。转换不持有数据库事务，重复领取不重转，过期结果不发布，已失败不自动重试；没有预览 retry API。原解析/规则/模型快照不改写，预览失败不改变机器审查状态。仅当前已解析 DOCX 自动生成，已有历史预览可按版本读取。

真实证据：F1/F4 经本机 LibreOffice 各生成 1 页，全文顺序一致、各 12 个段落全部对应完整视觉行；实际 PDF、JSON、PNG 保存在 Git 忽略的 `storage/verification/docx-preview-26.8.0.3/`。两份 PDF 渲染中文可读、无裁切；F1 的 `f1-location-overlay.png` 已叠加并目视核对 12 个段落框。独立 HTTP 测试也真实通过后台 worker 转换 F1/F4、持久保存并读取 PDF/映射，不只是组件模拟。

技术验证：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_docx_preview_api tests.test_pdf_preview -q` 5/5 通过（27.519 秒，无 skip）。覆盖真实转换；模拟产物验证匿名/角色权限、非法/缺失版本、版本修订后不复用旧预览、旧版留存、重复生成、重新初始化后读取、原解析和规则快照不变、原件/PDF/路径/映射/解析篡改拒绝、过期转换及缺依赖不自动重试。`python -X utf8 -m unittest discover -s tests -q` 完整 118/118 通过（139.372 秒，无 skip），`git diff --check` 通过。完整日志 `storage/verification/docx-preview-regression.log`；Windows PowerShell 将 unittest 的 stderr 进度包装为 NativeCommandError，日志最终明确为 Ran 118 / OK，并非测试失败。

边界：全部测试使用合成附件和临时 SQLite，没有新的付费模型调用、正式任务变更、提交或推送。复杂排版和字段/任意子串精确区域仍未验证，只对可靠完整段落/条款行框声明 locatable；其他区域明确不可定位。README 已给出文件查看、独立测试及法务 API 验收步骤。安装工具此前 429 与组件缺依赖均为下方历史记录，不是当前阻塞；用户仍须验收本功能，OCR、前端高亮、目标机验证未推进。

2026-09-25 LibreOffice 安装推进（D-22）：用户明确“允许，请安装”。已从官方当前下载页确定 Windows x86-64 26.8.0，官方 mirrorlist 公布大小 374,906,880 bytes、SHA256 `4aa6c6e1895f4055104effcb556bd3362d20c6ad707c149543304f395ef9db95`。默认镜像和 gwdg 证书校验失败后，改用官方列出的 `https://mirror.twds.com.tw/tdf/libreoffice/stable/26.8.0/win/x86_64/LibreOffice_26.8.0_Win_x86-64.msi` 下载，未关闭 TLS 校验。安装包已保存到 Git 忽略的 storage/installers，大小/摘要匹配；Windows Authenticode 状态 Valid，签名方 The Document Foundation；MSI Property 表 ProductVersion=26.8.0.3。

实际安装仍 `BLOCKED`：计划以系统 msiexec 安装到 `D:\AICoding\Tools\LibreOffice`，REGISTER_NO_MSO_TYPES=1、REGISTER_ALL_MSO_TYPES=0、CREATEDESKTOPLINK=0、/qn /norestart；不修改 PATH，不自动重启。提升权限工具在启动前被自动审批服务 `429 Too Many Requests / exceeded retry limit` 拒绝，明确未执行，不是安全否决。随后只读检查目标目录和本次安装日志均不存在。未绕过审批、未重新尝试同一受阻安装。已准备 `scripts/install_libreoffice.ps1` 供用户在管理员 PowerShell 手动执行，包含 SHA256/签名校验、目标已存在拒绝覆盖、退出码及路径检查；PowerShell AST 语法检查通过，仅静态验证，不代表安装成功。用户无需重复授权。安装实际成功、soffice 运行及真实 DOCX/PDF 转换尚 UNVERIFIED；本轮未运行模型、未修改已有任务证据。

2026-09-25 当前单元：第 3 工作块中的 DOCX 固定预览转换与段落定位基础组件，`PARTIAL / BLOCKED_DEPENDENCY`，尚未提交为完整功能验收。用户授权“进行下一项”；按 D-20 仍跳过依赖安装。业务要求（MVP 第 3 节：固定转换预览、同版字符锚点、可靠定位或明确原因）→ `backend/docx_preview.py` → `tests/test_docx_preview.py`。复用现有 DOCX/PDF 提取组件；独立临时输入/输出/LibreOffice profile、无 shell、60 秒转换超时、不自动下载或重试，宏/嵌入对象/外部关系拒绝。组件返回 PDF bytes、原件与预览摘要和原始 DOCX 段落字符区间；只有去空白后的全文顺序一致、段落恰好覆盖完整 PDF 行框时才给页码/归一化区域，可跨页。差异或行框边界不可靠明确不可定位，不用模糊匹配伪造精确位置。当前只支持段落完整行框，不声称字段/任意子串精准框。

验证：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_docx_preview tests.test_docx_parser tests.test_pdf_parser -q` 10/10 通过（1.289 秒）。F1 DOCX 与既有 F2 PDF 的真实文本抽取用于验证映射，F2 不是本轮转换产物；外部转换进程完全 mock。覆盖独立 F2 页码标注、Unicode、换行跨页、重复段落、合并行不可定位、全文不符、转换无输出/失败/超时、缺依赖与外链/宏/嵌入拒绝。真实本机组件预检 `converter_found=False`、`DOCX_PREVIEW_DEPENDENCY_MISSING`；PATH、常见 Program Files 路径、App Paths 及安装项注册表均未发现 LibreOffice/Word（只发现 Office 开发运行库，不是 Word）。未扫描全盘，因此不排除自定义目录的便携安装。

边界与下一步：没有安装依赖、没有模型调用、没有改动数据库/已验收 F1 证据或服务自动流程；无真实生成 PDF、无视觉校对，DOCX preview API 仍不可用。需用户提供已有 LibreOffice 可执行文件路径，或明确调整“暂不安装依赖”约束后，才能真实验证 F1/F4 的转换排版和页码，再完成不可覆盖的预览落库、受保护读取及字段/条款/风险映射接入；已有模型快照不得原位改写。OCR 未开始，不跨单元提前验收。新组件是基础代码而非已完成的固定预览功能。

2026-09-25 最新验收：用户手动执行已授权的真实 F1 命令，反馈 `{"state": "completed", "code": null}`，随后明确“验收通过”。第 2 项“模型持久作业与建议保存”记为 `ACCEPTED`；真实调用成功为用户提供的本机执行证据，替代下方工具审批受阻状态。本轮未重新调用模型、未读取密钥或数据库，不新增用量、账单或建议正文的独立核验证据；供应商实际费用仍待账单核对。此次为功能验收，不是正式法律确认，也不扩大付费次数授权。仅同步验收记录，等待下一步指令。

2026-09-25 当前单元：模型持久作业与建议保存，离线实现 `PENDING_ACCEPTANCE`，真实 F1 调用 `BLOCKED`，整体 `PARTIAL`。用户本轮“验收通过，进行下一项”已验收下方费用预检与私有 HTTP 功能。业务要求（MVP 机器草稿、D-08/D-09/D-15/D-21）→ `backend/model_jobs.py`、TaskStore、服务 worker、`GET /api/v1/tasks/{task_id}/model-result` → `tests/test_model_jobs.py`。模型作业与预算预留/单次授权标记同事务落库；并发不会重复发送，过期 running 转 blocked 并保留未知费用，不自动补发。已知 usage 按冻结单价结算；无效建议 completed 且明确需法务补充，传输失败 blocked。迟到旧版结果不完成新版任务；读取复核版本/证据和保存内容，只允许法务，历史规则版本显式返回 `rule_version_current`。机器 completed 不等于法务确认，review_version 仍空。

本轮授权边界：普通上传有规则命中时保持 reviewing/pending，等待调用授权，不自动读密钥或发起付费请求；无命中版本自动保存 MODEL_NOT_REQUIRED 并完成机器阶段，不表示法律安全。真实入口仅 `python -m backend.model_jobs TASK_ID VERSION`，校验固定合成 F1 原件摘要及上传根目录，使用数据库唯一授权 `D-15:F1:one-call`；没有公开付费发送 API，也没有模型付费 retry。当前自动模型 worker 只登记、处理免费版本与恢复超时。后续扩大付费授权或模型重试须另行确认。

验证证据：新增模型作业及既有模型组件回归 12/12（14.867 秒）；全后端 `python -X utf8 -m unittest discover -s tests -q` 107/107（114.973 秒）。随后新增后台 lifespan 免费完成、旧版本迟到不覆盖、预算不足不发送三个用例，独立模型作业 9/9（18.124 秒）。全部使用临时 SQLite、固定合成附件、本地真实 tokenizer、模拟模型响应；包括重启留存、崩溃未知占额、同一授权跨任务拒绝、预留/发送标记事务回滚、API 401/403/404、损坏结果拒绝。不是供应商或法律验收。

真实验证受阻：本机已有 F1 `ce6d479e179d410f85756ac2b22bcf8f` / 1，原件登记摘要及同版快照符合条件。尝试通过提升权限工具执行唯一已授权调用，但自动审批服务报 `429 Too Many Requests / exceeded retry limit`，明确命令未执行；不是判断操作不安全。未绕过审批、未重试、未发送 API、未消费本次授权，也未因本次命令写入正式数据库。需要用户按 README 手动执行同一入口并反馈状态；已授权一次调用，无须新增次数或提供密钥。若实际执行后失败，不再次运行付费验证，先核对输出与账本。真实账号、响应、供应商账单仍 UNVERIFIED。DOCX 固定预览/OCR、法务复核、报告与模拟回写等后续工作未在本轮实施。

最终复验：补齐历史规则版本提示后，`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_model_jobs -q` 再次通过 9/9（15.513 秒）；`git diff --check` 通过。只读核对正式库仍无 model_jobs 表、预算记录 0 条，证实被拒绝的命令没有执行；密钥配置及 tokenizer 资源仍被 Git 忽略。未提交或推送。

以下为历史证据；其“当前/待验收/尚未实现”按日期及本条最新范围解释。

2026-09-25 当前单元：模型费用预检与私有 HTTP 边界 `PENDING_ACCEPTANCE`。用户 D-21 已接受本地 tokenizer 估算、单次固定预留 0.10 元而非账单绝对上限；此前“线上绝对输入上界”阻塞被该决定替代，不声称原假设已经验证。业务要求（MVP 第 5 节 + D-21）→ backend/model_tokens.py、model_transport.py、model_budget.py → tests/test_model_transport.py。官方 CDN 来源由用户提供，资源 SHA256 见下条；复制到 Git 忽略的 storage/model，未执行包内脚本。使用本机已有 tokenizers 0.23.2/Jinja2 3.1.6 并补 requirements 声明，未安装依赖。F1 实际解析/同版快照、本地模板输入 476 token，输出限额 4096，预计 33,720 微元；账本实际预留 100,000 微元并冻结估算来源/摘要。估算超过限额拒绝、F4 零命中不加载资源；缺失/损坏资源与缺失依赖拒绝；相同调用不新增预留、改预留额冲突；未知用量完整占额且重启保留；模拟超预留 usage 按 112,768 微元如实核算。剩余预算足够 33,720 但不足 100,000 时仍拒绝调用。

本轮最终验证：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_model_transport tests.test_model_advice tests.test_model_budget tests.test_model_config -q`，6/6 通过（2.787 秒）；临时 SQLite、实际本地 tokenizer、合成 F1/F4，HTTPS/响应完全 mock。原传输成功/超时/错误/响应限制及账本并发/结算回归通过。未读真实密钥、未联网或产生费用、未修改生产数据库。真实 API/账号仍 UNVERIFIED；模型作业、自动预留发送、结果保存和 completed 尚未实现，为验收后下一功能。当前只提交离线预检/预算组合及私有传输边界验收，不提前进入下一功能。下方 PARTIAL/待下载链接/输入上界阻塞等为历史记录，以本条和 D-21 为准。

2026-09-25 tokenizer 人工材料验证：收到 Token 用量计算截图及用户提供的 `C:\Users\Administrator\Downloads\deepseek_v4_tokenizer.zip`，SHA256 `e7310d1dafe0a86d8a5629fe78a7c763760f651db9b8682718a1781dcd6fe495`。截图明确字符换算为近似值、实际用量以 usage 为准。压缩包含 tokenizer.json、tokenizer_config.json 和示例 Python；未执行包内脚本或其 trust_remote_code=True 指令。使用本机已有 tokenizers 从内存加载 JSON，以 Jinja 沙箱渲染包内模板，在临时 SQLite 中生成实际合成 F1 同版规则请求：解析 reviewing、规则 completed、本地模板输入 476 token，输出限额 4096，按 2/8 元每百万估算 33,720 微元（0.03372 元）。此为本地模板计数，未证明线上服务模板/JSON Output 包装一致，不能作为已验证的输入上界。包内未声明具体 Flash 版本，model_max_length=16384 与页面 1M 不一致，可能为遗留配置；待核对原始下载链接及适用性，不据此认定包错误。当前功能仍 PARTIAL；未安装依赖、未读取密钥、未发送请求、未消费额度，生产代码不变。

2026-09-25 人工资料补充：用户按手动核查要求提供模型价格表截图。截图可见 `deepseek-flash` / DeepSeek-V4.1-Flash、OpenAI 格式基址 `https://api.deepseek.com`、上下文 1M、最大输出 384K、JSON Output 支持；Flash 人民币每百万 token 高峰输入缓存命中 0.04 元/未命中 2 元/输出 8 元，空闲分别 0.02/1/4 元。与既有高峰未命中计价一致，型号与价格表核对已获得用户提供证据，不代表助手联网复核或账号实测。截图未包含价格脚注的完整时段条件和 token 计算/tokenizer 说明；本项目继续按表中较高价格估算，不依赖折扣。1M 上下文容量不等于当前请求 token 数或 tokenizer 上界证明；当前剩余阻塞为实际输入上界依据，仍 PARTIAL。仅更新证据文档，未改代码、未重复离线测试、未调用模型。

2026-09-25 按用户要求重试阻塞及回归：普通公开资料请求仍返回 Schannel `SEC_E_NO_CREDENTIALS`；提权只读请求在执行前被自动审批服务 `429 / retry limit` 中止（request id: 62422b1d-2baa-43cd-9516-d9853ed3d995）。不是项目业务代码错误，未修改系统证书、代理或权限，未绕过审批。当前资料验证仍 `BLOCKED`，按用户明确要求转人工浏览器核对。离线回归命令 `.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_model_transport tests.test_model_advice tests.test_model_budget tests.test_model_config -q`，6/6 通过（2.474 秒）；未读取真实密钥、未发送模型请求、未消费额度。手动核查步骤见 README；人工提供价格资料后仍须另行建立输入 token 上界依据，不能将价格核对当作真实传输或输入估算已通过。

2026-09-24 模型费用预检与 HTTP 边界：当前单元 `PARTIAL`，离线组件已验证、用户尚未验收，真实预检依据 `BLOCKED`。业务要求（MVP 第 5 节预算、后端设计模型边界）→ `backend/model_transport.py` → `tests/test_model_transport.py`。`prepare_request` 固定已选 Flash，要求调用方显式提供可信输入上界，缺失时拒绝；不从请求字节数猜 token。复用既有单价快照和整数微元算法，预计超过 0.10 元拒绝，返回可供既有账本预留的报价及请求摘要；报价本身不落库、不构成发送许可。零规则命中跳过。

私有 `_post_json` 使用标准库默认 TLS 校验、固定官方 HTTPS 主机和路径，不发现系统代理、不跟随重定向、不重试、不输出凭据或上游错误正文；socket 超时 30 秒，连接完成后的请求/响应读取预算 60 秒，响应最多 256 KiB，严格 JSON 对象/唯一键。阻塞 DNS 不受该响应期限约束，后续持久作业租约仍需覆盖进程卡住或中断；尚未实现端到端作业截止时间。此函数没有生产调用方、API 或 CLI；尚未接入真实密钥和自动预算/作业，机器状态不因本组件完成。

验证：首次独立 `.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_model_transport -v`，3/3 通过（1.255 秒）；补充传输响应与既有建议校验/账本结算组合、连接/响应头/读取超时后，最终 `.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_model_transport tests.test_model_advice tests.test_model_budget tests.test_model_config -q`，6/6 通过（2.511 秒）。F1/F4 实际本地解析；HTTP/TLS 使用 mock，输入用量为合成值、假密钥、临时数据库。预留 34,768 微元、模拟已知用量结算 60 微元，未知用量保留预留；项目不足拒绝和同调用重复预留不新增记录。不是实际供应商账单；未验证真实网络、真实 tokenizer、账号余额或操作系统杀进程恢复。

本轮联网证据：只读公开价格页面先遇 Windows Schannel `SEC_E_NO_CREDENTIALS`；随后请求环境授权时，自动审批服务以 `429 / retry limit` 在执行前中止，属于审批服务失败，不是认定请求不安全或 DeepSeek 错误。未绕过审批、未发送模型请求、未读取真实密钥、未消费额度。既有一次合成 F1 授权保留。继续前需恢复官方资料核对并建立可验证输入上界，不能把本单元整体记为通过，也不进入下一功能。

2026-09-24 当前安排（覆盖下方历史待复核/前端未授权描述）：用户确认已提交的演示内容复核完成，记为 `ACCEPTED`；专业法务核定仍 `UNVERIFIED`。用户同意继续后续顺序，前端按根目录 `pencil-new.pen` 实施（D-19/D-20）。本轮落实确认与执行安排，没有新增业务实现、没有调用模型、没有重新运行业务测试。设计文件 JSON 可读取，schema 2.17，共 10 个画板；仅结构核对，不代表浏览器视觉或交互验收。

下一单元：模型请求费用预检与传输边界。先验证输入 token 估算依据、冻结价格、单次预计 0.10 元和项目 50 元保护，再实现无自动重试的 HTTP 传输及模拟成功/超时/错误/响应上限测试；真实 F1 仍仅一次既有授权，未执行。未确认 token 上界或价格时不得发送。该单元通过后提交用户验收，再接入持久模型作业及机器完成状态。完整后续安排见 `BACKEND_WORK_BLOCKS.md` 顶部。

2026-09-24 复核责任确认：用户暂时承担演示规则、候选法律依据和示范条款的内容复核（D-18）。责任人已确认，具体内容尚须逐项提交用户核对；专业法务核定仍 `UNVERIFIED`，不能将用户演示验收写成专业法律结论。其余后端开发可继续按逐功能验收推进，既有角色权限保持不变。

2026-09-24 需求基线验收：用户明确确认 `docs/MVP_SPEC.md` 为正式需求基线，状态 `ACCEPTED`，决定见 D-17。本次仅同步文档状态，不改代码、不调用模型。其他设计文档和法务核定不视为已验收；真实 F1 调用仍受下述联网审批故障阻塞。本文及其他文件下方的“需求基线待验收”为历史记录。

2026-09-24 本地密钥填写后检查：用户授权测试使用；`python -X utf8 -m backend.model_config` 返回成功，未输出密钥。真实 F1 调用仍 `BLOCKED`：调用前公开价格复核的联网操作两次均被自动审批服务以 429/retry limit 中止，未执行网络请求，不代表价格或密钥无效。没有发送模型请求、没有消费本次授权额度，也未进行自动重试调用。只读检查默认 `storage/contract_approval.sqlite3` 无用户且尚无 tasks 表，真实测试执行前还需准备合成 F1 任务及持久预算记录。密钥有效性与余额仍 UNVERIFIED；保留用户一次低额度调用授权，待工具审批恢复后继续。

2026-09-24 最新确认：模型请求构造与返回校验已获用户明确“验收成功”，记为 `ACCEPTED`；用户选定 `deepseek-flash`，授权一次合成 F1 真实验证并要求控制用量。该次实现采用预计费用不超过 0.10 元、计入项目 50 元、超限不发送和失败不自动追加调用的保护边界，尚未执行。

本轮按用户要求准备本地密钥文件，状态 `PENDING_ACCEPTANCE`：`secrets/deepseek.ini` 留空待用户填写；`backend/model_config.py` 用标准库读取，路径不依赖启动目录，不设置环境变量，错误信息不包含密钥。`tests.test_model_config` 使用临时目录和假密钥验证 UTF-8 BOM、百分号、文件缺失、空值、错节、引号/空白、坏格式和重复配置拒绝及异常输出脱敏；命令 `.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_model_config -v`，1/1 通过（0.023 秒）。`git check-ignore -v -- secrets/deepseek.ini` 命中 `.gitignore:14:secrets/`，`git ls-files -- secrets/deepseek.ini` 无结果。空配置 CLI 预期退出 1 并提示填写；未读取真实密钥、未联网、未调用模型。真实密钥有效性、余额及 HTTP 接入仍未验证。

最新验收（2026-09-24）：用户明确“验收通过，进行下一功能”，内部模型预算账本记为 `ACCEPTED`。本轮模型请求构造与返回校验为 `PENDING_ACCEPTANCE`，不代表整个模型阶段、文档或法务验收。

业务要求 → 实现 → 证据：后端设计第 4 节 → `backend/model_advice.py` → `tests.test_model_advice`。临时数据库实际解析合成 F1/F2/F4，验证最小证据输入、显式模型、JSON 模式、禁用思考、F4 跳过及超长拒绝；合成响应覆盖正常、截断、错版/摘要/规则、重复 JSON 键、额外字段、缺漏/重复建议和非法用量；规则快照和任务状态不变。权限证据只覆盖既有法务草稿读取。

最终命令：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_model_advice tests.test_model_budget tests.test_rule_processing tests.test_rule_snapshot_api -q`，4/4 通过（7.707 秒）。修正预算恢复动作 adjust_budget 为 budget_decision 并增加断言。官方 Flash 估算价格配合合成 token 数：预留 34,768 微元，未知用量持续保留，后续结算 768 微元；不是实际账单。未重跑全量，下方为历史证据。

官方模型、人民币价格和响应契约已核对，来源见后端设计。Flash/Pro 选型已询问用户、待答复，不推定选择或付费授权。输入 token 保守上界、真实账号/账单、HTTP 传输、模型作业/超时、建议持久化及完整机器 completed 均未实现或验证；模型文本仍需法务核定。

最新验收（2026-09-24）：用户先明确“验收通过，只读询问”，随后明确“上述验收成功，请进行下一项”。自动规则保存与暂时故障管理员重试为 `ACCEPTED`；当前开展计划中的模型预算账本基础功能。此处覆盖下方历史待验收描述；未将功能验收记作文档或法务验收。

| 本轮功能 | 状态 | 业务要求 → 实现 → 证据与边界 |
| --- | --- | --- |
| 内部模型预算预留与持久估算账本 | `PENDING_ACCEPTANCE` | MVP 第 5 节、后端设计第 4 节 → `backend/model_budget.py`、`TaskStore.model_budget` → 独立冒烟 `tests.test_model_budget` 使用临时 SQLite、真实 F1 解析及合成单价，验证金额向上取整、非法参数、错版拒绝、跨连接并发限额、同调用并发幂等、拒绝任务落库、未知用量跨重启保留、已知用量结算、结算冲突拒绝、精确50元边界及超预留用量如实记账。中断通过 mock 在预留事务中注入，不是操作系统杀进程测试。无网络调用。 |

验证：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_model_budget -v` 初次独立冒烟 1/1 通过（0.434 秒）；补充同调用并发、错版和参数边界后，最终 `.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_model_budget tests.test_rule_processing tests.test_rule_snapshot_api -q` **3/3 通过（6.727 秒）**。未重跑全量；下方 95/95 为上轮历史结果。本轮新增表只由 `TaskStore.initialize` 初始化，不向运行中的演示数据库写入测试记录。

范围：预算组件为内部可信代码接口，不新增公开费用修改入口；不代表预算已接入模型自动作业。全项目固定 50 元，整数微元人民币，冻结每次价格/模型/输入输出上界与用量记录；未知费用保留预留，不自动释放；无预算调整、人工核账或解除预算受阻入口。官方价格、真实 token 估算、汇率缓冲的选择、真实模型及其超时任务状态/重试尚未实现或验证；工作块 4 仅部分完成。权限回归覆盖既有规则 API，不能当作未来预算 API 权限验证。机器仍 reviewing。

最新验收（2026-09-24）：用户明确“验收通过，允许进入下一功能”，法务读取已保存规则草稿记为 `ACCEPTED`。本轮自动规则阶段为 `PENDING_ACCEPTANCE`，下面旧段落的“本轮/最新/待验收”仅为历史记录。

本轮收尾：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_rule_processing -v` 独立冒烟 1/1 通过（3.695 秒）；随后补充新连接恢复待重试任务、旧版 pending 失效检查，最终 `.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -q` **95/95 通过（109.073 秒）**，包含最终独立冒烟。原手动保存与快照 API 专项 3/3 通过；本轮跟踪文件 `git diff --check` 无空白错误。验证仅覆盖本机合成数据，不含付费模型、目标机、浏览器前端或法务签批。

| 本轮功能 | 状态 | 业务要求 → 实现 → 证据与边界 |
| --- | --- | --- |
| 解析后自动保存规则草稿及暂时故障管理员重试 | `PENDING_ACCEPTANCE` | 工作块 3 同版规则持久处理 → `RuleSnapshotStore.run_next/retry`、服务内 `DocxWorker`、`POST /tasks/{task_id}/retry` → `tests.test_rule_processing` 在本机临时库和 F1/F2/F4 合成附件验证真实服务上传到持久草稿读取、两项/零风险、跨连接重复处理、插入后中断整体回滚、重启恢复、故障保留与管理员重试权限/错版/重复拒绝、坏证据与来源变化受阻、旧版 pending 失效。中断与暂时错误由 mock 注入，换版受阻状态由测试设置；非实际操作系统杀进程测试。纯本地规则短事务，无网络模型或新增依赖；机器继续 reviewing，无审查版本。 |

最新验收：用户明确回复“验收通过，进行下一功能”，同版 PDF 规则草稿手动持久化记为 `ACCEPTED`。本轮实现法务读取已保存规则草稿，`PENDING_ACCEPTANCE`；下方历史收尾中的待验收和未实现描述不覆盖本条最新进度。此次同时按用户指定的 `ponytail` 规范复用现有权限与存储，无新依赖。

本轮验证：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_rule_snapshot_api -v` 独立冒烟 1/1 通过（2.785 秒）；之后补充无风险 F4、已保存后的权限检查并校验风险字段，最终 `.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -q` 94/94 通过（94.757 秒），包含最终版独立冒烟；本轮文件 `git diff --check` 通过。全部为本机合成文件及临时库的 API 技术验证，非目标机、前端或真实业务验收。

| 本轮功能 | 状态 | 业务要求 → 实现 → 验证 |
| --- | --- | --- |
| 法务读取已保存规则草稿 | `ACCEPTED` | 同版结果与权限隔离 → `backend/main.py` 的 `/risks/snapshot`、`TaskStore.get_rule_snapshot`、`RuleSnapshotStore.read` → `tests.test_rule_snapshot_api` 使用本机临时 SQLite、F1/F2/F4 合成文件，验证 DOCX/PDF 两项风险、无命中草稿、权限、当前/历史版本、来源摘要、规则升级标识、无重新计算/写入、损坏 JSON/版本/引文拒绝及新连接重读。换版所需 `completed/confirmed` 是测试直接设置的模拟前置条件，不计作法务确认实现。仍无自动审查、模型、确认版本、报告/回写和前端。 |

同版 PDF 草稿保存收尾：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_pdf_snapshot tests.test_smoke.BackendSmokeTests.test_persisted_rule_draft_snapshot_smoke -v` 2/2；`.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -q` 93/93 通过（86.613 秒）；本轮文件 `git diff --check` 无空白错误。独立 PDF 冒烟为 `tests.test_pdf_snapshot`，已验证合成 F2 CLI 保存、重复/重启、来源变化拒绝与历史草稿不覆盖。功能保持 `PENDING_ACCEPTANCE`，未进入自动审查或法务确认。

用户已明确回复“验收通过，允许进入下一功能”，PDF 字段/条款提取与同版规则读取记为 `ACCEPTED`；本轮下一项为同版 PDF 规则草稿手动持久化，待验收。历史收尾段中的待验收表述保留为当时记录。

PDF 结构化提取本轮收尾：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_pdf_structure -v` 3/3，`tests.test_pdf_job` 2/2；`.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -q` 92/92 通过（91.186 秒），`git diff --check` 无空白错误。均为合成样例、本机临时库；F2 字段页码与条款/风险引文对照静态答案，跨页及旧库迁移使用受控数据。PDF 自动正文解析已获用户验收，本轮结构化提取与规则读取为 `PENDING_ACCEPTANCE`。旧功能行描述的是各自验收时范围，当前能力以最新条目及 README 顶部说明为准。

本轮用户明确回复“验收1,2完成，请进行下一步”：固定规则草稿缺陷修复与证据校验、F2 文本 PDF 提取组件均记为 `ACCEPTED`，覆盖下方历史记录中的待验收表述。PDF 自动解析与同版正文读取随后由用户回复“验收通过，进入下一功能”确认验收。其余文档基线不因此自动验收。

PDF 接入收尾证据：`.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -q` 88/88 通过（93.520 秒）。之后新增过期 PDF 租约恢复、旧令牌拒绝及原件摘要变化阻塞的专项用例，`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_pdf_job -v` 2/2 通过（4.322 秒）；新增测试后未重复全量。全部使用本机临时库和合成样例，无付费调用。旧数据补列路径亦经既有 DOCX/队列回归；同一事务复用原解析持久化逻辑。后续先等待此功能验收，再推进 PDF 字段/条款及风险映射。

更新时间：2026-09-24。本文只记录当前证据，不改变 [MVP SPEC](MVP_SPEC.md) 的需求。`NOT_STARTED` 表示没有实施；`PARTIAL` 表示该行整体目标未完成、已有部分组件；`UNVERIFIED` 表示缺少当前所需证据；`PENDING_ACCEPTANCE` 表示已提交但尚无用户验收；`ACCEPTED` 表示用户已明确验收。

| 项目 | 状态 | 当前证据或缺口 |
| --- | --- | --- |
| 同版 PDF 规则草稿手动持久化 | `ACCEPTED` | `backend/rule_snapshot.py` 支持当前版、机器 `reviewing` 且结构化状态 `available` 的 PDF；保存同版规则、引文、页码/区域与证据摘要。PDF 摘要包含全文、条款、缺失类型、段落和页数；DOCX 原摘要保持兼容。未解析或旧版仅正文 PDF 拒绝保存，旧版本请求拒绝；重复执行不覆盖，证据或规则版本变化拒绝复用。`tests.test_pdf_snapshot` 独立冒烟通过，覆盖真实 CLI、F2 两项风险与第 2/3 页、重复保存、段落/条款/页数变化、规则版本变化、新数据库连接重读及不改变 `reviewing`；既有 DOCX 保存冒烟通过。全部使用临时库和合成文件。仍无自动审查作业、持久快照读取 API、模型或法务确认版本 |
| PDF 字段/条款提取与同版规则读取 | `ACCEPTED` | `backend/pdf_structure.py` 复用已验收的显式标签/标题提取，字段保留同版字符区间及页码，字段只覆盖行内局部值时 `locatable=false/PDF_FIELD_REGION_UNVERIFIED`，不伪造精确框；条款合并同版各行区域，跨页保留多区域，风险沿用这些证据。新 PDF 作业原子持久化 12 项字段、7 项条款及缺失类型，并开放法务 `/risks` 即时评估；F2 两项高风险页码为知识产权 3、付款/验收 2。SQLite 新增结构化提取状态，旧 PDF 正文记录保持 `not_implemented`，不原位改写或误报；旧 PDF `/risks` 继续 409。专项 `tests.test_pdf_structure` 3/3、API/恢复冒烟 `tests.test_pdf_job` 2/2 通过，含固定答案、跨页、不可定位降级、旧库重复初始化及权限。浏览器高亮、复杂版式、精确字段框、目标机、自动审查和模型仍未验证 |
| PDF 自动解析与同版正文读取 | `ACCEPTED` | `backend/pdf_job.py` 接入现有独占解析租约与服务循环；F2 自动进入 `reviewing`，同版全文、逐行段落、3 页页码和区域落库，法务通过 `/document` 读取。字段/条款尚未提取，`structured_extraction_status=not_implemented`，`/risks` 返回 409/`RULE_EVIDENCE_NOT_READY`。加密 PDF 进入 `blocked/PDF_ENCRYPTED/replace_attachment`；损坏或无文本 PDF 同样保存原因。新增 `tests.test_pdf_job` 独立冒烟 1/1，使用临时库验证 F2 成功、角色隔离、加密受阻、换版恢复、重启读取；全量回归结果见本轮收尾记录。浏览器、目标机、OCR、PDF 字段/条款/风险映射未验证 |
| 固定规则草稿缺陷修复与证据校验 | `ACCEPTED` | 用户要求修复代码审查发现的三项缺陷与两项维护风险。`backend/demo_rules.py` 将规则升为 `demo-v2`：同版已识别的软件权属归供应商且无使用授权、到货付全款且验收条款缺失时生成带原文锚点的规则草稿；含糊验收和相反约定仍留法务判断。校验段落索引、原文区间与预览定位字段；`backend/tasks.py` 将损坏 JSON 映射为 409/`RULE_EVIDENCE_INVALID`；`backend/demo_rules.py:evaluate_persisted_rule_evidence` 供即时 API 与 `backend/rule_snapshot.py` 共用；旧规则版本快照返回 `RULE_VERSION_CHANGED`，不覆盖。独立冒烟 `python -X utf8 -m unittest tests.test_smoke.BackendSmokeTests.test_rule_evidence_repair_smoke -v` 1/1；定向测试 9/9；完整回归 `python -X utf8 -m unittest discover -s tests -q` 77/77（88.598 秒），均用合成 DOCX 与本机临时库。此前 `/risks` 和固定规则组件的原验收保留为历史；本轮行为变更部分待重新验收。 |
| 法务读取同版规则草稿 API | `ACCEPTED` | `backend/tasks.py:get_rule_drafts` 与 `backend/main.py` 新增 `GET /api/v1/tasks/{task_id}/risks`；依据同版已保存正文/条款即时评估已验收规则，返回来源、规则版本、原文锚点和建议，明确 `persisted=false`、`review_version=null`，无模型调用或状态写入。独立冒烟 `python -X utf8 -m unittest tests.test_smoke.BackendSmokeTests.test_rule_drafts_api_smoke -v` 本轮重新运行 1/1 通过，验证合成 F1 双命中、F4 无命中、原文一致、重复读取无数据库写入/状态变化、未解析 409、无此文档/审查版本 404、非法版本 422、未登录 401、本人业务/管理员 403、其他业务 404，以及受控错版条款 409。此前完整回归 `python -X utf8 -m unittest discover -s tests -q` 74/74 通过（69.821 秒），本轮未重跑。使用本机临时库，浏览器与目标机未验证；持久审查快照、自动审查作业、法务确认及已确认结果读取仍未实现。用户于 2026-09-24 明确回复“验收通过，进入下一功能” |
| 同版固定规则草稿持久化 | `ACCEPTED` | `backend/rule_snapshot.py` 的手动单次保存命令及 `rule_draft_snapshots` 表只处理已解析、仍为当前版且 `reviewing` 的 DOCX；同一事务写入一份 `demo-v2` 规则草稿、来源证据摘要与时间。重复调用不覆盖；未解析、PDF/图片、错版或坏证据不写入，已保存后来源证据改变返回 `RULE_EVIDENCE_CHANGED`，规则版本变化返回 `RULE_VERSION_CHANGED`，均不复用旧快照。`review_version=null`、机器状态仍为 `reviewing`；`/risks` 即时读取保持 `persisted=false`。独立冒烟 `python -X utf8 -m unittest tests.test_smoke.BackendSmokeTests.test_persisted_rule_draft_snapshot_smoke -v` 1/1 通过，覆盖 F1/F4、CLI、重复执行、证据变化和版本变化；此前完整回归 77/77。用户于 2026-09-24 明确回复“同版固定规则草稿持久化 验收成功”；自动审查作业、快照读取 API、模型输出或法务确认仍未实现。 |
| 核心文档基线及根目录阅读入口 | `PENDING_ACCEPTANCE` | 已编写 MVP SPEC、后端设计、前端设计、核心流程、决策记录和 `README.md`；版本状态、报告失败恢复及会话契约已在文档中补充，需用户明确验收 |
| 前端设计与预览接口契约 | `PENDING_ACCEPTANCE` | `FRONTEND_DESIGN.md` 与预览接口约定已编写；v0.4 十画板设计在根目录 `pencil-new.pen`，本地预览见 `design/v0.4-preview.png`、仪表盘单板见 `design/v0.4-board-02.png`，v0.3 原稿保存在 `design/pencil-new-v0.3.pen`。本版增加当前处理分布与下一步区域，明确统计口径，并使四条合成任务的申请人与概览数据一致；其余页面延续 v0.3。已检查 JSON 结构、节点 ID 与静态预览；尚未在 pen.dev 打开验证，也无前端运行验证，待用户审阅 |
| 本地三角色账号、会话与基础角色鉴权 | `ACCEPTED` | 本机交互式创建账号、登录、查询当前身份、退出撤销及服务端角色依赖已实现；7 项 API/CLI 自动测试通过，本机 HTTP 未登录请求返回 401；新增 `tests/test_smoke.py` 中 `test_account_session_smoke` 冒烟通过；用户于 2026-09-23 明确回复“验收通过，请进行下一功能” |
| 本地上传接入、任务列表与归属权限 | `ACCEPTED` | 支持合成 DOCX/PDF/常见扫描图片接入，SQLite 保存任务/文档版本/摘要/操作记录，原件本地持久化；业务仅见本人、法务见待处理、管理员仅见状态。5 项接入专项测试及 7 项既有鉴权测试通过；新增 `tests/test_smoke.py` 中 `test_local_upload_and_ownership_smoke` 冒烟通过；用户于 2026-09-23 明确回复“验收通过，进入下一功能”。新增模拟待办来源后，原上传路径通过接入回归测试；解析与审查尚未运行，任务保持 `pending` |
| 固定合成待办列表与导入 | `ACCEPTED` | `GET /api/v1/mock-pending` 返回一条明确标为合成数据的待办，业务账号可用 `POST /api/v1/mock-pending/demo-f1-001/import` 创建 `source=mock_pending` 的独立任务和文档版本；原件、摘要、模拟单 ID 与导入操作落库，重启后可读取。法务/管理员导入返回 403，其他业务账号不可读取该任务；旧任务表增列迁移已测；新增 `tests/test_smoke.py` 中 `test_mock_pending_import_smoke` 冒烟通过。该附件是未标注的 F1 候选，不计入 F1–F6 固定样例验收；用户于 2026-09-23 明确回复“验收通过，进入下一步” |
| 修订附件的新文档版本 | `ACCEPTED` | `POST /api/v1/tasks/{task_id}/documents` 要求本人业务账号和 `base_document_version`；仅当前文档 `blocked/replace_attachment` 或上一版机器完成且法务已确认时接受，处理中、其他恢复类型和过期基础版本返回 409。新原件、摘要和操作记录落库，当前三组状态及尝试次数重置；旧原件、旧审查版本号、旧版状态/阻塞原因和尝试次数保留，重启后当前版仍可读。`tests/test_smoke.py` 中 `test_document_revision_smoke` 冒烟通过；允许换版的前置状态由受控测试构造；解析器、法务确认、历史正式结论/报告 API 均尚未实现，F5 全链路未验证。用户于 2026-09-23 明确回复“验收通过，请根据现阶段项目内容进行 code-review” |
| 代码审查问题修复：附件事务失败清理与换版冲突响应 | `ACCEPTED` | 上传与换版共用附件暂存/发布逻辑，数据库事务失败时仅清理本次新建文件；本人换版的 409 响应增加 `task_id` 与 `current_status`，404 不泄露任务状态。`tests/test_tasks.py` 通过临时 SQLite 注入末端审计写入失败，验证任务/版本/历史回滚、新附件清理、旧原件及状态保留；`tests/test_smoke.py` 新增独立清理冒烟并扩展换版冲突检查。本轮 `python -m unittest tests.test_smoke -v` 5/5、`python -m unittest discover -s tests -v` 25/25 通过。进程断电/强杀下的文件与 SQLite 跨系统原子性尚未验证；该限制不等同于本轮受控异常测试失败。用户于 2026-09-23 明确回复“验收通过，进行下一项” |
| 解析作业登记、独占领取与租约恢复 | `ACCEPTED` | 上传、模拟待办导入及换版在文档版本同一 SQLite 事务内登记 `parse` 作业；旧版作业标为 `superseded`。`JobStore` 以事务独占领取一项待处理作业并把任务标为 `parsing`，保存尝试次数和租约；过期租约恢复为 `pending`，旧尝试记录保留，启动时补齐旧库中尚未登记的当前待处理任务。`tests/test_jobs.py` 覆盖版本登记、旧库补齐、跨连接独占领取、换版终止旧尝试、重启后超时恢复及旧令牌失效；独立冒烟 `tests.test_smoke.BackendSmokeTests.test_persistent_parse_job_smoke` 用临时合成附件及人工设定的过期租约验证可见状态。该项验收时 `python -m unittest tests.test_smoke -v` 6/6、`python -m unittest discover -s tests -v` 30/30 通过；当时仅实现队列，后续单次解析及自动循环另见下方功能记录。用户于 2026-09-23 明确回复“验收通过，进入下一项功能” |
| DOCX 正文与段落字符位置提取 | `ACCEPTED` | `backend/docx_parser.py` 从 DOCX 正文 XML 按顺序提取文字（含表格、超链接、制表符和换行），构造同版段落索引及规范化全文的零起始 Unicode 字符区间；空正文、损坏 XML/压缩包和过大内容给出明确解析错误。无固定 PDF 预览时，页码为空、`locatable=false`、`reason=PREVIEW_NOT_AVAILABLE`、`rects=[]`。独立冒烟 `tests.test_smoke.BackendSmokeTests.test_docx_text_extraction_smoke` 用内置合成 DOCX 核对 12 段及损坏附件错误；`tests/test_docx_parser.py` 核对表格/超链接、NFC Unicode 位置、空正文和实体定义拒绝。该项验收时 `python -m unittest tests.test_smoke -v` 7/7、`python -m unittest discover -s tests -v` 36/36 通过，均为本机合成数据。尚未接入作业执行、数据库或 API；用户于 2026-09-23 明确回复“验收通过，允许进入下一功能” |
| DOCX 显式标题条款识别与缺失标记 | `ACCEPTED` | `backend/clause_extractor.py` 以已解析 DOCX 的同版正文和段落区间为输入，仅识别明确标题（含常见条号）开头的标的、付款、验收、违约、保密、数据安全、知识产权、争议解决条款；原文顺序保留，连续正文并入上一标题条款，其他条号和元数据截断条款，重复标题保留多项，缺失类型单列供显示“未找到”。每条引文与同版零起始 Unicode 区间一致；无预览页时 `locatable=false`、`reason=PREVIEW_NOT_AVAILABLE`。独立冒烟 `tests.test_smoke.BackendSmokeTests.test_docx_clause_extraction_smoke` 使用内置合成 DOCX，预期 7 条、数据安全缺失，并用普通正文反例防止关键词误判；`tests/test_clause_extractor.py` 核对条号、跨段、顺序、重复、元数据边界和不一致版本拒绝。`python -m unittest tests.test_clause_extractor -v`：5/5，单项冒烟：1/1，本机完整回归：42/42 通过。该组件尚未接入作业/数据库/API，不能把“验收”标题下的“未约定条件”当成有效验收条件；未覆盖任意排版/复杂标题，不等于完成 F1 标注或商业规则判断；用户于 2026-09-23 明确回复“验收通过，允许进入下一功能” |
| DOCX 基础字段识别与缺失标记 | `ACCEPTED` | 依据 MVP SPEC 第 4 节及 A1，`backend/metadata_extractor.py` 从已解析 DOCX 正文中保守提取标题、编号、送审部门/申请人、双方名称及各自统一社会信用代码、金额/币种、履行期限、生效条件；仅接受明确标签或首段独立合同标题，金额/币种分别留原文片段。缺失、占位语、格式无法识别或冲突值标为“未识别”，不从提交信息或普通条款推断。已识别字段保留同版原文引文、零起始 Unicode 字符区间及段落索引；无预览时页码为空、`locatable=false`、`reason=PREVIEW_NOT_AVAILABLE`。独立冒烟 `tests.test_smoke.BackendSmokeTests.test_docx_metadata_extraction_smoke` 核对合成 DOCX 编号、金额/币种、缺失的两方信用代码及生效条件、锚点与正文误报反例；`tests/test_metadata_extractor.py` 覆盖 12 字段、可识别代码/条件、重复冲突、占位语、同段主体信用代码、错版及错误区间。专项测试 6/6，单项冒烟 1/1，逐功能冒烟 9/9，本机完整回归 49/49 通过；均为合成数据。统一社会信用代码只检查 18 位格式，不验证真伪；任意排版、F1 正式标注、在该项验收时作业/数据库/API 集成及 PDF 页定位尚未验证；用户于 2026-09-23 明确回复“验收通过，允许进入下一功能” |
| DOCX 单次解析作业与同版结果持久化 | `ACCEPTED` | `backend/docx_job.py` 手动领取一项 DOCX 作业，核对原件摘要，调用正文、字段和条款提取；`backend/jobs.py` 在有效租约及当前文档版本下用同一 SQLite 事务写入 `parsed_documents` 与作业/尝试/任务状态。成功进入 `reviewing`，空文、原件丢失或摘要不符进入 `blocked/replace_attachment`，旧令牌不写入结果；独占租约被占用时返回 `busy`，尝试记录缺失或数据库中途写入失败时不提交半份结果，过期后可恢复。旧作业表扩展结果状态时保留尝试历史。该项验收时独立冒烟 1/1、逐功能冒烟 10/10、专项 12/12、完整回归 62/62，通过本机临时合成数据验证；2026-09-24 自检修复忙碌提示并补事务故障测试。用户于 2026-09-24 明确回复“验收通过，允许进入下一功能”；固定预览、结果 API 和规则审查尚未实现 |
| 服务内 DOCX 自动处理循环 | `ACCEPTED` | `backend/main.py` 在正式 `backend.main:app` 的生命周期启动/停止 `backend/docx_worker.py`，启动时恢复过期租约，轮询并领取现有 DOCX 作业；`backend/docx_job.py` 在解析期间每 20 秒续租。成功持久化同版结果并进入 `reviewing`，空文进入 `blocked/replace_attachment`；已存在的权限检查使他人任务详情不可见；PDF 保持 `pending`。独立冒烟 `tests.test_smoke.BackendSmokeTests.test_automatic_docx_processing_smoke` 1/1（临时合成 DOCX 成功、空文受阻、越权 404），专项 `tests.test_docx_worker` 4/4（含启动恢复旧过期租约、旧尝试保留、租约续期落库、PDF 不误处理）；该项提交时完整回归 67/67。均为本机临时数据库和合成附件的 API 测试，实际浏览器/目标机尚未验证；用户于 2026-09-24 明确回复“验收通过，进入下一功能” |
| 法务读取同版 DOCX 解析结果 API | `ACCEPTED` | `backend/tasks.py` 与 `backend/main.py` 实现 `GET /api/v1/tasks/{task_id}/document`，读取当前或指定文档版本的已持久化正文、段落、字段、条款、缺失类型和锚点，`review_version/page_count=null`、`preview_available=false` 明示审查版本与固定预览尚无。仅法务能读取；本人业务在确认前 403、其他业务 404、管理员 403、未登录 401；解析未就绪 409、版本不存在 404。独立冒烟 `tests.test_smoke.BackendSmokeTests.test_parsed_document_api_smoke` 使用临时合成 DOCX/PDF 验证成功、锚点与同版正文一致、版本参数、未就绪与权限，1/1；当时完整回归 68/68 通过。浏览器与目标机未验证；用户于 2026-09-24 明确回复“验收通过，允许进入下一功能” |
| 固定商业演示规则草稿组件 | `ACCEPTED` | `backend/demo_rules.py` 对同版 DOCX 显式条款评估 `DEMO-IP-01` 和 `DEMO-PAY-01`，仅有明确供方权属且排除持续使用授权、或到货付全款且验收条款明确否定可执行付款前条件时出高风险机器草稿；每项保留规则 ID/版本、类别、原因、建议、同版原文锚点及“法律依据待核定”标记，双命中建议“建议拒绝并整改”。证据不完整、仅有标题或矛盾条款不自动判断；F4 候选修订合同无误报，也不自动宣称低风险或法律安全。独立冒烟 `python -X utf8 -m unittest tests.test_smoke.BackendSmokeTests.test_demo_rule_drafts_smoke -v` 1/1，边界测试 `tests.test_demo_rules` 4/4，完整回归 73/73，`python -X utf8 -m backend.demo_rules` 输出 F1 两项带原文高风险、F4 无命中。均用本机合成附件与临时库；该项验收时组件尚未接入作业、持久化、风险 API 或审查版本（本轮 API 增量见上行），F1/F4 正式逐项标注、法务签批和目标机验证仍无证据；用户已明确回复“验收通过，允许进入下一功能” |
| 合同解析、审查数据存储与自动处理循环 | `PARTIAL` | 持久作业队列、DOCX 文本/标题条款/基础字段组件、单次解析持久化、解析结果 API 及服务内 DOCX 自动循环已具备；两条固定商业规则可经 API 即时评估，手动同版草稿保存已验收。固定预览与页码定位、PDF/OCR、自动规则/模型审查作业及完整审查快照尚未实施 |
| F1/F4 固定 DOCX 文件与预览前答案清单 | `ACCEPTED` | `samples/f1-software-purchase.docx`、`samples/f4-revised-software-purchase.docx` 固定合成原件，`samples/f1_f4_expected.json` 独立记录 SHA-256、文档版本、12 项字段、段落与字符区间、7 项条款和缺失类型、F1 两条 `demo-v2` 高风险规则草稿与建议、F4 无命中及“待法务复核”；`samples/README.md` 说明坐标契约和限制。独立冒烟 `python -X utf8 -m unittest tests.test_fixed_samples.FixedSampleSmokeTests.test_f1_f4_fixed_sample_smoke -v` 1/1 通过，完整回归 `python -X utf8 -m unittest discover -s tests -q` 78/78 通过（94.339 秒）。测试核对文件哈希、模拟待办正文一致、全部标注区间与原文一致、F4 不误报；纯本机合成文件，独立冒烟不用数据库、模型或外部平台，完整回归使用临时库。固定 PDF 预览尚无，页码/区域为 `UNVERIFIED`，现阶段只核对 `page=null`、`locatable=false`；法务签批与 F1/F4 全链路未验证。用户于 2026-09-24 明确回复“验收通过，允许进入下一功能”。 |
| F5 固定空白 DOCX 与阻塞恢复标注 | `ACCEPTED` | `samples/f5-empty.docx` 为仅有空白正文段落的合成文件，`samples/f5_empty_expected.json` 固定 SHA-256、`DOCX_EMPTY`、`blocked`、`replace_attachment`、无解析或规则草稿的预期。独立冒烟 `python -X utf8 -m unittest tests.test_fixed_samples.FixedSampleSmokeTests.test_f5_empty_docx_fixed_sample_smoke -v` 1/1 通过（本机临时 SQLite、合成账号）；固定样例专项 `python -X utf8 -m unittest tests.test_fixed_samples -v` 2/2、完整回归 `python -X utf8 -m unittest discover -s tests -q` 79/79（70.688 秒）通过。核对文件、解析错误、API 任务状态、其他业务账号 404、法务结果 API 409、零解析/草稿、无盲目重试、换版后版本 1 阻塞记录保留及版本 2 可解析。用户于 2026-09-24 明确回复“验收通过，允许进入下一功能”；该验收仅覆盖 F5 空文档子场景，加密 PDF、严重模糊扫描件、目标机和 F5 全链路未验证。 |
| F2 三页文本 PDF 固定样例与预期标注 | `ACCEPTED` | `samples/f2-text-software-purchase.pdf` 为合成文本 PDF，嵌入 Noto Sans SC 字体子集及 Unicode 映射；`samples/f2_expected.json` 固定 SHA-256、3 页独立分页、字段/条款/风险页码与 `demo-v2` 两条高风险规则草稿预期，原文及段落/字符区间对照 `samples/f1_f4_expected.json` 的 F1 合同正文。`samples/build_f2_pdf.py` 可在本机已有 `fontTools` 与可嵌入字体条件下重建同一哈希；不添加后端运行依赖。独立冒烟 `python -X utf8 -m unittest tests.test_fixed_samples.FixedSampleSmokeTests.test_f2_text_pdf_fixed_sample_smoke -v` 1/1 通过（2.034 秒，合成账号与临时 SQLite）；此前完整回归 80/80 通过（67.555 秒）。核对 PDF 文本层与原文逐段一致、第 2 页付款/验收、第 3 页知识产权、字段/条款/风险标注、接入 201、本人可见、其他业务 404、法务正文/风险 409、零解析/草稿。此为固定文件的结构检查，不是通用 PDF 解析或独立渲染验证；实际 PDF 提取、可定位区域、规则命中及 F2 全链路仍未实现/验证。用户于 2026-09-24 明确回复“验收通过，允许进入下一功能”。 |
| F3 清晰合成扫描件与原图坐标标注 | `ACCEPTED` | `samples/f3-clear-scan.png` 为单页 2048×2800 灰度栅格合成合同，SHA-256 `c7cf33fff294b6842b679d99d99fdd3a411e6e551a52b8c547dcd2f06cc12548`；`samples/f3_expected.json` 固定 12 段原图像素框、同版字段/条款页码、两项 `demo-v2` 高风险规则草稿和建议，正文、段落及 Unicode 字符区间对照 F1 静态标注。`samples/build_f3_scan.py` 用本机已有 Pillow 与 Noto Sans SC 字体生成固定原件，不添加后端运行依赖。独立冒烟 `python -X utf8 -m unittest tests.test_fixed_samples.FixedSampleSmokeTests.test_f3_clear_scan_fixed_sample_smoke -v` 1/1 通过（6.226 秒，合成账号与临时 SQLite）；完整回归 `python -X utf8 -m unittest discover -s tests -q` 81/81 通过（81.401 秒）。已人工查看图片，测试核对 PNG 完整性、无文字元数据、哈希、段落像素框内有文字且框外无深色文字、预期标注、上传 201、其他业务 404、法务正文/风险 409、伪 PNG 422、零解析/草稿。用户于 2026-09-24 明确回复“验收通过，允许进入下一功能”。原图像素框不是 PDF 预览 `rects`；CPU OCR 输出与坐标、实际规则命中、F3 全链路及目标机尚未验证。 |
| F5 严重模糊扫描件固定样例与预期恢复标注 | `ACCEPTED` | `samples/f5-blurred-scan.png` 从已验收 F3 合成扫描件以半径 22 的高斯模糊生成，仍是单页 2048×2800 灰度 PNG，SHA-256 `6b38bbef76e70d028e484649b7d26a421d45651dc486539bfd92c602731c7a5d`；`samples/f5_blurred_expected.json` 固定来源哈希、未来预期 `blocked/replace_attachment` 与零解析/风险草稿，`samples/build_f5_blurred_scan.py` 可用本机现有 Pillow 重建，不增加后端运行依赖。独立冒烟 `python -X utf8 -m unittest tests.test_fixed_samples.FixedSampleSmokeTests.test_f5_blurred_scan_fixed_sample_smoke -v` 1/1 通过（4.750 秒，合成账号与临时 SQLite），完整回归 `python -X utf8 -m unittest discover -s tests -q` 82/82 通过（78.147 秒）：核对 PNG 完整性、无文字元数据、固定哈希、最深像素灰度不低于 220、上传 201、未登录 401、其他业务 404、法务正文/风险 409、伪 PNG 422、零解析/草稿。已人工查看模糊图。当前图片处理器尚无 OCR，实际任务仍为 `pending`；预期 `blocked` 与换版恢复是待后续 OCR 实现验证的答案，不计作已实现。 用户于 2026-09-24 明确回复“验收通过，允许进入下一功能”；验收仅覆盖固定样例及现有接入验证。 |
| F5 加密 PDF 固定样例与预期恢复标注 | `ACCEPTED` | 用户于 2026-09-24 明确允许新增样例工具依赖；pypdf 6.19.0 已仅安装在 `.tools/pdf-fixtures/`，版本固定于 `samples/requirements-pdf-fixtures.txt`，安装目录已忽略。`samples/build_f5_encrypted_pdf.py` 从已验收 F2 生成 `samples/f5-encrypted.pdf`（SHA-256 `cf6b4c30af93c800e29cb21b6cdac0165b902da1ce3582990f558dffb8e5243d`）；`samples/f5_encrypted_expected.json` 固定来源、三页、公开测试口令与未来预期 `blocked/replace_attachment`。独立冒烟 `python -X utf8 -m unittest tests.test_f5_encrypted_pdf -v` 1/1 通过（2.382 秒，合成账号与临时 SQLite）：无口令/错误口令不能读取，用户/所有者测试口令均可解密，三页正文与 F1 静态标注一致、内容流与页面尺寸和 F2 一致；上传 201、未登录 401、他人 404、法务正文/风险 409、伪 PDF 422、零解析/草稿。重复生成得到相同哈希；固定样例专项 `python -X utf8 -m unittest tests.test_fixed_samples tests.test_f5_encrypted_pdf -q` 6/6 通过（16.596 秒），`git diff --check` 通过。本轮未改后端运行代码，未重复全量回归。RC4-128 仅用于合成密码故障样例；当前 PDF 任务仍为 `pending`，自动识别加密并受阻、换版恢复、PDF 阅读器视觉检查与目标机未验证。 用户于 2026-09-24 明确回复“验收通过，允许进入下一功能”；仅覆盖样例与已验证接入行为。 |
| F6 模拟待办附件首次超时固定故障源 | `ACCEPTED` | `samples/f6_pending_timeout.py` 提供确定性依赖故障源：调用方传入尝试序号，第一次立即抛出 TimeoutError，第二次及以后校验哈希并返回固定 F1 DOCX；无需网络、睡眠、新依赖或数据库。`samples/f6_pending_timeout_expected.json` 独立标注未来处理器应为 `blocked/admin_retry`，重试沿用文档版本 1、保留第一次失败记录，不产生伪造解析或风险草稿。独立冒烟 `python -X utf8 -m unittest tests.test_f6_pending_timeout -v` 1/1 通过（0.015 秒）：首次超时且不读取附件、第二次原件与 F1 正文一致、重复序列稳定、非法尝试号与篡改附件拒绝、CLI 输出不冒充机器状态；实际运行 `python -X utf8 samples/f6_pending_timeout.py` 输出 timeout 后 attachment_available。固定样例专项 `python -X utf8 -m unittest tests.test_fixed_samples tests.test_f5_encrypted_pdf tests.test_f6_pending_timeout -q` 7/7 通过（27.067 秒），`git diff --check` 通过；后端运行代码未变，本轮未重跑全量回归。只是可复用的依赖模拟样例，未接入 API/作业处理器；真实受阻落库、管理员重试权限、尝试持久化及重启恢复仍未验证，F6 回写故障/重复提交实际 API 仍未实现。 用户于 2026-09-24 明确回复“验收通过，允许进入下一功能”；验收只覆盖固定故障源。 |
| F6 首次模拟回写失败与重复提交固定故障源 | `ACCEPTED` | `samples/f6_writeback_failure.py` 提供仅在内存运行的合成评论依赖：首次写入失败且零评论，重试创建 `synthetic-comment-001`，同 `(task_id, confirmed_review_version, mock_approval_id)` 重复提交返回原 ID、不增加评论，版本 2 产生 `synthetic-comment-002`，旧评论仍可读取；同键不同内容拒绝。`samples/f6_writeback_expected.json` 固定四次依赖结果与未来应用预期，评论明确标注“模拟回写”。独立冒烟 `python -X utf8 -m unittest tests.test_f6_writeback_failure -v` 1/1 通过（0.002 秒），固定样例专项 8/8 通过。当前尚无法务确认或回写 API，确认前拒绝、正式状态落库、权限、跨重启去重及实际评论持久化均未验证；这不是 F6 全链路。用户于 2026-09-24 明确回复“验收通过，进入下一功能”；验收只覆盖固定故障源。 |
| F2 同版 PDF 原件受保护预览 API | `ACCEPTED` | `backend/tasks.py:get_pdf_preview` 与 `backend/main.py` 实现 `GET /api/v1/tasks/{task_id}/document/preview` 的文本 PDF 原件读取：仅法务可取当前或指定文档版本，返回原字节、PDF 类型和禁缓存响应；读取前核对文件路径位于本任务附件目录、大小、SHA-256 和 PDF 文件头。独立冒烟 `python -X utf8 -m unittest tests.test_pdf_preview -v` 1/1 通过（2.471 秒），完整回归 `python -X utf8 -m unittest discover -s tests -q` 86/86 通过（80.128 秒），`git diff --check` 通过；使用 F2 合成三页 PDF 与临时 SQLite，验证同版原字节、换版后旧版保留、未登录 401、本人业务/管理员 403、其他业务 404、无此版本 404、非法版本 422、DOCX 无预览 409、原件篡改或路径逃逸 409。用户于 2026-09-24 明确回复“验收通过，进入下一功能”。仅本机 API 与固定 F2 字节已验证；PDF 文本提取、页码/区域锚点、完整 PDF 结构验证、加密 PDF 受阻、DOCX/扫描预览、业务已确认快照读取及目标机仍未验证。 |
| F2 文本 PDF 提取与同版段落页码/区域组件 | `ACCEPTED` | `backend/pdf_parser.py:parse_pdf` 使用已固定的 `pdfplumber==0.11.10`，仅在独立组件内读取合成 F2 原件，生成 NFC 全文、逐行段落、零起始字符区间、一起始原件页码及以页面左上角为原点的归一化区域；无区域时关闭定位并给出原因。F5 加密 PDF、坏格式和错版参数拒绝；本地隔离 `.venv` 验证，不改全局 Python。独立冒烟 `.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_pdf_parser -v` 1/1 通过（0.030 秒）；完整回归 `.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -q` 87/87 通过（93.684 秒），`git diff --check` 通过。上传的 PDF 仍为 `pending`，未接入作业、解析结果 API 或自动规则，不宣称可在页面高亮；仅 F2 固定版式验证，复杂 PDF、目标机与字段/条款/风险区域未验证。 |
| F1–F6 合成文件及逐项预期标注 | `PARTIAL` | F1/F4 固定 DOCX 文件和预览前标注、F5 空文档子场景、F2 固定文本 PDF 与独立页码标注、F3 固定图片与原图坐标标注已获用户验收；F5 严重模糊扫描件固定样例已获用户验收。F5 加密 PDF 固定样例已验收；F6 待办附件超时固定故障源已验收；F6 回写故障与重复提交固定故障源已验收；F3 实际 OCR 坐标、F5 加密/严重模糊扫描件的实际 `blocked` 恢复、F6 超时的实际受阻恢复及回写的实际持久化/权限验证、F1/F4 固定预览页码与区域及各场景全链路证据仍缺，不能计为 F1–F6 正式固定样例整体验收。 |
| DOCX、文本 PDF、扫描 OCR 的提取与定位 | `PARTIAL` | DOCX 正文、段落字符区间、显式标题条款、基础字段识别、单次 DOCX 作业持久化、自动循环与解析结果 API 已验收。F2 同版 PDF 原件受保护预览 API 已获用户验收；DOCX 预览页定位、PDF 作业/API 接入及扫描 OCR 尚未实现；pdfplumber 组件已在固定 F2 样例验证、待用户验收，目标机未验证 |
| DeepSeek 接入、真实 F1 调用及 50 元预算拦截 | `NOT_STARTED` | 模型 ID、官方计费、汇率、账号余额及调用结果尚未在本项目核实 |
| 法务复核、报告与模拟回写 | `NOT_STARTED` | 接入任务的归属权限已验证；复核、确认、报告与回写尚未实施，真实平台接入不在首期 |
| 前端大盘、双栏工作台和双向定位 | `NOT_STARTED` | 尚无代码或界面验证 |
| 后端阶段 F1–F6 API 验收 | `NOT_STARTED` | 固定样例和 API 均未实现 |
| 前端阶段 A1–A8 与另一台 Windows 电脑验收 | `NOT_STARTED` | 目标机运行和全链路证据尚无 |
| 法务对演示规则、候选法律依据和示范条款的确认 | `UNVERIFIED` | 需中国大陆现行权威来源核查及法务签批；不得宣称正式法律结论 |
| 真实审批平台、身份系统、主体查询及生产数据政策 | `UNVERIFIED` | 缺接口资料、权限与生产要求；不计入演示通过条件 |
| DeepSeek 供应商侧实际费用上限 | `UNVERIFIED` | 应用内为估算拦截；精确账单及供应商侧限额能力需核对 |

当前工作区的账号、会话、合成附件接入、任务列表、修订换版、持久解析作业队列、三个 DOCX 提取组件、手动与自动解析、法务读取解析结果 API、两条固定商业规则组件、法务即时读取规则草稿 API、手动同版草稿持久化，以及 F1/F4 固定 DOCX 与预览前答案清单、F5 空文档子场景、F2 固定文本 PDF、F3 固定清晰扫描件均曾获用户逐项验收；`demo-v2` 行为修复影响规则组件与 `/risks`，该变更部分仍待重新验收。F5 严重模糊扫描件、F5 加密 PDF、F6 待办附件超时固定样例均已获用户验收；F6 回写故障固定样例已获用户验收；F2 PDF 原件预览 API 已获用户验收；完整机器审查、DOCX/扫描固定预览、PDF 作业/API 接入、OCR、报告和回写仍未实现；F2 PDF 提取组件待本轮验收。文档基线仍待单独验收。技术检查不等于用户验收。每个可独立验收的后续功能仍按“业务要求 → 实现位置 → 验证证据 → 用户验收”记录。

2026-09-24 接手收尾：自审复现并修复跨条款矛盾误报。已识别的另一知识产权条款明确授予使用权，或另一付款/验收条款要求付款前验收时，不自动命中对应规则，留待人工核对。新增三类矛盾约定的前后顺序共六个子用例，修复前全部失败、修复后全部通过，另一独立规则的正常命中保留；这不证明通用语义识别能力。

本次验证使用合成附件和临时数据库：`python -X utf8 -m unittest tests.test_demo_rules tests.test_smoke.BackendSmokeTests.test_demo_rule_drafts_smoke -v` 通过 5/5（边界 4 项、独立冒烟 1 项）；`python -X utf8 -m unittest discover -s tests -q` 通过 73/73，耗时 85.078 秒；`python -X utf8 -m backend.demo_rules` 实际输出 F1 两项带原文高风险、F4 无命中。同步 README 使用步骤及核心流程/后端设计的组件边界，未进入下一功能，规则组件随后获用户明确验收，进入法务读取规则草稿 API 功能。
