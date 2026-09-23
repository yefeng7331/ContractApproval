# 合同审查演示系统

本项目计划在本地演示软件采购合同从提交、机器辅助审查到法务确认、报告导出和**模拟**审批评论回写的流程。演示使用合成合同；模拟回写不连接真实企业审批平台，也不代表正式法律审查结论。

## 当前能做什么

目前已实现并通过用户验收的是本地三角色账号与会话。合成合同的**本地上传接入、任务列表和本人任务权限**已通过本机技术测试，仍待用户验收；上传后任务保持 `pending`，后台解析、审查、报告、模拟回写和前端尚未实现。文档基线本身仍待验收。每完成一个可独立验收的功能，本页同步更新实际可用范围和经验证的使用步骤；详细证据与验收状态以[实施状态](docs/IMPLEMENTATION_STATUS.md)为准。

## 已实现功能的本机使用步骤

当前开发环境使用 Python 3.14.6；运行依赖列在 `requirements.txt`，新环境可先执行 `python -m pip install -r requirements.txt`，目标 Windows 电脑的安装尚未验证。

1. 在项目根目录分别执行 `python -m backend.cli create-user --username business1 --role business`、`python -m backend.cli create-user --username legal1 --role legal`、`python -m backend.cli create-user --username admin1 --role admin`。每条命令都会交互式要求输入至少 12 个字符的密码，不把密码写入命令或仓库。
2. 执行 `python -m uvicorn backend.main:app --host 127.0.0.1 --port 8765` 启动本地服务。账号、会话、任务与附件写入项目内被 `.gitignore` 忽略的 `storage/`。
3. 向 `POST http://127.0.0.1:8765/api/v1/sessions` 发送账号和密码，取得 `access_token`；后续请求在 `Authorization: Bearer <token>` 中携带它。`GET /api/v1/sessions/current` 返回当前账号与角色，`DELETE /api/v1/sessions/current` 撤销会话。令牌仅用于当前演示会话，刷新未来前端页面后须重新登录。
4. 可在浏览器打开 `http://127.0.0.1:8765/docs` 试用 API：用业务账号登录并复制返回的令牌，在页面右上角 `Authorize` 中填写令牌；调用 `POST /api/v1/tasks`，填入合成数据的 `department`、`applicant`，选择不超过 25 MiB 的 DOCX、PDF 或常见扫描图片。接口返回任务 ID、文档版本 `1` 与三组初始状态 `pending/pending/not_written`。`GET /api/v1/tasks` 查看本人列表，`GET /api/v1/tasks/{task_id}` 查看单个任务；其他业务账号查询此任务会得到 404。法务账号可看任务与提交信息，管理员只看状态和所属账号。此处的上传只完成接入，尚不产出解析结果或风险结论。

不准备演示附件时，可执行 `python -m unittest discover -s tests -v` 检查账号和接入接口；测试会在临时目录生成合成附件，不使用真实合同。

本机已验证账号 API 行为及服务启动后未登录访问返回 401；接入与任务列表通过 API 测试客户端验证了写入、权限、错误输入和重启后读取。浏览器手工操作、另一台目标电脑的安装运行仍待验证。

## 怎样阅读和验收文档

1. 先看 [MVP SPEC](docs/MVP_SPEC.md)：首期做什么、不做什么，以及 F1–F6 样例和 A1–A8 验收条件。它在用户验收后才成为唯一可执行需求基线。
2. 再看[核心流程](docs/CORE_FLOW.md)：任务、文档版本、法务确认和模拟回写如何流转。
3. 按职责看[后端设计](docs/BACKEND_DESIGN.md)和[前端设计](docs/FRONTEND_DESIGN.md)：分别核对 API、权限、页面与交互。
4. 对照[已确认决策](docs/DECISIONS.md)和[实施状态](docs/IMPLEMENTATION_STATUS.md)：区分已决定、尚未开发及仍待验证的事项。

[原始需求](Demand/Demand.md)和[先期 SPEC](Demand/SPEC.md)保留供溯源；若阶段表述不同，以用户验收后的 MVP SPEC 及后续确认的决策为准。`AGENTS.md` 是参与本项目的 AI 助手工作指令，不替代产品需求。

前端 v0.1 视觉初稿见 [pencil-new.pen](pencil-new.pen)，可先看[静态预览](design/v0.1-preview.png)。它尚未在左侧 pen.dev 标签页打开验证，也不代表前端功能已实现或通过验收。

## 将来的演示使用流程

规划中的使用顺序是：本地测试账号登录 → 上传合成合同或导入模拟待办 → 等待解析与机器草稿 → 法务核对、修改并确认 → 查看或导出已生成的报告 → 法务触发模拟回写。各角色能看到的内容不同；业务经办人不能查看未确认的风险草稿。具体状态和失败恢复见[核心流程](docs/CORE_FLOW.md)。

上述完整合同审查流程尚未实现，目前只有账号、上传接入和任务列表。后端和前端分别完成实际运行验证后，再补充对应的安装、启动和操作步骤。
