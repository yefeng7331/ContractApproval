"""Fixed synthetic approval item and attachment for the local demo."""

from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import escape


MOCK_PENDING_ID = "demo-f1-001"
MOCK_PENDING_ITEM = {
    "id": MOCK_PENDING_ID,
    "title": "合成软件采购合同（演示待办）",
    "department": "采购部",
    "applicant": "张三",
    "business_type": "软件采购",
    "attachment_filename": "synthetic-software-purchase.docx",
    "synthetic": True,
}

_PARAGRAPHS = (
    "合成软件采购合同（仅供演示，非真实交易）",
    "合同编号：SYN-2026-001",
    "送审部门：采购部；申请人：张三",
    "采购方：甲方演示科技有限公司；供应商：乙方演示软件有限公司",
    "采购金额：人民币100000元；履行期限：2026年10月1日至2026年12月31日",
    "标的：乙方向甲方交付软件系统及相关文档。",
    "付款：软件到货后，甲方一次性支付全部合同价款。",
    "验收：双方未约定交付成果的验收标准、程序或付款前验收条件。",
    "知识产权：交付软件及相关成果的全部知识产权归乙方所有，甲方不享有持续使用授权。",
    "违约：违约事项由双方另行协商。",
    "保密：双方对履约中知悉的非公开信息保密。",
    "争议解决：双方协商不成时向有管辖权的人民法院起诉。",
)


def _package_paragraphs(paragraphs: tuple[str, ...]) -> bytes:
    body = "".join(
        f"<w:p><w:r><w:t>{escape(paragraph)}</w:t></w:r></w:p>"
        for paragraph in paragraphs
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}<w:sectPr/></w:body></w:document>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '</Types>'
    )
    relationships = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        '</Relationships>'
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", relationships)
        archive.writestr("word/document.xml", document)
    return output.getvalue()


def synthetic_attachment() -> bytes:
    """Return the existing F1-candidate DOCX bytes for the mock pending item."""
    return _package_paragraphs(_PARAGRAPHS)


def synthetic_revised_attachment() -> bytes:
    """Return an F4-candidate DOCX with explicit license and acceptance milestones."""
    replacements = {
        "付款：软件到货后，甲方一次性支付全部合同价款。":
            "付款：甲方在交付成果经双方按约定标准验收合格后分期支付合同价款。",
        "验收：双方未约定交付成果的验收标准、程序或付款前验收条件。":
            "验收：双方按功能清单逐项测试并签署验收记录；未通过项目整改后复验。",
        "知识产权：交付软件及相关成果的全部知识产权归乙方所有，甲方不享有持续使用授权。":
            "知识产权：交付软件及相关成果的知识产权归乙方所有，甲方享有满足项目目的的持续使用授权。",
    }
    return _package_paragraphs(tuple(replacements.get(p, p) for p in _PARAGRAPHS))
