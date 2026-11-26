# Prompt 库

这些提示词用来一次说明讲义翻译需求。先按[项目安装说明](../README.md)选择并安装一个档位，再选一份模板，复制后填好方括号里的档位、入口名称和其他信息，最后附上讲义。格式、布局、注释、术语来源、配图和测验选项都可以按需修改。

> V4.0.4 的 Pro/Max 包支持读取来源 PPTX，但不含可编辑 PPTX 输出或学案补全。要使用这两项新功能，请从仓库当前源码安装对应档位；功能进入正式安装包后再更新此提示。

## 档位与入口

| 档位 | 入口 Skill | 输入材料 | 输出格式 | 学案补全 | 审计与工作流 |
| --- | --- | --- | --- | --- | --- |
| Lite | `foreign-academic-translator-lite` | PDF、DOCX、TXT、纯文本 | HTML、DOCX、Markdown | 不提供 | 单体流程；检查成品是否存在、非空且可读 |
| Plus | `foreign-academic-translator-plus` | 同 Lite | HTML、DOCX、Markdown | 可选；仅补明确挖空 | 单体流程；独立质量审计，也核对启用后的补全依据 |
| Pro | `translation-orchestrator` | PDF、PPTX、DOCX、TXT、纯文本 | HTML、DOCX、Markdown、可编辑 PPTX | 可选；证明题会核对全篇关联知识点 | 13 个模块化 Skills；每个 Skill 后重新判断并记录下一步 |
| Max | `translation-orchestrator` | 同 Pro | 同 Pro | 可选；同 Pro | 13 个模块化 Skills；执行完整编排流程 |

例如，使用 Lite 时，把模板首句中的 `[档位]` 填为 `Lite`、`[入口 Skill 名称]` 填为 `foreign-academic-translator-lite`。Pro 和 Max 的入口同名，但各自使用所安装档位的独立技能组；切换档位时请按安装说明更换完整套件。

Lite、Plus 适合旧版可处理的 PDF、DOCX、TXT 或纯文本；旧版配图提取仅支持 PDF。PPTX 输入、PPTX 输出、扫描件的完整读取和结构复杂的材料建议选 Pro 或 Max。Plus 需要在独立审阅上下文中运行质量审计 Skill；如果宿主无法提供该能力，会报告阻塞，不能声称审计通过。Lite 不提供学案挖空补全；Plus、Pro、Max 可选启用。补全只针对明确留空，无法确认的内容会保留并标记“待老师确认”。

## 提示词模板

| 提示词 | 适合的情况 |
| --- | --- |
| [自定义模板](custom.md) | 自己选择各项输出设置 |
| [日常预习](preview.md) | 想先用中文读懂讲义，保留常用术语 |
| [双语对照](bilingual.md) | 希望逐段对照原文与译文 |
| [考前复习](exam-review.md) | 希望获得解释、概念表和章末测验 |
| [简洁译文](concise.md) | 只需要便于阅读和保存的中文译稿 |
| [学案挖空补全](handout-completion.md) | 需要依据整份讲义和参考材料补全明确留空 |

PPTX 来源读取和可编辑 PPTX 输出仅 Pro/Max 支持。Lite 只做文件可读性检查；Plus、Pro、Max 要求独立质量审计。智能补全只在 Plus、Pro、Max 提供；只处理明确挖空，不能确定时保留空格并标记“待老师确认”。Pro 和 Max 使用新版读取与视觉核对流程。术语默认使用 Wikidata 在线候选查询，只发送选中的术语，不发送整份讲义；如不希望向外部服务发送术语，可选 `ai_auto`。各模板是使用示例，不是额外的 Skill。实际执行的 Skill 会按套件要求在对话中报出名称。

Pro 和 Max 处理 PDF/PPTX 时，配图只有在开启配图且图片经过视觉核对并被选中时才会插入。当前宿主和模型能够接收页面图像时，流程必须逐页核对；确实无法传递图像时会说明未审核页及处理限制。选择“不插入配图”不会关闭视觉核对。Lite 和 Plus 的旧版处理能力以对应档位说明为准。

提示词的表达参考 `humanizer-zh`：用自然、具体的语言交代需求，保留必要信息，不靠冗长的角色设定或空泛的修饰语。

