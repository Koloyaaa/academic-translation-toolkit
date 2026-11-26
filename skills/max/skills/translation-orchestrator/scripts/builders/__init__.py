"""格式构建器模块包：将 Markdown 译文转换为 HTML / DOCX / Markdown / PPTX。"""

from .html_builder import build_html
from .docx_builder import build_docx
from .md_builder import build_markdown
from .pptx_builder import build_pptx

__all__ = ["build_html", "build_docx", "build_markdown", "build_pptx"]
