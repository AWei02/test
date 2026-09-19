import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { Ellipsis, Pencil, Pin, Trash2 } from 'lucide-react';
import { sessionApi } from '@/api';
import { useSessionPins } from '@/hooks/useSessionPins';
import {
	DropdownMenu,
	DropdownMenuTrigger,
	DropdownMenuContent,
	DropdownMenuItem,
} from '@/components/ui/dropdown-menu';
import {
	Dialog,
	DialogContent,
	DialogTitle,
	DialogDescription,
	DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { SidebarMenuAction } from '@/components/ui/sidebar';
export function ProjectSessionMenu({
	agentId,
	sessionId,
	name,
	projectId,
	deleteOnly = false,
}: {
	agentId: string;
	sessionId: string;
	name: string;
	projectId: string;
	deleteOnly?: boolean;
}) {
	const [mode, setMode] = useState<'rename' | 'delete' | null>(null);
	const [value, setValue] = useState(name);
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState('');
	const pins = useSessionPins();
	const cache = useQueryClient();
	const navigate = useNavigate();
	const params = useParams();
	async function run(action: () => Promise<unknown>) {
		setBusy(true);
		setError('');
		try {
			await action();
			await Promise.all([
				cache.invalidateQueries({ queryKey: ['sessions'] }),
				cache.invalidateQueries({ queryKey: ['projects'] }),
			]);
			setMode(null);
		} catch (e) {
			setError(String(e));
		} finally {
			setBusy(false);
		}
	}
	return (
		<>
			{deleteOnly ? (
				<Button
					variant="ghost"
					className="text-destructive"
					onClick={() => {
						setError('');
						setMode('delete');
					}}
				>
					删除
				</Button>
			) : (
				<DropdownMenu>
					<DropdownMenuTrigger asChild>
						<SidebarMenuAction
							aria-label={'会话菜单 ' + name}
							className="static! bg-transparent"
						>
							<Ellipsis className="size-3.5" />
						</SidebarMenuAction>
					</DropdownMenuTrigger>
					<DropdownMenuContent className="w-auto" side="right" align="start">
						<DropdownMenuItem
							disabled={busy}
							onClick={() => void run(() => pins.toggle(agentId, sessionId))}
						>
							<Pin />
							{pins.isPinned(agentId, sessionId) ? '取消置顶' : '置顶'}
						</DropdownMenuItem>
						<DropdownMenuItem
							onClick={() => {
								setValue(name);
								setError('');
								setMode('rename');
							}}
						>
							<Pencil />
							重命名
						</DropdownMenuItem>
						<DropdownMenuItem
							variant="destructive"
							onClick={() => {
								setError('');
								setMode('delete');
							}}
						>
							<Trash2 />
							删除
						</DropdownMenuItem>
					</DropdownMenuContent>
				</DropdownMenu>
			)}
			{!mode && error && (
				<span role="alert" className="text-xs text-destructive">
					{error}
				</span>
			)}
			{mode && (
				<Dialog
					open
					onOpenChange={(open) => {
						if (!open && !busy) setMode(null);
					}}
				>
					<DialogContent>
						<DialogTitle>
							{mode === 'rename' ? '重命名会话' : '确认删除会话？'}
						</DialogTitle>
						<DialogDescription>
							{mode === 'delete'
								? `删除“${name}”及其聊天记录，不会删除项目共享文件或其他人的会话。此操作不可撤销。`
								: '为这个会话设置一个容易识别的名称。'}
						</DialogDescription>
						{mode === 'rename' && (
							<input
								autoFocus
								aria-label="会话名称"
								maxLength={200}
								className="rounded border px-3 py-2"
								value={value}
								onChange={(e) => setValue(e.target.value)}
							/>
						)}
						{error && (
							<p role="alert" className="text-destructive">
								{error}
							</p>
						)}
						<DialogFooter>
							<Button
								autoFocus={mode === 'delete'}
								variant="outline"
								disabled={busy}
								onClick={() => setMode(null)}
							>
								取消
							</Button>
							<Button
								variant={mode === 'delete' ? 'destructive' : 'default'}
								disabled={busy || (mode === 'rename' && !value.trim())}
								onClick={() =>
									void run(async () => {
										if (mode === 'rename')
											await sessionApi.update(sessionId, agentId, {
												name: value.trim(),
											});
										else {
											await sessionApi.delete(sessionId, agentId);
											if (params.sessionId === sessionId)
												navigate('/projects/' + projectId);
										}
									})
								}
							>
								{mode === 'delete' ? '确认删除' : '保存'}
							</Button>
						</DialogFooter>
					</DialogContent>
				</Dialog>
			)}
		</>
	);
}
