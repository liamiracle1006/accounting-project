"""
AgentLedger V4.0 — Vision 解析引擎（图片/PDF → StandardReceiptItem）(Sprint 3.5)

复用 services/ocr_service._call_vision_llm() 的 Vision API 调用基础设施，
通过专用批处理 Prompt 驱动 LLM 提取 StandardReceiptItem 格式的数据。

支持格式：
  图片：image/jpeg, image/png, image/webp
  PDF ：application/pdf

设计约束：
  - 每个 UploadFile 独立调用一次 Vision API
  - 单张图片可含多张票据（如合订本扫描）→ 返回多条 StandardReceiptItem
  - 单文件调用失败时 → 记录 warning，继续处理下一文件，不中断整批
  - VISION_API_KEY 未配置时 → 返回空列表（不报错）
"""
import json
import logging
import re
from typing import Any

from fastapi import UploadFile

from schemas.batch_schemas import StandardReceiptItem

logger = logging.getLogger(__name__)

# ── 批量票据提取专用 Prompt ────────────────────────────────────────────────────
_BATCH_EXTRACT_PROMPT = (
    "请从图片中识别所有票据/发票/收据的关键信息，"
    "以 JSON 数组格式返回，每张票据一个元素，包含以下字段：\n"
    "  date         : 日期，格式 YYYY-MM-DD（字符串）\n"
    "  amount       : 税后总金额（正数 float，单位：元）\n"
    "  counterparty : 对方单位名称（字符串，识别不到则 null）\n"
    "  summary      : 业务摘要/品名/用途（字符串）\n"
    "只返回 JSON 数组，不要任何说明文字。\n"
    "示例：\n"
    '[{"date":"2025-03-15","amount":3600.00,'
    '"counterparty":"阿里云计算有限公司","summary":"服务器费用"}]'
)


async def extract_from_images(files: list[UploadFile]) -> list[StandardReceiptItem]:
    """
    对每个图片/PDF 文件调用 Vision LLM，提取票据信息。

    参数：
      files — FastAPI UploadFile 列表（图片或 PDF）

    返回：
      所有文件的 StandardReceiptItem 汇总（顺序：按文件顺序拼接）
    """
    from services.ocr_service import _call_vision_llm

    results: list[StandardReceiptItem] = []
    for file in files:
        content   = await file.read()
        mime_type = file.content_type or _guess_mime(file.filename or "")
        try:
            raw   = _call_vision_llm(content, mime_type, prompt=_BATCH_EXTRACT_PROMPT)
            items = _parse_batch_output(raw)
            for raw_item in items:
                receipt = _to_receipt_item(raw_item)
                if receipt is not None:
                    results.append(receipt)
            logger.info("Vision 解析 '%s': %d 条记录", file.filename, len(items))
        except Exception as exc:
            logger.warning("Vision 解析失败 '%s': %s", file.filename, exc)

    return results


# ── 内部辅助 ──────────────────────────────────────────────────────────────────

def _guess_mime(filename: str) -> str:
    fn = filename.lower()
    if fn.endswith(".pdf"):   return "application/pdf"
    if fn.endswith(".png"):   return "image/png"
    if fn.endswith(".webp"):  return "image/webp"
    return "image/jpeg"


def _parse_batch_output(raw: str) -> list[dict[str, Any]]:
    """解析 LLM 输出 → list[dict]，支持直接 JSON / 代码块包裹 / 数组提取。"""
    text = raw.strip()

    # 直接解析
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return [result]
    except json.JSONDecodeError:
        pass

    # 提取 ```json ... ``` 代码块
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        try:
            result = json.loads(m.group(1).strip())
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    # 提取裸 [...] 数组
    m = re.search(r"\[[\s\S]*\]", text)
    if m:
        try:
            result = json.loads(m.group())
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    logger.warning("Vision LLM 输出无法解析为 JSON 数组: %s", raw[:200])
    return []


def _to_receipt_item(raw: dict[str, Any]) -> StandardReceiptItem | None:
    """原始字典 → StandardReceiptItem，失败返回 None。"""
    from datetime import datetime as _dt
    try:
        parsed_date = _dt.strptime(str(raw.get("date", "")), "%Y-%m-%d").date()
        amount      = float(raw.get("amount", 0) or 0)
        if amount <= 0:
            return None
        summary = str(raw.get("summary", "") or "").strip() or "票据识别"
        return StandardReceiptItem(
            date         = parsed_date,
            amount       = round(amount, 2),
            counterparty = raw.get("counterparty") or None,
            summary      = summary,
        )
    except Exception as exc:
        logger.warning("票据数据转换失败 %s: %s", raw, exc)
        return None
