import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { client } from '@/api/client';
import { beijingTime } from '@/lib/beijingTime';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog';
type Row = {
	session_id: string;
	agent_id: string;
	name: string;
	channel_id: string;
	channel_name: string;
	chat_name?: string;
	chat_id?: string;
	channel_user_id?: string;
	created_at: string;
	updated_at: string;
};
type Message = { id: string; name?: string; role?: string; timestamp?: string; content: unknown };
function contentText(value: unknown): string {
	if (typeof value === 'string') return value;
	if (Array.isArray(value)) return value.map(contentText).join('\n');
	if (value && typeof value === 'object') {
		const item = value as Record<string, unknown>;
		if (typeof item.text === 'string') return item.text;
		return JSON.stringify(value, null, 2);
	}
	return value == null ? '' : String(value);
}
export function ProjectChannelRecords({ projectId }: { projectId: string }) {
	const [search, setSearch] = useState('');
	const [selected, setSelected] = useState<Row | null>(null);
	const [messages, setMessages] = useState<Message[]>([]);
	const [more, setMore] = useState(false);
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState('');
	const url = `/portal/projects/${projectId}/channel-records`;
	const records = useQuery({
		queryKey: ['channel-records', projectId],
		queryFn: () => client.get<Row[]>(url),
	});
	useEffect(() => {
		setSelected(null);
		setSearch('');
	}, [projectId]);
	useEffect(() => {
		if (!selected) return;
		let alive = true;
		setMessages([]);
		setMore(false);
		setBusy(true);
		setError('');
		void client
			.get<{ messages: Message[]; has_more: boolean }>(
				`${url}/${selected.agent_id}/${selected.session_id}/messages`,
			)
			.then((r) => {
				if (alive) {
					setMessages(r.messages);
					setMore(r.has_more);
				}
			})
			.catch((e) => {
				if (alive) setError(String(e));
			})
			.finally(() => {
				if (alive) setBusy(false);
			});
		return () => {
			alive = false;
		};
	}, [selected, url]);
	return (
		<section className="space-y-3 rounded-xl border p-5">
			<div className="flex justify-between items-center">
				<h2 className="font-medium">
					频道记录{' '}
					<span className="text-muted-foreground">{records.data?.length ?? 0}</span>
				</h2>
				<Button variant="outline" size="sm" onClick={() => void records.refetch()}>
					刷新
				</Button>
			</div>
			<p className="text-xs text-muted-foreground">
				仅管理员可见，用于查看已保存的频道会话。此处只读；已删除的聊天记录无法恢复，不是不可篡改的审计日志。
			</p>
			<Input
				placeholder="搜索频道、会话、群聊或用户 ID"
				aria-label="搜索频道记录"
				value={search}
				onChange={(e) => setSearch(e.target.value)}
			/>
			{records.isPending && <p>正在加载…</p>}
			{records.isError && (
				<p role="alert" className="text-destructive">
					加载失败，请刷新重试。
				</p>
			)}
			{records.data
				?.filter((r) =>
					[
						r.name,
						r.channel_name,
						r.chat_name,
						r.chat_id,
						r.channel_user_id,
						r.session_id,
					].some((v) => v?.includes(search)),
				)
				.map((r) => (
					<button
						key={r.agent_id + r.session_id}
						onClick={() => setSelected(r)}
						className="block w-full rounded-lg border p-3 text-left hover:bg-accent"
					>
						<div className="font-medium text-sm">{r.name || '未命名会话'}</div>
						<div className="text-xs text-muted-foreground mt-1 break-all">
							频道：{r.channel_name} · 群聊：{r.chat_name || r.chat_id || '—'} ·
							用户：{r.channel_user_id || '群聊共用'}
						</div>
						<div className="text-xs text-muted-foreground mt-1">
							创建：{beijingTime(r.created_at)} · 更新：{beijingTime(r.updated_at)}
						</div>
					</button>
				))}
			{records.data?.length === 0 && (
				<p className="text-sm text-muted-foreground">
					暂无频道记录，收到消息并生成会话后会显示在这里。
				</p>
			)}
			<Dialog
				open={!!selected}
				onOpenChange={(open) => {
					if (!open) setSelected(null);
				}}
			>
				<DialogContent className="sm:max-w-3xl max-h-[85vh] overflow-y-auto">
					<DialogTitle>{selected?.name || '频道记录'}</DialogTitle>
					<DialogDescription>
						只读查看 · {selected?.channel_name} · 会话 {selected?.session_id}
					</DialogDescription>
					{error && (
						<p role="alert" className="text-destructive">
							{error}
						</p>
					)}
					{more && (
						<Button
							variant="outline"
							disabled={busy}
							onClick={async () => {
								if (!selected || !messages.length) return;
								setBusy(true);
								setError('');
								try {
									const r = await client.get<{
										messages: Message[];
										has_more: boolean;
									}>(
										`${url}/${selected.agent_id}/${selected.session_id}/messages?before=${encodeURIComponent(messages[0].id)}`,
									);
									setMessages((old) => [...r.messages, ...old]);
									setMore(r.has_more);
								} catch (e) {
									setError(String(e));
								} finally {
									setBusy(false);
								}
							}}
						>
							加载更早记录
						</Button>
					)}
					{busy && <p className="text-sm text-muted-foreground">正在加载…</p>}
					{!busy && !messages.length && !error && <p>暂无已保存消息。</p>}
					{messages.map((m) => (
						<article key={m.id} className="rounded-lg border p-3">
							<div className="text-xs text-muted-foreground mb-2">
								{m.name || m.role || '消息'}
								{m.timestamp ? ` · ${beijingTime(m.timestamp)}` : ''}
							</div>
							<pre className="whitespace-pre-wrap break-words text-sm font-sans">
								{contentText(m.content)}
							</pre>
							<details className="mt-2 text-xs text-muted-foreground">
								<summary className="cursor-pointer">完整消息数据</summary>
								<pre className="whitespace-pre-wrap break-all">
									{JSON.stringify(m, null, 2)}
								</pre>
							</details>
						</article>
					))}
				</DialogContent>
			</Dialog>
		</section>
	);
}
