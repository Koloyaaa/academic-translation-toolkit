# 贡献指南

欢迎提交翻译质量、术语、可访问性、页面样式和多语言提示词注入防护方面的改进。

## 提交前

- 先查看 [README](README.md)、[安全说明](SECURITY.md) 和相应 Harness 下的 `SKILL.md`。
- 请用合成文本或已获授权的材料复现问题。不要公开真实学生讲义、姓名、学校账号、成绩或其他个人信息。
- 项目提供 Lite、Plus、Pro、Max 四个独立档位：Lite 含一个 Skill，Plus 含三个 Skills，Pro 和 Max 各含十三个同级 Skills。Lite/Plus 沿用旧版单体流程；Pro/Max 使用模块化流程。修改前先确认受影响的档位，分别更新其入口、脚本和文档；不能依赖其他档位的运行资源。学案挖空补全仅 Plus/Pro/Max 提供；PPTX 读取和输出仅 Pro/Max 提供。PPTX Reader 自带解析脚本，读取渲染需要系统安装 LibreOffice；Pro/Max 套件已打包 `python-pptx`，用于生成 PPTX 时无需 LibreOffice。

## 提交内容

- 说明问题、预期行为和复现步骤；翻译问题请提供脱敏的原文片段及建议译法。
- 涉及提示词注入时，提供不包含真实凭据的合成样例，并说明预期处理方式。
- 更新 README、Harness 指南或使用指南中受影响的说明。
- 运行相关技能结构校验；如修改文档生成脚本，还要验证 HTML、DOCX、Markdown 或 PPTX 对应输出。
- 运行自动化回归：`python -m unittest discover -s tests -v`。
- 修改 Pro 状态或路由时，还要运行 `python -m unittest discover -s skills/pro/tests -v`。
- 检查差异只包含本次修改，没有样例讲义、生成文件或临时资料。

## 兼容性

除非任务需要，不要变更用户可选参数和输出格式。项目作者有权授权的文件采用 MIT；词库条目、依赖与示例素材可能有独立许可，新增前请核对来源和授权。改编内容应遵守对应材料的许可与署名要求。
