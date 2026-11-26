# Max

本目录包含独立的完整新版 Skills 组。安装时将 `skills/` 下的十三个 Skill 目录一起复制到宿主的 Skills 根目录，并保持同级；通过 `translation-orchestrator` 开始。已安装其他档位的同名 Skills 时，请先安全备份并移出，避免宿主发现名称冲突。Max 支持 PPTX 输出，Lite/Plus 不提供该格式。

Max 支持 PDF、PPTX、DOCX、TXT 和纯文本输入，可输出 HTML、DOCX、Markdown 和可编辑 PPTX，并可选启用学案挖空补全。Max 与 Pro 具有相同的材料格式、输出格式、补全和审计能力；Max 按现有完整编排流程执行适用阶段。四档对照见[项目首页](../../README.md#四档功能对比)。

工作流按现有规则执行所有适用阶段；未选择测验或输出格式时不会擅自生成。用户可选择补全明确挖空；数理证明会结合整份讲义中的关联知识点，并由质量审计 Skill 独立核验依据与推理。Max 使用 `.translator-cache-max/` 保存自身通过门禁的缓存，不把其他档位的缓存视为已审计结果。
