# 合同审查演示系统

本项目计划在本地演示软件采购合同从提交、机器辅助审查到法务确认、报告导出和**模拟**审批评论回写的流程。演示使用合成合同；模拟回写不连接真实企业审批平台，也不代表正式法律审查结论。

## 当前能做什么

最新进度：两条固定商业规则组件、法务读取规则草稿 API 与手动同版草稿持久化均已获用户验收；F1/F4 固定 DOCX 与预览前答案清单待本轮验收。法务在 DOCX 解析完成后调用 `GET /api/v1/tasks/{task_id}/risks`，可选 `document_version=1`，取得同版规则命中、原文锚点与建议。此 API 保持已验收的即时计算语义：`evaluation_mode=on_demand_rules_only`、`persisted=false`、`review_version=null`，读取不改变任务的 `reviewing` 状态。本人业务/管理员 403、其他业务 404、未登录 401；未解析 409、文档或审查版本不存在 404。当前不支持任何 `review_version`，不能把规则草稿用于法务确认、报告或回写。可独立运行 `python -X utf8 -m unittest tests.test_smoke.BackendSmokeTests.test_rule_drafts_api_smoke -v`，使用临时库和合成 F1/F4 验证成功、权限、版本、无写入及坏证据拒绝。

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

本轮 [F1/F4 固定样例与预览前答案清单](samples/README.md) 可单独运行 `python -X utf8 -m unittest tests.test_fixed_samples.FixedSampleSmokeTests.test_f1_f4_fixed_sample_smoke -v`。它只读取仓库内合成 DOCX 和静态答案清单，核对文件哈希、12 项字段、条款、段落/字符锚点、F1 两条高风险规则草稿及 F4 无命中；不修改演示数据。固定预览尚未生成，页码和区域仍未验证，不能以本项代替 F1/F4 正式全链路验收。

直接查看规则草稿可运行 `python -X utf8 -m backend.demo_rules`。预期 F1 候选输出 `DEMO-IP-01`、`DEMO-PAY-01` 和各自原文，F4 候选显示“未发现已启用规则风险”；此命令只读取仓库自带的合成附件，不修改任务或数据库。输出为机器规则草稿，不是法务结论。

2026-09-24 接手自审修复了相反约定分散在不同条款时的误报：已识别的知识产权条款另有使用权授权，或付款/验收条款另有付款前验收要求时，不自动命中对应规则，留待人工核对。运行 `python -X utf8 -m unittest tests.test_demo_rules -v` 可验证同条款/跨条款矛盾、条款顺序、错版或篡改引文及证据不足边界；这仍是固定措辞组件验证，不代表通用合同语义理解。

可在项目根目录运行 `python -X utf8 -c "from backend.docx_parser import parse_docx; from backend.mock_pending import synthetic_attachment; from backend.clause_extractor import extract_clauses; result = extract_clauses(parse_docx(synthetic_attachment(), 1)); print([c.clause_type for c in result.clauses]); print(result.missing_types)"` 直接查看条款识别结果：第一行依次为 `['标的', '付款', '验收', '知识产权', '违约', '保密', '争议解决']`，第二行为 `('数据安全',)`，表示未找到该标题条款。此命令只读仓库自带的合成附件，不读取或改写演示任务。

可运行 `python -X utf8 -c "from backend.docx_parser import parse_docx; from backend.mock_pending import synthetic_attachment; from backend.metadata_extractor import extract_metadata; r = extract_metadata(parse_docx(synthetic_attachment(), 1)); print([(f.name, f.value if f.value is not None else '未识别') for f in r.fields])"` 查看本轮字段：合同编号为 `SYN-2026-001`、金额为 `100000`、币种为 `人民币`；采购方和供应商统一社会信用代码及生效条件为“未识别”。只解析仓库自带合成附件，不修改任务数据。识别只覆盖明确标签、首段独立标题和约定格式，不验证统一社会信用代码真伪或合同法律效力。

本机通过临时库 API 测试验证账号、接入、权限、版本修订与持久队列；DOCX 自动处理成功、空文受阻、重启后过期租约恢复、PDF 保持待处理和他人任务不可见。正文、标题条款与基础字段提取使用合成文件验证；例如合成待办可识别合同编号、双方名称、金额/币种与履行期限，双方统一社会信用代码、生效条件及数据安全条款标记缺失。固定演示规则按 `demo-v2` 对已识别的供应商软件权属且无使用授权、到货付全款且验收条款缺失生成草稿；含糊验收或矛盾条款仍留法务判断。F1/F4 固定文件已有预览前答案清单，F1 两项高风险、F4 无命中。法务可即时读取草稿；手动持久规则草稿已验收，尚无完整审查快照、审查版本或正式法律依据；固定 PDF 预览、实际浏览器手工操作、目标机安装运行仍待验证。测试数量及本轮结果见[实施状态](docs/IMPLEMENTATION_STATUS.md)。

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
