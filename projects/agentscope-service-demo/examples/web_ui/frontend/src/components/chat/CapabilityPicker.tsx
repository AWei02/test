import { useEffect, useState } from 'react';
import { client } from '@/api/client';
import { Button } from '@/components/ui/button';
import { portalWrite } from '@/api/portal';
import {
	Dialog,
	DialogTrigger,
	DialogContent,
	DialogTitle,
	DialogDescription,
	DialogFooter,
	DialogClose,
} from '@/components/ui/dialog';

type Field = 'mcps' | 'skills' | 'knowledge';
type Values = Record<Field, string[]>;
type Data = {
	has_selection: boolean;
	has_model: boolean;
	catalog: Record<Field, { id: string; name: string }[]>;
	selected: Values;
};
const labels = { mcps: 'MCP', skills: '技能', knowledge: '知识库' };
export function CapabilityPicker({
	agentId,
	sessionId,
}: {
	agentId: string | null;
	sessionId: string | null;
}) {
	const [data, setData] = useState<Data>();
	const [error, setError] = useState('');
	const [busy, setBusy] = useState(false);
	const [saved, setSaved] = useState(false);
	useEffect(() => {
		let alive = true;
		setData(undefined);
		setError('');
		setSaved(false);
		setBusy(true);
		if (agentId && sessionId)
			void client
				.get<Data>(`/portal/capabilities/${agentId}/${sessionId}`)
				.then(async (d) => {
					if (!alive) return;
					if (!d.has_selection) {
						d.selected = {
							mcps: d.catalog.mcps.map((r) => r.id),
							skills: d.catalog.skills.map((r) => r.id),
							knowledge: d.catalog.knowledge.map((r) => r.id),
						};
						setData(d);
						await portalWrite(
							`/portal/capabilities/${agentId}/${sessionId}`,
							'PUT',
							d.selected,
						);
					}
					if (alive) {
						setData(d);
						setSaved(true);
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
	}, [agentId, sessionId]);
	if (!agentId || !sessionId) return null;
	return (
		<div className="flex min-w-0 justify-end">
			<Dialog key={`${agentId}/${sessionId}`}>
				<DialogTrigger asChild>
					<Button variant="outline" size="sm">
						能力 ·{' '}
						<span className="ml-2 text-xs font-normal text-muted-foreground">
							{error ? '应用失败' : busy ? '正在应用…' : saved ? '已应用' : '待应用'}
						</span>
					</Button>
				</DialogTrigger>
				<DialogContent className="max-h-[80vh] overflow-y-auto sm:max-w-xl">
					<DialogTitle>本次会话的可用能力</DialogTitle>
					<DialogDescription>
						选择本次对话可以使用的 MCP、技能和知识库。修改后点击“应用选择”生效。
					</DialogDescription>
					<div className="flex justify-between items-center gap-3 mb-2">
						<span className="text-xs text-muted-foreground">
							默认启用全部已授权能力，可按需调整。
						</span>
						<Button
							size="sm"
							variant="outline"
							disabled={busy || !data}
							onClick={async () => {
								setBusy(true);
								setError('');
								try {
									await portalWrite(
										`/portal/capabilities/${agentId}/${sessionId}`,
										'PUT',
										data?.selected,
									);
									setSaved(true);
								} catch (e) {
									setError(e instanceof Error ? e.message : '保存失败');
								} finally {
									setBusy(false);
								}
							}}
						>
							{busy ? '保存中' : saved ? '已应用' : '应用选择'}
						</Button>
					</div>
					{data &&
						(Object.keys(labels) as Field[]).map((k) => (
							<div
								className="flex flex-wrap items-center gap-x-4 gap-y-2 py-1"
								key={k}
							>
								<span className="w-12 text-xs text-slate-400">{labels[k]}</span>
								{data.catalog[k].map((r) => (
									<label className="flex items-center gap-1.5 text-xs" key={r.id}>
										<input
											type="checkbox"
											disabled={busy}
											checked={data.selected[k].includes(r.id)}
											onChange={(e) => {
												setSaved(false);
												setData({
													...data,
													selected: {
														...data.selected,
														[k]: e.target.checked
															? [...data.selected[k], r.id]
															: data.selected[k].filter(
																	(id) => id !== r.id,
																),
													},
												});
											}}
										/>
										{r.name}
									</label>
								))}
								{!data.catalog[k].length && (
									<span className="text-xs text-slate-400">未分配</span>
								)}
							</div>
						))}
					{data && !data.has_model && (
						<p className="text-xs text-amber-700 mt-2">
							管理员尚未分配模型凭据，分配后即可选择模型开始聊天。
						</p>
					)}
					{error && (
						<p role="alert" className="text-red-600 text-xs mt-2">
							{error}
						</p>
					)}
					<DialogFooter>
						<DialogClose asChild>
							<Button variant="outline">关闭</Button>
						</DialogClose>
					</DialogFooter>
				</DialogContent>
			</Dialog>
		</div>
	);
}
