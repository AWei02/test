import {
	Download,
	Files,
	Upload,
	Sparkles,
	Star,
	History,
	RefreshCw,
	Search,
	FileText,
	Pencil,
	Trash2,
} from 'lucide-react';
import { useCallback, useEffect, useRef, useState, type DragEvent } from 'react';

import { getAuthHeaders, serviceUrl } from '@/api/client';
import { Button } from '@/components/ui/button';
import {
	Dialog,
	DialogContent,
	DialogTitle,
	DialogDescription,
	DialogFooter,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';

type FileRow = {
	id: string;
	name: string;
	origin: 'uploaded' | 'generated' | 'unknown';
	size: number;
	is_result: boolean;
	modified_by: string;
	updated_at: string;
	version_count: number;
	current_version: string;
	sources: { name: string; id: string; version: string }[];
};
type Version = { id: string; number: number; time: string; actor: string; size: number };
type Pending = { row: FileRow; action: 'delete' | 'restore' | 'rename'; version?: string };
const originLabel = { uploaded: '用户上传', generated: 'AI 创建', unknown: '来源未记录' };
const formatSize = (size: number) =>
	size < 1024
		? `${size} B`
		: size < 1048576
			? `${(size / 1024).toFixed(1)} KB`
			: `${(size / 1048576).toFixed(1)} MB`;
const formatTime = (time: string) => new Date(time).toLocaleString('zh-CN', { hour12: false });

export function FileCatalogPanel({
	scope,
	resource,
	agentId,
}: {
	scope: 'session' | 'project';
	resource: string;
	agentId?: string;
}) {
	const base = `/portal/file-catalog/${scope}/${encodeURIComponent(resource)}`;
	const [files, setFiles] = useState<FileRow[]>([]);
	const [tab, setTab] = useState<'all' | 'uploaded' | 'generated'>('all');
	const [onlyResults, setOnlyResults] = useState(false);
	const [search, setSearch] = useState('');
	const [message, setMessage] = useState('');
	const [busy, setBusy] = useState(false);
	const [dragging, setDragging] = useState(false);
	const dragDepth = useRef(0);
	const uploadInFlight = useRef(false);
	const [loading, setLoading] = useState(true);
	const [history, setHistory] = useState<{ row: FileRow; versions: Version[] } | null>(null);
	const [pending, setPending] = useState<Pending | null>(null);
	const [newName, setNewName] = useState('');
	const uploadInput = useRef<HTMLInputElement>(null);
	const urlFor = useCallback(
		(suffix = '', params: Record<string, string> = {}) => {
			const url = serviceUrl(base + suffix);
			if (agentId) url.searchParams.set('agent_id', agentId);
			Object.entries(params).forEach(([key, value]) => url.searchParams.set(key, value));
			return url;
		},
		[base, agentId],
	);
	const request = useCallback(
		async (suffix = '', body?: unknown, params: Record<string, string> = {}) => {
			const response = await fetch(urlFor(suffix, params), {
				method: body === undefined ? 'GET' : 'POST',
				headers: {
					...getAuthHeaders(),
					...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
				},
				body: body === undefined ? undefined : JSON.stringify(body),
			});
			const data = await response.json();
			if (!response.ok) throw new Error(data.detail || '文件操作失败');
			return data;
		},
		[urlFor],
	);
	const refresh = useCallback(async () => {
		setLoading(true);
		try {
			const result = await request();
			setFiles(result.files);
		} finally {
			setLoading(false);
		}
	}, [request]);
	useEffect(() => {
		void refresh().catch((error) => setMessage(String(error)));
		const listener = () => {
			void refresh().catch((error) => setMessage(String(error)));
		};
		window.addEventListener('session-files-changed', listener);
		return () => window.removeEventListener('session-files-changed', listener);
	}, [refresh]);
	async function download(row: FileRow, version?: string) {
		try {
			const response = await fetch(
				urlFor('/download', { name: row.name, ...(version ? { version } : {}) }),
				{ headers: { ...getAuthHeaders() } },
			);
			if (!response.ok) throw new Error('下载失败，请刷新重试');
			const href = URL.createObjectURL(await response.blob());
			const link = document.createElement('a');
			link.href = href;
			link.download = row.name;
			link.click();
			setTimeout(() => URL.revokeObjectURL(href), 1000);
		} catch (error) {
			setMessage(String(error));
		}
	}
	async function mark(row: FileRow) {
		setBusy(true);
		setMessage('');
		try {
			await request('/action', { name: row.name, action: 'mark', is_result: !row.is_result });
			await refresh();
		} catch (error) {
			setMessage(String(error));
		} finally {
			setBusy(false);
		}
	}
	async function showHistory(row: FileRow) {
		setBusy(true);
		setMessage('');
		try {
			const result = await request('/history', undefined, { name: row.name });
			setHistory({ row, versions: result.versions });
		} catch (error) {
			setMessage(String(error));
		} finally {
			setBusy(false);
		}
	}
	async function confirm() {
		if (!pending) return;
		setBusy(true);
		setMessage('');
		try {
			await request('/action', {
				name: pending.row.name,
				action: pending.action,
				version: pending.version,
				new_name: newName,
				expected_version: pending.row.current_version,
				confirmed: true,
			});
			setPending(null);
			setHistory(null);
			await refresh();
		} catch (error) {
			setMessage(String(error));
		} finally {
			setBusy(false);
		}
	}
	async function upload(selected: File[]) {
		if (!selected.length || busy || uploadInFlight.current) return;
		uploadInFlight.current = true;
		setBusy(true);
		setMessage('');
		try {
			for (const file of selected) {
				if (file.size > 20 * 1024 * 1024) throw new Error(`${file.name} 超过 20MB`);
				const body = new FormData();
				body.append('file', file);
				const path =
					scope === 'project'
						? `/portal/projects/${encodeURIComponent(resource)}/files`
						: `/portal/skill-files/${encodeURIComponent(agentId!)}/${encodeURIComponent(resource)}`;
				const response = await fetch(serviceUrl(path), {
					method: 'POST',
					headers: { ...getAuthHeaders() },
					body,
				});
				const result = await response.json();
				if (!response.ok) throw new Error(result.detail || '上传失败');
				setTab('uploaded');
				setOnlyResults(false);
				setSearch('');
			}
		} catch (error) {
			setMessage(String(error));
		} finally {
			await refresh().catch((error) => setMessage(String(error)));
			uploadInFlight.current = false;
			setBusy(false);
		}
	}
	const isFileDrag = (event: DragEvent) => Array.from(event.dataTransfer.types).includes('Files');
	const dropDisabled = busy || history !== null || pending !== null;
	const visible = files.filter(
		(row) =>
			(tab === 'all' || row.origin === tab) &&
			(!onlyResults || row.is_result) &&
			row.name.toLowerCase().includes(search.toLowerCase()),
	);
	const tabs = [
		{ value: 'all' as const, label: '全部', icon: Files },
		{ value: 'uploaded' as const, label: '上传文件', icon: Upload },
		{ value: 'generated' as const, label: '生成文件', icon: Sparkles },
	];
	return (
		<section
			className={cn(
				'relative space-y-4 min-w-0 rounded-xl',
				dragging && 'ring-2 ring-primary ring-offset-4',
			)}
			onDragEnter={(event) => {
				if (!isFileDrag(event)) return;
				event.preventDefault();
				event.stopPropagation();
				dragDepth.current += 1;
				setDragging(true);
			}}
			onDragOver={(event) => {
				if (!isFileDrag(event)) return;
				event.preventDefault();
				event.stopPropagation();
				event.dataTransfer.dropEffect = dropDisabled ? 'none' : 'copy';
			}}
			onDragLeave={(event) => {
				if (!isFileDrag(event)) return;
				event.preventDefault();
				event.stopPropagation();
				dragDepth.current = Math.max(0, dragDepth.current - 1);
				if (dragDepth.current === 0) setDragging(false);
			}}
			onDrop={(event) => {
				if (!isFileDrag(event)) return;
				event.preventDefault();
				event.stopPropagation();
				dragDepth.current = 0;
				setDragging(false);
				if (dropDisabled) return;
				if (
					Array.from(event.dataTransfer.items).some(
						(item) => item.webkitGetAsEntry?.()?.isDirectory,
					)
				) {
					setMessage('暂不支持上传文件夹，请拖入文件夹内的文件。');
					return;
				}
				void upload(Array.from(event.dataTransfer.files));
			}}
		>
			{dragging && (
				<div
					role="status"
					className="pointer-events-none absolute inset-0 z-20 !mt-0 flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-primary bg-background/95 p-6 text-center"
				>
					<Upload className="size-7 text-primary" />
					<p className="text-sm font-medium">
						{dropDisabled ? '请先完成当前操作' : '松开鼠标上传文件'}
					</p>
					<p className="text-xs text-muted-foreground">支持多个文件，单文件最大 20MB</p>
				</div>
			)}
			<div className="flex flex-wrap items-center justify-between gap-3 border-b pb-3">
				<div
					role="group"
					aria-label="按文件来源筛选"
					className="inline-flex items-center gap-1 rounded-lg bg-muted/60 p-1"
				>
					{tabs.map(({ value, label, icon: Icon }) => (
						<button
							key={value}
							type="button"
							aria-pressed={tab === value}
							onClick={() => setTab(value)}
							className={cn(
								'flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm transition-colors',
								tab === value
									? 'bg-background text-foreground shadow-sm'
									: 'text-muted-foreground hover:text-foreground',
							)}
						>
							<Icon className="size-3.5" />
							{label}
							<span className="text-xs text-muted-foreground">
								{value === 'all'
									? files.length
									: files.filter((row) => row.origin === value).length}
							</span>
						</button>
					))}
				</div>
				<button
					type="button"
					aria-pressed={onlyResults}
					onClick={() => setOnlyResults(!onlyResults)}
					className={cn(
						'flex items-center gap-1.5 rounded-md px-2 py-1.5 text-sm',
						onlyResults
							? 'bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-300'
							: 'text-muted-foreground hover:bg-muted',
					)}
				>
					<Star className={cn('size-3.5', onlyResults && 'fill-current')} />
					仅看成果
				</button>
			</div>
			<div className="flex flex-wrap items-center gap-2">
				<div className="relative min-w-40 flex-1">
					<Search className="absolute left-3 top-2.5 size-4 text-muted-foreground" />
					<Input
						aria-label="搜索文件"
						placeholder="搜索文件名"
						className="pl-9"
						value={search}
						onChange={(event) => setSearch(event.target.value)}
					/>
				</div>
				<Button
					variant="outline"
					size="sm"
					disabled={busy}
					onClick={() => uploadInput.current?.click()}
				>
					<Upload className="size-3.5" />
					上传文件
				</Button>
				<Button
					variant="ghost"
					size="sm"
					disabled={busy || loading}
					onClick={() => void refresh().catch((error) => setMessage(String(error)))}
					aria-label="刷新文件"
				>
					<RefreshCw className={cn('size-4', loading && 'animate-spin')} />
				</Button>
				<input
					ref={uploadInput}
					className="hidden"
					type="file"
					multiple
					onChange={(event) => {
						void upload(Array.from(event.target.files ?? []));
						event.target.value = '';
					}}
				/>
			</div>
			<div className="overflow-hidden rounded-xl border">
				{visible.length === 0 ? (
					<div className="py-12 text-center text-sm text-muted-foreground">
						<Files className="mx-auto mb-3 size-7 opacity-50" />
						{loading
							? '正在读取文件…'
							: search || onlyResults || tab !== 'all'
								? '没有符合条件的文件'
								: '将文件拖到这里，或点击“上传文件”'}
					</div>
				) : (
					<div className="divide-y">
						{visible.map((row) => (
							<div
								key={row.id}
								className="flex flex-wrap items-center gap-3 px-4 py-3 hover:bg-muted/30"
							>
								<div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted/70">
									<FileText className="size-4 text-muted-foreground" />
								</div>
								<div className="min-w-0 flex-1 basis-48">
									<button
										className="block max-w-full truncate text-left text-sm font-medium hover:underline"
										title={row.name}
										onClick={() => void download(row)}
									>
										{row.name}
									</button>
									<div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
										<span>{originLabel[row.origin]}</span>
										<span>·</span>
										<span>{formatSize(row.size)}</span>
										<span>·</span>
										<span>{row.modified_by}</span>
										<span>{formatTime(row.updated_at)}</span>
									</div>
									{row.sources.length > 0 && (
										<p
											className="mt-1 truncate text-xs text-muted-foreground"
											title={row.sources
												.map((source) => source.name)
												.join('、')}
										>
											来源文件：
											{row.sources.map((source) => source.name).join('、')}
										</p>
									)}
								</div>
								<div className="ml-auto flex items-center gap-0.5">
									<Button
										variant="ghost"
										size="sm"
										disabled={busy}
										onClick={() => void showHistory(row)}
									>
										<History className="size-3.5" />
										{row.version_count} 版
									</Button>
									<Button
										variant="ghost"
										size="icon"
										disabled={busy}
										aria-label={`${row.is_result ? '取消' : '标记'}成果 ${row.name}`}
										title={row.is_result ? '取消成果标记' : '标记为成果'}
										onClick={() => void mark(row)}
									>
										<Star
											className={cn(
												'size-4',
												row.is_result && 'fill-amber-400 text-amber-500',
											)}
										/>
									</Button>
									<Button
										variant="ghost"
										size="icon"
										aria-label={`下载 ${row.name}`}
										onClick={() => void download(row)}
									>
										<Download className="size-4" />
									</Button>
									<Button
										variant="ghost"
										size="icon"
										disabled={busy}
										aria-label={`重命名 ${row.name}`}
										onClick={() => {
											setNewName(row.name);
											setPending({ row, action: 'rename' });
										}}
									>
										<Pencil className="size-3.5" />
									</Button>
									<Button
										variant="ghost"
										size="icon"
										disabled={busy}
										aria-label={`删除 ${row.name}`}
										onClick={() => setPending({ row, action: 'delete' })}
									>
										<Trash2 className="size-3.5 text-muted-foreground" />
									</Button>
								</div>
							</div>
						))}
					</div>
				)}
			</div>
			<p className="text-xs text-muted-foreground">
				来源不会随修改改变；每次内容变化保留版本。单文件最大 20MB。历史文件的来源未记录。
			</p>
			{message && (
				<p role="alert" className="text-sm text-destructive">
					{message}
				</p>
			)}
			<Dialog open={history !== null} onOpenChange={(open) => !open && setHistory(null)}>
				<DialogContent className="sm:max-w-xl max-h-[80vh] overflow-y-auto">
					<DialogTitle>版本历史</DialogTitle>
					<DialogDescription className="break-all">
						{history?.row.name} · 恢复会保留当前内容，不会删除历史版本。
					</DialogDescription>
					<div className="divide-y">
						{history?.versions.map((version) => (
							<div key={version.id} className="flex items-center gap-2 py-3">
								<div className="min-w-0 flex-1">
									<div className="text-sm font-medium">
										版本 {version.number}
										{version.id === history.row.current_version
											? ' · 当前版本'
											: ''}
									</div>
									<p className="mt-1 text-xs text-muted-foreground">
										{formatTime(version.time)} · {version.actor} ·{' '}
										{formatSize(version.size)}
									</p>
								</div>
								<Button
									variant="ghost"
									size="sm"
									onClick={() => void download(history.row, version.id)}
								>
									下载
								</Button>
								<Button
									variant="outline"
									size="sm"
									disabled={busy || version.id === history.row.current_version}
									onClick={() =>
										setPending({
											row: history.row,
											action: 'restore',
											version: version.id,
										})
									}
								>
									恢复
								</Button>
							</div>
						))}
					</div>
				</DialogContent>
			</Dialog>
			<Dialog
				open={pending !== null}
				onOpenChange={(open) => !open && !busy && setPending(null)}
			>
				<DialogContent>
					<DialogTitle>
						{pending?.action === 'restore'
							? '恢复此版本？'
							: pending?.action === 'rename'
								? '重命名文件'
								: '删除文件？'}
					</DialogTitle>
					<DialogDescription className="break-all">
						{pending?.row.name}
						{pending?.action === 'restore'
							? '：当前内容会保留在历史版本中。'
							: pending?.action === 'delete'
								? '：文件将移出列表，服务器保留历史备份。'
								: '：来源、成果标记和历史版本保持不变。'}
					</DialogDescription>
					{pending?.action === 'rename' && (
						<Input
							aria-label="新文件名"
							value={newName}
							onChange={(event) => setNewName(event.target.value)}
						/>
					)}
					{message && (
						<p role="alert" className="text-sm text-destructive">
							{message}
						</p>
					)}
					<DialogFooter>
						<Button variant="outline" disabled={busy} onClick={() => setPending(null)}>
							取消
						</Button>
						<Button disabled={busy} onClick={() => void confirm()}>
							{busy ? '处理中…' : '确认'}
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>
		</section>
	);
}
