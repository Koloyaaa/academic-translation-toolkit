# Plus 档：旧版单体翻译 + 独立审计

此目录是一个独立的 Plus 套件，共包含三个 Skills：

- 主入口：`foreign-academic-translator-plus`，基于完整旧版 V3.1.3 单体翻译流程。
- 审计入口：`foreign-academic-quality-auditor-plus`，这是在独立审阅上下文中运行的质量审计 Skill。
- 补全 Skill：`foreign-academic-handout-completer-plus`，仅在用户启用智能补全后处理明确挖空，并由独立审计 Skill 复核。

补全只针对讲义明确留出的空格；无法从本讲义或参考资料确认的内容会保留空格并标为“待老师确认”。数学证明会结合整份讲义中出现的相关定义、定理、公式和假设逐步核对。

Plus 沿用旧版 PDF、DOCX、TXT 和纯文本读取流程，可输出 HTML、DOCX 或 Markdown；不提供 PPTX 输入读取或 PPTX 输出。若需要 PPTX 或专用逐页视觉核对，请使用 Pro/Max。四档能力对照见[项目首页](../../README.md#四档功能对比)。

## 安装与调用

将 `skills/` 下的三个 Skill 文件夹都复制到所用宿主的技能目录，例如 Codex 项目的 `.agents/skills/`。保留各自整个文件夹，以便脚本、模板、补全参考和审计说明都能通过相对路径找到。默认通过 Wikidata 公开 API 在线查询术语；其结构化数据采用 CC0 1.0。查询只发送单个术语或短语。通过 `foreign-academic-translator-plus` 启动翻译；宿主需要能提供独立审阅上下文，并在其中运行 `foreign-academic-quality-auditor-plus` 质量审计 Skill。

如果宿主不能在独立上下文中运行质量审计 Skill，Plus 入口会把任务标记为 `BLOCKED` 或 `FAIL`，不会把作者自检包装为审计通过。该 Skill 必须直接读取完整源文、译文核心 Markdown 和每个用户选择的成品。图像未能实际查看时标记为 `PARTIAL_TEXT_ONLY`，不能称 Plus 整体审计通过。

脚本需要 Python 3.10+。按[安装说明](skills/foreign-academic-translator-plus/README.md)安装主入口 `requirements.txt` 中的依赖。检查脚本和其他资源均随各自入口独立复制。

## 旧版来源

翻译入口及其依赖沿用 Git 提交 `2f5d4f3`（`Release v3.1.3: complete translation in one turn`）中的旧版资源；独立审计和智能补全是此档新增 Skills。补全 Skill 的数学证明规则位于其 `references/math-proof-completion.md`。

## 审计范围

Plus 要求全文覆盖可读源文，核对标题、正文、表格、公式、练习、术语、关键数字与各成品内容。审计报告写入 `plus-audit-report.md`。若无法读取全部内容或未实际查看图像，报告会保留相应范围和限制，不会声称整体内容或视觉审核通过。
