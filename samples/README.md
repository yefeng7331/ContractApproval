# F1/F4 合成合同固定样例（页码标注前）

此目录只含虚构主体与交易。`f1-software-purchase.docx` 对应模拟待办 `demo-f1-001` 的正文；`f4-revised-software-purchase.docx` 只修改付款、验收、知识产权三个段落。固定文件的 SHA-256、12 项字段、7 项已识别条款、缺失的数据安全条款、段落及零起始 Unicode 字符区间、两条规则的等级/证据/建议都在 [f1_f4_expected.json](f1_f4_expected.json)。空字段以 `null` 表示“未识别”，不代表合同事实不存在。

| 样例 | 当前规则预期 | 机器建议 |
| --- | --- | --- |
| F1 | `DEMO-IP-01`、`DEMO-PAY-01`，各为高风险规则草稿 | 建议拒绝并整改 |
| F4 | 两条已启用规则均不命中；不推断低风险或法律安全 | 待法务复核 |

位置契约：每条已识别字段和条款的 `start/end` 指向对应 DOCX 的 NFC 规范化全文，`end` 不包含末字符；`paragraph_index` 从 0 开始。当前无固定 PDF 预览，所有页码、区域及精准高亮预期均为 `UNVERIFIED`，现有组件返回 `page=null`、`locatable=false`、`PREVIEW_NOT_AVAILABLE`。生成预览后须为每份样例单独补充人工复核的页码与区域，不能用 F1 页码推断 F4 或后续 F2/F3。

可单独运行 `python -X utf8 -m unittest tests.test_fixed_samples.FixedSampleSmokeTests.test_f1_f4_fixed_sample_smoke -v`。测试只读取本目录附件与答案清单，校验固定文件哈希、模拟待办正文一致、字段/条款/风险逐项结果及 F4 不误报；不使用数据库、模型或外部平台。法务确认、真实模型调用和正式 F1/F4 全链路验收均尚无证据。
