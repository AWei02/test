import { useQuery } from '@tanstack/react-query';
import { Download, Loader2, RefreshCw } from 'lucide-react';
import { useState } from 'react';

import { client } from '@/api/client';
import { ProjectChannelRecords } from '@/components/ProjectChannelRecords';
import { Button } from '@/components/ui/button';
import {
	Sheet,
	SheetContent,
	SheetHeader,
	SheetTitle,
	SheetDescription,
} from '@/components/ui/sheet';
import { usePortal } from '@/hooks/usePortal';
import { beijingTime } from '@/lib/beijingTime';

type Span = {
	id: string;
	parent_id?: string;
	name: string;
	started: number;
	duration_ms: number;
	status: string;
	attributes: Record<string, unknown>;
	events: unknown[];
};
type Run = {
	id: string;
	user_id: string;
	session_name?: string;
	project_name?: string;
	session_id: string;
	source: string;
	status: string;
	started: number;
	duration_ms?: number;
	input: string;
	output: string;
	input_tokens: number | null;
	output_tokens: number | null;
	tool_count: number;
	tool_errors?: number;
	error?: unknown;
	reply_ids: string[];
	senders?: string[];
	spans?: Span[];
	triggers?: unknown[];
	truncated?: boolean;
};
type Page = { items: Run[]; has_more?: boolean; next_before?: number };
const statuses: Record<string, string> = {
	running: '执行中',
	limited: '达到迭代上限',
	completed: '完成',
	error: '失败',
	cancelled: '已取消',
	waiting: '等待确认 / 外部结果',
};
const sources: Record<string, string> = {
	web: 'Web 对话',
	channel: '渠道',
	schedule: '定时任务',
	background: '后台唤醒',
	team: '子智能体',
};
function show(value: unknown): string {
	return typeof value === 'string' ? value : (JSON.stringify(value, null, 2) ?? '—');
}
function CsvDownload({
	url,
	filename,
	label = '下载 CSV',
}: {
	url: string;
	filename: string;
	label?: string;
}) {
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState('');
	async function download() {
		setBusy(true);
		setError('');
		try {
			const response = await client.stream(url, { silent: true });
			const blob = await response.blob();
			const href = URL.createObjectURL(blob);
			const link = document.createElement('a');
			link.href = href;
			link.download = filename;
			document.body.appendChild(link);
			link.click();
			link.remove();
			window.setTimeout(() => URL.revokeObjectURL(href), 10000);
		} catch (e) {
			setError(e instanceof Error ? e.message : '导出失败，请重试');
		} finally {
			setBusy(false);
		}
	}
	return (
		<div className="flex flex-col items-end gap-1">
			<Button
				variant="outline"
				size="icon-sm"
				title={busy ? '正在导出…' : label}
				aria-label={busy ? '正在导出…' : label}
				aria-busy={busy}
				disabled={busy}
				onClick={() => void download()}
			>
				{busy ? (
					<Loader2 className="size-3.5 animate-spin" />
				) : (
					<Download className="size-3.5" />
				)}
			</Button>
			{error && (
				<p role="alert" className="text-xs text-destructive max-w-sm">
					{error}
				</p>
			)}
		</div>
	);
}
function Payload({ title, value }: { title: string; value: unknown }) {
	return (
		<details className="rounded-lg border p-3">
			<summary className="cursor-pointer text-sm font-medium">{title}</summary>
			<pre className="mt-3 whitespace-pre-wrap break-all text-xs leading-6 font-sans max-h-96 overflow-auto">
				{show(value)}
			</pre>
		</details>
	);
}
function RunDetail({ run }: { run: Run }) {
	return (
		<article className="space-y-4 border-b pb-6">
			<div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
				<span>{beijingTime(new Date(run.started * 1000).toISOString())}</span>
				<span>{sources[run.source] || run.source}</span>
				<span className={run.status === 'error' ? 'text-destructive' : ''}>
					{statuses[run.status] || run.status}
				</span>
			</div>
			<div className="grid grid-cols-3 gap-2 rounded-xl bg-muted p-3 text-sm">
				<div>
					耗时
					<p className="font-medium">
						{run.duration_ms == null
							? '执行中'
							: `${(run.duration_ms / 1000).toFixed(2)} 秒`}
					</p>
				</div>
				<div>
					Token 输入 / 输出
					<p className="font-medium">
						{run.input_tokens ?? '—'} / {run.output_tokens ?? '—'}
					</p>
				</div>
				<div>
					工具调用<p className="font-medium">{run.tool_count}</p>
				</div>
			</div>
			<p className="text-xs text-muted-foreground break-all">
				所属账号：{run.user_id}
				{run.source === 'channel' && run.senders?.length
					? ` · 本次发送者：${run.senders.join('、')}`
					: ''}{' '}
				· 会话：{run.session_name || run.session_id}
			</p>
			<section className="rounded-lg border border-blue-300 bg-blue-50 p-4 dark:bg-blue-950/30">
				<h3 className="text-sm font-medium mb-2">用户问题 / 触发内容</h3>
				<p className="whitespace-pre-wrap break-words text-sm leading-6">
					{run.input || '后台触发，参见触发信息或模型输入。'}
				</p>
			</section>
			<section className="rounded-lg border border-green-300 bg-green-50 p-4 dark:bg-green-950/30">
				<h3 className="text-sm font-medium mb-2">回答</h3>
				<p className="whitespace-pre-wrap break-words text-sm leading-6">
					{run.output || '尚无文本回答'}
				</p>
			</section>
			{run.error != null && (
				<div
					role="alert"
					className="rounded-lg bg-destructive/10 text-destructive p-3 text-sm whitespace-pre-wrap break-all"
				>
					{show(run.error)}
				</div>
			)}
			{!!run.triggers?.length && <Payload title="触发信息与消息来源" value={run.triggers} />}
			{!!run.tool_errors && (
				<p className="text-sm text-destructive">
					其中 {run.tool_errors} 次工具调用失败或被拒绝，详情见下方步骤。
				</p>
			)}
			<h3 className="text-sm font-medium">执行过程</h3>
			{run.spans
				?.filter((s) => s.name !== 'chat.run')
				.map((s) => (
					<section key={s.id} className="rounded-xl border p-3 space-y-2">
						<div className="flex justify-between gap-3 text-sm">
							<span className="font-medium break-all">{s.name}</span>
							<span className="shrink-0 text-muted-foreground">
								{(s.duration_ms / 1000).toFixed(2)} 秒
							</span>
						</div>
						{s.status === 'ERROR' && (
							<p className="text-sm text-destructive">此步骤出现异常</p>
						)}
						{s.attributes['gen_ai.operation.name'] === 'chat' && (
							<p className="text-xs text-muted-foreground">
								Token：{show(s.attributes['gen_ai.usage.input_tokens'])} /{' '}
								{show(s.attributes['gen_ai.usage.output_tokens'])}
							</p>
						)}
						{Object.entries(s.attributes)
							.filter(([k]) =>
								[
									'gen_ai.input.messages',
									'gen_ai.output.messages',
									'gen_ai.tool.call.arguments',
									'gen_ai.tool.call.result',
								].includes(k),
							)
							.map(([key, value]) => (
								<Payload
									key={key}
									title={
										key.includes('input')
											? '模型输入'
											: key.includes('output')
												? '模型输出'
												: key.includes('arguments')
													? '工具参数'
													: '工具结果'
									}
									value={value}
								/>
							))}
						{!!s.events.length && <Payload title="异常与事件" value={s.events} />}
						<Payload title="步骤完整信息" value={s.attributes} />
					</section>
				))}
			{run.truncated && (
				<p className="text-xs text-muted-foreground">
					此执行步骤较多，仅保留前 500 个步骤；Token 统计包含后续调用。
				</p>
			)}
			{!run.spans?.length && (
				<p className="text-sm text-muted-foreground">执行完成后可刷新查看步骤。</p>
			)}
		</article>
	);
}
function AuditDrawer({
	url,
	open,
	onClose,
	exportUrl,
}: {
	url: string;
	open: boolean;
	onClose: () => void;
	exportUrl?: string;
}) {
	const query = useQuery({
		queryKey: ['execution-detail', url],
		queryFn: () => client.get<Run | Page>(url),
		enabled: open && !!url,
		staleTime: 0,
	});
	const runs = query.data ? ('items' in query.data ? query.data.items : [query.data]) : [];
	return (
		<Sheet
			open={open}
			onOpenChange={(value) => {
				if (!value) onClose();
			}}
		>
			<SheetContent className="overflow-y-auto data-[side=right]:w-full data-[side=right]:sm:w-[max(46vw,640px)] data-[side=right]:sm:max-w-full">
				<SheetHeader>
					<SheetTitle>执行详情</SheetTitle>
					<SheetDescription>
						问题、回答、工具与用量；同一回复的继续执行按时间排列。
					</SheetDescription>
				</SheetHeader>
				<div className="px-5 pb-6 space-y-5">
					<div className="flex items-start justify-end gap-2">
						{(exportUrl || runs[0]) && (
							<CsvDownload
								url={
									exportUrl || `/portal/audit/runs/${runs[0].id}/conversation.csv`
								}
								filename="会话完整聊天记录.csv"
								label="导出会话 CSV"
							/>
						)}
						<Button
							variant="outline"
							size="icon-sm"
							title="刷新"
							aria-label="刷新"
							disabled={query.isFetching}
							onClick={() => void query.refetch()}
						>
							<RefreshCw
								className={`size-3.5 ${query.isFetching ? 'animate-spin' : ''}`}
							/>
						</Button>
					</div>
					{query.isPending && <p>正在加载…</p>}
					{query.isError && (
						<p role="alert" className="text-destructive">
							无法读取记录，请检查权限或刷新重试。
						</p>
					)}
					{query.isSuccess && !runs.length && (
						<p className="text-sm text-muted-foreground">
							暂无执行详情。仅接入审计后的执行会被记录，正在执行的回复请稍后刷新；记录保留
							30 天。
						</p>
					)}
					{runs.map((run) => (
						<RunDetail key={run.id} run={run} />
					))}
				</div>
			</SheetContent>
		</Sheet>
	);
}
export function ReplyAuditButton({
	replyId,
	agentId,
	sessionId,
}: {
	replyId: string;
	agentId?: string | null;
	sessionId?: string | null;
}) {
	const [open, setOpen] = useState(false);
	if (!agentId || !sessionId) return null;
	return (
		<>
			<Button
				variant="ghost"
				size="sm"
				className="font-sans text-xs"
				onClick={() => setOpen(true)}
			>
				执行详情
			</Button>
			<AuditDrawer
				open={open}
				onClose={() => setOpen(false)}
				exportUrl={`/portal/audit/sessions/${encodeURIComponent(agentId)}/${encodeURIComponent(sessionId)}/export.csv`}
				url={`/portal/audit/sessions/${encodeURIComponent(agentId)}/${encodeURIComponent(sessionId)}/replies/${encodeURIComponent(replyId)}`}
			/>
		</>
	);
}
export function ProjectAudit({ projectId }: { projectId?: string }) {
	const { isAdmin } = usePortal();
	const [user, setUser] = useState('');
	const [project, setProject] = useState('');
	const [days, setDays] = useState('30');
	const options = useQuery({
		queryKey: ['global-audit-options'],
		queryFn: () =>
			client.get<{ users: string[]; projects: { id: string; name: string }[] }>(
				'/portal/audit/options',
			),
		enabled: !projectId && isAdmin,
	});
	const [source, setSource] = useState('');
	const [status, setStatus] = useState('');
	const [before, setBefore] = useState<number | undefined>();
	const [selected, setSelected] = useState('');
	const query = useQuery({
		queryKey: ['project-audit', projectId, source, status, before, user, project, days],
		enabled: !!projectId || isAdmin,
		queryFn: () =>
			client.get<Page>(
				`${projectId ? `/portal/projects/${encodeURIComponent(projectId)}/audit` : '/portal/audit/runs'}?source=${source}&status=${status}&user_id=${encodeURIComponent(user)}&project_id=${encodeURIComponent(project)}&days=${days}${before ? `&before=${before}` : ''}`,
			),
	});
	return (
		<section className="space-y-4 rounded-xl border p-5">
			<div className="flex justify-between items-center">
				<h2 className="font-medium">{projectId ? '审计记录' : '全站审计'}</h2>
				<div className="flex items-start gap-2">
					{!projectId && isAdmin && (
						<CsvDownload
							url={`/portal/audit/export.csv?days=${days}&user_id=${encodeURIComponent(user)}&project_id=${encodeURIComponent(project)}&source=${source}&status=${status}`}
							filename={`全站审计-最近${days}天.csv`}
						/>
					)}
					<Button
						variant="outline"
						size="icon-sm"
						title="刷新"
						aria-label="刷新"
						disabled={query.isFetching}
						onClick={() => {
							setBefore(undefined);
							void query.refetch();
						}}
					>
						<RefreshCw
							className={`size-3.5 ${query.isFetching ? 'animate-spin' : ''}`}
						/>
					</Button>
				</div>
			</div>
			<p className="text-xs text-muted-foreground">
				{!projectId
					? '汇总所有用户的项目、普通会话、渠道和后台执行。'
					: isAdmin
						? '显示项目内全部执行。'
						: '仅显示你自己的执行记录。'}{' '}
				每条记录对应一次执行，保留 30 天；Token 为 — 表示模型未返回用量。
			</p>
			<div className="flex flex-wrap gap-2">
				{!projectId && (
					<>
						<select
							aria-label="审计用户"
							value={user}
							onChange={(e) => {
								setUser(e.target.value);
								setBefore(undefined);
							}}
							className="rounded-md border bg-background p-2 text-sm"
						>
							<option value="">全部用户</option>
							{options.data?.users.map((u) => (
								<option key={u} value={u}>
									{u}
								</option>
							))}
						</select>
						<select
							aria-label="审计项目"
							value={project}
							onChange={(e) => {
								setProject(e.target.value);
								setBefore(undefined);
							}}
							className="max-w-full rounded-md border bg-background p-2 text-sm"
						>
							<option value="">全部项目与普通会话</option>
							<option value="__ordinary__">仅普通会话（未关联项目）</option>
							{options.data?.projects.map((p) => (
								<option key={p.id} value={p.id}>
									{p.name}
								</option>
							))}
						</select>
						<select
							aria-label="审计时间范围"
							value={days}
							onChange={(e) => {
								setDays(e.target.value);
								setBefore(undefined);
							}}
							className="rounded-md border bg-background p-2 text-sm"
						>
							<option value="1">最近 24 小时</option>
							<option value="7">最近 7 天</option>
							<option value="30">最近 30 天</option>
						</select>
					</>
				)}
				<select
					aria-label="审计来源"
					value={source}
					onChange={(e) => {
						setSource(e.target.value);
						setBefore(undefined);
					}}
					className="rounded-md border bg-background p-2 text-sm"
				>
					<option value="">全部来源</option>
					{Object.entries(sources).map(([k, v]) => (
						<option key={k} value={k}>
							{v}
						</option>
					))}
				</select>
				<select
					aria-label="执行状态"
					value={status}
					onChange={(e) => {
						setStatus(e.target.value);
						setBefore(undefined);
					}}
					className="rounded-md border bg-background p-2 text-sm"
				>
					<option value="">全部状态</option>
					{Object.entries(statuses).map(([k, v]) => (
						<option key={k} value={k}>
							{v}
						</option>
					))}
				</select>
			</div>
			{query.isPending && <p>正在加载…</p>}
			{query.isError && (
				<p role="alert" className="text-destructive">
					加载失败，请刷新重试。
				</p>
			)}
			{query.data?.items.map((run) => (
				<button
					key={run.id}
					onClick={() => setSelected(run.id)}
					className="block w-full rounded-xl border p-4 text-left hover:bg-accent space-y-2"
				>
					<div className="flex flex-wrap justify-between gap-2 text-xs text-muted-foreground">
						<span>
							{beijingTime(new Date(run.started * 1000).toISOString())} ·{' '}
							{run.user_id} · {sources[run.source] || run.source}
						</span>
						<span className={run.status === 'error' ? 'text-destructive' : ''}>
							{statuses[run.status] || run.status}
						</span>
					</div>
					<p className="text-xs text-muted-foreground">
						{run.project_name && <span>{run.project_name} · </span>}
						{run.session_name || run.session_id}
					</p>
					<p className="text-sm font-medium line-clamp-2 break-words">
						{run.input || '后台触发'}
					</p>
					<p className="text-sm text-muted-foreground line-clamp-2 break-words">
						{run.output || '暂无回答'}
					</p>
					<p className="text-xs text-muted-foreground">
						{run.duration_ms == null
							? '执行中'
							: `${(run.duration_ms / 1000).toFixed(2)} 秒`}{' '}
						· Token {run.input_tokens ?? '—'} / {run.output_tokens ?? '—'} · 工具{' '}
						{run.tool_count} 次
					</p>
				</button>
			))}
			{query.isSuccess && !query.data.items.length && (
				<p className="text-sm text-muted-foreground py-4">
					暂无匹配的执行记录。可调整筛选条件，或在新对话完成后刷新。
				</p>
			)}
			<div className="flex gap-2">
				{before && (
					<Button variant="outline" size="sm" onClick={() => setBefore(undefined)}>
						返回最新
					</Button>
				)}
				{query.data?.has_more && (
					<Button
						variant="outline"
						size="icon-sm"
						title="刷新"
						aria-label="刷新"
						disabled={query.isFetching}
						onClick={() => setBefore(query.data?.next_before)}
					>
						更早记录
					</Button>
				)}
			</div>
			{projectId && isAdmin && (!source || source === 'channel') && (
				<details>
					<summary className="cursor-pointer text-sm text-muted-foreground">
						历史渠道会话
					</summary>
					<div className="mt-3">
						<ProjectChannelRecords projectId={projectId} />
					</div>
				</details>
			)}
			<AuditDrawer
				open={!!selected}
				onClose={() => setSelected('')}
				url={selected ? `/portal/audit/runs/${selected}` : ''}
			/>
		</section>
	);
}
