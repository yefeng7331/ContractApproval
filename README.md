# 合同审查演示系统

## 当前进度（2026-09-26）

FE1–FE8、A8 的 F1 人工操作记录、管理员查询接口、操作记录页面、处理记录、本机 HTTP 联调及单命令启动已由用户验收。法务账号可在任务详情核对原文、修改审查草稿并正式确认；业务与法务可查看已确认版本的 Markdown/PDF 报告。法务可将确认结论写为本地模拟评论。管理员可查看受阻原因、按条件重试当前文档版本，并查看模拟待办附件获取历史与处理记录；换件和预算决策受阻不提供管理员重试。F2 文本 PDF、F3 清晰扫描件、F4 修订合同零误报的本机 HTTP 联调已验收；F5 空文 DOCX 受阻换件联调待验收，浏览器页面点击与总体验收仍未完成。此系统不连接真实审批平台，不主动调用付费模型；规则依据仍待法务核定。

A7 F5 空文 DOCX 受阻换件本机 HTTP 联调（待验收）：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_local_http_acceptance.LocalHttpAcceptanceTests.test_f5_empty_docx_live_proxy_block_replacement_and_permissions -v`。临时 SQLite、固定空文 DOCX 和有效替换件经 Vite 代理核对受阻原因、禁止虚假结论、所属业务换件、越权与旧版冲突拒绝，以及 v1/v2 处理记录。定向 1/1、F1–F5 本机 HTTP 回归 5/5 通过；加密 PDF、模糊扫描件的本机 HTTP 联调及浏览器点击尚未验证。

A1–A4 F4 修订合同零误报本机 HTTP 联调（已由用户验收）：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_local_http_acceptance.LocalHttpAcceptanceTests.test_f4_revised_docx_live_proxy_no_false_risks_and_permissions -v`。临时 SQLite 与固定合成 DOCX 经 Vite 代理核对解析、同版预览、零规则命中、`MODEL_NOT_REQUIRED`、法务确认、含法律风险边界提示的报告及权限拒绝；不请求模型。定向 1/1、F1–F4 本机 HTTP 回归 4/4 通过。浏览器实际显示和点击尚未验证。

A1–A4 F3 清晰扫描件本机 HTTP 联调（已由用户验收）：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_local_http_acceptance.LocalHttpAcceptanceTests.test_f3_scan_live_proxy_ocr_regions_review_and_permissions -v`。临时 SQLite 与固定合成 PNG 经 Vite 代理完成上传、真实 CPU OCR、同版原图区域预览、两条风险、受控模型响应、法务确认及报告；覆盖提前确认/预览拒绝、越权及错误版本。定向 1/1、F1–F3 本机 HTTP 回归 3/3 通过。浏览器双向高亮与真实点击尚未验证。

A1–A4 F2 文本 PDF 本机 HTTP 联调（已由用户验收）：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_local_http_acceptance.LocalHttpAcceptanceTests.test_f2_pdf_live_proxy_pages_review_and_permissions -v`，使用临时 SQLite 与固定合成 PDF，经 Vite 代理核对上传、解析、F2 本版第 2/3 页风险锚点、原 PDF 预览、法务确认、报告及权限拒绝；受控模型响应不联网。定向 1/1、包含 F1 的本机 HTTP 回归 2/2 通过。浏览器双向高亮与真实点击尚未验证。

A8 Windows 本机单命令启动（已由用户验收）：安装已有 `.venv` 与 `frontend/node_modules` 后，在仓库根目录运行 `.\.venv\Scripts\python.exe scripts/start_local.py`，打开 <http://127.0.0.1:5173/>；按 `Ctrl+C` 结束两个本次启动的服务。默认使用 `storage/contract_approval.sqlite3` 和 `storage/uploads`；要隔离验收数据，可附加 `--data-root D:\path\to\isolated-data`，并可用 `--backend-port`、`--frontend-port` 改端口。启动前会拒绝占用端口。此入口为查询模式，不启动解析、报告或模型等后台作业；新提交任务不会自动处理。独立冒烟：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_local_launcher -v`（2/2，成功启动/释放端口、API 代理 401 及占用端口拒绝）；浏览器实际点击尚未验证。

A8 本机 HTTP 联调入口：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_local_http_acceptance -v`。冒烟临时启动 Uvicorn 和 Vite，所有业务请求经 Vite `/api` 代理，使用临时 SQLite、合成 F1/F2/F3/F4/F5 空文与受控模型响应（F4/F5 无须模型响应）；覆盖登录、上传、机器处理、法务复核/确认、报告、模拟回写、管理员记录、F5 受阻换件和权限拒绝，完成后关闭服务并清理数据。需已有 `frontend/node_modules`，不调用付费模型。这是 HTTP 联调证据，浏览器交互与视觉尚未点验。

A8 处理记录验收：按下方 FE1 启动命令打开前端，用管理员账号进入已完成处理的合成 F1 任务，在“任务处理记录”核对解析、规则、模型和两种报告的状态、文档版本及审查版本；切换全部/指定文档版本，有超过 20 条时核对翻页。业务与法务任务详情不应出现该区，直接请求接口应返回 403。隔离冒烟：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_processing_records -q`（1/1，通过真实 TestClient、临时 SQLite 和受控模型响应，不联网）；前端请求冒烟 `node --experimental-strip-types --test frontend/tests/processing.test.ts`（3/3），全量前端 34/34，构建通过。实际浏览器点击及本机端到端仍待核对。

A8 操作记录页面验收记录（已由用户验收）：按下方 FE1 启动命令打开前端，用管理员账号进入已存在的合成任务，核对操作记录中的动作、文档版本、时间和操作人；切换“全部版本”与指定版本，若记录超过 20 条则核对翻页。用业务、法务账号核对任务详情没有该区域；直接调用接口仍由后端返回 403。交付时页面独立冒烟 3/3、前端全量 31/31、构建及后端 F1 接口冒烟 1/1 通过；实际浏览器点击和本机端到端仍待核对。

A8 操作记录与管理员查询冒烟：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_backend_integration.BackendIntegrationTests.test_f1_operation_record_smoke -q`。测试使用临时数据库、合成 F1 和受控模型响应，核对成功链路、越权/冲突拒绝、重复请求、查询权限、版本过滤和分页。

FE8 验收：按下方 FE1 命令启动前后端，用管理员账号打开一个 `blocked/admin_retry` 的合成任务，核对故障代码、当前阶段尝试次数和文档版本；点击一次“重试文档”后刷新，核对状态或新的受阻原因。若是模拟待办附件超时任务，还应看到累计附件尝试历史。打开 `blocked/replace_attachment` 或 `blocked/budget_decision` 任务时，页面应显示对应指引且没有重试按钮；业务和法务账号没有管理员恢复区。若无合成受阻任务，需先使用现有 F5/F6 测试样例准备隔离测试任务，不能手改业务库状态凑验收。前端独立冒烟 5/5、全量 28/28、构建及相关后端 12/12 通过；实际浏览器点击与本机端到端仍待核对。

FE7 验收记录（已由用户验收）：按下方 FE1 启动命令打开 <http://127.0.0.1:5173/>，用法务账号进入已有确认版本的合成任务，在“模拟回写”区核对文档/审查版本与目标，执行一次本地模拟回写。先见“写入中”，后台作业完成后刷新或等待轮询，成功须显示同版评论 ID 和正文；如失败，仅法务可对同版目标重试。用任务所属业务账号核对仅能查看确认评论与状态，用管理员账号核对只有当前确认版本的状态/故障而无评论正文和提交按钮；未确认任务无回写入口，旧确认结果应标明“历史确认版本”。普通查询模式不运行后台回写作业，若保持“写入中”，须在授权的测试环境运行已有作业或使用已有成功样例，不能手改状态凑验收。交付时前端独立冒烟 4/4、全量 23/23、构建及后端回写 4/4 通过；实际浏览器点击与本机端到端仍未记录。

FE6 验收记录（已由用户验收）：按下方 FE1 启动命令打开 <http://127.0.0.1:5173/>，分别用法务与任务所属业务账号进入已有确认版本的合成任务。核对报告版本标签、Markdown/PDF 分开显示状态；就绪时预览及下载，生成中无文件按钮，失败时仅法务有重试按钮。换版或新草稿后，旧报告须标明“历史确认版本”；管理员没有报告入口，其他业务账号不能访问该任务。普通查询模式不运行后台报告作业，若现有任务报告仍为生成中，须在授权的测试环境运行已有报告作业或使用已有就绪样例，不能手改报告状态凑验收。交付时前端 19/19、构建及后端报告 4/4 通过；实际浏览器点击与本机端到端仍未记录。

FE5 验收记录（已由用户验收）：按下方 FE1 启动命令打开 <http://127.0.0.1:5173/>，用法务测试账号进入已有机器完成且同版模型结果的合成任务。修改一项风险和批注并保存，核对审查版本增加、状态仍为草稿；填写正式结论并确认，核对法务状态为已确认。重新编辑已确认内容应另存新草稿。修改后返回大盘或刷新应提示丢弃；业务和管理员账号没有复核入口。若没有满足前置条件的任务，当前查询模式不会自动运行解析/模型，请使用已有合成任务，不能手改真实任务状态凑验收。交付时前端测试 16/16、构建及后端审查测试 5/5 通过；实际浏览器点击与端到端确认仍未记录。

FE4 验收记录（已由用户验收）：按下方 FE1 启动命令打开 <http://127.0.0.1:5173/>，用法务测试账号进入已完成解析的 F1–F3 任务，检查页码与原文、三类高亮双向选择、无定位提示和规则/模型建议区分；再用业务或管理员账号确认看不到法务草稿工作台。当时前端逻辑冒烟 13/13、构建通过；`tests.test_frontend_workbench` 用隔离合成 F1/F2 跑过真实 API、PDF.js Node canvas 与区域核验。浏览器双向点击及 F3 预览区域脚本核验仍未记录。

业务账号从“合同接入”上传合成附件或导入模拟待办；在本人任务详情中，只有“需更换附件”的受阻任务或“机器完成且法务确认”的任务显示“上传新版附件”。

FE3 验收步骤（已由用户验收）：打开 <http://127.0.0.1:5173/> → 使用业务账号进入符合条件的本人任务 → 选择 `samples/f4-revised-software-purchase.docx` → 勾选新版本确认 → 上传。预期同一任务文档版本加 1，三组状态重置为等待处理/待复核/未回写，旧确认不冒充新版。法务/管理员不显示换版表单；过期版本提交应提示返回刷新。

前端冒烟 7/7、后端任务回归 13/13、TypeScript/Vite 构建通过。实际浏览器点击仍待手动验证；如果没有符合条件的任务，暂不能完成页面换版验收，请反馈“没有可换版任务”。当前 8010 查询模式不运行后台解析，新提交停在等待处理属预期；不应为验收手改业务库状态。启动命令沿用下方 FE1。以下较早进度按历史保留。

## 当前进度（2026-09-25）

**最新：UI v0.5 已验收；FE1 正式登录与任务大盘待用户验收。** 已对接会话/任务 API，支持账号角色、全部可见任务统计、筛选与分页、任务版本及受阻指引。Node 逻辑冒烟 4/4、隔离库接口及相关权限/版本回归 13/13 通过；依赖已获准安装，TypeScript/Vite 构建通过，实际首页及脚本 HTTP 200、代理未登录查询/错误登录均返回 JSON 401。浏览器自动检查因审批服务 429 未执行，页面视觉与真实点击待手动验证。本单元不包含附件接入、工作台、报告或恢复操作页面。

FE1 本机启动方式（两个 PowerShell 窗口，均从仓库根目录开始；已有对应服务时无需重复启动）：

```powershell
# 窗口 1：FE1 查询验收模式，不启动解析/模型后台作业
.\.venv\Scripts\python.exe -m uvicorn backend.main:create_app --factory --host 127.0.0.1 --port 8010

# 窗口 2：前端由 /api 代理到上述本机后端
npm.cmd --prefix frontend run dev
```

正式页面地址为 <http://127.0.0.1:5173/>，使用之前创建的本地测试账号登录，身份由后端返回。设计预览的 `8765` 地址仍是合成静态页面，不是正式客户端。查询模式读取已有任务，不主动推进解析；没有任务时应显示空态，不补造演示数据。停止对应服务按 `Ctrl+C`。

FE1 验收：错误密码应有提示；业务只见本人任务，法务可看可见任务，管理员不显示正式风险/合同正文；筛选不改变顶部总量；查看任务进度保留三个状态及版本；退出或刷新后返回登录。请手动核对后反馈通过或具体问题。详见 [前端契约与验收](docs/FRONTEND_DESIGN.md)。

安装记录：在 `frontend/` 执行 `npm.cmd install --cache ../storage/npm-cache --no-audit --no-fund`，新增 21 个包并生成 `package-lock.json`；未全局安装。npm 提示 esbuild 安装脚本尚未批准，当前构建已成功，无需额外开放脚本。后端使用 `8010`，因为本机 `8000` 已被 DailyNews 占用；不停止该服务。

独立检查：`npm.cmd --prefix frontend test`；安装后构建：`npm.cmd --prefix frontend run build`；接口回归：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_frontend_dashboard tests.test_auth tests.test_reviews -q`。下方 UI 待确认和“正式客户端未开始”均为历史记录。

**最新：F6 待办恢复已验收，前端开发已获授权；UI v0.5 交互设计预览待确认。** 按既有 Pencil 样例提供三角色大盘、接入、双栏复核、报告和恢复页面。当前为合成设计预览，未接 API；设计通过后逐页面实现正式客户端，同时收口后端 A8，最后进行本机前后端总体验收。下方此前“前端须另获审批”等进度已由 D-27 更新。

预览启动（只绑定本机，不启动后端、不调用模型）：

```powershell
.\.venv\Scripts\python.exe -m http.server 8765 --bind 127.0.0.1 --directory design/ui-preview
```

打开 <http://127.0.0.1:8765/>。若已有本预览服务在运行，直接打开即可。选择预览身份，无需真实账号；页面顶部明确“未连接后端”，所有操作仅演示反馈。三角色操作顺序见 [UI 设计验收步骤](docs/FRONTEND_DESIGN.md)。停止服务按 `Ctrl+C`。

独立冒烟：`node design/ui-preview/smoke.cjs`，预期输出 `PASS`。Node 逻辑检查和 HTTP 200 已验证；浏览器自动打开因审批服务 429 未执行，实际视觉/点击待手动核对，不作为整体业务证据。

**最新增量：F3 标题修复已验收；F6 待办超时恢复已补齐，待本功能验收。** 超时后保留受阻任务，仅管理员可按原文档版本重试；支持历史查询、并发保护和过期中断恢复。附件尚未取得时不生成正文或风险。以下“F6 未接入”是此前集成发现，本轮已修复；后端阶段仍需收口验收，前端须另获审批。

本功能验收（无须启动服务、不调用外部模型、仅临时数据库）：

验证记录：F6 与接口冒烟 20/20 PASS；全量首轮 146 项中 145 通过，1 项旧测试因重新生成 DOCX 的 ZIP 时间戳造成哈希不稳定。固定实际输入并同步新增审计事件断言后，任务/F6 定向回归 17/17 PASS；未重复全量。详情见实施状态。

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_pending_imports -v
```

预期 4 项 `ok`、最终 `OK`。测试实际调用导入和管理员重试接口：首次超时返回 201 + blocked/ATTACHMENT_FETCH_TIMEOUT，尝试 1；重试后保持 v1，附件尝试 2，并进入真实 DOCX 解析、命中两条演示风险；普通业务/法务重试 403。其余用例验证重开数据库、中断租约、并发/迟到请求及落盘事务失败。正常运行的导入仍使用成功合成附件，故障仅在测试中注入。

API：管理员 `POST /api/v1/tasks/{id}/retry`，JSON `{"document_version":1}`；管理员 `GET /api/v1/tasks/{id}/attachment-attempts` 查看历史。附件缺失时任务 submission 的 filename/format/sha256 为 null；201 不代表附件处理成功。

**已验收范围：法务编辑与确认、同版 Markdown/PDF 报告、模拟审批评论回写及 F3 标题修复。** F1–F5 主链已验证，F6 待办恢复现已补齐待验收；后端阶段仍待 A8 操作记录统一核对与阶段验收。完整结果见 [后端集成验收记录](docs/BACKEND_INTEGRATION_ACCEPTANCE.md)。阶段验收通过后仍须另行取得前端开发审批；下方旧进度按时间保留。

本轮独立复验（临时数据库、合成数据，使用已安装 LibreOffice 与项目 CPU OCR，模型受控、不产生外部调用费用）：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_metadata_extractor tests.test_backend_integration tests.test_writeback tests.test_reports -q
```

前次集成结果 `Ran 18 tests`、`OK`。覆盖 F1 上传至同版报告/评论、F2/F3 解析与定位、F4 无演示规则误报、F5 受阻换件，以及报告/回写恢复。F3 标题保留 OCR 原文和锚点；这 18 项不包含 F6 待办超时专项，不表示整个后端阶段通过。

模拟回写独立冒烟（临时 SQLite、合成 F1/F6、模拟模型和固定故障源，不请求外部服务）：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_writeback -v
```

预期 4 项 OK：首次失败/重试/去重与角色权限；双连接并发/重启/新旧审查隔离；事务回滚及过期处理器防覆盖；FastAPI 自动处理及新附件隔离。

模拟回写手动验收：

1. 重启现有后端，在 `/docs` 以法务账号登录并 Authorize。选取已确认任务，记下 task_id 和 review_version；未确认版本会返回 409。
2. GET `/api/v1/mock-writeback-targets`，当前目标为 `demo-f1-001`。POST `/api/v1/tasks/{task_id}/mock-writeback`，填写 `{"review_version":1,"mock_approval_id":"demo-f1-001"}`（换成实际版本）。首次请求返回 writing，不代表已经保存成功。
3. GET 同一路径，加 `?review_version=1`，等待 success；核对 comment_id、模拟标识、确认版本、风险总评、最终建议及法务批注。再次 POST 相同请求，comment_id 不变，attempts 不增加；重启后读取结果不变。
4. 若结果 failed，再次 POST 原请求重试，旧失败尝试保留；若进程处理中断，原两分钟租约到期后自动恢复。正常服务不故意制造失败；F6 首次失败由上述独立冒烟的合成故障源验证。
5. 本人业务账号可读已确认版本最终评论，无内部故障/尝试；其他业务读取 404，管理员仅见状态/故障而无 markdown；非法律角色 POST 403。首次绑定后改目标返回 409，未绑定时选择不存在的目标为 404。新草稿/新附件当前回写仍为 not_written，旧评论仅在对应历史版本查看。

以上仅本地模拟保存，不向真实审批平台发送评论。

报告独立冒烟（临时库、合成合同、模拟模型；真实本机 LibreOffice，无付费调用）：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_reports -v
```

预期 4 项 OK：真实中文两格式、历史/权限/产物校验，独立失败重试及重启租约恢复，确认登记失败整体回滚，过期处理器拒绝覆盖。

报告手动验收：

1. 重启现有后端，在 `/docs` 使用法务账号登录；选择已 completed 的合成任务，按下方法务流程保存并确认，记下响应的 `review_version`。旧确认版本在启动时自动补登记报告，无需重新确认。
2. GET `/api/v1/tasks/{task_id}/reports/status?review_version=1`（换成实际版本）；两项由 pending 变为 ready。PDF 缺依赖/转换失败只影响自身格式。
3. 使用相同 Bearer 和版本 GET `/api/v1/tasks/{task_id}/reports/markdown?review_version=1`、`/reports/pdf?review_version=1`；核对标题、结论、最终建议、批注、确认人和版本号。浏览器地址栏不带 Bearer，请从 `/docs` 或带 Authorization 的客户端获取文件。
4. 新建草稿后重读旧报告，内容须不变；新草稿版本取报告为 409。本人业务可读旧确认报告，其他业务 404、管理员 403、未登录 401。
5. 若某格式 failed，法务 POST `/api/v1/tasks/{task_id}/reports/pdf/retry`，JSON 为 `{"review_version":1}`；pending/ready 重试为 409。重启后已领取任务在原两分钟租约到期后恢复，不覆盖 ready 文件。

本轮合成 PDF 可视检查样例：`storage/report-check/synthetic-report.pdf`（测试产物）。报告中的“模拟回写”仅为标识，本单元不执行回写。

本轮报告交付证据：全量 **134/134 PASS（434.544 秒）**；最终报告专项 **4/4 PASS（47.396 秒）**。一页中文与三页长批注报告已逐页检查；后台自动调度使用模拟 renderer 验证，真实 PDF 转换另由专项覆盖。模型均模拟，无付费调用；真实复杂合同和目标机仍未验证。下方 130/130 为上轮法务功能记录。

本轮全量回归 130/130 通过（271.407 秒）；补强有效模型建议采纳断言后专项再次 5/5 通过（19.280 秒）。本轮没有付费模型调用。

独立验收（临时库、合成 F1/F2/F4、模拟模型，不用密钥、不产生付费调用）：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_reviews -v
```

预期 5 项全部 OK：编辑/确认与角色隔离、两连接并发冲突及无风险结论、证据变化拒绝、失败事务回滚/机器未完成拒绝、确认后 PDF 预览权限。新草稿和新文档都不能让业务看到未确认内容，旧确认版本可重读。

手动 API 验收：重启服务后打开 `/docs`，使用法务账号并选机器状态 completed 的合成任务；先 GET `/risks/snapshot` 和 `/model-result` 核对规则与建议，再 PUT `/review`（参数示例见下），最后 POST `/confirm`。不要为本次验收重新触发付费模型；没有 completed 任务时使用上述独立测试即可。

```json
{
  "document_version": 1,
  "base_review_version": null,
  "risks": [
    {"rule_id": "DEMO-IP-01", "retained": true, "risk_level": "high", "suggestion_source": "manual", "final_suggestion": "演示：协商满足项目目的的使用权"},
    {"rule_id": "DEMO-PAY-01", "retained": true, "risk_level": "high", "suggestion_source": "rule"}
  ],
  "annotation": "演示批注，待专业法务核定"
}
```

以上仅适用于两风险、文档版本 1 且尚未建立审查版本的 F1；已有审查时先 GET `/review`，用返回 review_version 作为 base_review_version。确认提交 `{"document_version":1,"review_version":1,"conclusion":"演示：整改后复核"}`，版本以实际保存响应为准。切换本人业务账号 GET `/review` 应可见正式结果；法务再次 PUT 新草稿后，业务仍得到旧确认版本，任务摘要 risk_level=null；旧基础版本再提交应 409。管理员编辑/确认/原文请求应 403。界面和报告不属于本项验收。

最新：图片 OCR 业务接入已验收；扫描 PDF 接入已实现，待用户验收。全量 124/124 通过，随后同页图片检测及文本 PDF 定向 4/4 通过。包含图片或无文本页的 PDF 会整份 OCR，低分/空页受阻换件，暂时故障可管理员重试。法务通过同版 `/document` 获取正文/页码/区域及 OCR 提示，通过 `/document/preview` 查看原 PDF；PDF 不使用图片/DOCX 的 preview-map。没有新增安装或付费调用。

扫描 PDF 验收文件位于 `storage/verification/scanned-pdf/f3-clear-scan.pdf` 和 `f5-blurred-scan.pdf`（由已有合成 PNG 生成，无文本层）。重启现有服务后，业务账号在 `/docs` 上传清晰文件；预期 reviewing。法务读取 document 应为 extraction_method=ocr、1 页、12 行，风险 snapshot 为 2 条，preview 返回同版原 PDF。上传模糊文件预期 blocked/OCR_UNREADABLE/replace_attachment，换传清晰件可恢复。独立复验：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_ocr.OcrTests.test_scanned_pdf_real_and_recovery tests.test_ocr.OcrTests.test_mixed_pdf_all_pages_and_encryption -v`。同页文本与扫描图片混排、复杂版式、旋转裁剪及真实多页尚未验证。

DOCX 固定预览与定位、OCR 隔离基础已获用户验收。图片业务接入为 `PENDING_ACCEPTANCE`。D-24 已确定低置信度件整份受阻并要求换件，不保留部分草稿；初始单行阈值 0.9 未经样本标定，不能保证不漏字。本轮定向 2/2 测试通过：低分受阻、禁止直接重试、换版恢复且没有部分正文/规则或模型预算记录；本轮未启动正式服务或改正式业务数据。

复验：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_ocr -v`。临时数据库和真实 CPU OCR 验证：F3 清晰 PNG → reviewing、同版正文/字段/两条规则及固定 PDF；F5 模糊件 → blocked/OCR_UNREADABLE/replace_attachment，换清晰附件后版本递增并恢复。法务读取 `/api/v1/tasks/{task_id}/document`、`/document/preview`、`/document/preview-map`、`/risks/snapshot`。reviewing 不代表模型审查完成。暂时 OCR 故障由管理员调用 `POST /api/v1/tasks/{task_id}/retry`，JSON 含 document_version；永久模糊件不允许盲目重试。测试预算记录为 0。

上轮全量回归 121/121 通过（198.041 秒）。PNG/JPEG/TIFF 路径已实现，真实业务链证据仅 F3/F5 PNG，多页 TIFF 为模拟识别测试。扫描 PDF、复杂版式、前端与目标机未验证。OCR 可能漏字，法务须对照原图；单行高分不保证全文完整。下方独立基础脚本不验证 blocked 的描述仍适用于该脚本；业务状态已由新测试验证。

用户已按 D-23 授权安装。运行时位于 `.tools/ocr/venv`：Python 3.12.13、PaddleOCR 3.7.0、PaddlePaddle 3.3.1、PaddleX 3.7.2；模型和缓存位于 `storage/ocr`，均被 Git 忽略。主 `.venv`、全局 PATH 和已有 Conda 环境未修改。Windows oneDNN 推理报错已通过 `enable_mkldnn=False` 关闭可选加速解决，使用普通 CPU，不调用付费模型。

在项目根目录复验：`.\.tools\ocr\venv\Scripts\python.exe -X utf8 scripts/verify_ocr.py`。预期退出码 0；F3 识别 12 行，11 行逐字一致，标题存在括号宽度与空格差异；仅在测试比较时执行 NFKC/去空白，原始 OCR 结果不改写。12 个框与独立标注的最小交并比为 0.764；F5 严重模糊图识别 0 行。本机复验耗时 24.344 秒，不代表目标机性能。

查看 `storage/verification/ocr/verification-summary.json` 和 `f3-location-overlay.png`，红框应对应原图 12 行；同目录保留两个原始识别 JSON。验证脚本含正文、坐标范围/重叠及模糊样例断言。安装复现入口为 `scripts/install_ocr.ps1`，通过 `-UvExecutable` 指定本机 uv 路径，依赖固定于 `scripts/requirements-ocr-lock.txt`；重新安装/下载仍须依照本地授权范围执行。F5 的 0 行结果仅证明样例不可识别，不代表业务 `blocked` 状态已实现。

## DOCX 固定预览与定位（2026-09-25，已验收）

LibreOffice 已安装在 `D:\AICoding\Tools\LibreOffice\program\soffice.exe`，版本 26.8.0.3；用户反馈安装退出码 0，已实际完成 F1/F4 转换。程序通过 Windows App Paths 自动发现，无须改 PATH 或再次安装。安装日志：`storage/installers/libreoffice-install-20260925-121055.log`。

后台对已解析的当前 DOCX 生成一次固定 PDF，独立保存同版定位映射；不改写既有解析、规则或模型快照。F1/F4 真实转换各 1 页、12 个段落全部可定位，中文排版已目视核查。复杂排版、字段/任意子串精确框仍未验证；不可靠区域返回 `locatable=false`。

验收步骤：

1. 打开 [F1 固定 PDF](storage/verification/docx-preview-26.8.0.3/f1-software-purchase.pdf) 和 [F4 固定 PDF](storage/verification/docx-preview-26.8.0.3/f4-revised-software-purchase.pdf)，确认中文清晰、完整且条款与 DOCX 一致。
2. 运行下方独立测试，预期 4 项通过且无 skipped；其中一项真实调用本机 LibreOffice，另外三项模拟转换产物验证存储、权限和失败处理。均使用临时 SQLite，不使用正式任务或付费模型。
3. 接口演示可重启现有 `backend.main:app` 服务，在 `/docs` 使用法务账号登录授权。业务账号上传 F1/F4 后，法务读取 `GET /api/v1/tasks/{task_id}/document/preview`（PDF）及 `/document/preview-map`（页码/归一化区域）。刚上传时 409 为未准备完成，等待转换后应返回 200；两个接口均支持 `document_version=1`。
4. `/document.preview_available=true` 表示预览已登记就绪；DOCX 原始 page_count 和锚点仍保持原样。页面应使用独立 preview-map 的页数和坐标，按同版 start/end 对应风险，不混用不同版本。本人业务/管理员读取 403、其他业务账号 404、未登录 401。

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_docx_preview_api -v
```

预览失败独立返回 409，不改变机器审查状态，不自动重试。缺依赖、转换超时、过期转换、证据损坏均有固定错误码；遇到失败请保留错误码反馈，当前没有预览重试 API。已有失败记录不会因重启被覆盖。目标机验证、OCR 和前端 PDF 高亮界面尚未完成。

以下安装及基础组件描述为历史记录，以本节最新结果为准；不要重复安装。

## LibreOffice 安装推进历史（2026-09-25）

用户已授权安装。本机已下载并验证官方 LibreOffice 26.8.0 安装包（MSI 产品版本 26.8.0.3）：大小和官方 SHA256 一致、The Document Foundation 数字签名有效。安装包位于 `storage/installers/LibreOffice_26.8.0_Win_x86-64.msi`，被 Git 忽略。自动执行安装因审批服务 429 未能启动，尚未安装，不需重复授权。

请打开**管理员 PowerShell**运行以下本地脚本，等待输出安装退出码、可执行路径和版本：

```powershell
& 'D:\AICoding\List\ContractApproval\scripts\install_libreoffice.ps1'
```

脚本再次验证安装包摘要和签名，安装至 `D:\AICoding\Tools\LibreOffice`，关闭 Microsoft Office 格式关联和桌面快捷方式，不改 PATH、不自动重启；Windows Installer 可能在 C 盘保留必要系统缓存。`InstallerExitCode=0` 表示安装成功，3010 表示安装器要求重启但脚本不会重启。若失败，请反馈输出，不盲目重试。脚本目前只通过语法检查，真实安装和转换待用户执行后继续验证。

官方来源：https://www.libreoffice.org/download/download-libreoffice/ ，摘要依据：https://download.documentfoundation.org/libreoffice/stable/26.8.0/win/x86_64/LibreOffice_26.8.0_Win_x86-64.msi.mirrorlist 。

## DOCX 固定预览基础组件历史（当时受依赖阻塞，现已解除）

模型作业已验收，现进入 DOCX 预览与定位。已新增 `backend/docx_preview.py` 独立转换/段落映射组件，尚未接入数据库、后台或预览 API。本机未发现 LibreOffice，真实预检返回 `DOCX_PREVIEW_DEPENDENCY_MISSING`；遵守当前暂不安装依赖的约束，未安装软件。若另有便携安装可提供 `soffice.exe` 的完整路径供核对。

可复验组件逻辑（不需 LibreOffice，不联网、不调用模型）：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_docx_preview tests.test_docx_parser tests.test_pdf_parser -q
```

预期 10 项通过。转换进程使用 mock，映射采用固定 F1 正文和既有 F2 PDF；这不表示 F1 已被真实转换。仅全文顺序一致且完整行框可核对的段落返回页码/区域，其他情况返回不可定位原因；字段级精确框未实施。真实 F1/F4 转换、视觉核查、不可覆盖的预览存储和 API 接入仍待完成，暂不进行完整功能验收。

## 当前功能：模型作业与建议保存（2026-09-25）

模型作业与建议保存已获用户验收。已接入 SQLite 持久模型作业、重启后超时恢复、同版建议保存和法务读取接口；离线验证通过。用户已手动执行真实 F1 命令并反馈 `{"state": "completed", "code": null}`，随后确认验收通过。真实成功依据用户本机执行反馈；供应商实际费用仍以账单为准，本次一次调用授权已使用，不需再次执行。

服务启动后，无规则命中的版本可自动完成机器阶段；有命中的普通任务等待付费授权，不自动消费额度。机器 completed 仍为待法务核定草稿。法务登录后可用 `GET /api/v1/tasks/{task_id}/model-result`，可带 `?document_version=1` 查看历史版本；未保存返回 409，业务人员和管理员不可读取建议。接口不发起模型调用。

离线复验（不读取真实密钥，不调用模型）：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_model_jobs -v
```

预期 9 项通过。覆盖免费完成、持久化/重启、法务权限、换版、损坏证据、预算拒绝、并发防重复、超时未知占额和事务回滚。全后端回归另已通过 107 项，随后补充的 3 项测试已通过独立复验。

以下命令保留供溯源：本次真实验证已由用户执行并验收，不需再次运行；新增付费调用须另行授权。

```powershell
Set-Location D:\AICoding\List\ContractApproval
.\.venv\Scripts\python.exe -X utf8 -m backend.model_jobs ce6d479e179d410f85756ac2b22bcf8f 1
```

该入口只接受固定合成 F1，发送前持久预留 0.10 元并记录唯一授权，输出限额 4096 token。成功输出 `{"state": "completed", "code": null}`；若 completed 但 code 为 MODEL_RESPONSE_INVALID，表示需法务补充、不能算建议有效通过。blocked 表示受阻，保留费用占额，不自动重试。请反馈终端 state/code；不要发送密钥。重复运行不会再次发送已经登记的授权，但遇到任何失败请先停下核查，不手工修改账本。实际费用仍以供应商账单为准；只有法务读取接口会展示建议正文。

以下保留此前功能的使用说明与历史证据；当前状态以上述记录及 `docs/IMPLEMENTATION_STATUS.md` 为准。

2026-09-25 当前功能：模型费用预检与私有 HTTP 边界已完成离线验证，待用户验收。依据 D-21，使用用户提供的官方 V4 tokenizer 作本地模板估算，预计超过 0.10 元拒绝，否则账本固定预留 0.10 元；输出限额 4096 token，未知用量保留预留，已知用量按冻结单价核算。0.10 元不是供应商账单绝对上限。F1 本地输入 476 token、估算 0.03372 元；相关测试 6/6 通过。HTTP 使用模拟响应，真实 API/账号尚未验证；没有生产发送入口，不自动读密钥或消费额度。此前人工资料请求已完成，不需重复提供截图或链接。

本机复验：在项目根目录 PowerShell 执行：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_model_transport tests.test_model_advice tests.test_model_budget tests.test_model_config -q
```

预期 `Ran 6 tests` / `OK`；测试使用临时数据库，不调用模型。`prepare_request` 是内部组件，不是 Swagger 接口。模型持久作业与建议保存为验收后的下一功能。

本地资源：`storage/model/deepseek_v4_tokenizer.zip` 已从用户提供文件复制并被 Git 忽略。源地址为 https://cdn.deepseek.com/api-docs/deepseek_v4_tokenizer.zip ，固定 SHA256 `e7310d1dafe0a86d8a5629fe78a7c763760f651db9b8682718a1781dcd6fe495`；缺失或不一致时安全拒绝，不自动下载。新工作区需另行准备同一资源；本机已具备 tokenizers 0.23.2/Jinja2 3.1.6，版本已登记到 requirements，本轮未安装依赖。本地模板与线上包装可能不同，见 [决策 D-21](docs/DECISIONS.md) 和 [验证记录](docs/IMPLEMENTATION_STATUS.md)。

2026-09-24 当前安排：用户已确认本次演示内容复核完成；后续先补齐后端，再按 [Pencil 样例](pencil-new.pen) 实施前端并逐页对接真实 API，继续逐功能验收。模型费用预检与 HTTP 传输组件的最新状态见上方 2026-09-25 记录；完整顺序见 [执行清单](docs/BACKEND_WORK_BLOCKS.md)。没有新增可用接口或执行付费调用；专业法务核定与目标机验证仍未完成。下方关于前端尚未授权的描述为历史状态。

模型传输离线冒烟（无真实密钥、无网络、临时数据库）：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_model_transport -v
```

预期 3 项通过。检查 F1 请求缺少输入上界时拒绝、F4 无命中跳过、单次预计费用恰好 0.10 元允许/超限拒绝、项目预算不足、未知用量占额，以及 HTTP 成功、超时、TLS 错误、重定向、限流、无效和超大响应。输入 token 数为合成测试值，不是真实 tokenizer 结果；价格沿用历史快照。`backend/model_transport.py` 不读取本地密钥，不接入服务或自动作业，不提供真实调用命令。真实调用仍须完成现价和输入上界核实、持久调度及预算接线；不能把通过此测试当作账号/API 已可用。

需求基线：用户于 2026-09-24 正式验收 [MVP_SPEC.md](docs/MVP_SPEC.md)。此确认不代表后端全部完成、其他设计文档通过、前端开发授权或法务签批；下方关于需求基线待验收的描述为历史记录。

本地 DeepSeek 密钥配置（2026-09-24）：编辑 `secrets/deepseek.ini`，在 `api_key =` 后填入密钥，不加引号，保存为 UTF-8。文件已由 `.gitignore` 的 `secrets/` 规则忽略，且未被 Git 跟踪；普通提交/推送不会包含它，不要强制添加该文件。代码及说明可以正常提交，不包含真实密钥。

在项目根目录运行 `.\.venv\Scripts\python.exe -X utf8 -m backend.model_config`，填写成功后输出 `DeepSeek key loaded locally; no API call made.`；这仅验证本地读取和基本格式，不验证密钥有效性或余额。加载器不设置全局环境变量，不打印密钥；后续模型传输代码可调用 `load_api_key()`，当前尚未接入真实请求。独立离线测试：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_model_config -v`（1/1 通过）。

最新确认：模型请求与返回校验已获用户验收，演示模型选定 `deepseek-flash`；用户仅授权一次合成 F1 真实调用并要求节约额度。实施时该次调用预计费用上限 0.10 元、计入既有 50 元预算，超限不发送，失败不自动追加调用；实际费用仍以供应商账单为准。本轮只准备本地配置，没有消费额度。下方关于模型选型待答复、尚无单次真实调用授权的描述为历史记录。

最新功能（2026-09-24，待验收）：`backend/model_advice.py` 实现同版持久规则证据的模型请求构造与返回校验。输入仅含必要规则证据；F4 无启用规则命中不构造请求。返回校验版本、摘要、规则与建议结构；无效内容标记需法务补充，token 用量独立保留。结构通过不代表建议语义或法律正确。

独立验收：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_model_advice -v`。临时库使用实际解析的合成 F1/F2/F4，模型响应及 token 数为合成，无网络调用。模型、预算、自动规则及草稿 API 专项 4/4 通过（7.707 秒）。预算阻塞恢复动作修正为既有契约 `budget_decision` 并通过断言。

预算账本已获本轮用户验收；官方模型和人民币价格已核对，见后端设计。Flash/Pro 选型待用户答复，必须显式指定模型。尚无 HTTP 传输、模型作业、建议持久化或模型 API；100 KB 请求限制不是输入 token 上界。无付费调用，机器仍 reviewing。以下旧段落的预算待验收及官方价格未核查为历史记录。

最新功能（2026-09-24，待验收）：新增内部模型预算账本 `TaskStore.model_budget`，支持全项目固定 50 元预留、并发拦截、重复调用标识去重、已知用量结算及未知用量保留。自动规则保存与管理员暂时故障重试已获用户验收；下方旧段落的待验收状态为历史记录。

本项验收入口：在项目根目录执行 `.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_model_budget -v`。使用临时数据库、F1 合成附件和明确标注的合成价格，不修改演示数据，不访问网络。预期：两个并发 30 元预留仅一个成功；另一任务为 `blocked/BUDGET_LIMIT`；未知用量重启后仍占用 30 元；结算为 5 元后可再预留 45 元；同调用并发重复只创建一次；实际用量估算超出预留时如实记账并拦截后续预留。专项回归 `.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_model_budget tests.test_rule_processing tests.test_rule_snapshot_api -q`：3/3 通过。

内部调用顺序为 `reserve(...)` → 检查 `created` 和 `state` → 由未来模型作业负责调用 → `settle(...)`；`summary()` 读取限额、已估费用、未结预留和可用额度，均以整数微元人民币表示（1 元 = 1,000,000 微元）。`reserve` 保存模型、价格来源、输入上界、最大输出和每百万 token 的人民币微元单价快照；调用方须提供保守估算和汇率缓冲后的价格。`settle` 不传用量表示未知，不释放额度；已结算记录不允许用不同用量覆盖。账本不是供应商账单。

边界：本轮只完成可独立测试的预算组件，服务初始化建表，但自动规则流程不会创建模型预留；尚无模型作业、真实 token 估算、官方价格核查、人工调账/预算调整入口或预算 HTTP API。`BUDGET_LIMIT` 不会因其他预留结算而自动解除；后续预算调整仍需用户明确批准。真实付费调用必须另行授权。机器仍 `reviewing`，不能据此进入法务确认。

最新功能（待验收）：正式 `backend.main:app` 在 DOCX/文本 PDF 解析后自动保存同版规则草稿，无需再运行手动保存命令。业务上传 F1/F2 后，法务在 `/docs` 调用 `GET /api/v1/tasks/{task_id}/risks/snapshot` 可看到两项风险；F4 返回空风险列表。该读取功能已获用户验收。规则阶段成功仍为 `reviewing`、`review_version=null`，模型与完整机器审查未完成。

规则处理暂时故障返回任务 `blocked/RULE_PROCESSING_FAILED/admin_retry`，管理员可用 `POST /api/v1/tasks/{task_id}/retry`，JSON `{"document_version":1}`，排障后按原版重试；重复请求或错版返回 409，非管理员 403。证据无效或变化要求换传附件，不能盲目重试。重试接口目前仅覆盖规则阶段暂时故障，解析/模型重试尚未接入。独立冒烟：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_rule_processing -v`，临时库验证自动处理、故障注入、权限、事务回滚及重启恢复；不会修改演示库。下面的“手动保存”“读取待验收”等为之前阶段记录，当前范围以本段为准。

当前功能（待验收）：法务可读取已保存的 DOCX/PDF 规则草稿。先按下方手动保存命令生成草稿，再在本机 `/docs` 登录授权并调用 `GET /api/v1/tasks/{task_id}/risks/snapshot`；默认读取当前文档，可用 `document_version=1` 读取历史文档。结果为 `persisted=true`、`evaluation_mode=persisted_rule_draft_only`，带 `created_at`、`rule_version`、`evidence_sha256`；`rule_version_current=false` 表示保存时规则已不是当前规则，仍返回原草稿而不重新计算。`review_version` 仍为空。

验收检查：未保存返回 409/`RULE_SNAPSHOT_NOT_READY`；本人业务与管理员 403、其他业务 404、未登录 401；换版后不会返回旧草稿充当新版，指定旧版仍可读；损坏快照或变化的来源证据拒绝。现有 `/risks` 保持即时评估且 `persisted=false`。独立验证：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_rule_snapshot_api -v`，使用临时库与 F1/F2/F4 合成附件，换版前置确认状态由测试模拟。PDF 草稿保存已获本轮用户验收；下方阶段记录中的“待验收/未接入”以此处及实施状态最新记录为准。自动审查、法务确认、报告和回写仍未实现。

本项目计划在本地演示软件采购合同从提交、机器辅助审查到法务确认、报告导出和**模拟**审批评论回写的流程。演示使用合成合同；模拟回写不连接真实企业审批平台，也不代表正式法律审查结论。

## 当前能做什么

当前新增（待验收）：同版 PDF 规则草稿可手动保存。新上传 F2 并等待任务进入 `reviewing`、`/document` 的 `structured_extraction_status=available` 后，在项目根目录执行 `.\.venv\Scripts\python.exe -X utf8 -m backend.rule_snapshot TASK_ID 1`（替换任务 ID 和当前文档版本）。此命令会写入项目 `storage/` 演示库，仅用于合成数据；首次返回 `operation=created`、重复为 `already_exists`，含 `persisted=true` 及 F2 第 2/3 页风险证据。旧版仅正文 PDF、非当前版本、证据或规则版本变化会拒绝，不覆盖已有草稿。任务仍是 `reviewing`，`review_version=null`；`/risks` 仍即时评估，不读取此快照。独立验证命令：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_pdf_snapshot -v`，使用临时库，不修改演示任务。上一项 PDF 字段/条款与规则读取已获验收。

当前新增（待验收）：新上传的文本 PDF 已提取字段与显式标题条款。上传 F2 并等待 `reviewing` 后，法务在 `/document` 查看 `structured_extraction_status=available`、12 项字段、7 项条款及缺失的数据安全条款；`/risks` 返回两项机器规则草稿，知识产权证据在第 3 页、付款及验收证据在第 2 页。字段引文和页码可核对，但行内局部字段的精确框尚未验证，返回 `locatable=false` 与原因；条款/风险可使用本版逐行区域。旧版只保存正文的 PDF 不自动改写，仍返回结构化未完成及风险 409；需新建合成任务验证新流程。独立冒烟：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_pdf_job.PdfJobTests.test_pdf_processing_smoke -v`。机器状态仍为 `reviewing`，风险为即时规则草稿，不是法务结论。下段及样例介绍保留此前阶段记录，当前行为以本段为准。

最新增量（待验收）：正式 `backend.main:app` 已自动处理 DOCX 和文本 PDF。业务上传 `samples/f2-text-software-purchase.pdf` 后，任务自动进入 `reviewing`；法务调用 `/api/v1/tasks/{task_id}/document` 可读取同版全文、段落、3 页页码与归一化区域。`fields/clauses/missing_clause_types` 暂为空，`structured_extraction_status=not_implemented` 明示 PDF 结构化提取未接入，不能把空数组当作合同缺失；PDF `/risks` 返回 409/`RULE_EVIDENCE_NOT_READY`。上传 `samples/f5-encrypted.pdf` 后进入 `blocked/PDF_ENCRYPTED`，本人业务可换传可解析 PDF 恢复。无文本层 PDF 暂以 `PDF_EMPTY` 受阻，不进行 OCR。图片仍保持 `pending`。独立验证：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_pdf_job -v`（临时库和固定合成文件）。下文样例制作时的 `pending` 描述属于历史证据，正式服务当前行为以本段为准。

最新进度：两条固定商业规则组件、法务读取规则草稿 API、手动同版草稿持久化、F1/F4 固定 DOCX、F5 空白 DOCX 子场景、F2 文本 PDF 及 F3 清晰扫描件固定样例均已获用户验收；F5 严重模糊扫描件固定样例已验收；F5 加密 PDF 固定样例已验收；F6 待办附件超时固定故障源已验收；F6 回写故障与重复提交固定故障源已验收；F2 同版 PDF 原件受保护预览 API 已获用户验收。法务在 DOCX 解析完成后调用 `GET /api/v1/tasks/{task_id}/risks`，可选 `document_version=1`，取得同版规则命中、原文锚点与建议。此 API 保持已验收的即时计算语义：`evaluation_mode=on_demand_rules_only`、`persisted=false`、`review_version=null`，读取不改变任务的 `reviewing` 状态。本人业务/管理员 403、其他业务 404、未登录 401；未解析 409、文档或审查版本不存在 404。当前不支持任何 `review_version`，不能把规则草稿用于法务确认、报告或回写。可独立运行 `python -X utf8 -m unittest tests.test_smoke.BackendSmokeTests.test_rule_drafts_api_smoke -v`，使用临时库和合成 F1/F4 验证成功、权限、版本、无写入及坏证据拒绝。

本地三角色账号与会话、合成合同接入、任务列表及归属权限、修订附件换版、持久解析作业队列、DOCX 正文/条款/字段提取、手动单次解析持久化、服务内 DOCX 自动处理和法务读取同版解析结果 API 均已通过用户验收。两条固定商业演示规则组件与法务即时读取规则草稿 API 也已验收。当前可手动为已解析的当前 DOCX 版本保存一份固定规则草稿；自动审查任务处理尚未实现。`reviewing` 仅表示解析结果已提交，机器审查尚未完成。PDF/图片仍停留 `pending`；固定预览与页码定位、完整机器审查、报告、模拟回写和前端尚未实现。文档基线本身仍待验收。详细证据与验收状态以[实施状态](docs/IMPLEMENTATION_STATUS.md)为准。

代码审查指出的附件写入失败遗留文件、换版 409 响应缺少当前状态已修复、通过本机测试并获用户验收。

## 已实现功能的本机使用步骤

当前开发环境使用 Python 3.14.6；运行依赖列在 `requirements.txt`，新环境可先执行 `python -m pip install -r requirements.txt`，目标 Windows 电脑的安装尚未验证。

1. 在项目根目录分别执行 `python -m backend.cli create-user --username business1 --role business`、`python -m backend.cli create-user --username legal1 --role legal`、`python -m backend.cli create-user --username admin1 --role admin`。每条命令都会交互式要求输入至少 12 个字符的密码，不把密码写入命令或仓库。
2. 执行 `python -m uvicorn backend.main:app --host 127.0.0.1 --port 8765` 启动本地服务。账号、会话、任务与附件写入项目内被 `.gitignore` 忽略的 `storage/`。
3. 向 `POST http://127.0.0.1:8765/api/v1/sessions` 发送账号和密码，取得 `access_token`；后续请求在 `Authorization: Bearer <token>` 中携带它。`GET /api/v1/sessions/current` 返回当前账号与角色，`DELETE /api/v1/sessions/current` 撤销会话。令牌仅用于当前演示会话，刷新未来前端页面后须重新登录。
4. 可在浏览器打开 `http://127.0.0.1:8765/docs` 试用 API：用业务账号登录并复制返回的令牌，在页面右上角 `Authorize` 中填写令牌；调用 `POST /api/v1/tasks`，填入合成数据的 `department`、`applicant`，选择不超过 25 MiB 的 DOCX、PDF 或常见扫描图片。接口返回任务 ID、文档版本 `1` 与三组初始状态 `pending/pending/not_written`。`GET /api/v1/tasks` 查看本人列表，`GET /api/v1/tasks/{task_id}` 查看单个任务；其他业务账号查询此任务会得到 404。法务账号可看任务与提交信息，管理员只看状态和所属账号。DOCX 接入后由同一服务后台自动解析，稍后刷新任务详情应看到 `reviewing` 或 `blocked`；PDF/图片尚无自动解析，保持 `pending`，均不产出风险结论。
5. 不准备本地附件时，仍用业务账号在 `/docs` 调用 `GET /api/v1/mock-pending`，确认唯一待办 `demo-f1-001` 标记为 `synthetic=true`；再调用 `POST /api/v1/mock-pending/demo-f1-001/import`。返回独立任务 ID、`source=mock_pending`、`mock_approval_id=demo-f1-001`、文档版本 `1` 和三组初始状态 `pending/pending/not_written`；`GET /api/v1/tasks` 可看到本人新任务。法务和管理员不能导入，其他业务账号不能读取该任务。再次导入会创建另一项演示任务；该附件正文与 [F1 固定样例](samples/README.md) 一致，但页码及全链路验收仍未完成。
6. `POST /api/v1/tasks/{task_id}/documents` 用于本人业务账号换上传修订附件，表单须含 `base_document_version`（从任务详情读取的当前文档版本）和 `file`。仅当前任务受阻且恢复动作为 `replace_attachment`，或上一文档已由法务确认时返回新版本；旧原件不覆盖，新版当前状态重置为 `pending/pending/not_written`。法务确认尚未实现，正常创建的 `pending` 任务调用此接口会得到 409；本人可从该响应的 `task_id` 和 `current_status` 核对服务端当前版本、状态，再刷新任务。可运行 `python -m unittest tests.test_tasks.TaskIntakeTests.test_blocked_task_replacement_preserves_old_evidence_and_resets_current_state -v` 查看受控状态下的成功换版、旧版留档及重启读取验证。
7. 法务账号在任务状态变为 `reviewing` 后，可在 `/docs` 调用 `GET /api/v1/tasks/{task_id}/document`，默认读取当前文档版本；加 `document_version=1` 可读取指定的已解析版本。响应含同版正文、段落、字段、条款、缺失条款类型及锚点。`page_count=null`、`preview_available=false` 表示固定 PDF 预览与页码定位尚未实现；`review_version=null` 表示尚无审查版本。未完成解析时返回 409，版本不存在返回 404；未登录返回 401，业务本人在法务确认前返回 403、其他业务账号返回 404，管理员返回 403。业务查看确认结果的能力仍待法务确认功能实现。

服务按约半秒间隔检查待处理 DOCX，重启时恢复过期租约；处理期间定期续租。同一数据库的有效租约仍保持独占，另一服务进程不会同时提交同一作业。需要排查时仍可在项目根目录执行 `python -X utf8 -m backend.docx_job` 手动领取一项待解析 DOCX；正在自动处理时可能返回 `busy`，无待处理项返回 `no_pending_docx`。该命令会写入项目 `storage/` 的演示数据库，只在使用合成演示任务时运行。

已验收的同版规则草稿持久化可在合成 DOCX 解析完成后手动执行 `python -X utf8 -m backend.rule_snapshot <task_id> <document_version>`，例如版本 `1`。命令写入一条 `rule_draft_snapshots` 记录，保存 `demo-v2` 规则版本、来源证据 SHA-256 和草稿；输出 `operation=created`，重复执行为 `already_exists`，不覆盖已有草稿。未解析、非当前版本或证据损坏会拒绝写入；来源证据事后改变返回 `RULE_EVIDENCE_CHANGED`，已存规则版本不同返回 `RULE_VERSION_CHANGED`，均不会覆盖旧结果。该命令默认操作项目 `storage/` 演示库，仅用于合成数据；独立冒烟 `python -X utf8 -m unittest tests.test_smoke.BackendSmokeTests.test_persisted_rule_draft_snapshot_smoke -v` 使用临时库。此增量尚无自动审查作业、持久草稿读取 API 或审查版本；`/risks` 仍是法务即时计算结果。

不准备演示附件时，可执行 `python -X utf8 -m unittest tests.test_smoke -v` 运行后端逐功能冒烟测试。本轮缺陷修复可单独执行 `python -X utf8 -m unittest tests.test_smoke.BackendSmokeTests.test_rule_evidence_repair_smoke -v`：合成 DOCX 缺少使用授权和验收条款时，两条规则均生成带同版锚点的草稿；非法 JSON 证据返回 409。F1/F4 对照可运行 `python -X utf8 -m unittest tests.test_smoke.BackendSmokeTests.test_demo_rule_drafts_smoke -v`。这些测试使用临时库和合成附件，不写入正式演示数据。完整回归可运行 `python -X utf8 -m unittest discover -s tests -q`。

已验收的 [F1/F4 固定样例与预览前答案清单](samples/README.md) 可单独运行 `python -X utf8 -m unittest tests.test_fixed_samples.FixedSampleSmokeTests.test_f1_f4_fixed_sample_smoke -v`。它只读取仓库内合成 DOCX 和静态答案清单，核对文件哈希、12 项字段、条款、段落/字符锚点、F1 两条高风险规则草稿及 F4 无命中；不修改演示数据。固定预览尚未生成，页码和区域仍未验证，不能以本项代替 F1/F4 正式全链路验收。

已验收的 [F5 空白 DOCX 固定样例](samples/README.md#f5-空文档子场景) 可通过业务账号按第 4 步上传 `samples/f5-empty.docx`。自动处理后，任务详情预期显示 `machine_status=blocked`、`blocked_code=DOCX_EMPTY`、`recovery_action=replace_attachment`；法务读取 `/document` 或 `/risks` 得到 409/`DOCUMENT_NOT_READY`，没有虚假结论。业务账号可按第 6 步重新上传可解析的合成 DOCX，生成版本 2。独立冒烟 `python -X utf8 -m unittest tests.test_fixed_samples.FixedSampleSmokeTests.test_f5_empty_docx_fixed_sample_smoke -v` 用临时库验证这条路径和其他业务账号不可见；本机服务人工操作尚未验证，F5 另两种故障仍待实现。

已验收的 [F2 文本 PDF 固定样例](samples/README.md#f2-文本-pdf-固定样例) 为 `samples/f2-text-software-purchase.pdf`；3 页与 F1 具有相同商业条款，第 2 页含付款和验收，第 3 页含知识产权。`samples/f2_expected.json` 记录独立页码和两条预期高风险规则草稿。可按第 4 步上传，当前任务仍会保持 `pending`，法务读取 `/document` 或 `/risks` 返回 409/`DOCUMENT_NOT_READY`；PDF 自动解析尚未接入。独立冒烟 `python -X utf8 -m unittest tests.test_fixed_samples.FixedSampleSmokeTests.test_f2_text_pdf_fixed_sample_smoke -v` 使用临时库核对文件文本层、页码标注、接入、权限和未就绪状态；固定 F2 样例本身没有可视化页面区域验证。

已验收的 [F3 清晰合成扫描件](samples/README.md#f3-清晰合成扫描件) 为 `samples/f3-clear-scan.png`，单页灰度栅格图，与 F1 保持相同合同条款。`samples/f3_expected.json` 记录段落在原图中的像素框、字段/条款页码和两条规则预期；字符区间引用 F1 同版规范化全文。按第 4 步可上传，当前图片任务仍为 `pending`，法务读取 `/document` 或 `/risks` 返回 409/`DOCUMENT_NOT_READY`；CPU OCR 尚未开发。独立冒烟 `python -X utf8 -m unittest tests.test_fixed_samples.FixedSampleSmokeTests.test_f3_clear_scan_fixed_sample_smoke -v` 使用临时库核对图片、静态标注、接入和拒绝路径；原图像素框不能直接作为 PDF 预览高亮区域。

已验收的 [F5 严重模糊扫描件](samples/README.md#f5-严重模糊扫描件子场景) 为 `samples/f5-blurred-scan.png`，从 F3 合成图片生成。可按第 4 步上传，当前返回文档版本 1、机器状态 `pending`；法务读取 `/document` 或 `/risks` 得到 409/`DOCUMENT_NOT_READY`。`samples/f5_blurred_expected.json` 标记未来 OCR 实现后应进入 `blocked/replace_attachment` 且无伪造结论；目前尚不能演示该状态或换版恢复。独立冒烟 `python -X utf8 -m unittest tests.test_fixed_samples.FixedSampleSmokeTests.test_f5_blurred_scan_fixed_sample_smoke -v` 使用临时库检查文件、接入、权限和未就绪状态。

已验收的 [F5 加密 PDF 固定样例](samples/README.md#f5-加密-pdf-子场景) 为 `samples/f5-encrypted.pdf`。用 PDF 阅读器打开应要求口令，公开测试口令为 `f5-synthetic-user`；自动测试已验证口令拒绝和解密后的原文一致。按第 4 步上传后当前仍为 `pending`，法务结果接口返回 409；自动识别加密及 `blocked/replace_attachment` 恢复尚未实现。独立冒烟 `python -X utf8 -m unittest tests.test_f5_encrypted_pdf -v`；新环境运行此测试或完整回归前须执行 `python -m pip install --target .tools/pdf-fixtures -r samples/requirements-pdf-fixtures.txt`，这仅安装样例工具，不属于后端运行依赖。

已验收的 [F6 待办附件超时固定故障源](samples/README.md#f6-待办附件首次超时子场景) 可运行 `python -X utf8 samples/f6_pending_timeout.py` 查看：第一行 `dependency_outcome=timeout` 且不返回附件，第二行 `attachment_available` 并给出固定 F1 的 SHA-256。它不创建任务，也不接入当前模拟待办 API；机器受阻与管理员重试仍待实现。独立冒烟 `python -X utf8 -m unittest tests.test_f6_pending_timeout -v` 只用合成原件验证故障源，不使用数据库或外部服务。

已验收的 [F6 回写故障固定样例](samples/README.md#f6-首次模拟回写失败与重复提交子场景) 可运行 `python -X utf8 samples/f6_writeback_failure.py`，四行 JSON 依次显示失败、重试成功、同版重复返回原评论 ID、新版生成新评论 ID。该样例仅在内存模拟评论依赖，现有系统尚无法务确认或回写 API。独立冒烟 `python -X utf8 -m unittest tests.test_f6_writeback_failure -v` 不使用数据库或外部平台；持久去重与角色权限留待正式后端功能验证。

已验收的 F2 文本 PDF 原件可由法务使用 Bearer 凭据调用 `GET /api/v1/tasks/{task_id}/document/preview`，可加 `document_version=1` 指定版本。返回 `application/pdf` 的同版上传字节；未登录 401，本人业务和管理员 403，其他业务 404，缺失版本 404，非 PDF 或原件异常 409。运行 `python -X utf8 -m unittest tests.test_pdf_preview -v` 可用 F2 合成三页 PDF 和临时数据库核对这些路径。该接口尚不提取 PDF 文本或提供页码/高亮区域，也未完成加密 PDF 识别和 DOCX/扫描件预览。
本轮待验收：`backend.pdf_parser.parse_pdf` 在独立组件中读取 F2 文本 PDF，返回 3 页、12 个视觉行段落、与固定原文一致的 Unicode 字符区间，以及同版页面的归一化段落区域；F5 加密 PDF 拒绝解析。新环境执行 `python -m venv .venv`、`.\.venv\Scripts\python.exe -m pip install --index-url https://pypi.org/simple -r requirements-dev.txt`，再运行 `.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_pdf_parser -v`。该组件尚未接入 PDF 作业、数据库或 `/document` API；上传 F2 后仍为 `pending`。区域只按视觉行标出段落范围，字段/条款/风险精准高亮及目标机运行待验证。

直接查看规则草稿可运行 `python -X utf8 -m backend.demo_rules`。预期 F1 候选输出 `DEMO-IP-01`、`DEMO-PAY-01` 和各自原文，F4 候选显示“未发现已启用规则风险”；此命令只读取仓库自带的合成附件，不修改任务或数据库。输出为机器规则草稿，不是法务结论。

2026-09-24 接手自审修复了相反约定分散在不同条款时的误报：已识别的知识产权条款另有使用权授权，或付款/验收条款另有付款前验收要求时，不自动命中对应规则，留待人工核对。运行 `python -X utf8 -m unittest tests.test_demo_rules -v` 可验证同条款/跨条款矛盾、条款顺序、错版或篡改引文及证据不足边界；这仍是固定措辞组件验证，不代表通用合同语义理解。

可在项目根目录运行 `python -X utf8 -c "from backend.docx_parser import parse_docx; from backend.mock_pending import synthetic_attachment; from backend.clause_extractor import extract_clauses; result = extract_clauses(parse_docx(synthetic_attachment(), 1)); print([c.clause_type for c in result.clauses]); print(result.missing_types)"` 直接查看条款识别结果：第一行依次为 `['标的', '付款', '验收', '知识产权', '违约', '保密', '争议解决']`，第二行为 `('数据安全',)`，表示未找到该标题条款。此命令只读仓库自带的合成附件，不读取或改写演示任务。

可运行 `python -X utf8 -c "from backend.docx_parser import parse_docx; from backend.mock_pending import synthetic_attachment; from backend.metadata_extractor import extract_metadata; r = extract_metadata(parse_docx(synthetic_attachment(), 1)); print([(f.name, f.value if f.value is not None else '未识别') for f in r.fields])"` 查看本轮字段：合同编号为 `SYN-2026-001`、金额为 `100000`、币种为 `人民币`；采购方和供应商统一社会信用代码及生效条件为“未识别”。只解析仓库自带合成附件，不修改任务数据。识别只覆盖明确标签、首段独立标题和约定格式，不验证统一社会信用代码真伪或合同法律效力。

本机通过临时库 API 测试验证账号、接入、权限、版本修订与持久队列；DOCX 自动处理成功、空文受阻、重启后过期租约恢复、PDF 保持待处理和他人任务不可见。正文、标题条款与基础字段提取使用合成文件验证；例如合成待办可识别合同编号、双方名称、金额/币种与履行期限，双方统一社会信用代码、生效条件及数据安全条款标记缺失。固定演示规则按 `demo-v2` 对已识别的供应商软件权属且无使用授权、到货付全款且验收条款缺失生成草稿；含糊验收或矛盾条款仍留法务判断。F1/F4、F2、F3 已有固定文件与预期标注，F5 严重模糊扫描件的文件与故障预期已验收；这些不等于 F1–F3 已完成解析或审查，也不等于 F5 模糊件能自动受阻。法务可即时读取 DOCX 规则草稿；手动持久规则草稿已验收，尚无完整审查快照、审查版本或正式法律依据；固定 PDF 预览、实际浏览器手工操作、目标机安装运行仍待验证。测试数量及本轮结果见[实施状态](docs/IMPLEMENTATION_STATUS.md)。

## 怎样阅读和验收文档

1. 先看 [MVP SPEC](docs/MVP_SPEC.md)：首期做什么、不做什么，以及 F1–F6 样例和 A1–A8 验收条件。它在用户验收后才成为唯一可执行需求基线。
2. 再看[核心流程](docs/CORE_FLOW.md)：任务、文档版本、法务确认和模拟回写如何流转。
3. 按职责看[后端设计](docs/BACKEND_DESIGN.md)和[前端设计](docs/FRONTEND_DESIGN.md)：分别核对 API、权限、页面与交互。
4. 对照[已确认决策](docs/DECISIONS.md)和[实施状态](docs/IMPLEMENTATION_STATUS.md)：区分已决定、尚未开发及仍待验证的事项。

[原始需求](Demand/Demand.md)和[先期 SPEC](Demand/SPEC.md)保留供溯源；若阶段表述不同，以用户验收后的 MVP SPEC 及后续确认的决策为准。`AGENTS.md` 是参与本项目的 AI 助手工作指令，不替代产品需求。

前端 v0.4 视觉设计见 [pencil-new.pen](pencil-new.pen)，可先看[十画板静态预览](design/v0.4-preview.png)，其中[任务仪表盘](design/v0.4-board-02.png)突出当前处理分布、下一步和合同明细；v0.3、v0.2、v0.1 原稿分别保存在 [design/pencil-new-v0.3.pen](design/pencil-new-v0.3.pen)、[design/pencil-new-v0.2.pen](design/pencil-new-v0.2.pen)、[design/pencil-new-v0.1.pen](design/pencil-new-v0.1.pen)。v0.4 已完成本地结构与静态预览检查，尚未在 pen.dev 中打开验证，也不代表前端功能已实现或通过验收。

## 将来的演示使用流程

规划中的使用顺序是：本地测试账号登录 → 上传合成合同或导入模拟待办 → 等待解析与机器草稿 → 法务核对、修改并确认 → 查看或导出已生成的报告 → 法务触发模拟回写。各角色能看到的内容不同；业务经办人不能查看未确认的风险草稿。具体状态和失败恢复见[核心流程](docs/CORE_FLOW.md)。

上述完整合同审查流程尚未实现，目前已有账号、两种接入方式、任务列表、修订换版及 DOCX 自动解析作业。后端和前端分别完成实际运行验证后，再补充对应的安装、启动和操作步骤。
