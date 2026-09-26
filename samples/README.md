# 固定合成样例与预期标注

## F1/F4 DOCX（页码标注前）

此目录只含虚构主体与交易。`f1-software-purchase.docx` 对应模拟待办 `demo-f1-001` 的正文；`f4-revised-software-purchase.docx` 只修改付款、验收、知识产权三个段落。固定文件的 SHA-256、12 项字段、7 项已识别条款、缺失的数据安全条款、段落及零起始 Unicode 字符区间、两条规则的等级/证据/建议都在 [f1_f4_expected.json](f1_f4_expected.json)。空字段以 `null` 表示“未识别”，不代表合同事实不存在。

| 样例 | 当前规则预期 | 机器建议 |
| --- | --- | --- |
| F1 | `DEMO-IP-01`、`DEMO-PAY-01`，各为高风险规则草稿 | 建议拒绝并整改 |
| F4 | 两条已启用规则均不命中；不推断低风险或法律安全 | 待法务复核 |

位置契约：每条已识别字段和条款的 `start/end` 指向对应 DOCX 的 NFC 规范化全文，`end` 不包含末字符；`paragraph_index` 从 0 开始。当前无固定 PDF 预览，所有页码、区域及精准高亮预期均为 `UNVERIFIED`，现有组件返回 `page=null`、`locatable=false`、`PREVIEW_NOT_AVAILABLE`。生成预览后须为每份样例单独补充人工复核的页码与区域，不能用 F1 页码推断 F4 或后续 F2/F3。

可单独运行 `python -X utf8 -m unittest tests.test_fixed_samples.FixedSampleSmokeTests.test_f1_f4_fixed_sample_smoke -v`。测试只读取本目录附件与答案清单，校验固定文件哈希、模拟待办正文一致、字段/条款/风险逐项结果及 F4 不误报；不使用数据库、模型或外部平台。法务确认、真实模型调用和正式 F1/F4 全链路验收均尚无证据。

## F5 空文档子场景

`f5-empty.docx` 是仅含一个空白正文段落的合成 DOCX；固定哈希和预期错误、状态、恢复动作见 [f5_empty_expected.json](f5_empty_expected.json)。它可通过附件接入，但解析应返回 `DOCX_EMPTY`，任务进入 `blocked`，恢复动作为 `replace_attachment`；不应产生解析正文或风险草稿。上传一份可解析的新附件后产生版本 2，版本 1 的阻塞记录应保留。

独立冒烟：`python -X utf8 -m unittest tests.test_fixed_samples.FixedSampleSmokeTests.test_f5_empty_docx_fixed_sample_smoke -v`。测试使用临时数据库和合成账号，验证任务 API、越权隔离、法务结果未就绪、无伪造证据以及换版恢复；不会写入正式演示数据。F5 的加密 PDF 已有固定文件，加密与严重模糊扫描件的实际阻塞/换版尚未实现；不能把本子场景当作 F5 全部通过。

## F2 文本 PDF 固定样例

`f2-text-software-purchase.pdf` 是 3 页合成文本 PDF，商业条款正文与 F1 相同，但独立分页：第 1 页为合同信息和标的，第 2 页为付款及验收，第 3 页为知识产权及后续条款。它嵌入 Noto Sans SC 字体子集并带 Unicode 文本映射，不是扫描图片。`f2_expected.json` 固定 PDF 哈希、页码、字段/条款/风险页码和两项 `demo-v2` 规则草稿预期；文字、段落及零起始字符区间复用 `f1_f4_expected.json` 的 F1 原文清单，测试逐字核对 PDF 文本层。F2 页码独立标注，不套用 F1 的未验证页码。

独立冒烟：`python -X utf8 -m unittest tests.test_fixed_samples.FixedSampleSmokeTests.test_f2_text_pdf_fixed_sample_smoke -v`。它核对 PDF 哈希、嵌入字体与 Unicode 映射、3 页逐段文本及标注，并用临时库验证上传成功、其他业务账号不可见、当前 PDF 仍为 `pending`、法务读取正文或风险为 409、零解析与零规则草稿。该检查针对固定文件结构，不代替通用 PDF 解析器或可视化渲染验证。PDF 提取、页面区域、实际规则处理及 F2 全链路均尚未实现/验证。

可用本机已安装的 `fontTools` 和允许嵌入的 Noto Sans SC 字体运行 `python -X utf8 samples/build_f2_pdf.py --font <local-font-path>` 重新生成固定文件；此脚本只供维护样例，不是后端运行依赖。重新生成后须核对哈希及标注。

## F3 清晰合成扫描件

`f3-clear-scan.png` 是单页、2048×2800 像素的灰度栅格图，逐段展示与 F1 同语义的合成合同；图片没有文字层。`f3_expected.json` 固定 SHA-256、F1 同版规范化全文的段落和字符区间引用、字段/条款页码、两条高风险规则草稿预期，以及每段在**原始图片像素坐标**中的外接框。原图像素框供后续 OCR 对照，不能直接当作 PDF 预览的归一化 `rects`；预览坐标仍待固定转换后复核。

独立冒烟：`python -X utf8 -m unittest tests.test_fixed_samples.FixedSampleSmokeTests.test_f3_clear_scan_fixed_sample_smoke -v`。它核对 PNG 完整性、灰度栅格及无文字元数据、固定哈希、每段文字像素位于所标框内、F1 文字/字段/条款/风险预期、上传成功、其他业务账号不可见、法务正文/风险目前返回 409，以及伪 PNG 被 422 拒绝；使用临时数据库。人工已查看图片文字与排版，但目前没有 CPU OCR 实际识别或坐标输出，也没有 F3 规则审查全链路证据。可用本机 Pillow 和 Noto Sans SC 字体运行 `python -X utf8 samples/build_f3_scan.py --font C:\Windows\Fonts\NotoSansSC-VF.ttf` 重建；这是样例维护工具，不是后端运行依赖。

## F5 严重模糊扫描件子场景

`f5-blurred-scan.png` 是从已验收的 F3 清晰合成合同图片进行半径 22 的高斯模糊后得到的单页灰度图。肉眼查看已无法辨认条款，最深像素也不低于灰度 220；原图与模糊图的哈希、尺寸、预期故障状态和恢复动作记录在 [f5_blurred_expected.json](f5_blurred_expected.json)。样例只含合成内容，无文字层。真实 CPU OCR 处理此固定样例后进入 `blocked/OCR_UNREADABLE/replace_attachment`，没有可靠正文、原文锚点或风险草稿。

上传回执初始为版本 1、`machine_status=pending`；OCR 作业运行后为 `blocked/OCR_UNREADABLE/replace_attachment`，正文与风险快照均不可读取。所属业务账号换传 F3 清晰图片成为版本 2 后可恢复解析，旧版故障记录保留。本机 HTTP 独立冒烟：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_local_http_acceptance.LocalHttpAcceptanceTests.test_f5_blurred_scan_live_proxy_block_replacement_and_permissions -v`，使用临时 SQLite、合成账号、真实 CPU OCR 与 Vite 代理，核对受阻、换件、版本冲突和权限。文件接入冒烟：`python -X utf8 -m unittest tests.test_fixed_samples.FixedSampleSmokeTests.test_f5_blurred_scan_fixed_sample_smoke -v`。可用本机已有 Pillow 执行 `python -X utf8 samples/build_f5_blurred_scan.py` 重建；无需后端运行依赖。其他模糊程度和真实业务扫描件尚未验证。

## F5 加密 PDF 子场景

`f5-encrypted.pdf` 从 F2 的三页合成合同生成；固定哈希、来源与阻塞/恢复预期见 [f5_encrypted_expected.json](f5_encrypted_expected.json)。公开测试用户口令为 `f5-synthetic-user`，所有者口令为 `f5-synthetic-owner`，均只用于本合成样例。RC4-128 是故障样例的兼容性选项，不作为生产加密方案。

先执行 `python -m pip install --target .tools/pdf-fixtures -r samples/requirements-pdf-fixtures.txt` 安装固定版本的样例工具。可运行 `python -X utf8 samples/build_f5_encrypted_pdf.py` 重建；重建后须核对固定哈希。工具目录被 Git 忽略，后端运行无需导入 pypdf。

独立文件冒烟：`python -X utf8 -m unittest tests.test_f5_encrypted_pdf -v`。它核对口令、解密内容和上传后、PDF 作业运行前的 `pending` 状态；不会执行 PDF 作业。后续本机 HTTP 冒烟 `tests.test_local_http_acceptance.LocalHttpAcceptanceTests.test_f5_encrypted_pdf_live_proxy_block_replacement_and_permissions` 已验证作业运行后的 `blocked/PDF_ENCRYPTED/replace_attachment`、无虚假结论及换件恢复。缺少样例工具时文件冒烟明确失败，不跳过。

验收可用 PDF 阅读器打开文件：空口令或错误口令应不能读取，正确口令应显示 F2 三页合同；本轮尚未人工验证阅读器显示。当前上传后仍为 `pending`，未来应由 PDF 处理器识别为 `blocked/replace_attachment`，不从加密内容生成虚假结论。具体错误代码和实际换版恢复待该处理功能实现；本样例通过不代表 F5 全链路完成。

## F6 待办附件首次超时子场景

`f6_pending_timeout.py` 是处理器测试使用的确定性依赖故障源。`fetch_attachment(attempt_number)` 的第一次尝试立即抛出 `TimeoutError`，第二次及以后返回经过 SHA-256 校验的固定 F1 原件；非法尝试号与被篡改原件均拒绝。尝试号由调用方传入，没有进程内“一次性开关”，不同测试或重启不会自行改变故障计划。脚本不访问网络、不等待真实超时、不创建任务，也不保存尝试次数。

运行 `python -X utf8 samples/f6_pending_timeout.py`，预期输出两行 JSON：第一行为 `dependency_outcome=timeout`、`attachment_returned=false`，第二行为 `attachment_available`、`attachment_returned=true` 与 F1 原件哈希。每行都标明 `scope=dependency_fixture_only`。独立冒烟为 `python -X utf8 -m unittest tests.test_f6_pending_timeout -v`，覆盖超时、重试返回固定附件、重复序列、非法尝试号、原件篡改和实际 CLI 输出。

[f6_pending_timeout_expected.json](f6_pending_timeout_expected.json) 的处理器预期已接入 `backend/pending_imports.py`：首次超时为 `blocked/admin_retry`，不得生成解析/风险草稿；管理员按原文档版本重试，附件尝试次数变为 2，保留首次失败记录，不新建附件版本。后端业务冒烟：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_pending_imports -v`，验证 API、权限、持久化、重开连接、过期租约、并发、迟到结果及存储回滚。本机 HTTP 联调：`.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_local_http_acceptance.LocalHttpAcceptanceTests.test_f6_pending_attachment_timeout_live_proxy_admin_retry_and_permissions -v`，经 Vite 代理核对受阻、管理员重试、同版解析与历史；该联调已由用户验收。技术验证使用故障注入，不代表真实平台网络超时。当前 API 仍只列出 `demo-f1-001`，没有新增 F6 待办 ID；正常导入不故意制造超时。

## F6 首次模拟回写失败与重复提交子场景

`f6_writeback_failure.py` 是仅在内存中运行的合成评论依赖。运行 `python -X utf8 samples/f6_writeback_failure.py` 得到四行 JSON：首次失败、同版重试成功、同版重复提交返回同一评论 ID 且不新增评论、新确认版本得到独立 ID。每行均标记 `scope=in_memory_dependency_fixture_only`，评论正文包含“模拟回写”。静态结果和未来应用状态预期见 [f6_writeback_expected.json](f6_writeback_expected.json)。

独立冒烟 `python -X utf8 -m unittest tests.test_f6_writeback_failure -v` 核对首次失败无评论、重试与同版去重、不同版本独立评论、同键不同内容拒绝、参数边界和脚本实际输出。此故障依赖本身不写入 SQLite 或连接真实审批平台；进程重启后其内存评论不存在。应用已通过 `backend/writeback.py` 将同版模拟回写状态、尝试历史和评论持久化到 SQLite；后端冒烟 `tests.test_writeback` 覆盖确认前拒绝、跨连接幂等与角色权限。本机 HTTP 联调 `tests.test_local_http_acceptance.LocalHttpAcceptanceTests.test_f6_writeback_failure_live_proxy_retry_dedup_and_permissions` 经 Vite 代理核对首次失败、重试、去重与权限，待用户验收。真实审批平台回写与浏览器点击仍未验证。
