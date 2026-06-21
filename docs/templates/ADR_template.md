# 架构决策记录 (Architecture Decision Record)

## ADR 001: 核心技术栈与架构选型

### 状态 (Status)
提案中 (Proposed) -> 等待用户确认

### 背景 (Context)
本项目是一款为中国外贸公司定制的**智能财务软件**，核心特色在于：
1. 重度依赖 AI 技术：电子发票信息提取、账务/银行流水智能对账与平账。
2. 包含类似 Agent 的自然语言交互：通过对话直接配置《小企业会计准则》的科目树。
3. **AI 模型解耦**：系统不能锁定单一厂商，要求可动态配置。
4. 强财务严谨性：多账套隔离，账期回转，账务需保证事务一致性。

### 决策 (Decision)

我们决定采用以下全栈架构：

1. **前端层 (Frontend): Next.js (React) + TailwindCSS**
   - **原因**：非常适合快速构建出现代化、带毛玻璃/微动画效果的 SaaS 级 UI，以及通过 `@media print` 控制 24x14cm 的精准财务打印排版。

2. **后端层 (Backend): Python + FastAPI**
   - **原因**：Python 是 AI 领域绝对的一等公民，极其适合处理复杂的 OCR 与大模型路由调度。

3. **PDF/图片解析引擎 (OCR & Document Parsing): OpenDataLoader-PDF + LiteLLM**
   - **原因**：引入您推荐的开源工具 **`opendataloader-project/opendataloader-pdf`**。这是一个专门为 AI（RAG）准备的高性能本地 PDF 解析器。它支持将发票/水单 PDF 完美转化为携带边界框的 JSON 或 Markdown，特别是它对**复杂表格（发票明细、流水列表）**的处理极其优秀。结合 `LiteLLM`，我们可以将解析出的高质量文本动态发送给任何配置的大模型进行最终提取。完全契合了我们在“引擎 B”中所需的本地化、高性能、重隐私的诉求。

4. **数据层 (Database): PostgreSQL**
   - **原因**：财务软件对数据一致性、关系约束和事务 (ACID) 要求极高。利用行级安全 (RLS) 和 Schema 机制可完美实现**多账套**的物理隔离。

### 替代方案评估 (Alternatives Considered)
- **纯 Node.js 后端**：在集成像 `opendataloader-pdf` 这样强大的 AI/数据科学工具包时生态较弱。
- **商用云 OCR API (如阿里云/腾讯云)**：会产生持续费用且有隐私泄露风险，违背了本地优先与解耦原则。

### 结论 (Consequences)
- **正面**：架构完美契合了本地解析、数据安全、模型自由组合的外贸实战需求。
