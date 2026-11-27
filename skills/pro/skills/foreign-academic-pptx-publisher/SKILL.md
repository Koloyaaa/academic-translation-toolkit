---
name: foreign-academic-pptx-publisher
description: Turn the audited translated Markdown into an editable PowerPoint deck and inspect slide coverage and layout; use only when PPTX output is selected.
license: MIT
---

## 强制 Skill 使用声明

- 在本 Skill 开始实质工作前，先向用户单独输出一行：当前使用 Skill：foreign-academic-pptx-publisher。如果编排器已在进入本阶段前输出了这一行，不重复。
- 编排器必须先声明本 Skill，再调用或委派；没有编排器时由本 Skill 自行声明。未声明不得启动。
- 只声明本轮实际执行的 Skill；缓存命中而跳过时不声明。这行提示不得写入成品。

# PPTX 发布 Skill

仅在用户选择 PPTX 输出、且统一译稿已通过质量审计后使用。读取 .translation-task-pro.json 和 translated_markdown，只负责把该 Markdown 排成幻灯片并检查成品；不重新翻译、总结、补写或调整正文语义，不读取或保存偏好。PPTX Reader 负责读取源课件，本 Skill 负责生成输出课件。

## 构建

1. 仅当编排器确认 PPTX 阶段签名和成品哈希命中时，才可复用已有文件；否则从清单的 shared_runtime/scripts/builder.py 绝对路径运行单格式构建，参数为 --formats pptx，并传入本轮 translated_markdown、output_dir 和 base_name translated_doc。
2. 必须确认本次退出码为 0、返回路径为 output_dir/translated_doc.pptx 且文件非空。同名旧文件不能证明本次构建成功。共享构建器使用已安装的 python-pptx；不需要另外安装 Deno、Node 或新的 Python 包。
3. 构建器将统一 Markdown 转为 16:9、原生可编辑文本框和表格；按标题和内容长度分页，不删减、不改写正文。来源页码、测验、公式文本和链接文字应保留。公式以源 Markdown 中的可见公式文本呈现；不得伪称已转为 PowerPoint 原生公式。
4. 仅嵌入 Markdown 中引用的本地图片。PDF/PPTX 图片必须是 Reader 已审核批准并正式导出的原图，保持比例，不得裁切、修图、翻译图片文字或覆盖任何叠加标注。拒绝网络图片、缺失图片和越出本次 output_dir 的路径。不要从页渲染图或未审核 OCR 推断内容。

## 检查

- 用 PPTX 解析器重新打开成品，确认幻灯片数量大于零、所有形状均在画布内，正文、标题、表格单元格和图片引用均有对应内容；报告解析失败、缺失资产或覆盖检查失败，不得交付为通过。
- 有 LibreOffice 时将成品渲染为临时 PDF/页图，逐页检查文字溢出、遮挡、异常分页和图片变形；临时预览留在本轮工作区并在成功交付后清理。当前宿主能接收图像时，可将页图传给模型视觉检查。无法渲染或传图时，说明视觉版面检查未完成，不要声称已逐页目视通过。
- 发现漏字、错误顺序或语义问题时退回编排器修复统一 Markdown，并重建所有已选格式；只在 PPTX 版面局部失败时重建 PPTX。不得为了塞入页面而删除或概括原文。
