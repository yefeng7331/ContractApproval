"""Generate the v0.2 pen.dev design board from the documented UI contract.

This creates design data only; it is not a frontend implementation.
"""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "pencil-new.pen"

C = {
    "paper": "#F4F6F3", "white": "#FFFFFF", "ink": "#172B25",
    "muted": "#53635B", "faint": "#68786F", "line": "#D9E2DA",
    "accent": "#1D6953", "accent_soft": "#E5F1EA", "nav": "#11261F",
    "nav_muted": "#B8C8BF", "red": "#9E433A", "red_soft": "#F8ECE8",
    "amber": "#8A6226", "amber_soft": "#F5EEDD", "gray_soft": "#EFF2EE",
    "line_strong": "#BCCBC0", "surface_tint": "#EAF0EA",
}

children = []
count = 0


def ident(name):
    global count
    count += 1
    safe_name = name.replace(" ", "_").replace("/", "_")
    return f"n{count:04d}_{safe_name}"


def frame(parent, name, x, y, w, h, fill=None, radius=0, stroke=None):
    item = {"id": ident(name), "type": "frame", "name": name,
            "x": x, "y": y, "width": w, "height": h,
            "layout": "none", "children": []}
    if fill:
        item["fill"] = fill
    if radius:
        item["cornerRadius"] = radius
    if stroke:
        item["stroke"] = stroke
        item["strokeWidth"] = 1
    parent.append(item)
    return item["children"]


def rect(parent, name, x, y, w, h, fill, radius=0, stroke=None):
    item = {"id": ident(name), "type": "rectangle", "name": name,
            "x": x, "y": y, "width": w, "height": h, "fill": fill}
    if radius:
        item["cornerRadius"] = radius
    if stroke:
        item["stroke"] = stroke
        item["strokeWidth"] = 1
    parent.append(item)
    return item


def text(parent, name, x, y, w, content, size=14, color=None, weight="400", h=None):
    item = {"id": ident(name), "type": "text", "name": name,
            "x": x, "y": y, "width": w, "content": content,
            "textGrowth": "fixed-width", "fontFamily": "Microsoft YaHei",
            "fontSize": size, "fontWeight": weight,
            "lineHeight": 1.42, "fill": color or C["ink"]}
    if h:
        item["height"] = h
        item["textGrowth"] = "fixed-width-height"
    parent.append(item)
    return item


def rule(parent, name, x, y, w, color=None):
    rect(parent, name, x, y, w, 1, color or C["line"])


def pill(parent, name, x, y, w, label, bg, fg, border=None):
    rect(parent, name, x, y, w, 28, bg, 14, border)
    text(parent, name + " label", x + 12, y + 5, w - 24, label, 12, fg, "600")


def button(parent, name, x, y, w, label, primary=False, disabled=False):
    bg = C["gray_soft"] if disabled else C["accent"] if primary else C["white"]
    fg = C["faint"] if disabled else C["white"] if primary else C["ink"]
    rect(parent, name, x, y, w, 38, bg, 9, None if primary else C["line"])
    text(parent, name + " label", x + 15, y + 9, w - 30, label, 13, fg, "600")


def shell(parent, title, role, active="任务大盘", width=1440):
    rect(parent, "navigation", 0, 0, 222, 900, C["nav"])
    rect(parent, "brand mark", 27, 25, 32, 32, C["accent"], 9)
    text(parent, "brand letter", 37, 29, 20, "审", 17, C["white"], "700")
    text(parent, "brand", 69, 24, 130, "合同审查", 19, C["white"], "700")
    text(parent, "brand caption", 69, 50, 135, "CONTRACT REVIEW", 9, C["nav_muted"], "600")
    text(parent, "nav workspace", 28, 106, 150, "工作空间", 11, C["nav_muted"], "600")
    if role == "业务经办人":
        navigation = ["任务大盘", "合同接入", "已确认报告"]
    elif role == "法务审查人":
        navigation = ["任务大盘", "审查工作台", "交付与回写"]
    else:
        navigation = ["任务状态", "故障与恢复"]
    for i, label in enumerate(navigation):
        yy = 142 + i * 53
        if label == active:
            rect(parent, "selected navigation", 12, yy - 7, 198, 40, "#24443A", 9)
            rect(parent, "selected marker", 12, yy - 7, 3, 40, "#61BA97", 1)
        text(parent, "nav " + label, 32, yy, 160, label, 14,
             C["white"] if label == active else C["nav_muted"], "600" if label == active else "400")
    rule(parent, "nav footer divider", 26, 801, 168, "#35514A")
    text(parent, "nav demo notice", 28, 819, 178, "合成数据演示版 · v0.2 设计", 11, C["nav_muted"])
    text(parent, "page title", 266, 32, 850, title, 28, C["ink"], "700")
    pill(parent, "role", width - 184, 34, 136, role, C["accent_soft"], C["accent"])
    rule(parent, "header separator", 266, 82, width - 312)


def status_trio(parent, x, y, machine, legal, writeback, w=1088):
    rect(parent, "status strip", x, y, w, 71, C["white"], 12, C["line"])
    col = w / 3
    for i, (label, value) in enumerate([("机器审查", machine), ("法务复核", legal), ("模拟回写", writeback)]):
        xx = x + 22 + i * col
        if i:
            rect(parent, "status separator", x + i * col, y + 16, 1, 39, C["line"])
        state_color = (C["red"] if any(term in value for term in ("受阻", "失败"))
                       else C["accent"] if any(term in value for term in ("已完成", "已确认", "成功"))
                       else C["amber"])
        text(parent, label + " title", xx, y + 10, col - 44, label, 12, C["muted"], "600")
        rect(parent, label + " semantic marker", xx, y + 43, 7, 7, state_color, 4)
        text(parent, label + " value", xx + 17, y + 31, col - 61, value, 15, C["ink"], "700")


# 01 — Local sign-in
p = frame(children, "01 登录 · 本地测试账号", 0, 0, 1440, 900, C["paper"])
rect(p, "left field", 0, 0, 656, 900, C["nav"])
rect(p, "brand mark", 58, 58, 40, 40, C["accent"], 11)
text(p, "brand letter", 70, 65, 24, "审", 21, C["white"], "700")
text(p, "brand", 111, 63, 260, "合同审查", 25, C["white"], "700")
text(p, "opening statement", 60, 238, 490, "让每一个审查结论，\n都能回到原文。", 43, C["white"], "700")
text(p, "opening explanation", 62, 378, 470, "从合同接入、证据定位，到法务复核与报告交付。\n同一任务里看清来源、版本和责任。", 17, C["nav_muted"])
rule(p, "left anchor", 62, 726, 506, "#49675C")
text(p, "demo scope", 62, 750, 490, "中国大陆软件采购合同 · 合成数据演示 · 非正式法律意见", 13, C["nav_muted"])
text(p, "login heading", 805, 194, 420, "登录工作空间", 31, C["ink"], "700")
text(p, "login subhead", 806, 245, 420, "使用本地测试账号继续", 15, C["muted"])
text(p, "username label", 806, 315, 400, "账号", 14, C["ink"], "600")
rect(p, "username field", 805, 342, 420, 49, C["white"], 9, C["line"])
text(p, "username hint", 822, 356, 385, "请输入本地测试账号", 14, C["faint"])
text(p, "password label", 806, 419, 400, "密码", 14, C["ink"], "600")
rect(p, "password field", 805, 446, 420, 49, C["white"], 9, C["line"])
text(p, "password hint", 822, 460, 385, "请输入密码", 14, C["faint"])
button(p, "sign in", 805, 525, 420, "登录", True)
text(p, "login security", 806, 588, 418, "会话仅在本次浏览器页面中有效；刷新后需要重新登录。", 12, C["muted"])
rect(p, "login error specimen", 805, 649, 420, 66, C["red_soft"], 9)
text(p, "login error", 822, 662, 380, "错误状态示例 · 账号或密码不正确", 13, C["red"], "600")
text(p, "login error action", 822, 684, 380, "请核对后重试。", 12, C["red"])

# 02 — Business dashboard
p = frame(children, "02 任务大盘 · 业务经办人", 1680, 0, 1440, 900, C["paper"])
shell(p, "任务大盘", "业务经办人")
text(p, "dashboard hint", 267, 105, 735, "查看本人合同的处理进度与已确认结果", 14, C["muted"])
button(p, "import mock", 1005, 103, 147, "导入模拟待办")
button(p, "upload", 1164, 103, 230, "上传合成合同", True)
text(p, "overview heading", 266, 173, 700, "先看进度，再看结论。", 30, C["ink"], "700")
text(p, "overview note", 267, 224, 1000,
     "当前版本的处理状态与历史已确认结果分开呈现；尚未确认的草稿不作为正式结论。", 14, C["muted"])
rule(p, "overview top rule", 266, 266, 1128, C["line_strong"])
for xx, heading, detail, marker in [
    (267, "待法务确认", "2 份 · 草稿仅法务可见", C["amber"]),
    (641, "报告可用", "1 份 · 同版已确认", C["accent"]),
    (1016, "处理受阻", "1 份 · 查看恢复路径", C["red"]),
]:
    rect(p, "overview marker", xx, 288, 8, 8, marker, 4)
    text(p, "overview state", xx + 18, 278, 250, heading, 15, C["ink"], "700")
    text(p, "overview detail", xx + 18, 305, 325, detail, 12, C["muted"])
rule(p, "overview bottom rule", 266, 336, 1128, C["line_strong"])
text(p, "task section", 266, 363, 480, "我的合同", 20, C["ink"], "700")
text(p, "table count", 1296, 369, 98, "共 4 项", 12, C["muted"])
rect(p, "filter status", 266, 410, 184, 38, C["white"], 9, C["line"])
text(p, "filter status text", 281, 420, 150, "状态：全部  ▾", 13, C["ink"])
rect(p, "filter risk", 462, 410, 184, 38, C["white"], 9, C["line"])
text(p, "filter risk text", 477, 420, 150, "风险：全部  ▾", 13, C["ink"])
rect(p, "table", 266, 467, 1128, 355, C["white"], 12, C["line"])
rect(p, "table header", 267, 468, 1126, 48, C["gray_soft"], 11)
for xx, label in [(288, "合同 / 申请人"), (664, "金额"), (782, "机器审查"), (916, "法务复核"), (1044, "模拟回写"), (1192, "当前正式等级")]:
    text(p, "column " + label, xx, 482, 184, label, 12, C["muted"], "600")
rows = [
    ("软件采购合同 A · 张明", "¥ 480,000", "草稿完成", "待复核", "未回写", "—", "文档 V2 · 旧版已确认 V1"),
    ("软件采购合同 B · 李晴", "¥ 260,000", "已完成", "已确认", "模拟成功", "高", "文档 V1 · 审查 V1"),
    ("软件采购合同 C · 张明", "¥ 320,000", "解析中", "待复核", "未回写", "—", "文档 V1 · 当前无结论"),
    ("软件采购合同 D · 李晴", "¥ 175,000", "受阻", "待复核", "未回写", "—", "文档 V1 · 附件加密"),
]
for i, row in enumerate(rows):
    yy = 516 + i * 76
    if i:
        rule(p, "row divider", 283, yy, 1093)
    text(p, "contract", 288, yy + 13, 350, row[0], 14, C["ink"], "600")
    text(p, "version note", 288, yy + 38, 350, row[6], 11, C["muted"])
    for xx, val, ww in [(664, row[1], 112), (782, row[2], 130), (916, row[3], 122), (1044, row[4], 145), (1192, row[5], 120)]:
        color = C["red"] if val in ("受阻", "高") else C["accent"] if val in ("已确认", "模拟成功") else C["ink"]
        text(p, "row state", xx, yy + 25, ww, val, 13, color, "600")
text(p, "dashboard disclaimer", 266, 842, 1120, "画板中的名称、金额及状态为合成示意；接口和权限仍需实施与验证。", 11, C["muted"])

# 03 — Legal workbench
p = frame(children, "03 双栏审查工作台 · 法务", 3360, 0, 1600, 900, C["paper"])
shell(p, "软件采购合同 A", "法务审查人", "审查工作台", 1600)
text(p, "breadcrumb", 266, 96, 930, "任务大盘  /  软件采购合同 A  /  文档 V1 · 审查草稿 V1", 12, C["muted"])
pill(p, "draft badge", 1360, 101, 187, "机器草稿 · 待法务确认", C["amber_soft"], C["amber"])
status_trio(p, 266, 144, "已完成 · 可复核", "复核中 · 未确认", "未回写", 1282)
text(p, "document heading", 268, 235, 550, "合同原文与证据", 19, C["ink"], "700")
text(p, "risk heading", 1054, 235, 450, "风险与法务意见", 19, C["ink"], "700")
rect(p, "preview outer", 266, 270, 764, 565, C["white"], 12, C["line"])
rect(p, "preview toolbar", 267, 271, 762, 50, C["gray_soft"], 11)
text(p, "preview filename", 288, 284, 340, "F1_软件采购合同.pdf  ·  文档 V1", 13, C["ink"], "600")
text(p, "page control", 813, 284, 193, "‹    第 3 / 8 页    ›", 13, C["ink"], "600")
rect(p, "pdf area", 286, 338, 724, 476, "#E9EEEA", 6)
rect(p, "pdf page", 401, 354, 496, 443, C["white"], 2)
text(p, "pdf title", 442, 382, 414, "软件采购合同", 20, C["ink"], "700")
text(p, "pdf intro", 442, 432, 414, "甲方与乙方就软件采购与交付达成以下约定。", 12, C["muted"])
text(p, "pdf clause title", 442, 486, 414, "第五条  付款与验收", 14, C["ink"], "700")
rect(p, "selected original highlight", 438, 523, 421, 74, C["accent_soft"], 4, C["accent"])
text(p, "selected clause", 447, 531, 404, "软件到货后，甲方于五个工作日内一次性支付\n全部合同价款。", 13, C["ink"])
text(p, "pdf missing", 442, 619, 405, "验收条件：原文未找到。", 12, C["red"], "600")
text(p, "pdf footer", 442, 748, 405, "页码与高亮来自文档 V1 的固定预览", 11, C["muted"])
rect(p, "risk panel", 1050, 270, 498, 565, C["white"], 12, C["line"])
text(p, "risk summary", 1074, 286, 440, "机器发现 2 项企业演示规则风险", 15, C["ink"], "700")
text(p, "not final", 1074, 309, 440, "草稿仅供复核 · 正式结论由法务确认", 11, C["muted"])
rule(p, "risk divider", 1074, 342, 450)
pill(p, "risk selected badge", 1074, 358, 74, "高风险", C["red_soft"], C["red"])
text(p, "risk title", 1161, 362, 340, "付款先于可核验验收", 15, C["ink"], "700")
text(p, "rule id", 1075, 397, 438, "企业规则  DEMO-PAY-01  ·  版本 1", 11, C["muted"])
text(p, "quoted source", 1075, 421, 440, "原文：“到货后五个工作日内一次性支付全部价款”\n关联缺失：验收条款未找到", 12, C["ink"])
rect(p, "draft advice", 1074, 476, 450, 75, C["gray_soft"], 7)
text(p, "draft advice text", 1087, 486, 424, "模型建议 · 草稿\n建议法务考虑按可核验交付与验收节点付款。", 12, C["muted"])
text(p, "legal input label", 1075, 566, 442, "法务意见 · 待保存", 12, C["ink"], "600")
rect(p, "legal input", 1074, 590, 450, 78, C["white"], 7, C["line"])
text(p, "legal input example", 1087, 603, 424, "建议补充可执行验收条件，再确定付款节点。", 12, C["ink"])
button(p, "copy suggestion", 1074, 686, 132, "复制建议")
button(p, "save legal changes", 1216, 686, 139, "保存修改")
button(p, "confirm version", 1365, 686, 159, "确认审查 V1", True)
rule(p, "second risk divider", 1074, 742, 450)
pill(p, "second risk badge", 1074, 757, 74, "高风险", C["red_soft"], C["red"])
text(p, "second risk", 1161, 761, 340, "软件使用权安排缺失  ·  DEMO-IP-01", 13, C["ink"], "600")
text(p, "workbench footer", 266, 851, 1280, "交互说明：点右侧风险跳到同版原文；点高亮选中风险。定位失败时仅展示摘录与原因，不画精准高亮。", 11, C["muted"])

# 04 — Business in-progress and historical snapshot
p = frame(children, "04 当前待审与历史快照 · 业务", 0, 1040, 1440, 900, C["paper"])
shell(p, "软件采购合同 A", "业务经办人", "任务大盘")
text(p, "current version", 266, 105, 850, "当前文档 V2  ·  提交于 2026-09-23 10:32", 14, C["muted"])
pill(p, "pending badge", 1182, 100, 212, "当前版本尚无法务结论", C["amber_soft"], C["amber"])
status_trio(p, 266, 158, "审查中", "待复核", "未回写", 1128)
rect(p, "progress panel", 266, 255, 1128, 215, C["white"], 12, C["line"])
text(p, "progress title", 291, 278, 720, "当前进度", 20, C["ink"], "700")
text(p, "progress explanation", 291, 314, 1000, "文档已接收，机器审查正在进行。当前版本的风险、原文预览和报告在法务确认前不可查看。", 14, C["muted"])
rect(p, "progress track", 291, 373, 1062, 5, C["gray_soft"], 2)
rect(p, "progress completed", 291, 373, 560, 5, C["accent"], 2)
for xx, title, detail in [(291, "已接收", "10:32"), (630, "解析完成", "10:33"), (1002, "审查中", "正在处理")]:
    rect(p, "progress dot", xx, 367, 16, 16, C["accent"], 8)
    text(p, "progress step", xx, 398, 230, title, 13, C["ink"], "600")
    text(p, "progress time", xx, 421, 230, detail, 11, C["muted"])
text(p, "history title", 266, 507, 600, "历史已确认快照", 20, C["ink"], "700")
text(p, "history explain", 266, 538, 1010, "以下结果仅属于旧版，不代表当前文档 V2 的结论。", 13, C["muted"])
rect(p, "history card", 266, 580, 1128, 169, C["white"], 12, C["line"])
pill(p, "history version", 290, 601, 170, "文档 V1 · 审查 V1", C["gray_soft"], C["ink"])
text(p, "history conclusion", 290, 646, 750, "旧版正式结论：建议整改后复核", 18, C["ink"], "700")
text(p, "history confirmation", 290, 681, 750, "确认人：法务审查人  ·  确认时间：2026-09-22 16:40", 12, C["muted"])
button(p, "open historical", 1186, 646, 180, "查看旧版正式结果")
text(p, "history note", 266, 784, 1128, "当前正式风险等级：—　　当前报告：未生成　　旧版报告仅在该快照内查看", 13, C["muted"])

# 05 — Legal delivery and simulated writeback
p = frame(children, "05 报告与模拟回写 · 法务", 1680, 1040, 1440, 900, C["paper"])
shell(p, "交付与回写", "法务审查人", "交付与回写")
text(p, "delivery task", 266, 104, 1080, "软件采购合同 A  ·  文档 V1  ·  已确认审查 V1", 15, C["ink"], "600")
status_trio(p, 266, 145, "已完成", "已确认 · 16:40", "未回写", 1128)
text(p, "report heading", 266, 248, 650, "同版报告", 20, C["ink"], "700")
text(p, "report explanation", 266, 280, 1100, "两种格式均依据审查 V1 的确认快照生成，状态各自独立。", 13, C["muted"])
rect(p, "report markdown", 266, 326, 546, 165, C["white"], 12, C["line"])
pill(p, "markdown ready", 289, 348, 73, "已生成", C["accent_soft"], C["accent"])
text(p, "markdown title", 289, 387, 260, "Markdown 报告", 17, C["ink"], "700")
text(p, "markdown version", 289, 417, 300, "审查 V1 · 2026-09-23 10:48", 12, C["muted"])
button(p, "markdown preview", 594, 390, 92, "预览")
button(p, "markdown download", 696, 390, 92, "下载")
rect(p, "report pdf", 832, 326, 562, 165, C["white"], 12, C["line"])
pill(p, "pdf failed", 856, 348, 73, "生成失败", C["red_soft"], C["red"])
text(p, "pdf title", 856, 387, 280, "PDF 报告", 17, C["ink"], "700")
text(p, "pdf reason", 856, 417, 400, "生成超时；法务确认状态保持不变。", 12, C["muted"])
button(p, "retry pdf", 1266, 390, 104, "重试 PDF")
text(p, "writeback heading", 266, 539, 650, "模拟回写", 20, C["ink"], "700")
text(p, "writeback explanation", 266, 571, 1090, "只向本地模拟审批单的评论区写入已确认版本；不连接真实平台。", 13, C["muted"])
rect(p, "writeback panel", 266, 617, 1128, 172, C["white"], 12, C["line"])
text(p, "writeback target label", 290, 638, 360, "目标模拟审批单", 11, C["muted"], "600")
text(p, "writeback target", 290, 660, 420, "MOCK-2026-0098", 16, C["ink"], "700")
text(p, "writeback version", 290, 700, 500, "引用版本：文档 V1 · 已确认审查 V1", 12, C["muted"])
rect(p, "writeback divider", 828, 639, 1, 129, C["line"])
pill(p, "writeback failed", 853, 638, 86, "首次失败", C["red_soft"], C["red"])
text(p, "writeback reason", 853, 676, 492, "模拟评论保存失败；保留尝试记录，可对同一版本重试。", 12, C["ink"])
button(p, "writeback retry", 1219, 724, 151, "重试模拟回写", True)
text(p, "writeback id note", 266, 813, 1120, "成功状态显示评论 ID；重复提交返回同一评论，不新建第二条同版评论。", 12, C["muted"])

# 06 — Admin recovery
p = frame(children, "06 受阻恢复 · 管理员", 3360, 1040, 1440, 900, C["paper"])
shell(p, "故障与恢复", "系统管理员", "故障与恢复")
text(p, "admin subtitle", 266, 106, 1010, "查看任务状态与恢复指引；管理员不进入合同原文与法务编辑区。", 14, C["muted"])
pill(p, "admin scope", 1216, 106, 178, "仅状态与故障", C["gray_soft"], C["ink"])
text(p, "blocked heading", 266, 179, 680, "需要处理的任务", 20, C["ink"], "700")
rect(p, "blocked list", 266, 221, 1128, 505, C["white"], 12, C["line"])
blocked = [
    ("F5 · 加密 PDF", "解析受阻", "附件受密码保护，无法读取正文", "业务重新上传附件", False),
    ("F5 · OCR 暂时失败", "解析受阻", "OCR 临时故障 · 已尝试 2 次", "管理员重试", True),
    ("F6 · 模拟待办超时", "接入受阻", "附件读取超时 · 已尝试 1 次", "管理员重试", True),
    ("模型费用预算", "审查受阻", "预计调用将超过 50 元预算", "等待用户预算决定", False),
]
for i, (name, status, reason, action, allowed) in enumerate(blocked):
    yy = 244 + i * 119
    if i:
        rule(p, "blocked row rule", 289, yy - 15, 1081)
    text(p, "blocked task", 290, yy, 320, name, 15, C["ink"], "700")
    pill(p, "blocked state", 617, yy - 2, 100, status, C["red_soft"], C["red"])
    text(p, "blocked reason", 290, yy + 32, 790, reason, 12, C["muted"])
    text(p, "blocked action", 290, yy + 58, 550, "恢复路径：" + action, 12, C["ink"], "600")
    if allowed:
        button(p, "admin retry", 1214, yy + 30, 151, "按原版本重试")
    else:
        pill(p, "admin no action", 1171, yy + 33, 194, "此角色不可直接操作", C["gray_soft"], C["muted"])
rect(p, "admin boundary", 266, 757, 1128, 79, C["accent_soft"], 10)
text(p, "admin boundary text", 286, 775, 1076,
     "权限边界  ·  管理员仅重试允许的暂时故障；不可代法务确认或回写，也不可自行提高模型预算。", 13, C["accent"], "600")

# 07 — Interaction and semantic-state notes live on the same board
p = frame(children, "07 交互与状态说明 · v0.1", 0, 2080, 1440, 430, C["white"])
text(p, "note heading", 48, 39, 1190, "v0.1 交互与视觉约束", 26, C["ink"], "700")
rule(p, "note divider", 48, 93, 1344)
notes = [
    ("版本", "所有预览、高亮、风险、编辑和报告均绑定明确文档与审查版本；切换版本清除旧选中。"),
    ("定位", "可定位时卡片与原文双向选中；不可定位时显示摘录、可靠页段和原因，不伪造高亮。"),
    ("权限", "业务仅见本人当前进度与已确认快照；管理员仅见状态与恢复；法务编辑与确认单独授权。"),
    ("状态", "机器、法务、模拟回写始终分列；报告 Markdown/PDF 独立显示 pending、ready、failed。"),
    ("反馈", "包括登录失效、无权、版本冲突、附件拒绝、异步受阻、报告失败和回写重试。"),
]
for i, (label, body) in enumerate(notes):
    yy = 119 + i * 57
    pill(p, "note label", 48, yy, 88, label, C["accent_soft"], C["accent"])
    text(p, "note body", 158, yy + 3, 1210, body, 14, C["ink"])

# 08 — Business intake through file upload or a fixed mock pending item
p = frame(children, "08 合同接入 · 业务经办人", 1680, 2080, 1440, 900, C["paper"])
shell(p, "接入合同", "业务经办人")
text(p, "intake lead", 266, 104, 1050,
     "上传合成样本，或从固定模拟待办导入。提交后先创建任务，再异步处理附件与审查。", 14, C["muted"])
rect(p, "upload surface", 266, 148, 650, 551, C["white"], 14, C["line"])
text(p, "upload heading", 290, 174, 500, "上传本地合同", 19, C["ink"], "700")
pill(p, "business upload only", 747, 170, 140, "仅业务经办人", C["accent_soft"], C["accent"])
rect(p, "drop area", 290, 222, 602, 182, C["paper"], 12, C["line"])
rect(p, "document icon", 554, 260, 54, 60, C["accent_soft"], 8)
text(p, "document glyph", 572, 272, 28, "文", 24, C["accent"], "700")
text(p, "drop heading", 417, 330, 365, "选择 DOCX、PDF 或扫描件", 16, C["ink"], "600")
text(p, "drop hint", 419, 365, 370, "上传后将进行解析；受阻时显示原因与恢复入口", 12, C["muted"])
text(p, "file label", 290, 428, 450, "已选择的合成附件", 12, C["muted"], "600")
rect(p, "file selected", 290, 453, 602, 58, C["accent_soft"], 9)
text(p, "file name", 309, 467, 450, "软件采购合同_F1.docx", 14, C["ink"], "600")
text(p, "file details", 309, 490, 450, "DOCX  ·  合成测试样本  ·  待提交", 11, C["muted"])
text(p, "type field label", 290, 535, 240, "业务类型", 12, C["muted"], "600")
rect(p, "type field", 290, 561, 286, 43, C["white"], 8, C["line"])
text(p, "type value", 305, 571, 255, "软件采购", 13, C["ink"])
text(p, "amount field label", 606, 535, 240, "合同金额", 12, C["muted"], "600")
rect(p, "amount field", 606, 561, 286, 43, C["white"], 8, C["line"])
text(p, "amount value", 621, 571, 255, "¥ 480,000", 13, C["ink"])
button(p, "create task", 732, 634, 160, "创建审查任务", primary=True)
text(p, "upload disclaimer", 290, 646, 430,
     "文件类型与大小由服务端校验；失败时保留本页说明。", 11, C["muted"])

rect(p, "mock pending surface", 940, 148, 454, 551, C["white"], 14, C["line"])
text(p, "mock heading", 964, 174, 265, "固定模拟待办", 19, C["ink"], "700")
pill(p, "mock label", 1276, 170, 94, "模拟入口", C["amber_soft"], C["amber"])
text(p, "mock description", 964, 210, 390,
     "仅演示从待办读取合成附件及审批单信息。", 12, C["muted"])
rule(p, "mock divider", 964, 249, 406)
text(p, "mock id", 964, 273, 300, "MOCK-2026-0098", 15, C["ink"], "700")
pill(p, "mock pending status", 1255, 268, 115, "待导入", C["gray_soft"], C["muted"])
text(p, "mock title", 964, 310, 390, "软件采购合同 A · 采购申请", 14, C["ink"], "600")
text(p, "mock metadata", 964, 346, 390, "申请人  张雨  ·  金额  ¥ 480,000", 12, C["muted"])
text(p, "mock attachment", 964, 378, 390, "附件  软件采购合同_F1.docx", 12, C["muted"])
rect(p, "mock callout", 964, 437, 406, 81, C["amber_soft"], 9)
text(p, "mock callout text", 981, 450, 372,
     "模拟导入也会创建独立任务；附件处理超时仍保留任务与受阻状态。", 12, C["amber"])
button(p, "import pending", 1198, 634, 172, "导入模拟待办")

rect(p, "created progress surface", 266, 726, 1128, 110, C["white"], 12, C["line"])
pill(p, "created status", 288, 745, 108, "任务已创建", C["accent_soft"], C["accent"])
text(p, "created task", 410, 749, 430, "TASK-F1-002  ·  附件解析中", 14, C["ink"], "600")
text(p, "created warning", 288, 786, 1060,
     "已接收只代表任务创建成功；机器审查、法务确认与模拟回写继续分别显示，不提前标记为完成。", 13, C["muted"])

document = {"version": "2.18", "children": children}
OUT.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Wrote {OUT} with {len(children)} artboards and {count} nodes")
