import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { client } from '@/api/client';
import { portalWrite } from '@/api/portal';
import { Button } from '@/components/ui/button';
import {
	Dialog,
	DialogTrigger,
	DialogContent,
	DialogTitle,
	DialogDescription,
	DialogFooter,
} from '@/components/ui/dialog';
export function ProjectTransfer({ projectId }: { projectId: string }) {
	const cache = useQueryClient();
	const [open, setOpen] = useState(false);
	const [confirm, setConfirm] = useState(false);
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState('');
	const [options, setOptions] = useState<{ owner: string; users: string[] }>();
	const [target, setTarget] = useState('');
	async function load() {
		setBusy(true);
		setError('');
		setOptions(undefined);
		setTarget('');
		try {
			setOptions(await client.get(`/portal/projects/${projectId}/transfer-options`));
		} catch (e) {
			setError(String(e));
		} finally {
			setBusy(false);
		}
	}
	return (
		<Dialog
			open={open}
			onOpenChange={(v) => {
				if (!busy) {
					setOpen(v);
					setConfirm(false);
					if (v) void load();
				}
			}}
		>
			<DialogTrigger asChild>
				<Button variant="outline">转移所有权</Button>
			</DialogTrigger>
			<DialogContent>
				<DialogTitle>{confirm ? '确认转移项目所有权？' : '转移项目所有权'}</DialogTitle>
				<DialogDescription>
					文件、历史版本、频道绑定和共享设置保持不变。聊天记录仍归原用户，新所有者不会获得其他人的私有聊天。原所有者失去管理权，后续访问取决于共享设置和授权。
				</DialogDescription>
				<p className="text-sm">当前所有者：{options?.owner ?? '加载中…'}</p>
				<select
					aria-label="新所有者"
					className="h-10 rounded border bg-background px-3"
					value={target}
					disabled={busy || confirm}
					onChange={(e) => setTarget(e.target.value)}
				>
					<option value="">请选择新所有者</option>
					{options?.users.map((u) => (
						<option key={u} value={u}>
							{u}
						</option>
					))}
				</select>
				{options?.users.length === 0 && (
					<p className="text-sm text-muted-foreground">
						没有符合条件的用户，请先启用用户并分配智能体权限。
					</p>
				)}
				{confirm && (
					<p className="font-medium">
						将从“{options?.owner}”转移给“{target}”。是否继续？
					</p>
				)}
				{error && (
					<p role="alert" className="text-sm text-destructive">
						{error}
					</p>
				)}
				<DialogFooter>
					<Button
						autoFocus
						variant="outline"
						disabled={busy}
						onClick={() => {
							if (confirm) setConfirm(false);
							else setOpen(false);
						}}
					>
						取消
					</Button>
					<Button
						disabled={busy || !target}
						onClick={async () => {
							if (!confirm) {
								setConfirm(true);
								return;
							}
							setBusy(true);
							setError('');
							try {
								await portalWrite(
									`/portal/projects/${projectId}/transfer`,
									'POST',
									{
										owner: target,
										expected_owner: options?.owner,
										confirmed: true,
									},
								);
								await cache.invalidateQueries({ queryKey: ['projects'] });
								setOpen(false);
							} catch (e) {
								setError(String(e));
							} finally {
								setBusy(false);
							}
						}}
					>
						{busy ? '处理中…' : confirm ? '确认转移' : '转移所有权'}
					</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}
