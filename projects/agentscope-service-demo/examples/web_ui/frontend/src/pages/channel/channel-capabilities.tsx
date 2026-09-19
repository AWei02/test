import { useState } from 'react';
import { SlidersHorizontal } from 'lucide-react';
import { channelApi, type ChannelRecord } from '@/api';
import { client } from '@/api/client';
import { Button } from '@/components/ui/button';
import {
	Dialog,
	DialogTrigger,
	DialogContent,
	DialogTitle,
	DialogDescription,
	DialogFooter,
} from '@/components/ui/dialog';
type Field = 'mcps' | 'skills' | 'knowledge';
const labels = { mcps: 'MCP', skills: '技能', knowledge: '知识库' };
export function ChannelCapabilities({
	channel,
	onSaved,
}: {
	channel: ChannelRecord;
	onSaved: () => void;
}) {
	const [open, setOpen] = useState(false);
	const [record, setRecord] = useState(channel);
	const [catalog, setCatalog] = useState<Record<Field, { id: string; name: string }[]>>();
	const [selected, setSelected] = useState<Record<Field, string[]>>({
		mcps: [],
		skills: [],
		knowledge: [],
	});
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState('');
	async function load() {
		setBusy(true);
		setError('');
		setCatalog(undefined);
		try {
			const [r, c] = await Promise.all([
				client.get<ChannelRecord>('/channels/' + channel.id),
				client.get<{ catalog: Record<Field, { id: string; name: string }[]> }>(
					'/portal/admin',
				),
			]);
			setRecord(r);
			setCatalog(c.catalog);
			setSelected(
				Object.fromEntries(
					(Object.keys(labels) as Field[]).map((k) => [
						k,
						c.catalog[k]
							.filter(
								(x) =>
									!r.session.capabilities ||
									r.session.capabilities[k].includes(x.id),
							)
							.map((x) => x.id),
					]),
				) as Record<Field, string[]>,
			);
		} catch (e) {
			setError(String(e));
		} finally {
			setBusy(false);
		}
	}
	return (
		<div onClick={(e) => e.stopPropagation()}>
			<Dialog
				open={open}
				onOpenChange={(v) => {
					if (!busy) {
						setOpen(v);
						if (v) void load();
					}
				}}
			>
				<DialogTrigger asChild>
					<Button variant="outline" size="sm">
						<SlidersHorizontal className="size-4" />
						频道能力
					</Button>
				</DialogTrigger>
				<DialogContent>
					<DialogTitle>频道能力</DialogTitle>
					<DialogDescription>
						仅启用勾选的能力。保存后从下一次调用起生效，不删除历史消息；文件继续使用绑定项目。
					</DialogDescription>
					{error && (
						<p role="alert" className="text-destructive text-sm">
							{error}
						</p>
					)}
					{(Object.keys(labels) as Field[]).map((k) => (
						<fieldset key={k} className="space-y-2" disabled={busy}>
							<legend className="font-medium text-sm">{labels[k]}</legend>
							<div className="flex flex-wrap gap-3">
								{catalog?.[k].map((r) => (
									<label key={r.id} className="flex items-center gap-2 text-sm">
										<input
											type="checkbox"
											checked={selected[k].includes(r.id)}
											onChange={(e) =>
												setSelected({
													...selected,
													[k]: e.target.checked
														? [...selected[k], r.id]
														: selected[k].filter((id) => id !== r.id),
												})
											}
										/>
										{r.name}
									</label>
								))}
							</div>
						</fieldset>
					))}
					<DialogFooter>
						<Button variant="outline" disabled={busy} onClick={() => setOpen(false)}>
							取消
						</Button>
						<Button
							disabled={busy || !catalog}
							onClick={async () => {
								setBusy(true);
								setError('');
								try {
									await channelApi.update(channel.id, {
										session: { ...record.session, capabilities: selected },
									});
									setOpen(false);
									onSaved();
								} catch (e) {
									setError(String(e));
								} finally {
									setBusy(false);
								}
							}}
						>
							{busy ? '加载／保存中…' : '应用选择'}
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>
		</div>
	);
}
