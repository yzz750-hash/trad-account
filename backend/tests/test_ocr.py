"""Tests for OCR pipeline: PDF extraction via OpenDataLoader-PDF + LLM parsing."""
import os
import sys
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ocr import (
    extract_structured_data_from_pdf,
    process_invoice_with_ai,
    process_csv_statement_with_ai,
    start_hybrid_backend,
    stop_hybrid_backend,
    _extract_with_opendataloader,
    _extract_with_pymupdf,
)


def _create_text_pdf(filepath: str, text: str = "Test Invoice Content"):
    """Create a minimal text PDF using PyMuPDF."""
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 100), text)
    doc.save(filepath)
    doc.close()


def _create_empty_pdf(filepath: str):
    """Create a PDF with a blank page (no text)."""
    import fitz
    doc = fitz.open()
    doc.new_page()
    doc.save(filepath)
    doc.close()


class TestPDFExtraction:

    def test_extract_text_pdf_with_opendataloader(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name
        try:
            _create_text_pdf(pdf_path, "Invoice Number: INV-001\nVendor: Test Company\nAmount: 10000.00")
            result = extract_structured_data_from_pdf(pdf_path)
            assert result["status"] == "success"
            assert "Invoice" in result["raw_markdown"]
            assert result["engine"] == "opendataloader"
        finally:
            if os.path.exists(pdf_path):
                os.unlink(pdf_path)

    def test_extract_missing_file(self):
        result = extract_structured_data_from_pdf("/nonexistent/file.pdf")
        assert result["status"] == "error"
        assert "not found" in result["message"]

    def test_extract_empty_pdf_falls_back(self):
        """Empty PDF (no text layer) should fall through to PyMuPDF."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name
        try:
            _create_empty_pdf(pdf_path)
            result = extract_structured_data_from_pdf(pdf_path)
            # Empty PDF: OpenDataLoader may return empty markdown, falls to PyMuPDF
            # PyMuPDF also returns empty text → error
            # Either way, not a crash
            assert result["status"] in ("success", "error")
            if result["status"] == "error":
                assert "Could not extract" in result["message"]
        finally:
            if os.path.exists(pdf_path):
                os.unlink(pdf_path)

    def test_pymupdf_fallback_standalone(self):
        """PyMuPDF fallback should extract text from a basic PDF."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name
        try:
            _create_text_pdf(pdf_path, "Hello World")
            text = _extract_with_pymupdf(pdf_path)
            assert text is not None
            assert "Hello World" in text
        finally:
            if os.path.exists(pdf_path):
                os.unlink(pdf_path)

    def test_opendataloader_returns_markdown(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name
        try:
            _create_text_pdf(pdf_path, "Line 1 Line 2")
            md = _extract_with_opendataloader(pdf_path)
            assert md is not None
            assert len(md) > 0
        finally:
            if os.path.exists(pdf_path):
                os.unlink(pdf_path)

    def test_engine_field_in_response(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name
        try:
            _create_text_pdf(pdf_path, "Invoice data ABC")
            result = extract_structured_data_from_pdf(pdf_path)
            assert "engine" in result
            assert result["engine"] in ("opendataloader", "opendataloader-hybrid", "pymupdf")
        finally:
            if os.path.exists(pdf_path):
                os.unlink(pdf_path)


class TestHybridBackend:

    def test_start_stop_hybrid_backend(self):
        # Start backend — will fail if Java not available, but should not crash
        started = start_hybrid_backend()
        # If it started, stop it
        if started:
            stop_hybrid_backend()
        # Either way, no exception
        assert started in (True, False)


class TestInvoiceAIProcessing:

    @patch("app.llm.get_llm_response")
    def test_process_invoice_success(self, mock_llm):
        mock_llm.return_value = json.dumps({
            "vendor_name": "测试供应商",
            "items": [{"item_name": "电脑", "specification": "X1", "quantity": "1", "amount": "5000.00", "remarks": ""}],
        }, ensure_ascii=False)

        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test-key-for-unit-test-long-enough"}):
            result = process_invoice_with_ai("发票号码: INV-001\n供应商: 测试供应商")
            assert result["status"] == "success"
            assert result["data"]["vendor_name"] == "测试供应商"
            assert len(result["data"]["items"]) == 1

    @patch("app.llm.get_llm_response")
    def test_process_invoice_llm_failure(self, mock_llm):
        mock_llm.side_effect = Exception("LLM timeout")

        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test-key-for-unit-test-long-enough"}):
            result = process_invoice_with_ai("some invoice text")
            assert result["status"] == "error"

    def test_process_invoice_no_api_key(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            result = process_invoice_with_ai("some text")
            assert result["status"] == "error"

    def test_process_invoice_short_api_key(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-short"}):
            result = process_invoice_with_ai("some text")
            assert result["status"] == "error"


class TestCSVStatementProcessing:

    @patch("app.llm.get_llm_response")
    def test_process_csv_success(self, mock_llm):
        mock_llm.return_value = json.dumps({
            "bank_name": "工商银行",
            "transactions": [
                {"transaction_date": "2024-05-12", "counterpart_name": "ABC", "amount": "10000.00", "remarks": "货款"},
            ],
        }, ensure_ascii=False)

        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test-key-for-unit-test-long-enough"}):
            result = process_csv_statement_with_ai("date,amount\n2024-05-12,10000")
            assert result["status"] == "success"
            assert result["data"]["bank_name"] == "工商银行"

    def test_process_csv_no_api_key(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            result = process_csv_statement_with_ai("some csv")
            assert result["status"] == "error"
