"""Create a readable, editable PowerPoint deck from the canonical Markdown."""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

import markdown
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE, MSO_SHAPE_TYPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

from .base import WATERMARK, annotate_first_occurrences, mark_handout_completion_blocks, protect_math, restore_math, source_marker_label, validate_rendered_text


SLIDE_WIDTH = Inches(13.333)
SLIDE_HEIGHT = Inches(7.5)
NAVY = RGBColor(24, 43, 64)
TEAL = RGBColor(27, 137, 142)
INK = RGBColor(43, 54, 66)
MUTED = RGBColor(105, 117, 128)
PAPER = RGBColor(250, 251, 252)
PALE_TEAL = RGBColor(231, 244, 243)
WHITE = RGBColor(255, 255, 255)
FONT_NAME = "Microsoft YaHei"
BODY_FONT_SIZE = 20
MAX_BODY_LINES = 12
MAX_BODY_ITEMS = 5
MAX_TEXT_CHARS = 340


@dataclass
class Block:
    kind: str
    text: str = ""
    level: int = 0
    ordered: bool = False
    marker: str = ""
    rows: list[list[str]] = field(default_factory=list)
    src: str = ""
    alt: str = ""


class _MarkdownBlockParser(HTMLParser):
    """Collect visible Markdown content without retaining its HTML wrappers."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[Block] = []
        self._kind: str | None = None
        self._level = 0
        self._ordered = False
        self._marker = ""
        self._buffer: list[str] = []
        self._list_stack: list[tuple[bool, int]] = []
        self._li_depth = 0
        self._table_rows: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._link_stack: list[str] = []
        self._completion_depth = 0
        self._blockquote_stack: list[bool] = []

    @staticmethod
    def _clean(text: str) -> str:
        text = text.replace("\xa0", " ")
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n[ \t]+", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _flush_text(self) -> None:
        if self._kind is None:
            self._buffer.clear()
            return
        text = self._clean("".join(self._buffer))
        if text:
            kind = self._kind
            if kind == "paragraph" and source_marker_label(text):
                kind = "source"
            self.blocks.append(Block(kind=kind, text=text, level=self._level, ordered=self._ordered, marker=self._marker))
        self._kind = None
        self._buffer.clear()
        self._marker = ""

    def _start_text(self, kind: str, level: int = 0, ordered: bool = False, marker: str = "") -> None:
        if self._kind is None:
            self._kind = kind
            self._level = level
            self._ordered = ordered
            self._marker = marker

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = dict(attrs)
        heading = re.fullmatch(r"h([1-6])", tag)
        if heading:
            self._flush_text()
            self._start_text("heading", int(heading.group(1)))
        elif tag == "blockquote":
            self._flush_text()
            is_completion = "smart-completion" in (attrs_map.get("class") or "").split()
            self._blockquote_stack.append(is_completion)
            if is_completion:
                self._completion_depth += 1
        elif tag in {"ul", "ol"}:
            try:
                start = max(1, int(attrs_map.get("start") or "1"))
            except ValueError:
                start = 1
            self._list_stack.append((tag == "ol", start))
        elif tag == "li":
            self._flush_text()
            self._li_depth += 1
            ordered = bool(self._list_stack and self._list_stack[-1][0])
            marker = ""
            if self._list_stack:
                is_ordered, next_number = self._list_stack[-1]
                if is_ordered:
                    marker = f"{next_number}. "
                    self._list_stack[-1] = (True, next_number + 1)
            self._start_text("bullet", ordered=ordered, marker=marker)
        elif tag == "p":
            if self._kind != "bullet":
                self._flush_text()
                self._start_text("completion" if self._completion_depth else "paragraph")
        elif tag == "pre":
            self._flush_text()
            self._start_text("code")
        elif tag == "table":
            self._flush_text()
            self._table_rows = []
        elif tag == "tr" and self._table_rows is not None:
            self._row = []
        elif tag in {"th", "td"} and self._row is not None:
            self._cell = []
        elif tag == "img":
            self._flush_text()
            self.blocks.append(Block(kind="image", src=(attrs_map.get("src") or "").strip(), alt=(attrs_map.get("alt") or "").strip()))
        elif tag == "a":
            self._link_stack.append((attrs_map.get("href") or "").strip())
        elif tag == "br" and self._kind is not None:
            self._buffer.append("\n")
        elif tag == "hr":
            self._flush_text()

    def handle_endtag(self, tag: str) -> None:
        if re.fullmatch(r"h[1-6]", tag) or tag in {"p", "pre"}:
            self._flush_text()
        elif tag == "blockquote":
            self._flush_text()
            if self._blockquote_stack and self._blockquote_stack.pop():
                self._completion_depth -= 1
        elif tag == "li":
            self._flush_text()
            self._li_depth = max(0, self._li_depth - 1)
        elif tag in {"ul", "ol"} and self._list_stack:
            self._list_stack.pop()
        elif tag in {"th", "td"} and self._row is not None and self._cell is not None:
            self._row.append(self._clean("".join(self._cell)))
            self._cell = None
        elif tag == "tr" and self._table_rows is not None and self._row is not None:
            if any(cell for cell in self._row):
                self._table_rows.append(self._row)
            self._row = None
        elif tag == "table" and self._table_rows is not None:
            if self._table_rows:
                self.blocks.append(Block(kind="table", rows=self._table_rows))
            self._table_rows = None
        elif tag == "a" and self._link_stack:
            href = self._link_stack.pop()
            if href and self._kind is not None:
                visible = self._clean("".join(self._buffer))
                if href not in visible:
                    self._buffer.append(f" ({href})")

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)
        elif self._kind is not None:
            self._buffer.append(data)
        elif self._li_depth:
            self._start_text("paragraph")
            self._buffer.append(data)


def _markdown_blocks(markdown_text: str) -> list[Block]:
    annotated = annotate_first_occurrences(markdown_text)
    protected, formulas = protect_math(annotated)
    rendered = markdown.markdown(protected, extensions=["tables", "fenced_code", "sane_lists"])
    rendered = mark_handout_completion_blocks(rendered)
    rendered = restore_math(rendered, formulas)
    validate_rendered_text(rendered, "PPTX")
    parser = _MarkdownBlockParser()
    parser.feed(rendered)
    parser.close()
    return parser.blocks


def _display_width(text: str) -> float:
    width = 0.0
    for char in text:
        if char == "\n":
            continue
        width += 1.0 if unicodedata.east_asian_width(char) in {"F", "W"} else 0.55
    return width


def _estimated_lines(text: str, width_inches: float = 11.7, font_size: int = BODY_FONT_SIZE) -> int:
    capacity = max(15.0, width_inches * 72 / (font_size * 1.12))
    explicit_lines = text.splitlines() or [text]
    return max(1, sum(max(1, math.ceil(_display_width(line) / capacity)) for line in explicit_lines))


def _split_long_text(text: str, limit: int = MAX_TEXT_CHARS) -> list[str]:
    if len(text) <= limit:
        return [text]
    sentences = re.split(r"(?<=[。！？；.!?;])\s*", text)
    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        if not sentence:
            continue
        while len(sentence) > limit:
            cut = limit
            boundary = max(sentence.rfind(" ", 0, limit), sentence.rfind("，", 0, limit), sentence.rfind(",", 0, limit))
            if boundary > limit // 2:
                cut = boundary + 1
            if current:
                pieces.append(current)
                current = ""
            pieces.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if current and len(current) + len(sentence) + 1 > limit:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces or [text]


def _set_background(slide, color: RGBColor) -> None:
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = color


def _add_cover(prs: Presentation, title: str) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_background(slide, NAVY)
    accent = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.9), Inches(1.56), Inches(0.12), Inches(3.8))
    accent.fill.solid()
    accent.fill.fore_color.rgb = TEAL
    accent.line.fill.background()
    title_shape = slide.shapes.add_textbox(Inches(1.4), Inches(2.15), Inches(10.8), Inches(2.5))
    title_frame = title_shape.text_frame
    title_frame.clear()
    title_frame.word_wrap = True
    title_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    title_frame.margin_left = 0
    title_frame.margin_right = 0
    paragraph = title_frame.paragraphs[0]
    paragraph.text = title or "学习材料"
    paragraph.font.name = FONT_NAME
    title_width = _display_width(title or "学习材料")
    paragraph.font.size = Pt(max(20, min(38, int(38 * 38 / max(title_width, 38)))))
    paragraph.font.bold = True
    paragraph.font.color.rgb = WHITE
    paragraph.space_after = Pt(8)
    subtitle = slide.shapes.add_textbox(Inches(1.42), Inches(4.95), Inches(10.5), Inches(0.5))
    run = subtitle.text_frame.paragraphs[0].add_run()
    run.text = "学习材料"
    run.font.name = FONT_NAME
    run.font.size = Pt(16)
    run.font.color.rgb = RGBColor(194, 211, 223)
    footer = slide.shapes.add_textbox(Inches(1.42), Inches(6.85), Inches(10.8), Inches(0.28))
    run = footer.text_frame.paragraphs[0].add_run()
    run.text = WATERMARK
    run.font.name = FONT_NAME
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(173, 190, 203)


def _add_slide_header(slide, title: str) -> None:
    accent = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.72), Inches(0.48), Inches(0.68), Inches(0.08))
    accent.fill.solid()
    accent.fill.fore_color.rgb = TEAL
    accent.line.fill.background()
    box = slide.shapes.add_textbox(Inches(0.72), Inches(0.66), Inches(11.9), Inches(0.78))
    frame = box.text_frame
    frame.clear()
    frame.word_wrap = True
    frame.margin_left = frame.margin_right = 0
    paragraph = frame.paragraphs[0]
    paragraph.text = title or "课程内容"
    paragraph.font.name = FONT_NAME
    title_width = _display_width(title or "课程内容")
    paragraph.font.size = Pt(max(12, min(26, int(26 * 30 / max(title_width, 30)))))
    paragraph.font.bold = True
    paragraph.font.color.rgb = NAVY
    paragraph.space_after = Pt(0)


def _add_footer(slide) -> None:
    box = slide.shapes.add_textbox(Inches(0.72), Inches(7.08), Inches(11.9), Inches(0.2))
    box.name = "pptx-footer"
    frame = box.text_frame
    frame.clear()
    frame.margin_left = frame.margin_right = 0
    paragraph = frame.paragraphs[0]
    paragraph.text = WATERMARK
    paragraph.alignment = PP_ALIGN.RIGHT
    paragraph.font.name = FONT_NAME
    paragraph.font.size = Pt(8)
    paragraph.font.color.rgb = MUTED


def _add_text_item(slide, block: Block, top: float) -> float:
    if block.kind == "source":
        left, width, font_size, color, alignment = 0.72, 11.9, 12, MUTED, PP_ALIGN.CENTER
        prefix = ""
    elif block.kind == "code":
        left, width, font_size, color, alignment = 0.85, 11.7, 16, INK, PP_ALIGN.LEFT
        prefix = ""
    elif block.kind == "completion":
        left, width, font_size, color, alignment = 0.92, 11.45, 18, INK, PP_ALIGN.LEFT
        prefix = ""
    elif block.kind == "bullet":
        left, width, font_size, color, alignment = 1.08, 11.45, BODY_FONT_SIZE, INK, PP_ALIGN.LEFT
        prefix = block.marker if block.ordered else ""
    else:
        left, width, font_size, color, alignment = 0.78, 11.85, BODY_FONT_SIZE, INK, PP_ALIGN.LEFT
        prefix = ""
    lines = _estimated_lines(block.text, width, font_size)
    height = max(0.32, lines * 0.34 + (0.02 if block.kind == "source" else 0.1))
    if block.kind == "code":
        panel = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.72), Inches(top), Inches(11.9), Inches(height + 0.12))
        panel.fill.solid()
        panel.fill.fore_color.rgb = PALE_TEAL
        panel.line.fill.background()
    elif block.kind == "completion":
        panel = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.72), Inches(top), Inches(11.9), Inches(height + 0.12))
        panel.fill.solid()
        panel.fill.fore_color.rgb = RGBColor(238, 246, 248)
        panel.line.color.rgb = TEAL
    elif block.kind == "source":
        for line_left, line_width in ((0.72, 3.0), (9.62, 3.0)):
            line = slide.shapes.add_shape(
                MSO_SHAPE.RECTANGLE,
                Inches(line_left),
                Inches(top + 0.16),
                Inches(line_width),
                Inches(0.012),
            )
            line.fill.solid()
            line.fill.fore_color.rgb = RGBColor(190, 199, 207)
            line.line.fill.background()
    elif block.kind == "bullet" and not block.ordered:
        dot = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(0.82), Inches(top + 0.14), Inches(0.11), Inches(0.11))
        dot.fill.solid()
        dot.fill.fore_color.rgb = TEAL
        dot.line.fill.background()
    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    frame = box.text_frame
    frame.clear()
    frame.word_wrap = True
    frame.vertical_anchor = MSO_ANCHOR.TOP
    frame.margin_left = frame.margin_right = Inches(0.02)
    frame.margin_top = frame.margin_bottom = Inches(0.02)
    paragraph = frame.paragraphs[0]
    paragraph.text = prefix + block.text
    paragraph.alignment = alignment
    paragraph.line_spacing = 1.08
    paragraph.font.name = "Consolas" if block.kind == "code" else FONT_NAME
    paragraph.font.size = Pt(font_size)
    paragraph.font.color.rgb = color
    return height + (0.2 if block.kind != "source" else 0.05)


def _add_body_slide(prs: Presentation, title: str, blocks: list[Block]) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_background(slide, PAPER)
    _add_slide_header(slide, title)
    top = 1.55
    for block in blocks:
        top += _add_text_item(slide, block, top)
    _add_footer(slide)


def _add_section_slide(prs: Presentation, title: str) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_background(slide, PALE_TEAL)
    band = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(0.24), SLIDE_HEIGHT)
    band.fill.solid()
    band.fill.fore_color.rgb = TEAL
    band.line.fill.background()
    box = slide.shapes.add_textbox(Inches(1.1), Inches(2.0), Inches(10.9), Inches(3.0))
    frame = box.text_frame
    frame.clear()
    frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    frame.word_wrap = True
    paragraph = frame.paragraphs[0]
    paragraph.text = title
    paragraph.font.name = FONT_NAME
    title_width = _display_width(title)
    paragraph.font.size = Pt(max(20, min(34, int(34 * 24 / max(title_width, 24)))))
    paragraph.font.bold = True
    paragraph.font.color.rgb = NAVY
    _add_footer(slide)


def _resolve_image(src: str, asset_root: Path) -> Path:
    parsed = urlsplit(src)
    if parsed.scheme or parsed.netloc or not parsed.path:
        raise ValueError(f"Only local, Reader-approved images can be embedded in PPTX: {src}")
    relative = Path(unquote(parsed.path.replace("\\", "/")))
    root = asset_root.resolve()
    image_path = (root / relative).resolve()
    if not image_path.is_relative_to(root):
        raise ValueError(f"PPTX image path escapes the output directory: {src}")
    if not image_path.is_file():
        raise FileNotFoundError(f"PPTX image referenced by translated Markdown was not found: {image_path}")
    return image_path


def _add_image_slide(prs: Presentation, title: str, block: Block, asset_root: Path) -> None:
    image_path = _resolve_image(block.src, asset_root)
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_background(slide, PAPER)
    _add_slide_header(slide, title)
    max_width, max_height = 11.1, 4.7
    with Image.open(image_path) as image:
        aspect = image.width / max(image.height, 1)
    if aspect >= max_width / max_height:
        width = max_width
        height = width / aspect
    else:
        height = max_height
        width = height * aspect
    left = (13.333 - width) / 2
    top = 1.5 + (4.8 - height) / 2
    slide.shapes.add_picture(str(image_path), Inches(left), Inches(top), width=Inches(width), height=Inches(height))
    if block.alt:
        caption_lines = _estimated_lines(block.alt, 11.9, 12)
        if caption_lines <= 2:
            caption_box = slide.shapes.add_textbox(Inches(0.72), Inches(6.38), Inches(11.9), Inches(0.48))
            caption_box.text_frame.word_wrap = True
            caption_box.text_frame.margin_left = caption_box.text_frame.margin_right = Inches(0.02)
            caption = caption_box.text_frame.paragraphs[0]
            caption.text = block.alt
            caption.font.name = FONT_NAME
            caption.font.size = Pt(12)
            caption.font.color.rgb = MUTED
            caption.alignment = PP_ALIGN.CENTER
    _add_footer(slide)
    if block.alt and _estimated_lines(block.alt, 11.9, 12) > 2:
        for chunk in _split_long_text(block.alt):
            _add_body_slide(prs, title, [Block(kind="paragraph", text=chunk)])


def _add_table_slides(prs: Presentation, title: str, rows: list[list[str]]) -> None:
    if not rows:
        return
    columns = max((len(row) for row in rows), default=0)
    if columns == 0:
        return
    max_cell_chars = max((len(cell) for row in rows for cell in row), default=0)
    def add_fallback_slides() -> None:
        fallback = [Block(kind="bullet", text=" | ".join(cell for cell in row if cell)) for row in rows if any(row)]
        page: list[Block] = []
        page_lines = 0
        page_number = 0
        for row in fallback:
            for text in _split_long_text(row.text):
                piece = Block(kind="bullet", text=text)
                lines = _estimated_lines(text, 11.45)
                if page and (len(page) >= MAX_BODY_ITEMS or page_lines + lines > MAX_BODY_LINES):
                    page_title = title if page_number == 0 else f"{title}（表格续）"
                    _add_body_slide(prs, page_title, page)
                    page_number += 1
                    page = []
                    page_lines = 0
                page.append(piece)
                page_lines += lines
        if page:
            page_title = title if page_number == 0 else f"{title}（表格续）"
            _add_body_slide(prs, page_title, page)

    if columns > 6 or max_cell_chars > 180:
        add_fallback_slides()
        return
    normalized_rows = [row + [""] * (columns - len(row)) for row in rows]
    header = normalized_rows[0]
    body = normalized_rows[1:]
    font_size = 12 if columns >= 4 or max_cell_chars > 60 else 14
    column_width = 11.9 / columns

    def row_height(row: list[str], is_header: bool = False) -> float:
        size = 14 if is_header and font_size > 12 else font_size
        lines = max((_estimated_lines(cell, column_width - 0.2, size) for cell in row), default=1)
        return max(0.48, lines * (size * 1.2 / 72) + 0.16)

    header_height = row_height(header, is_header=True)
    if header_height > 2.0:
        add_fallback_slides()
        return
    chunks: list[list[list[str]]] = []
    chunk: list[list[str]] = []
    used_height = header_height
    for row in body:
        height = row_height(row)
        if header_height + height > 5.35:
            add_fallback_slides()
            return
        if chunk and used_height + height > 5.35:
            chunks.append(chunk)
            chunk = []
            used_height = header_height
        chunk.append(row)
        used_height += height
    if chunk or not chunks:
        chunks.append(chunk)
    for index, chunk in enumerate(chunks):
        slide_title = title if index == 0 else f"{title}（表格续）"
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        _set_background(slide, PAPER)
        _add_slide_header(slide, slide_title)
        page_rows = [header, *chunk]
        row_heights = [header_height, *(row_height(row) for row in chunk)]
        table_height = sum(row_heights)
        shape = slide.shapes.add_table(len(page_rows), columns, Inches(0.72), Inches(1.52), Inches(11.9), Inches(table_height))
        table = shape.table
        for column in table.columns:
            column.width = Inches(11.9 / columns)
        for row_index, row_values in enumerate(page_rows):
            table.rows[row_index].height = Inches(row_heights[row_index])
            for column_index, value in enumerate(row_values):
                cell = table.cell(row_index, column_index)
                cell.text = value
                cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                cell.margin_left = cell.margin_right = Inches(0.08)
                cell.margin_top = cell.margin_bottom = Inches(0.04)
                cell.fill.solid()
                cell.fill.fore_color.rgb = NAVY if row_index == 0 else (WHITE if row_index % 2 else PALE_TEAL)
                for paragraph in cell.text_frame.paragraphs:
                    paragraph.font.name = FONT_NAME
                    paragraph.font.size = Pt(14 if row_index == 0 and font_size > 12 else font_size)
                    paragraph.font.bold = row_index == 0
                    paragraph.font.color.rgb = WHITE if row_index == 0 else INK
        _add_footer(slide)


def _normalise_for_coverage(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _deck_text(prs: Presentation) -> str:
    parts: list[str] = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                parts.append(shape.text_frame.text)
            if shape.has_table:
                for row in shape.table.rows:
                    parts.extend(cell.text for cell in row.cells)
    return "\n".join(parts)


def build_pptx(markdown_text: str, output_path: str | Path, asset_root: str | Path | None = None) -> str:
    """Build a 16:9 editable deck, splitting content without summarizing it."""
    output_path = Path(output_path)
    asset_root = Path(asset_root) if asset_root else output_path.parent
    blocks = _markdown_blocks(markdown_text)
    first_title_index = next((i for i, block in enumerate(blocks) if block.kind == "heading" and block.level == 1), None)
    title = blocks[first_title_index].text if first_title_index is not None else "学习材料"
    prs = Presentation()
    prs.slide_width = SLIDE_WIDTH
    prs.slide_height = SLIDE_HEIGHT
    prs.core_properties.title = title
    prs.core_properties.subject = "由已审计的统一 Markdown 生成的学习幻灯片"
    _add_cover(prs, title)

    current_title = title
    continuation = 0
    group: list[Block] = []
    group_lines = 0
    heading_pending = False
    consumed_title = False

    def flush_group() -> None:
        nonlocal group, group_lines, continuation, heading_pending
        if not group:
            return
        slide_title = current_title if continuation == 0 else f"{current_title}（续）"
        _add_body_slide(prs, slide_title, group)
        continuation += 1
        group = []
        group_lines = 0
        heading_pending = False

    for index, block in enumerate(blocks):
        if block.kind == "heading":
            if block.level == 1 and index == first_title_index and not consumed_title:
                consumed_title = True
                continue
            flush_group()
            if heading_pending and current_title and current_title != title:
                _add_section_slide(prs, current_title)
            current_title = block.text or "课程内容"
            continuation = 0
            heading_pending = True
            continue
        if block.kind == "image":
            flush_group()
            _add_image_slide(prs, current_title, block, asset_root)
            continuation += 1
            heading_pending = False
            continue
        if block.kind == "table":
            flush_group()
            _add_table_slides(prs, current_title, block.rows)
            continuation += 1
            heading_pending = False
            continue
        chunks = _split_long_text(block.text)
        for chunk_index, chunk in enumerate(chunks):
            piece = Block(kind=block.kind, text=chunk, ordered=block.ordered, marker=block.marker if chunk_index == 0 else "")
            if piece.kind == "completion":
                lines = _estimated_lines(chunk, 11.45, 18)
            elif piece.kind == "bullet":
                lines = _estimated_lines(chunk, 11.45, BODY_FONT_SIZE)
            elif piece.kind == "source":
                lines = _estimated_lines(chunk, 11.9, 12)
            elif piece.kind == "code":
                lines = _estimated_lines(chunk, 11.7, 16)
            else:
                lines = _estimated_lines(chunk, 11.85, BODY_FONT_SIZE)
            item_limit_reached = len(group) >= MAX_BODY_ITEMS and piece.kind != "source"
            if group and (item_limit_reached or group_lines + lines > MAX_BODY_LINES):
                flush_group()
            group.append(piece)
            group_lines += lines
            heading_pending = False
    flush_group()
    if heading_pending and current_title and current_title != title:
        _add_section_slide(prs, current_title)

    if len(prs.slides) <= 1:
        raise ValueError("The translated Markdown did not contain enough content to create a PowerPoint deck")
    total = len(prs.slides)
    page_number = 0
    for slide in list(prs.slides)[1:]:
        page_number += 1
        for shape in slide.shapes:
            if shape.name == "pptx-footer":
                shape.text_frame.text = f"{page_number:02d} / {total:02d}    {WATERMARK}"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(output_path))
    reopened = Presentation(str(output_path))
    if len(reopened.slides) != total:
        raise RuntimeError("Saved PowerPoint slide count changed when reopened")
    expected_images = sum(block.kind == "image" for block in blocks)
    actual_images = sum(shape.shape_type == MSO_SHAPE_TYPE.PICTURE for slide in reopened.slides for shape in slide.shapes)
    if actual_images != expected_images:
        raise RuntimeError(f"PowerPoint image coverage check failed: expected {expected_images}, found {actual_images}")
    for slide in reopened.slides:
        for shape in slide.shapes:
            if shape.left < 0 or shape.top < 0 or shape.left + shape.width > SLIDE_WIDTH + Inches(0.02) or shape.top + shape.height > SLIDE_HEIGHT + Inches(0.02):
                raise RuntimeError(f"PowerPoint element extends beyond the slide: {shape.name}")
    deck_text = _normalise_for_coverage(_deck_text(reopened))
    expected_text = []
    for block in blocks:
        if block.kind == "heading" or block.kind in {"paragraph", "bullet", "source", "code", "completion"}:
            expected_text.extend(_split_long_text(block.text))
        elif block.kind == "table":
            expected_text.extend(cell for row in block.rows for cell in row if cell)
        elif block.kind == "image" and block.alt:
            expected_text.append(block.alt)
    missing = [text for text in expected_text if _normalise_for_coverage(text) not in deck_text]
    if missing:
        raise RuntimeError(f"PowerPoint text coverage check failed for {len(missing)} content block(s)")
    return str(output_path)
