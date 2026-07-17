import asyncio
from typing import Optional, Any
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.llm import get_llm_response, stream_llm_response
from app.auth import get_current_user, CurrentUser, require_write
from app.routers.ledgers import get_ledger_id
from app.routers.vouchers import _get_llm_config_for_ledger
import json
import logging
from pathlib import Path

logger = logging.getLogger("trad_account")

router = APIRouter()

# Sandbox: only allow file access within these directories
UPLOADS_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp"}

def _safe_resolve_file(file_path: str) -> Path | None:
    """Resolve a file path and verify it stays within the uploads directory."""
    if not file_path or file_path.startswith("http"):
        return None
    try:
        resolved = Path(file_path).resolve()
        allowed = UPLOADS_DIR.resolve()
        if not str(resolved).startswith(str(allowed)):
            return None
        if resolved.suffix.lower() not in ALLOWED_EXTENSIONS:
            return None
        return resolved
    except (ValueError, OSError):
        return None


class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    history: list[dict] = []  # [{"role": "user"|"assistant", "content": "..."}]


SYSTEM_PROMPT = """
你是一个中国外贸财务软件的 AI 助理。请根据用户的输入判断意图，并且必须返回合法的 JSON 格式。
如果用户想增设科目（比如：在管理费用下加一个软件订阅费），
请提取父科目名称和新科目名称，返回格式如下：
{"intent": "ADD_ACCOUNT", "parent_name": "管理费用", "new_account_name": "软件订阅费"}
如果用户发送的是发票的文件路径、发票地址、图片地址、PDF地址，或者要求你解析发票/读取发票，
请提取发票的路径或地址，返回格式如下：
{"intent": "INVOICE_OCR", "file_path": "发票的路径或地址"}
如果用户要求"核销"、"对账"、"开始对账"、"智能核销"，请返回格式如下：
{"intent": "RECONCILE"}
如果用户描述了一笔经济业务并希望生成会计凭证（例如："收到XX公司货款72000元"、"支付本月工资"、"购买办公用品500元"、"计提本月折旧"、"报销差旅费1000元"等），请返回格式如下：
{"intent": "CREATE_VOUCHER"}
如果是一般聊天，请返回：
{"intent": "CHAT", "reply": "你的回复内容"}
"""

CHAT_SYSTEM_PROMPT = """
你是一个中国外贸财务软件的 AI 助理。请用中文回复用户的问题，语气专业且友好。
你可以帮助用户解答会计科目设置、凭证管理、发票处理、银行对账等财务相关问题。
"""


def _classify_intent(user_msg: str, config, db: Session, ledger_id: int) -> dict:
    """Classify user intent using LLM. Returns parsed JSON dict."""
    prompt = f"{SYSTEM_PROMPT}\n\n用户输入: {user_msg}"
    raw = get_llm_response(
        prompt=prompt, config=config,
        response_format={"type": "json_object"},
        max_tokens=500, temperature=0.1, timeout=30.0,
    )
    return json.loads(raw)


def _build_chat_messages(history: list[dict], user_msg: str) -> list[dict]:
    """Build messages array for chat LLM call with conversation history."""
    messages: list[dict] = [{"role": "system", "content": CHAT_SYSTEM_PROMPT}]
    for h in history[-20:]:
        role = h.get("role", "user")
        content = h.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_msg})
    return messages


@router.get("/health")
def ai_health(
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
    ledger_id: int = Depends(get_ledger_id),
):
    """Check if LLM API key is configured for the current ledger."""
    config = _get_llm_config_for_ledger(db, ledger_id)
    configured = bool(config.api_key and len(config.api_key) > 8)
    return {
        "status": "ok" if configured else "no_api_key",
        "provider": config.provider,
        "model": config.model_name,
        "configured": configured,
    }


@router.post("/chat")
async def handle_ai_chat(
    request: ChatRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    ledger_id: int = Depends(get_ledger_id),
):
    """AI chat with SSE streaming for CHAT intent, structured actions for others."""

    config = _get_llm_config_for_ledger(db, ledger_id)
    if not config.api_key:
        async def no_key():
            msg = json.dumps({"type": "error", "text": "AI API key 未配置。请在 .env 中设置 DEEPSEEK_API_KEY 或在账套设置中配置 LLM API key。"}, ensure_ascii=False)
            yield f"data: {msg}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(no_key(), media_type="text/event-stream")

    user_msg = request.message[:1500]

    try:
        parsed = await asyncio.to_thread(_classify_intent, user_msg, config, db, ledger_id)
    except Exception as e:
        logger.error("Intent classification failed: %s", e)
        async def intent_error():
            msg = json.dumps({"type": "error", "text": "AI 助理暂时无法理解您的请求，请稍后重试。"}, ensure_ascii=False)
            yield f"data: {msg}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(intent_error(), media_type="text/event-stream")

    intent = parsed.get("intent", "CHAT")

    if intent == "ADD_ACCOUNT":
        if current_user.role not in ("admin", "accountant"):
            async def no_perm():
                msg = json.dumps({"type": "error", "text": "抱歉，您没有权限进行科目管理。"}, ensure_ascii=False)
                yield f"data: {msg}\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(no_perm(), media_type="text/event-stream")

        async def add_account():
            parent_name = parsed.get("parent_name", "")
            from app.models.financial import Account
            parent_acc = db.query(Account).filter(
                Account.name.like(f"%{parent_name}%"),
                Account.ledger_id == ledger_id,
            ).first()

            if not parent_acc:
                err = json.dumps({"type": "error", "text": f"未找到科目: {parent_name}"}, ensure_ascii=False)
                yield f"data: {err}\n\n"
                yield "data: [DONE]\n\n"
                return

            children = db.query(Account).filter(
                Account.parent_id == parent_acc.id,
                Account.ledger_id == ledger_id,
            ).all()
            max_suffix = 0
            for c in children:
                try:
                    suffix = int(c.code[-2:])
                    if suffix > max_suffix:
                        max_suffix = suffix
                except (ValueError, IndexError):
                    pass
            new_suffix = str(max_suffix + 1).zfill(2)
            proposed_code = parent_acc.code + new_suffix

            payload = {
                "type": "meta",
                "action_type": "SUGGEST_ACCOUNT",
                "action_payload": {
                    "parent_id": parent_acc.id,
                    "parent_name": parent_acc.name,
                    "new_account_name": parsed.get("new_account_name", ""),
                    "proposed_code": proposed_code,
                },
                "text": "我已经为您草拟了新科目，请确认是否添加？",
            }
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(add_account(), media_type="text/event-stream")

    elif intent == "INVOICE_OCR":
        async def invoice_ocr():
            file_path = parsed.get("file_path", "")
            from app.ocr import extract_structured_data_from_pdf, process_invoice_with_ai
            from app.models.financial import OriginalDocument

            safe_path = _safe_resolve_file(file_path)
            if safe_path is None or not safe_path.exists():
                err = json.dumps({"type": "error", "text": "找不到该文件路径，请先上传真实的发票文件。"}, ensure_ascii=False)
                yield f"data: {err}\n\n"
                yield "data: [DONE]\n\n"
                return

            ocr_res = extract_structured_data_from_pdf(str(safe_path))
            if ocr_res.get("status") != "success":
                err = json.dumps({"type": "error", "text": f"读取发票文件失败: {ocr_res.get('message')}"}, ensure_ascii=False)
                yield f"data: {err}\n\n"
                yield "data: [DONE]\n\n"
                return

            ai_res = process_invoice_with_ai(ocr_res["raw_markdown"])
            if ai_res.get("status") != "success":
                err = json.dumps({"type": "error", "text": f"AI 提取结构化数据失败: {ai_res.get('message')}"}, ensure_ascii=False)
                yield f"data: {err}\n\n"
                yield "data: [DONE]\n\n"
                return

            # Create OriginalDocument so the frontend can generate a voucher
            doc = OriginalDocument(
                ledger_id=ledger_id,
                doc_type="INVOICE",
                file_path=str(safe_path),
                extracted_data=ai_res["data"],
            )
            db.add(doc)
            db.flush()
            db.commit()

            items = ai_res["data"].get("items", [])
            vendor = ai_res["data"].get("vendor_name", "")
            reply_text = f"已成功解析发票 (供应商: {vendor})\n"
            for item in items:
                reply_text += f"- {item.get('item_name')} ({item.get('specification')}): {item.get('quantity')}件，共 {item.get('amount')}元\n"

            action_data = {**ai_res["data"], "doc_id": doc.id}
            payload = {
                "type": "meta",
                "action_type": "INVOICE_RESULT",
                "action_payload": action_data,
                "text": reply_text,
            }
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(invoice_ocr(), media_type="text/event-stream")

    elif intent == "RECONCILE":
        if current_user.role not in ("admin", "accountant"):
            async def no_perm2():
                msg = json.dumps({"type": "error", "text": "抱歉，您没有权限进行核销操作。"}, ensure_ascii=False)
                yield f"data: {msg}\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(no_perm2(), media_type="text/event-stream")

        async def reconcile():
            from app.routers.vouchers import reconcile_suggestions
            reconcile_res = reconcile_suggestions(db, ledger_id=ledger_id)
            if reconcile_res.get("status") == "success":
                matches = reconcile_res.get("matches", [])
                if not matches:
                    msg = json.dumps({"type": "meta", "action_type": "TEXT", "text": "目前没有需要核销的待处理账单和流水！"}, ensure_ascii=False)
                    yield f"data: {msg}\n\n"
                    yield "data: [DONE]\n\n"
                    return

                payload = {
                    "type": "meta",
                    "action_type": "RECONCILE_SUGGESTIONS",
                    "action_payload": {"matches": matches},
                    "text": f"我已为您找到 {len(matches)} 组匹配的核销建议，请确认：",
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            else:
                err = json.dumps({"type": "error", "text": "AI 智能对账失败，请稍后再试。"}, ensure_ascii=False)
                yield f"data: {err}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(reconcile(), media_type="text/event-stream")

    elif intent == "CREATE_VOUCHER":
        if current_user.role not in ("admin", "accountant"):
            async def no_perm_voucher():
                msg = json.dumps({"type": "error", "text": "抱歉，您没有权限生成凭证。"}, ensure_ascii=False)
                yield f"data: {msg}\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(no_perm_voucher(), media_type="text/event-stream")

        from app.routers.voucher_nl import create_voucher_suggestion
        return StreamingResponse(
            create_voucher_suggestion(db, ledger_id, config, user_msg),
            media_type="text/event-stream",
        )

    else:  # CHAT
        messages = _build_chat_messages(request.history, user_msg)

        async def chat_stream():
            try:
                async for token in stream_llm_response(
                    prompt="", config=config, messages=messages,
                    max_tokens=2000, temperature=0.7, timeout=120.0,
                ):
                    payload = json.dumps({"type": "token", "text": token}, ensure_ascii=False)
                    yield f"data: {payload}\n\n"
            except Exception as e:
                logger.error("Chat stream error: %s", e)
                err = json.dumps({"type": "error", "text": "AI 响应中断，请稍后重试。"}, ensure_ascii=False)
                yield f"data: {err}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(chat_stream(), media_type="text/event-stream")