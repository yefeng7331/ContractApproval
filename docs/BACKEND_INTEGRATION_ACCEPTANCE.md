# 后端集成验收记录

2026-09-25 D-27 更新：F6 待办附件恢复已获用户验收，A7 增量验收完成；A8 统一操作记录仍待收口。用户已批准先前端设计与逐页面接口对接，结合页面完成本机总体验收。下方原“阶段先通过再申请前端”及 F6 待用户验收的内容为历史，不再阻塞前端开工；UI 预览不作为真实业务证据。

2026-09-25 最新：**PARTIAL，阶段尚未验收**。F3 标题修复已获用户验收；F6 待办附件超时业务已补齐，专项技术验证通过、待用户验收。A8 统一操作记录对照仍待收口。前端未获本阶段开发审批。

F6 增量命令：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_pending_imports tests.test_smoke -q`，20/20 PASS，29.821 秒。四项恢复专项使用固定 F6 故障源、真实 HTTP 和临时 SQLite；涵盖首次失败、管理员重试、同版本解析/规则、角色拒绝、双连接竞争、重开数据库、过期租约、迟到结果、存储回滚及无效附件。原 HTTP 500/无任务缺口已修复，不代表真实外部平台验证。

## 执行范围

全量回归 `.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -q` 执行 146 项（419.111 秒），首轮 145 通过、1 失败：旧导入测试重新生成 DOCX，ZIP 时间戳导致哈希不稳定。测试现固定实际下载字节，并核对新增的获取开始/导入完成审计序列；生产代码未因该失败修改。修正后 `.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_tasks tests.test_pending_imports -q` **17/17 PASS（52.228 秒）**，覆盖该失败及任务/F6 回归。未重复全量，不记作单次 146/146 PASS。

使用真实 FastAPI TestClient 接口、临时 SQLite、合成附件、本机 LibreOffice、pdfplumber 和隔离 CPU OCR。处理器在集成测试中显式推进，不把它描述为浏览器演示或后台调度全链路。模型响应受控且禁止意外联网；本轮无付费调用。自动处理、重启和故障恢复另由已有 reports/writeback 专项覆盖。

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_metadata_extractor tests.test_backend_integration tests.test_writeback tests.test_reports -q
```

前次集成执行：**18/18 PASS，102.926 秒**。该命令不包含 F6 待办超时专项，不代表整个阶段通过。首轮集成暴露 F3 title=null；修复时补测发现全角空格也需支持，改为接受括号前横向空白后，上述命令重新全部通过。

运行环境：Windows 11 10.0.26200、主 Python 3.14.6、FastAPI 0.141.1、Pydantic 2.13.5、pdfplumber 0.11.10、pypdfium2 5.13.0。LibreOffice 安装版本 26.8.0.3 沿用前次用户安装证据，本轮实际执行转换。OCR 使用项目隔离环境，不是主 Python 环境。

## 样例结果

| 样例 | 结果 | 可复查证据及边界 |
| --- | --- | --- |
| F1 | PASS（本机受控模型链路） | `test_f1_full_http_chain_and_import`：上传和待办成功导入、全部字段/条款、两条高风险、真实 DOCX 固定预览、法务编辑确认、同版 Markdown/PDF 内容、本地评论及重复返回同 ID；最终 completed/confirmed/success |
| F2 | PASS | `test_f2_f3_f4_same_rules_real_parsers_and_legal_versions`：真实 PDF 提取、答案清单、两风险、原文切片及风险页码、法务编辑确认 |
| F3 | PASS（修复已验收） | 同上：真实 CPU OCR；标题括号前空格原先导致 title=null，现保留原文提取；字段、条款、风险和页码核对通过。答案比较仅归一化 Unicode 宽度和空白，实际存储与锚点原文不改 |
| F4 | PASS | 同上：修订 DOCX 两演示规则无命中，能够完成法务确认；不代表通用合同无风险 |
| F5 | PASS | `test_f5_blocked_no_conclusion_and_replacement`：DOCX_EMPTY/PDF_ENCRYPTED/OCR_UNREADABLE，blocked、replace_attachment、无风险等级、拒绝确认；换件为 v2 后重新解析 |
| F6 回写 | PASS（故障注入） | `tests.test_writeback`：首次失败、重试、唯一评论、固定目标、版本/权限隔离、租约与重开连接恢复；非真实平台 |
| F6 待办超时 | PASS（故障注入，待用户验收） | `tests.test_pending_imports`：实际路由首次超时返回 201 + blocked，持久 attempt 1；管理员同 v1 重试成功 attempt 2，再真实解析/两风险；重开数据库、过期租约、并发、迟到结果与存储回滚通过 |

## A1–A8 后端证据矩阵

| 要求 | 结果 | 证据 |
| --- | --- | --- |
| A1 接入解析 | PASS | F1–F3 与待办成功路径逐字段/条款对答案 |
| A2 定位 | PASS（固定样例） | F1 固定预览 12 段均可定位；F2/F3 风险页、段、版本与原文切片；既有预览/OCR 专项提供坐标证据；前端双向联动未验证 |
| A3 风险建议 | PASS（受控模型） | F1–F3 两高风险，F4 无命中；HTTP 人工编辑与确认。真实模型证据另列于下方 |
| A4 复核权限 | PASS（本轮覆盖接口） | 确认前本人业务/管理员 403、其他业务 404，管理员确认 403；回写/报告专项复核对应权限，不宣称任意接口安全审计 |
| A5 同版报告 | PASS | F1 两种真实报告文本对照；`tests.test_reports` 覆盖独立失败、同版重试、权限、历史、事务回滚及租约 |
| A6 模拟回写 | PASS | 未确认 409、成功评论 ID、重复请求相同 ID；回写专项覆盖失败/恢复/去重 |
| A7 受阻重试 | PASS（F6 增量待用户验收） | F5 和回写已有证据；F6 附件失败历史、管理员同版重试、重开数据库及中断恢复专项已补齐 |
| A8 端到端 | PARTIAL | F1 API 主链通过，法务版本/确认和回写尝试持久保存；跨阶段操作记录统一对照仍未完成，待 F6 补齐后一并收口 |

## F6 缺口历史与修复边界

`backend/main.py` 的 `POST /api/v1/mock-pending/demo-f1-001/import` 在 `create_task` 前同步调用 `synthetic_attachment()`。以 `tests.test_reviews.ReviewTests` 临时环境、`TestClient(..., raise_server_exceptions=False)`、业务本人 Bearer 请求，并 patch `backend.main.synthetic_attachment` 抛出 `TimeoutError('Synthetic F6 timeout')`：HTTP 500、正文 `Internal Server Error`、tasks 数量差为 0。未触碰正式数据库。

当时 `samples/f6_pending_timeout_expected.json` 标记 NOT_IMPLEMENTED/UNVERIFIED。本轮已有真实处理器及专项证据，更新为 IMPLEMENTED_PENDING_ACCEPTANCE/VERIFIED_FAULT_INJECTION；固定组件本身仍只证明依赖行为。

本轮已在下载前登记持久任务，保存首次超时及尝试；仅管理员按同一文档版本重试，成功取得附件后进入已有解析队列，未预存占位附件。该功能验收后收口 A8 操作记录及阶段矩阵，再申请后端阶段验收；阶段通过后按 D-25 单独申请前端审批。

## 外部证据与限制

- 真实 DeepSeek F1：沿用实施状态中用户手动运行后反馈 `{"state":"completed","code":null}` 并验收的记录；本轮未新增真实调用，未独立核对完整供应商响应及 usage。
- 应用估算不等于实际账单；供应商账单仍 UNVERIFIED。
- 法律判断和用户阶段验收分别记录；本文件的技术结果不替代二者。
- 前端页面和另一台 Windows 目标机不在本轮验证范围。
