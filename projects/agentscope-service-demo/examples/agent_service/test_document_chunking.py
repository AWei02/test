"""Chunking/parent retrieval regression tests: no external services."""
import unittest
from pydantic import ValidationError
from agentscope.rag._vdb import VectorSearchResult
from document_chunking import ChunkingConfig, build_chunks, split_text, expand_parent_hits


class ChunkingTests(unittest.TestCase):
    def test_literal_separator_and_lossless_hard_split(self):
        source = 'abc|def|' * 30
        pieces = list(split_text(source, '|', 50))
        self.assertEqual(''.join(pieces), source)
        self.assertTrue(all(len(p) <= 50 for p in pieces))
        source = '一二三四五' * 40
        self.assertEqual(''.join(split_text(source, '', 50)), source)
        self.assertEqual(''.join(split_text(source, '.*', 50)), source)

    def test_overlap_and_newline_escapes(self):
        pieces = list(split_text('0123456789'*20, '', 50, 10))
        self.assertEqual(pieces[0][-10:], pieces[1][:10])
        self.assertEqual(list(split_text('first\nsecond\nthird', r'\n', 12, 3)), ['first', 'second', 'third'])

    def test_overlap_only_within_oversized_segment(self):
        self.assertEqual(list(split_text('short\nabcdefghijklm\nlast', r'\n', 6, 2)),
                         ['short', 'abcdef', 'efghij', 'ijklm', 'last'])
        self.assertEqual(list(split_text('abcdef\n123456\nxy', r'\n', 6, 2)),
                         ['abcdef', '123456', 'xy'])
        self.assertEqual(list(split_text('\n\nfirst\n\nsecond\n', r'\n', 20, 5)), ['first', 'second'])
        self.assertEqual(list(split_text('one.*two.*three', '.*', 50, 10)), ['one.*', 'two.*', 'three'])
        self.assertEqual(list(split_text('aa\n\nbb\ncc', r'\n\n', 50, 10)), ['aa', 'bb\ncc'])

    def test_general_and_parent_child_respect_every_separator(self):
        raw = 'First paragraph\n\nSecond paragraph\n\n' + 'z'*120
        chunks = build_chunks(raw, 't', ChunkingConfig(separator=r'\n\n', max_length=50, overlap=10))
        self.assertEqual([c.content.text for c in chunks], ['First paragraph', 'Second paragraph', 'z'*50, 'z'*50, 'z'*40])
        chunks = build_chunks('One\nTwo\n\nThree\nFour', 't', ChunkingConfig(mode='parent_child'))
        self.assertEqual([c.content.text for c in chunks], ['One', 'Two', 'Three', 'Four'])
        self.assertEqual([c.metadata['parent_index'] for c in chunks], [0, 0, 1, 1])

    def test_validation_and_cleaning(self):
        for settings in ({'overlap':1024}, {'max_length':49}, {'max_length':2.5}, {'mode':'bad'},
                         {'mode':'parent_child','parent_max_length':100,'child_max_length':200}):
            with self.assertRaises(ValidationError): ChunkingConfig(**settings)
        raw = 'A   B\t\tC\n\n\n\ncontact: test@example.com https://example.com/end'
        chunks = build_chunks(raw, 'test.md', ChunkingConfig(remove_urls_emails=True))
        text = '\n'.join(c.content.text for c in chunks)
        self.assertIn('A B C', text); self.assertNotIn('example.com', text)
        self.assertNotIn('\n\n\n', text)
        self.assertIn('test@example.com', '\n'.join(c.content.text for c in build_chunks(raw,'t',ChunkingConfig())))

    def test_heading_boundaries_and_indices(self):
        chunks = build_chunks('# Alpha\n\n' + 'a'*200 + '\n# Beta\n\n' + 'b'*200, 'test.md', ChunkingConfig(max_length=50, overlap=0))
        self.assertTrue(all(not ('a'*10 in c.content.text and 'b'*10 in c.content.text) for c in chunks))
        self.assertEqual([c.chunk_index for c in chunks], list(range(len(chunks))))
        self.assertTrue(all(c.total_chunks == len(chunks) and c.source == 'test.md' for c in chunks))

    def test_parent_children_context_and_per_document_dedup(self):
        chunks = build_chunks('abcdefghij'*60, 'test.md', ChunkingConfig(mode='parent_child',parent_max_length=200,child_max_length=50))
        self.assertEqual(len(chunks), 12)
        self.assertEqual(len({c.metadata['parent_index'] for c in chunks}), 3)
        self.assertTrue(all(len(c.content.text)<=50 and len(c.metadata['parent_text'])<=200 for c in chunks))
        hits = [VectorSearchResult(document_id='d', chunk=c, score=1-i/100) for i,c in enumerate(chunks)]
        expanded = expand_parent_hits(hits)
        self.assertEqual(len(expanded), 3)
        self.assertEqual(expanded[0].score, hits[0].score)
        self.assertEqual(expanded[0].chunk.content.text, chunks[0].metadata['parent_text'])
        self.assertEqual(expanded[0].chunk.metadata['matched_child_text'], chunks[0].content.text)
        self.assertEqual(len(expand_parent_hits([hits[0], hits[0].model_copy(update={'document_id':'other'})])),2)
        self.assertEqual(len(chunks[0].content.text),50)  # no mutation of the vector-store hit

    def test_full_parent_never_silently_truncates(self):
        config = ChunkingConfig(mode='parent_child',parent_mode='full',child_max_length=50)
        raw='# First\n'+ 'a'*80 + '\n# Next\n'+'b'*80
        chunks = build_chunks(raw, 'test.md', config)
        self.assertTrue(all(c.metadata['parent_text']==raw for c in chunks))
        with self.assertRaisesRegex(ValueError, '40000'):
            build_chunks('a'*40001, 'test.md', config)

    def test_empty_after_cleaning_is_explicit_error(self):
        with self.assertRaisesRegex(ValueError,'没有可用文本'):
            build_chunks('https://example.com', 'test.md', ChunkingConfig(remove_urls_emails=True))


if __name__ == '__main__': unittest.main()
