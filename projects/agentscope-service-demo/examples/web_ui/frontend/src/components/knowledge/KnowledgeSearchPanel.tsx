import { Loader2, Search } from 'lucide-react';
import { useState } from 'react';

import type { VectorSearchResult } from '@/api';
import { Badge } from '@/components/ui/badge.tsx';
import { Button } from '@/components/ui/button.tsx';
import {
	Empty,
	EmptyDescription,
	EmptyHeader,
	EmptyMedia,
	EmptyTitle,
} from '@/components/ui/empty.tsx';
import { Input } from '@/components/ui/input.tsx';
import { Label } from '@/components/ui/label.tsx';
import { Textarea } from '@/components/ui/textarea.tsx';
import { useKnowledgeBases } from '@/hooks/useKnowledgeBases.ts';
import { useTranslation } from '@/i18n/useI18n.ts';

interface Props {
	knowledgeBaseId: string;
}

/**
 * A persistent retrieval workbench.  Unlike the former transient drawer,
 * results stay visible while an operator checks source chunks and iterates on
 * a question — the shortest feedback loop for tuning a RAG knowledge base.
 */
export function KnowledgeSearchPanel({ knowledgeBaseId }: Props) {
	const { t } = useTranslation();
	const { search } = useKnowledgeBases();
	const [query, setQuery] = useState('');
	const [topK, setTopK] = useState(5);
	const [loading, setLoading] = useState(false);
	const [results, setResults] = useState<VectorSearchResult[] | null>(null);
	const [error, setError] = useState<string | null>(null);

	const handleSearch = async () => {
		const trimmed = query.trim();
		if (!trimmed) return;
		setLoading(true);
		setError(null);
		try {
			const response = await search(knowledgeBaseId, { query: trimmed, top_k: topK });
			setResults(response.results);
		} catch (e) {
			setError((e as Error).message || String(e));
			setResults(null);
		} finally {
			setLoading(false);
		}
	};

	return (
		<div className="flex min-h-0 flex-1 flex-col gap-y-5">
			<div className="rounded-xl border bg-muted/20 p-4">
				<div className="mb-3 flex items-center justify-between gap-3">
					<div>
						<h3 className="text-sm font-medium">{t('knowledge.test.title')}</h3>
						<p className="mt-1 text-xs text-muted-foreground">
							{t('knowledge.test.workbenchHint')}
						</p>
					</div>
					<Badge variant="outline">{t('knowledge.test.vectorMode')}</Badge>
				</div>
				<div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto_auto] md:items-end">
					<div className="flex flex-col gap-y-1.5">
						<Label htmlFor="kb-workbench-query" className="text-xs">
							{t('knowledge.test.queryLabel')}
						</Label>
						<Textarea
							id="kb-workbench-query"
							value={query}
							onChange={(event) => setQuery(event.target.value)}
							placeholder={t('knowledge.test.queryPlaceholder')}
							rows={2}
							disabled={loading}
						/>
					</div>
					<div className="flex items-center gap-x-2">
						<Label htmlFor="kb-workbench-top-k" className="text-xs whitespace-nowrap">
							{t('knowledge.test.topKLabel')}
						</Label>
						<Input
							id="kb-workbench-top-k"
							type="number"
							min={1}
							max={50}
							value={topK}
							onChange={(event) =>
								setTopK(Math.max(1, Math.min(50, Number(event.target.value) || 1)))
							}
							className="w-20"
							disabled={loading}
						/>
					</div>
					<Button onClick={handleSearch} disabled={loading || !query.trim()}>
						{loading ? <Loader2 className="size-3.5 animate-spin" /> : <Search className="size-3.5" />}
						{t('knowledge.test.searchButton')}
					</Button>
				</div>
			</div>

			<div className="flex min-h-0 flex-1 flex-col gap-y-3">
				<div className="flex items-center justify-between">
					<h3 className="text-sm font-medium">{t('knowledge.test.resultsTitle')}</h3>
					{results !== null && <span className="text-xs text-muted-foreground">{results.length} {t('knowledge.test.resultCount')}</span>}
				</div>
				{error && <p className="text-destructive text-sm">{error}</p>}
				{results === null ? (
					<Empty className="min-h-48 border border-dashed py-8">
						<EmptyHeader>
							<EmptyMedia variant="icon"><Search /></EmptyMedia>
							<EmptyTitle>{t('knowledge.test.readyTitle')}</EmptyTitle>
							<EmptyDescription>{t('knowledge.test.readyDescription')}</EmptyDescription>
						</EmptyHeader>
					</Empty>
				) : results.length === 0 ? (
					<Empty className="border-none py-8">
						<EmptyHeader>
							<EmptyMedia variant="icon"><Search /></EmptyMedia>
							<EmptyTitle>{t('knowledge.test.emptyTitle')}</EmptyTitle>
							<EmptyDescription>{t('knowledge.test.emptyDescription')}</EmptyDescription>
						</EmptyHeader>
					</Empty>
				) : (
					<div className="grid gap-3 xl:grid-cols-2">
						{results.map((hit, index) => <ResultCard key={`${hit.document_id}-${index}`} hit={hit} index={index} />)}
					</div>
				)}
			</div>
		</div>
	);
}

function ResultCard({ hit, index }: { hit: VectorSearchResult; index: number }) {
	const { t } = useTranslation();
	const text = hit.chunk.content && typeof hit.chunk.content === 'object' && 'text' in hit.chunk.content
		? String(hit.chunk.content.text ?? '')
		: JSON.stringify(hit.chunk.content);
	return (
		<div className="flex flex-col gap-y-2 rounded-lg border bg-card p-3">
			<div className="flex items-center gap-x-2 text-xs text-muted-foreground">
				<Badge variant="secondary" className="font-mono">#{index + 1}</Badge>
				<Badge variant="outline" className="font-mono">{t('knowledge.test.score')}: {hit.score.toFixed(4)}</Badge>
				<span className="ml-auto truncate" title={hit.chunk.source}>{hit.chunk.source}</span>
			</div>
			<p className="text-sm whitespace-pre-wrap break-words">{text}</p>
			<div className="text-xs text-muted-foreground">
				{t('knowledge.test.chunkPosition', { index: hit.chunk.chunk_index + 1, total: hit.chunk.total_chunks })}
			</div>
		</div>
	);
}
