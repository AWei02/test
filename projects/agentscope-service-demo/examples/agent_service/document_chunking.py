"""Deterministic, document-local character chunking; no model/API calls."""
import re
from typing import Literal
from pydantic import BaseModel, Field, model_validator, ConfigDict
from agentscope.rag import Chunk
from agentscope.message import TextBlock
from document_parsing import markdown_sections


class ChunkingConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    mode: Literal['general', 'parent_child'] = 'general'
    separator: str = Field(r'\n', max_length=50)
    max_length: int = Field(1024, ge=50, le=16000)
    overlap: int = Field(50, ge=0, le=8000)
    normalize_whitespace: bool = True
    remove_urls_emails: bool = False
    parent_mode: Literal['paragraph', 'full'] = 'paragraph'
    parent_separator: str = Field(r'\n\n', max_length=50)
    parent_max_length: int = Field(2048, ge=50, le=16000)
    child_separator: str = Field(r'\n', max_length=50)
    child_max_length: int = Field(512, ge=50, le=16000)

    @model_validator(mode='after')
    def check(self):
        if self.mode == 'general' and self.overlap >= self.max_length:
            raise ValueError('重叠长度必须小于分段最大长度')
        if self.mode == 'parent_child' and self.parent_mode == 'paragraph' and self.child_max_length > self.parent_max_length:
            raise ValueError('子块最大长度不能大于父块最大长度')
        return self


def delimiter(value):
    # Literal delimiter, never a user-supplied regular expression.
    return re.sub(r'\\([nrt\\])', lambda m: {'n':'\n', 'r':'\r', 't':'\t', '\\':'\\'}[m[1]], value)


def split_text(text, separator, size, overlap=0):
    """Split at every literal delimiter, then window only oversized segments.

    Keep delimiters at the end of their segment (trim surrounding whitespace).
    Overlap is local to one segment and never crosses a delimiter boundary.
    """
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError('Require size > 0 and 0 <= overlap < size')
    separator = delimiter(separator)
    start = 0
    while start < len(text):
        boundary = text.find(separator, start) if separator else -1
        end = boundary + len(separator) if boundary >= 0 else len(text)
        segment = text[start:end].strip()
        offset = 0
        while offset < len(segment):
            stop = min(offset + size, len(segment))
            content = segment[offset:stop].strip()
            if content:
                yield content
            if stop == len(segment):
                break
            offset = stop - overlap
        start = end


def build_chunks(markdown, filename, config):
    if len(markdown) > 8_000_000:
        raise ValueError('Markdown 超过 800 万字符，请拆分文件后再切片')
    text = markdown.replace('\r\n', '\n').replace('\r', '\n')
    if config.normalize_whitespace:
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'\n[ \t]*\n(?:[ \t]*\n)+', '\n\n', text)
    if config.remove_urls_emails:
        text = re.sub(r'(?:https?://|www\.)[^\s<>\)\]]+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '', text)
    # Markdown headings remain hard boundaries for general/paragraph mode.
    sections = markdown_sections(text, filename)
    if config.mode == 'parent_child' and config.parent_mode == 'full':
        if len(text) > 40000:
            raise ValueError('全文父块最多 40000 字符，请改用段落父块；不会自动截断文档')
        from agentscope.rag import Section
        sections = [Section(content=TextBlock(text=text), source=filename)]
    chunks = []
    parent_index = 0
    for section in sections:
        content = section.content.text
        if config.mode == 'general':
            groups = [(None, split_text(content, config.separator, config.max_length, config.overlap))]
        else:
            parents = ([content] if config.parent_mode == 'full' else
                       split_text(content, config.parent_separator, config.parent_max_length))
            groups = ((parent, split_text(parent, config.child_separator, config.child_max_length)) for parent in parents)
        for parent, children in groups:
            for child in children:
                metadata = {**section.metadata, 'chunk_mode': config.mode, 'length_unit': 'characters'}
                if parent is not None:
                    metadata.update(parent_index=parent_index, parent_text=parent)
                chunks.append(Chunk(content=TextBlock(text=child), source=filename,
                    chunk_index=len(chunks), total_chunks=0, metadata=metadata))
                if len(chunks) > 20000:
                    raise ValueError('分片超过 20000 个，请增大长度或拆分文件')
            parent_index += 1
    if not chunks:
        raise ValueError('清洗后没有可用文本，请调整清洗规则或检查 Markdown')
    for chunk in chunks:
        chunk.total_chunks = len(chunks)
    return chunks


def expand_parent_hits(hits):
    """After child retrieval/reranking, return one context per document parent.

    No cross-document lookups: parent text is stored alongside the child and
    covered by exactly the same document ACL. Scores remain child-hit scores.
    """
    result, seen = [], set()
    for hit in hits:
        meta = hit.chunk.metadata
        parent = meta.get('parent_text') if meta.get('chunk_mode') == 'parent_child' else None
        key = (hit.document_id, 'parent', meta.get('parent_index')) if parent else (hit.document_id, 'chunk', hit.chunk.chunk_index)
        if key in seen:
            continue
        seen.add(key)
        if parent:
            chunk = hit.chunk.model_copy(update={'content': TextBlock(text=parent),
                'metadata': {**meta, 'matched_child_text': hit.chunk.content.text}})
            hit = hit.model_copy(update={'chunk': chunk})
        result.append(hit)
    return result
