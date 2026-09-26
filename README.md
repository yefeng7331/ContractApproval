# 合同审查演示系统

一个面向本机演示的合同审查工作台。业务经办人提交**合成合同**，系统保存原件和版本、提取字段与条款并生成规则草稿；法务核对证据、编辑和确认结论后，可生成 Markdown/PDF 报告，并向**本地模拟审批单**回写评论。系统不连接真实审批平台，机器草稿不构成法律意见。

> **当前状态（2026-09-26）**：功能已进入 A1–A8 全面验收。此前合成样例的后端回归 171/171、前端测试 43/43 及构建通过；这些是技术验证。A1 的浏览器上传、导入和页面核对仍待实际操作，A1–A8 尚未全部通过。最新证据和逐项结论见[实施与验收状态](docs/IMPLEMENTATION_STATUS.md)。

## 功能范围

| 区域 | 当前能力 |
| --- | --- |
| 接入与版本 | 上传 DOCX、文本 PDF、清晰扫描件；导入固定模拟待办；受阻或已确认任务可换传新版本，旧版证据保留 |
| 审查工作台 | 展示分页原文、字段、条款、规则风险与证据锚点；法务核对、编辑、批注和确认 |
| 结论与回写 | 确认后生成同版 Markdown/PDF 报告；法务向本地模拟审批单回写，失败可按状态恢复 |
| 任务与恢复 | 大盘显示机器、法务、回写三组状态；管理员查看故障与处理记录，并对允许的暂时故障重试 |
| 权限 | 业务只访问本人任务，确认前不见风险草稿；法务处理审查；管理员不读取合同正文或代为确认 |

技术组成：React、TypeScript、Vite、PDF.js 前端；FastAPI、SQLite 和本地文件后端。DOCX 预览依赖 LibreOffice；扫描件识别使用单独的 CPU OCR 运行时。前端通过 Vite 的 `/api` 代理访问本机后端。

## 本机快速启动（Windows PowerShell）

以下命令在仓库根目录执行。准备 Python、Node.js/npm、LibreOffice；需要验证 F3 扫描件时，还需按[OCR 安装脚本](scripts/install_ocr.ps1)及[实施状态](docs/IMPLEMENTATION_STATUS.md)准备项目内独立 OCR 运行时。依赖安装和目标机器运行情况需在使用的电脑上实际核对。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm.cmd --prefix frontend ci

$demoRoot = Join-Path (Get-Location) 'storage\readme-demo'
New-Item -ItemType Directory -Path $demoRoot -Force | Out-Null
$demoDb = Join-Path $demoRoot 'contract_approval.sqlite3'

.\.venv\Scripts\python.exe -m backend.cli --database $demoDb create-user --username business1 --role business
.\.venv\Scripts\python.exe -m backend.cli --database $demoDb create-user --username legal1 --role legal
.\.venv\Scripts\python.exe -m backend.cli --database $demoDb create-user --username admin1 --role admin

.\.venv\Scripts\python.exe scripts/start_local.py --process-local --data-root $demoRoot
```

创建账号时会交互式输入至少 12 个字符的密码；不要把密码写进命令或仓库。启动器会在同一个终端启动前后端；显示 `Ready` 后打开 <http://127.0.0.1:5173/>，按 `Ctrl+C` 停止。后端 API 文档位于 <http://127.0.0.1:8010/docs>。端口被占用时，可用 `--backend-port` 和 `--frontend-port` 指定其他端口。

`--process-local` 会处理指定数据目录里的待办任务，所以应使用专门的合成数据目录。此模式不会自动发起付费模型请求；F1 的规则命中任务可能停在 `reviewing`，需按已授权的模型或人工处理流程继续。固定 F1 的一次真实 DeepSeek 调用此前已单独执行并验收，不应为普通上手或 A1 验收重复调用。应用费用是估算，供应商账单未独立核对。

### 建议的首次操作

1. 用 `business1` 登录，选择“软件采购（演示）”，上传 [F4 修订合同](samples/f4-revised-software-purchase.docx)。F4 已补足演示规则关注的使用权与付款前验收条件，适合无付费模型调用的流程演示。
2. 等待任务处理，在大盘查看机器状态；用 `legal1` 打开工作台，核对原文、字段、条款及“未发现已启用规则风险”，填写法务结论并确认。该提示只表示**两条已启用演示规则未命中**，不表示合同法律安全。
3. 查看已确认版本的报告，必要时由法务触发**模拟回写**；用 `business1` 核对本人已确认版本。用 `admin1` 查看状态与故障记录，不进入合同内容。

要核对当前 A1 接入解析验收，按[实施状态中的 A1 清单](docs/IMPLEMENTATION_STATUS.md)分别上传 F1、F2、F3，并导入 `demo-f1-001` 模拟待办；逐项核对本版字段、页码、权限和错误提示。F1–F3 的机器审查可能因需要单独授权的模型步骤保持 `reviewing`，不能把它当成解析失败。

## 验证与样例

仓库提供 F1–F6 固定合成样例及预期标注，详见[样例说明](samples/README.md)。F1–F3 覆盖 DOCX、文本 PDF、清晰扫描件；F4 用于检查两条规则不误报；F5 覆盖加密、空文和严重模糊附件受阻；F6 覆盖模拟待办超时、回写失败与去重。

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -q
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run build
```

上次完整技术回归分别为后端 171/171、前端 43/43 和构建通过，使用合成数据、临时库及受控模型响应。本机 HTTP 测试覆盖 Vite 代理与 API 链路；测试通过不等于浏览器实际点击、视觉、下载体验或法务专业核定通过。全面验收以 [MVP SPEC 第 6 节](docs/MVP_SPEC.md)的 F1–F6、A1–A8 条件和[实施状态](docs/IMPLEMENTATION_STATUS.md)的最新记录为准。目标 Windows 电脑的验证按已确认决策安排在本机总体验收后。

## 数据与使用限制

- 仅使用仓库中的虚构合同和测试账号。真实合同上传外部模型的政策、法律依据与最终法务判断尚需另行确认。
- 本地数据库、附件、报告、OCR 模型与缓存放在 `storage/` 等 Git 忽略目录；`.env`、密钥、证书也被忽略。提交或推送前仍须检查暂存内容，避免泄露个人信息和凭据。
- 规则、模型建议和法务最终意见在界面与数据中分开；报告和模拟回写只针对已确认版本。真实待办监听、真实审批平台回写、规则编辑及生产部署不在当前演示范围。
- 页面操作和双向定位目前尚缺浏览器验收证据；规则与示范条款尚未经过专业法务核定。当前状态请以[实施与验收状态](docs/IMPLEMENTATION_STATUS.md)顶部的最新记录为准。

## 文档导航

- [MVP 范围与验收标准](docs/MVP_SPEC.md) · [核心流程](docs/CORE_FLOW.md)
- [后端设计](docs/BACKEND_DESIGN.md) · [前端设计](docs/FRONTEND_DESIGN.md) · [已确认决策](docs/DECISIONS.md)
- [实施与验收状态](docs/IMPLEMENTATION_STATUS.md) · [固定合成样例](samples/README.md)
- [原始需求](Demand/Demand.md) · [先期 SPEC](Demand/SPEC.md)（溯源资料）

遇到启动、权限或样例结果问题，先查看[实施状态](docs/IMPLEMENTATION_STATUS.md)对应功能的命令、证据和限制，再对照[核心流程](docs/CORE_FLOW.md)与[设计文档](docs/BACKEND_DESIGN.md)。根目录 README 只保留上手和当前范围，逐轮历史记录以实施状态文档为准。
