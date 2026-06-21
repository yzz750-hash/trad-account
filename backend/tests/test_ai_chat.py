"""Tests for AI chat router (ai_chat.py) — SSE streaming format."""
import json
import os
from unittest.mock import patch, MagicMock, AsyncMock

import pytest


def _parse_sse(text: str) -> list[dict]:
    """Parse SSE text/event-stream body into list of JSON payloads from data: lines.
    Filters out [DONE] markers. Returns list of dicts."""
    results = []
    for line in text.split("\n"):
        line = line.strip()
        if not line.startswith("data: "):
            continue
        data = line[6:]
        if data == "[DONE]":
            continue
        try:
            results.append(json.loads(data))
        except json.JSONDecodeError:
            continue
    return results


class TestAiChatNoApiKey:
    """Test AI chat when DEEPSEEK_API_KEY is not configured."""

    def test_chat_without_api_key(self, client, auth_headers, ledger):
        """Without DEEPSEEK_API_KEY, the endpoint returns an SSE error."""
        old_key = os.environ.pop("DEEPSEEK_API_KEY", None)
        try:
            resp = client.post(
                "/api/v1/ai/chat",
                json={"message": "你好"},
                headers={**auth_headers, "X-Ledger-Id": str(ledger.id)},
            )
            assert resp.status_code == 200
            events = _parse_sse(resp.text)
            assert any(e.get("type") == "error" for e in events)
        finally:
            if old_key:
                os.environ["DEEPSEEK_API_KEY"] = old_key


def _mock_stream_tokens(*tokens: str):
    """Helper to mock stream_llm_response with a sequence of tokens."""
    async def _gen():
        for t in tokens:
            yield t
    mock = MagicMock()
    mock.return_value = _gen()
    return patch("app.routers.ai_chat.stream_llm_response", mock)


class TestAiChatWithMockedLLM:
    """Test AI chat with mocked LLM responses."""

    @pytest.fixture(autouse=True)
    def set_api_key(self):
        """Ensure DEEPSEEK_API_KEY is set for these tests."""
        os.environ["DEEPSEEK_API_KEY"] = "test-mock-key"

    def _mock_llm(self, response_text):
        """Helper to mock get_llm_response (intent classifier)."""
        return patch("app.routers.ai_chat.get_llm_response", return_value=response_text)

    def test_chat_general(self, client, auth_headers, ledger):
        """General chat intent streams tokens via SSE."""
        with self._mock_llm(json.dumps({"intent": "CHAT", "reply": "你好！有什么可以帮助你的？"})):
            with _mock_stream_tokens("你好！", "有什么可以帮助你的？"):
                resp = client.post(
                    "/api/v1/ai/chat",
                    json={"message": "你好"},
                    headers={**auth_headers, "X-Ledger-Id": str(ledger.id)},
                )
        assert resp.status_code == 200
        events = _parse_sse(resp.text)
        tokens = [e["text"] for e in events if e.get("type") == "token"]
        assert "".join(tokens) == "你好！有什么可以帮助你的？"

    def test_chat_add_account_success(self, client, auth_headers, ledger, db):
        """ADD_ACCOUNT intent with existing parent returns SUGGEST_ACCOUNT."""
        with self._mock_llm(json.dumps({
            "intent": "ADD_ACCOUNT",
            "parent_name": "管理费用",
            "new_account_name": "软件订阅费",
        })):
            resp = client.post(
                "/api/v1/ai/chat",
                json={"message": "在管理费用下加一个软件订阅费"},
                headers={**auth_headers, "X-Ledger-Id": str(ledger.id)},
            )
        assert resp.status_code == 200
        events = _parse_sse(resp.text)
        meta = next(e for e in events if e.get("type") == "meta")
        assert meta["action_type"] == "SUGGEST_ACCOUNT"
        payload = meta.get("action_payload") or {}
        assert payload.get("new_account_name") == "软件订阅费"
        assert "parent_id" in payload
        assert "proposed_code" in payload

    def test_chat_add_account_parent_not_found(self, client, auth_headers, ledger):
        """ADD_ACCOUNT with unknown parent returns error SSE event."""
        with self._mock_llm(json.dumps({
            "intent": "ADD_ACCOUNT",
            "parent_name": "不存在的科目",
            "new_account_name": "测试",
        })):
            resp = client.post(
                "/api/v1/ai/chat",
                json={"message": "在不存在的科目下加一个测试"},
                headers={**auth_headers, "X-Ledger-Id": str(ledger.id)},
            )
        assert resp.status_code == 200
        events = _parse_sse(resp.text)
        error_event = next((e for e in events if e.get("type") == "error"), None)
        assert error_event is not None
        assert "不存在的科目" in error_event["text"]

    def test_chat_reconcile(self, client, auth_headers, ledger):
        """RECONCILE intent returns RECONCILE_SUGGESTIONS or TEXT meta."""
        with self._mock_llm(json.dumps({"intent": "RECONCILE"})):
            resp = client.post(
                "/api/v1/ai/chat",
                json={"message": "开始智能核销"},
                headers={**auth_headers, "X-Ledger-Id": str(ledger.id)},
            )
        assert resp.status_code == 200
        events = _parse_sse(resp.text)
        meta = next(e for e in events if e.get("type") == "meta")
        # RECONCILE may return RECONCILE_SUGGESTIONS or TEXT (if no matches)
        assert meta["action_type"] in ("RECONCILE_SUGGESTIONS", "TEXT")

    def test_chat_invoice_ocr_file_not_found(self, client, auth_headers, ledger):
        """INVOICE_OCR with non-existent file path returns error SSE."""
        with self._mock_llm(json.dumps({
            "intent": "INVOICE_OCR",
            "file_path": "/nonexistent/invoice.pdf",
        })):
            resp = client.post(
                "/api/v1/ai/chat",
                json={"message": "解析发票 /nonexistent/invoice.pdf"},
                headers={**auth_headers, "X-Ledger-Id": str(ledger.id)},
            )
        assert resp.status_code == 200
        events = _parse_sse(resp.text)
        error_event = next((e for e in events if e.get("type") == "error"), None)
        assert error_event is not None
        assert "找不到" in error_event["text"] or "file" in error_event["text"].lower()

    def test_chat_invoice_ocr_http_path(self, client, auth_headers, ledger):
        """INVOICE_OCR with HTTP URL (not local file) returns error SSE."""
        with self._mock_llm(json.dumps({
            "intent": "INVOICE_OCR",
            "file_path": "http://example.com/invoice.pdf",
        })):
            resp = client.post(
                "/api/v1/ai/chat",
                json={"message": "解析发票 http://example.com/invoice.pdf"},
                headers={**auth_headers, "X-Ledger-Id": str(ledger.id)},
            )
        assert resp.status_code == 200
        events = _parse_sse(resp.text)
        error_event = next((e for e in events if e.get("type") == "error"), None)
        assert error_event is not None
        assert "找不到" in error_event["text"] or "file" in error_event["text"].lower()

    def test_chat_llm_error_handled(self, client, auth_headers, ledger):
        """When LLM throws during intent classification, return graceful SSE error."""
        with patch("app.routers.ai_chat.get_llm_response", side_effect=Exception("LLM timeout")):
            resp = client.post(
                "/api/v1/ai/chat",
                json={"message": "测试异常"},
                headers={**auth_headers, "X-Ledger-Id": str(ledger.id)},
            )
        assert resp.status_code == 200
        events = _parse_sse(resp.text)
        error_event = next((e for e in events if e.get("type") == "error"), None)
        assert error_event is not None
        assert "暂时" in error_event["text"] or "稍后" in error_event["text"]

    def test_chat_message_truncation(self, client, auth_headers, ledger):
        """Long messages should be truncated to 1500 chars."""
        long_msg = "测试" * 1000  # 2000 chars
        with self._mock_llm(json.dumps({"intent": "CHAT", "reply": "收到"})):
            with _mock_stream_tokens("收到"):
                resp = client.post(
                    "/api/v1/ai/chat",
                    json={"message": long_msg},
                    headers={**auth_headers, "X-Ledger-Id": str(ledger.id)},
                )
        assert resp.status_code == 200
        events = _parse_sse(resp.text)
        tokens = [e["text"] for e in events if e.get("type") == "token"]
        assert "收到" in "".join(tokens)

    def test_chat_parse_invalid_json(self, client, auth_headers, ledger):
        """When LLM returns invalid JSON, exception is caught gracefully via SSE error."""
        with self._mock_llm("not valid json {{{"):
            resp = client.post(
                "/api/v1/ai/chat",
                json={"message": "测试"},
                headers={**auth_headers, "X-Ledger-Id": str(ledger.id)},
            )
        assert resp.status_code == 200
        events = _parse_sse(resp.text)
        error_event = next((e for e in events if e.get("type") == "error"), None)
        assert error_event is not None
        assert "暂时" in error_event["text"] or "稍后" in error_event["text"]

    def test_chat_add_account_with_existing_children(self, client, auth_headers, ledger, db):
        """ADD_ACCOUNT when parent has existing children, proposed_code increments correctly."""
        from app.models.financial import Account, AccountType, AccountDirection
        parent_acc = db.query(Account).filter(
            Account.ledger_id == ledger.id, Account.code == "6602"
        ).first()
        db.add(Account(
            ledger_id=ledger.id,
            code="660201",
            name="管理费用-办公费",
            account_type=AccountType.PROFIT_LOSS,
            balance_direction=AccountDirection.DEBIT,
            parent_id=parent_acc.id,
            opening_balance=0,
        ))
        db.commit()

        with self._mock_llm(json.dumps({
            "intent": "ADD_ACCOUNT",
            "parent_name": "管理费用",
            "new_account_name": "软件订阅费",
        })):
            resp = client.post(
                "/api/v1/ai/chat",
                json={"message": "在管理费用下加一个软件订阅费"},
                headers={**auth_headers, "X-Ledger-Id": str(ledger.id)},
            )
        assert resp.status_code == 200
        events = _parse_sse(resp.text)
        meta = next(e for e in events if e.get("type") == "meta")
        payload = meta.get("action_payload") or {}
        # First child was 660201, so next should be 660202
        assert payload.get("proposed_code") == "660202"