# 当前项目上下文及进度备份 (Context Backup)

## 1. 之前发生的问题
由于 IDE 或系统底层的不稳定，本窗口的后端任务和 AI 对话经常出现意外关闭或系统重启（导致“反复闪退”现象）。为了防止聊天记录丢失，在此备份我们的修复进度。

## 2. 已经完成的修复与功能
1. **后端启动报错修复**
   - 修改了 `backend/app/main.py`，加入了 `sys.path.insert` 逻辑。解决了直接用 Python 运行 `main.py` 时由于找不到 `app` 模块而瞬间闪退（ModuleNotFoundError）的问题。
2. **AI 发票识别（OCR）对接**
   - 在 `backend/app/routers/ai_chat.py` 中，增加了针对 `INVOICE_OCR` 意图的识别与处理逻辑。
   - 现在，AI 助手能够识别发票的路径，并且调用后端的 `extract_structured_data_from_pdf` 和 `process_invoice_with_ai` 去提取并返回结构化的商品明细。
3. **前端 AI 对话 UI 升级**
   - 修改了 `frontend/src/components/AIChat.tsx`，增加了对 `INVOICE_RESULT` 动作类型的前端专属 UI 卡片渲染。现在发票解析成功后会显示带有一键生成入账凭证按钮的美观卡片。
4. **Swagger UI 接口测试报错修复**
   - 您在使用 FastAPI 的 Swagger 文档页面测试 `/api/v1/vouchers/upload-invoices` 接口时，遇到传入字符串导致 422 `Unprocessable Content` 的报错。
   - 修复了 `backend/app/routers/vouchers.py`，在参数列表中加入了 `= File(...)`。现在刷新 Swagger 页面后，就可以正常看到文件选择按钮并上传文件了。

## 3. 下一步建议
如果后续 IDE 再次崩溃导致聊天清空，您可以让 AI 首先读取本文件（`CONTEXT.md`）以快速恢复记忆。

您可以手动在系统命令行（如 CMD、PowerShell 或 VS Code 终端）分别运行以下命令启动服务，以防 IDE 内置终端因监听刷新而引起崩溃：
- **后端**：在 `backend` 目录下运行 `venv\Scripts\python -m app.main`
- **前端**：在 `frontend` 目录下运行 `npm run dev`
