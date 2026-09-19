import { format } from 'date-fns';
import { Copy, Database, Ellipsis, Files, Loader2, Network, Pencil, Plus, Settings2, Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';
import { copyToClipboard } from '@/utils/common';

import type { ChatModelConfig, KnowledgeBaseView } from '@/api';
import { client } from '@/api/client.ts';
import { CreateCredentialDialog } from '@/components/dialog/CreateCredentialDialog.tsx';
import { CreateKnowledgeBaseDialog } from '@/components/dialog/CreateKnowledgeBaseDialog.tsx';
import { DeleteDialog } from '@/components/dialog/DeleteDialog.tsx';
import { EditKnowledgeBaseDialog } from '@/components/dialog/EditKnowledgeBaseDialog.tsx';
import { KnowledgeDocumentsPanel } from '@/components/knowledge/KnowledgeDocumentsPanel.tsx';
import { KnowledgePermissionSettings } from '@/components/knowledge/KnowledgePermissionSettings';
import { RetrievalWorkbench } from '@/components/knowledge/RetrievalWorkbench.tsx';
import { ParsingSettings } from '@/components/knowledge/DocumentParsing';
import { GraphRulesEditor, type RuleStatus } from '@/components/knowledge/GraphRulesEditor';
import { LlmSelect } from '@/components/select/LlmSelect.tsx';
import { Badge } from '@/components/ui/badge.tsx';
import { Button } from '@/components/ui/button.tsx';
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu.tsx';
import {
	Empty,
	EmptyContent,
	EmptyDescription,
	EmptyHeader,
	EmptyMedia,
	EmptyTitle,
} from '@/components/ui/empty.tsx';
import { Separator } from '@/components/ui/separator.tsx';
import {
	Sidebar,
	SidebarContent,
	SidebarFooter,
	SidebarGroup,
	SidebarGroupContent,
	SidebarGroupLabel,
	SidebarHeader,
	SidebarMenu,
	SidebarMenuAction,
	SidebarMenuButton,
	SidebarMenuItem,
} from '@/components/ui/sidebar.tsx';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs.tsx';
import { useKnowledgeBases } from '@/hooks/useKnowledgeBases.ts';

function DetailPanel({ knowledgeBase }: { knowledgeBase?: KnowledgeBaseView }) {
	const { t } = useTranslation();

	if (!knowledgeBase) {
		return (
			<div className="flex h-full items-center justify-center">
				<Empty className="border-none">
					<EmptyHeader>
						<EmptyTitle>{t('knowledge.selectHint')}</EmptyTitle>
						<EmptyDescription>{t('knowledge.selectHintDescription')}</EmptyDescription>
					</EmptyHeader>
				</Empty>
			</div>
		);
	}

	return (
		<div className="flex h-full flex-col">
			{/* Header */}
			<div className="shrink-0 flex flex-wrap items-start justify-between gap-4 p-[18px_18px_16px]">
				<div className="flex flex-col gap-y-1 min-w-0">
					<div className="flex items-center gap-x-2">
						<span className="truncate text-lg font-medium tracking-[-0.015em] text-foreground">
							{knowledgeBase.name}
						</span>
						{!knowledgeBase.editable && (
							<Badge variant="secondary" title={t('common.readOnlyTooltip')}>
								{t('common.readOnly')}
							</Badge>
						)}
					</div>
					{knowledgeBase.description ? (
						<p className="text-sm text-text-data">{knowledgeBase.description}</p>
					) : null}
				</div>
				<button
					type="button"
					className="ml-auto flex max-w-full items-center gap-2 rounded-md border px-2 py-1 font-mono text-xs hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
					title="点击复制完整知识库 ID"
					aria-label={`复制知识库 ID：${knowledgeBase.id}`}
					onClick={async () => {
						if (await copyToClipboard(knowledgeBase.id)) {
							toast.success('知识库 ID 已复制');
						} else {
							toast.error('复制失败，请手动选择并复制 ID');
						}
					}}
				>
					<span className="select-text break-all">{knowledgeBase.id}</span>
					<Copy className="size-3.5 shrink-0" aria-hidden="true" />
				</button>
			</div>

			<Separator className="shrink-0" />

			<Tabs defaultValue="documents" className="group/knowledge-tabs relative flex min-h-0 flex-1 flex-col">
				<div className="shrink-0 px-[18px] pt-3 lg:group-has-[[data-testid=chunking-preview]]/knowledge-tabs:w-1/2">
					<TabsList className="h-auto max-w-full flex-wrap">
						<TabsTrigger value="overview"><Database className="size-3.5" />{t('knowledge.tabs.overview')}</TabsTrigger>
						<TabsTrigger value="documents"><Files className="size-3.5" />{t('knowledge.tabs.documents')}</TabsTrigger>
						<TabsTrigger value="retrieval">{t('knowledge.tabs.retrieval')}</TabsTrigger>
						<TabsTrigger value="graph"><Network className="size-3.5" />{t('knowledge.tabs.graph')}</TabsTrigger>
						<TabsTrigger value="settings"><Settings2 className="size-3.5" />{t('knowledge.tabs.settings')}</TabsTrigger>
					</TabsList>
				</div>
				<div className="min-h-0 flex-1 overflow-y-auto p-[20px_18px_24px]">
					<TabsContent value="overview" className="mt-0">
						<div className="flex flex-col gap-y-6">
							<KnowledgeHealthCard knowledgeBase={knowledgeBase} />
							<ConfigCard knowledgeBase={knowledgeBase} />
						</div>
					</TabsContent>
					<TabsContent value="documents" className="mt-0 h-full min-h-0">
						<KnowledgeDocumentsPanel key={knowledgeBase.id} knowledgeBaseId={knowledgeBase.id} editable={knowledgeBase.editable} />
					</TabsContent>
					<TabsContent value="retrieval" className="mt-0 min-h-full">
						<RetrievalWorkbench key={knowledgeBase.id} knowledgeBaseId={knowledgeBase.id} editable={knowledgeBase.editable} />
					</TabsContent>
					<TabsContent value="graph" className="mt-0">
						<GraphRagPanel key={knowledgeBase.id} knowledgeBaseId={knowledgeBase.id} />
					</TabsContent>
					<TabsContent value="settings" className="mt-0">
                        {knowledgeBase.editable && <KnowledgePermissionSettings key={knowledgeBase.id} kbId={knowledgeBase.id} />}
                        {knowledgeBase.editable && <ParsingSettings key={'parsing-' + knowledgeBase.id} kbId={knowledgeBase.id} />}
						<SettingsPanel knowledgeBase={knowledgeBase} />
					</TabsContent>
				</div>
			</Tabs>
		</div>
	);
}

function KnowledgeHealthCard({ knowledgeBase }: { knowledgeBase: KnowledgeBaseView }) {
	const { t } = useTranslation();
	const counts = knowledgeBase.status_counts;
	const cards = [
		[t('knowledge.health.ready'), counts.ready, 'text-emerald-700'],
        ['待审核', (counts.awaiting_parse_confirmation ?? 0) + (counts.awaiting_chunk_confirmation ?? 0), 'text-amber-700'],
		[t('knowledge.health.processing'), counts.pending + counts.parsing + counts.chunking + counts.indexing, 'text-primary'],
		[t('knowledge.health.failed'), counts.error, 'text-destructive'],
	] as const;
	return (
		<div className="rounded-xl border bg-muted/20 p-4">
			<div className="mb-3">
				<h3 className="text-sm font-medium">{t('knowledge.health.title')}</h3>
				<p className="mt-1 text-xs text-muted-foreground">{t('knowledge.health.description')}</p>
			</div>
			<div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
				{cards.map(([label, value, tone]) => (
					<div key={label} className="rounded-lg border bg-card px-3 py-2.5">
						<div className="text-xs text-muted-foreground">{label}</div>
						<div className={`mt-1 text-xl font-medium ${tone}`}>{value}</div>
					</div>
				))}
			</div>
		</div>
	);
}

type GraphSnapshot = {
	nodes: Array<{ id: string; label: string; type: string }>;
	edges: Array<{ source: string; target: string; relation: string; filename: string; chunk_index: number }>;
	processed_chunks?: number;
	relations?: number;
};

function GraphRagPanel({ knowledgeBaseId }: { knowledgeBaseId: string }) {
	const { t } = useTranslation();
	const [model, setModel] = useState<ChatModelConfig | null>(null);
	const [snapshot, setSnapshot] = useState<GraphSnapshot | null>(null);
	const [loading, setLoading] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [rulesStatus, setRulesStatus] = useState<RuleStatus | null>(null);
	const [rulesReload, setRulesReload] = useState(0);
	const [confirmBuild, setConfirmBuild] = useState(false);
	const [maxChunks, setMaxChunks] = useState(30);

	const load = async () => {
		try {
			setError(null);
			setSnapshot(await client.get<GraphSnapshot>(`/portal/knowledge-graph/${knowledgeBaseId}`, undefined, { silent: true }));
		} catch (e) {
			setError((e as Error).message || String(e));
		}
	};
	useEffect(() => { void load(); }, [knowledgeBaseId]);

	const build = async () => {
		if (!model || !rulesStatus || rulesStatus.dirty) return;
		setConfirmBuild(false);
		setLoading(true);
		setError(null);
		try {
			setSnapshot(await client.post<GraphSnapshot>(`/portal/knowledge-graph/${knowledgeBaseId}/build`, { chat_model_config: model, rules_revision:rulesStatus.revision, max_chunks_per_document:maxChunks }, undefined, { silent: true }));
			setRulesReload(value => value + 1);
		} catch (e) {
			setError((e as Error).message || String(e));
		} finally {
			setLoading(false);
		}
	};

	return (
		<div className="rounded-xl border bg-muted/20 p-5">
			<div className="flex items-center gap-x-2">
				<Network className="size-4 text-primary" />
				<h3 className="text-sm font-medium">{t('knowledge.graph.title')}</h3>
				<Badge variant="outline">{snapshot ? t('knowledge.graph.ready') : t('knowledge.graph.setupRequired')}</Badge>
			</div>
			<p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">{t('knowledge.graph.description')}</p>
			<fieldset disabled={loading}><GraphRulesEditor key={knowledgeBaseId} kbId={knowledgeBaseId} reloadKey={rulesReload} onStatus={setRulesStatus} /></fieldset>
			<div className="mt-4 flex flex-wrap items-center gap-2 rounded-lg border bg-card p-3">
				<LlmSelect value={model} onChange={setModel} className="w-64" placeholder={t('knowledge.graph.modelPlaceholder')} />
				<label className="text-xs">每文件分块上限 <input aria-label="每文件分块上限" type="number" min={1} max={100} className="w-16 rounded border bg-background p-1" value={maxChunks} onChange={e => setMaxChunks(Math.max(1,Math.min(100,Number(e.target.value)||1)))} disabled={loading} /></label>
				<Button size="sm" onClick={() => setConfirmBuild(true)} disabled={!model || loading || !rulesStatus || rulesStatus.dirty}>
					{loading ? <Loader2 className="size-3.5 animate-spin" /> : <Network className="size-3.5" />}
					{t('knowledge.graph.buildButton')}
				</Button>
				<Button size="sm" variant="ghost" onClick={() => void load()} disabled={loading}>{t('knowledge.graph.refresh')}</Button>
			</div>
			{confirmBuild && <div role="alert" className="mt-3 rounded-lg border border-amber-400 p-3 text-sm space-y-2"><p>将使用已保存的规则重新抽取所有就绪文本分块，产生模型调用费用。成功后替换旧图谱；抽取或数据库提交失败会保留旧图谱。超过分块上限会报错，不会静默截断。</p><div className="flex gap-2"><Button size="sm" onClick={build} disabled={!rulesStatus || rulesStatus.dirty || loading}>确认重新构建</Button><Button size="sm" variant="outline" onClick={() => setConfirmBuild(false)}>取消</Button></div></div>}
			{error && <p className="mt-3 text-sm text-destructive">{error}</p>}
			{snapshot && (
				<div className="mt-4 grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
					<div className="rounded-lg border bg-card p-3">
						<div className="mb-2 text-xs text-muted-foreground">{t('knowledge.graph.entities')} · {snapshot.nodes.length}</div>
						<div tabIndex={0} role="region" aria-label="实体列表，可向下滚动" className="max-h-80 overflow-y-auto overscroll-contain pr-2 [scrollbar-gutter:stable]">
						<div className="flex flex-wrap gap-1.5">
							{snapshot.nodes.length ? snapshot.nodes.map((node) => <Badge key={node.id} variant="secondary" title={`类型：${node.type}`}>{node.label} · {node.type}</Badge>) : <span className="text-sm text-muted-foreground">{t('knowledge.graph.empty')}</span>}
						</div>
						</div>
					</div>
					<div className="rounded-lg border bg-card p-3">
						<div className="mb-2 text-xs text-muted-foreground">{t('knowledge.graph.relations')} · {snapshot.edges.length}</div>
						<div tabIndex={0} role="region" aria-label="关系列表，可向下滚动" className="flex max-h-80 flex-col gap-2 overflow-y-auto overscroll-contain pr-2 [scrollbar-gutter:stable]">
							{snapshot.edges.map((edge, index) => <div key={`${edge.source}-${edge.target}-${index}`} className="shrink-0 break-words text-sm"><span className="font-medium">{edge.source}</span><span className="mx-2 text-muted-foreground">— {edge.relation} →</span><span className="font-medium">{edge.target}</span><span className="ml-2 text-xs text-muted-foreground">{edge.filename} · #{edge.chunk_index + 1}</span></div>)}
							{snapshot.edges.length === 0 && <span className="text-sm text-muted-foreground">{t('knowledge.graph.empty')}</span>}
						</div>
					</div>
				</div>
			)}
		</div>
	);
}

function SettingsPanel({ knowledgeBase }: { knowledgeBase: KnowledgeBaseView }) {
	const { t } = useTranslation();
	return (
		<div className="flex max-w-3xl flex-col gap-y-5">
			<div>
				<h3 className="text-sm font-medium">{t('knowledge.settings.pinnedTitle')}</h3>
				<p className="mt-1 text-sm text-muted-foreground">{t('knowledge.settings.pinnedDescription')}</p>
			</div>
			<ConfigCard knowledgeBase={knowledgeBase} />
			<div className="rounded-xl border border-dashed p-4">
				<h3 className="text-sm font-medium">{t('knowledge.settings.retrievalTitle')}</h3>
				<p className="mt-1 text-sm leading-6 text-muted-foreground">{t('knowledge.settings.retrievalDescription')}</p>
			</div>
		</div>
	);
}

function ConfigItem({ label, value }: { label: string; value: string }) {
	return (
		<div className="flex min-w-0 flex-col gap-y-0.5">
			<span className="text-muted-foreground text-xs">{label}</span>
			<span className="truncate text-sm text-foreground" title={value}>
				{value}
			</span>
		</div>
	);
}

/**
 * Read-only card surfacing the full configuration pinned at creation
 * time — embedding model, credential — plus the aggregated
 * counts the list endpoint now serves (#2360).
 */
function ConfigCard({ knowledgeBase }: { knowledgeBase: KnowledgeBaseView }) {
	const { t } = useTranslation();
	const embedding = knowledgeBase.embedding_model_config;

	// Only worth showing when something is not ready — a KB where every
	// document indexed cleanly says nothing extra beyond the totals.
	const counts = knowledgeBase.status_counts;
	const unfinished = counts.pending + counts.parsing + counts.chunking + counts.indexing;
	const statusValue =
		counts.error > 0 || unfinished > 0
			? t('knowledge.config.statusValue', {
					ready: counts.ready,
					indexing: unfinished,
					failed: counts.error,
				})
			: null;

	return (
		<div className="flex flex-col gap-y-3">
			<h3 className="text-[13.5px] font-medium text-foreground">
				{t('knowledge.config.title')}
			</h3>
			<div className="border-border bg-card grid grid-cols-2 gap-x-4 gap-y-3 rounded-lg border p-3 sm:grid-cols-3">
				<ConfigItem label={t('knowledge.config.embeddingModel')} value={embedding.model} />
				<ConfigItem
					label={t('knowledge.config.dimensions')}
					value={String(embedding.dimensions)}
				/>
				<ConfigItem
					label={t('knowledge.config.credential')}
					value={knowledgeBase.credential_name ?? embedding.credential_id}
				/>
				<ConfigItem
					label={t('knowledge.config.counts')}
					value={t('knowledge.config.countsValue', {
						documents: knowledgeBase.document_count,
						chunks: knowledgeBase.chunk_count,
					})}
				/>
				{statusValue && (
					<ConfigItem label={t('knowledge.config.status')} value={statusValue} />
				)}
				<ConfigItem
					label={t('knowledge.config.createdAt')}
					value={format(new Date(knowledgeBase.created_at), 'yyyy-MM-dd HH:mm')}
				/>
			</div>
		</div>
	);
}

export const KnowledgePage = () => {
	const navigate = useNavigate();
	const { kbId: urlKbId } = useParams<{ kbId?: string }>();
	const { t } = useTranslation();

	const { knowledgeBases, remove, refetch } = useKnowledgeBases();
	const [selectedKbId, setSelectedKbId] = useState<string | undefined>(urlKbId);
	const [createDialogOpen, setCreateDialogOpen] = useState(false);
	const [credentialOpen, setCredentialOpen] = useState(false);
	const [credentialRefetchTrigger, setCredentialRefetchTrigger] = useState(0);

	const [editTarget, setEditTarget] = useState<KnowledgeBaseView | null>(null);
	const [deleteTarget, setDeleteTarget] = useState<KnowledgeBaseView | null>(null);

	const selectedKb = knowledgeBases.find((kb) => kb.id === selectedKbId);

	// Default to the first knowledge base when none is selected (or the
	// selected one no longer exists), mirroring the URL so refresh keeps it.
	useEffect(() => {
		if (knowledgeBases.length === 0) return;
		if (knowledgeBases.some((kb) => kb.id === selectedKbId)) return;
		const first = knowledgeBases[0].id;
		setSelectedKbId(first);
		navigate(`/knowledge/${first}`, { replace: true });
	}, [knowledgeBases, selectedKbId, navigate]);

	const handleCreated = async (knowledgeBaseId: string) => {
		await refetch();
		setSelectedKbId(knowledgeBaseId);
		navigate(`/knowledge/${knowledgeBaseId}`);
	};

	const handleConfirmDelete = async () => {
		if (!deleteTarget) return;
		const id = deleteTarget.id;
		await remove(id);
		await refetch();
		if (selectedKbId === id) {
			setSelectedKbId(undefined);
			navigate('/knowledge');
		}
	};

	return (
		<div className="flex size-full p-2 gap-2">
			<Sidebar collapsible="none" className="rounded-[22px]">
				<SidebarHeader className={'flex flex-col p-[20px_18px_14px] gap-y-1'}>
					<div className="text-xl font-medium tracking-[-0.02em] text-foreground">
						{t('common.knowledge')}
					</div>
					<div className="text-text-tertiary text-xs">{t('knowledge.subtitle')}</div>
				</SidebarHeader>
				<SidebarContent>
					<SidebarGroup className="mt-6 px-2 py-0">
						<SidebarGroupLabel className="justify-between">
							{t('knowledge.list.label')}
							<Button
								variant="ghost"
								size="icon-xs"
								onClick={() => setCreateDialogOpen(true)}
								title={t('knowledge.list.createButton')}
							>
								<Plus className="size-3.5" />
							</Button>
						</SidebarGroupLabel>
						<SidebarGroupContent>
							{knowledgeBases.length === 0 ? (
								<Empty className="border-none py-4 min-h-50">
									<EmptyHeader>
										<EmptyMedia variant="icon">
											<Files />
										</EmptyMedia>
										<EmptyTitle>{t('knowledge.list.emptyTitle')}</EmptyTitle>
										<EmptyDescription>
											{t('knowledge.list.emptyDescription')}
										</EmptyDescription>
									</EmptyHeader>
									<EmptyContent>
										<Button
											variant="outline"
											size="sm"
											onClick={() => setCreateDialogOpen(true)}
										>
											<Plus />
											{t('knowledge.list.createButton')}
										</Button>
									</EmptyContent>
								</Empty>
							) : (
								<SidebarMenu>
									{knowledgeBases.map((kb) => {
										return (
											<SidebarMenuItem key={kb.id}>
												<SidebarMenuButton
													isActive={urlKbId === kb.id}
													onClick={() => {
														setSelectedKbId(kb.id);
														navigate(`/knowledge/${kb.id}`);
													}}
												>
													<span className="min-w-0 flex-1 truncate">
														{kb.name}
													</span>
													{!kb.editable && (
														<Badge
															variant="secondary"
															className="text-[10px] px-1 py-0"
															title={t('common.readOnlyTooltip')}
														>
															{t('common.readOnly')}
														</Badge>
													)}
												</SidebarMenuButton>
												{kb.editable && (
													<SidebarMenuAction showOnHover>
														<DropdownMenu>
															<DropdownMenuTrigger asChild>
																<Ellipsis />
															</DropdownMenuTrigger>
															<DropdownMenuContent
																side="right"
																align="start"
															>
																<DropdownMenuItem
																	onClick={() =>
																		setEditTarget(kb)
																	}
																>
																	<Pencil />
																	{t('common.edit')}
																</DropdownMenuItem>
																<DropdownMenuItem
																	variant="destructive"
																	onClick={() =>
																		setDeleteTarget(kb)
																	}
																>
																	<Trash2 />
																	{t('common.delete')}
																</DropdownMenuItem>
															</DropdownMenuContent>
														</DropdownMenu>
													</SidebarMenuAction>
												)}
											</SidebarMenuItem>
										);
									})}
								</SidebarMenu>
							)}
						</SidebarGroupContent>
					</SidebarGroup>
				</SidebarContent>
				<SidebarFooter />
			</Sidebar>
			<main className="flex-1 min-h-0 overflow-hidden rounded-[22px] bg-card shadow-panel">
				<DetailPanel knowledgeBase={selectedKb} />
			</main>
			<CreateKnowledgeBaseDialog
				open={createDialogOpen}
				onOpenChange={setCreateDialogOpen}
				onCreated={handleCreated}
				onAddCredential={() => setCredentialOpen(true)}
				credentialRefetchTrigger={credentialRefetchTrigger}
			/>
			<CreateCredentialDialog
				open={credentialOpen}
				onOpenChange={setCredentialOpen}
				onCreated={() => setCredentialRefetchTrigger((n) => n + 1)}
			/>
			<EditKnowledgeBaseDialog
				open={editTarget !== null}
				onOpenChange={(open) => {
					if (!open) setEditTarget(null);
				}}
				knowledgeBase={editTarget}
				onUpdated={() => refetch()}
			/>
			<DeleteDialog
				open={deleteTarget !== null}
				onOpenChange={(open) => {
					if (!open) setDeleteTarget(null);
				}}
				title={t('dialog-knowledge-base-delete.title')}
				description={t('dialog-knowledge-base-delete.description', {
					name: deleteTarget?.name ?? '',
				})}
				onConfirm={handleConfirmDelete}
			/>
		</div>
	);
};
