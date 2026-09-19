import { useState } from 'react';
import { Users, Plus, Trash2 } from 'lucide-react';
import { portalWrite } from '@/api/portal';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
	Dialog,
	DialogTrigger,
	DialogContent,
	DialogTitle,
	DialogDescription,
	DialogFooter,
} from '@/components/ui/dialog';

export function RoleManager({ roles, refresh }: { roles: string[]; refresh: () => Promise<void> }) {
	const [name, setName] = useState('');
	const [deleting, setDeleting] = useState<string | null>(null);
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState('');
	async function submit(remove = false) {
		setBusy(true);
		setError('');
		try {
			await portalWrite(remove ? '/portal/roles/delete' : '/portal/roles', 'POST', {
				name: remove ? deleting : name.trim(),
				confirmed: remove,
			});
			if (remove) setDeleting(null);
			else setName('');
			await refresh();
		} catch (e) {
			setError(e instanceof Error ? e.message : '操作失败');
		} finally {
			setBusy(false);
		}
	}
	return (
		<Dialog
			onOpenChange={() => {
				setError('');
				setDeleting(null);
			}}
		>
			<DialogTrigger asChild>
				<Button variant="outline">
					<Users className="size-4" />
					角色管理
				</Button>
			</DialogTrigger>
			<DialogContent className="max-h-[80vh] overflow-y-auto">
				<DialogTitle>角色管理</DialogTitle>
				<DialogDescription>
					用户和角色授权统一使用此列表。仍被引用的角色不能删除。
				</DialogDescription>
				<form
					className="flex gap-2"
					onSubmit={(e) => {
						e.preventDefault();
						void submit();
					}}
				>
					<Input
						aria-label="角色名称"
						placeholder="输入新角色名称"
						maxLength={80}
						value={name}
						onChange={(e) => setName(e.target.value)}
						disabled={busy}
					/>
					<Button disabled={busy || !name.trim()}>
						<Plus className="size-4" />
						添加
					</Button>
				</form>
				{!deleting && error && (
					<p role="alert" className="text-sm text-destructive">
						{error}
					</p>
				)}
				<div className="divide-y">
					{roles.map((role) => (
						<div key={role} className="flex items-center justify-between gap-3 py-3">
							<span className="min-w-0 break-words">{role}</span>
							<Button
								variant="ghost"
								className="text-destructive shrink-0"
								disabled={busy}
								onClick={() => {
									setError('');
									setDeleting(role);
								}}
							>
								<Trash2 className="size-4" />
								删除
							</Button>
						</div>
					))}
				</div>
				<Dialog
					open={deleting !== null}
					onOpenChange={(open) => {
						if (!open && !busy) {
							setDeleting(null);
							setError('');
						}
					}}
				>
					<DialogContent>
						<DialogTitle>确认删除角色？</DialogTitle>
						<DialogDescription>
							删除“{deleting}”前将检查用户和访问授权引用；存在引用时会拒绝删除。
						</DialogDescription>
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
									setDeleting(null);
									setError('');
								}}
							>
								取消
							</Button>
							<Button
								variant="destructive"
								disabled={busy}
								onClick={() => void submit(true)}
							>
								{busy ? '检查中…' : '确认删除'}
							</Button>
						</DialogFooter>
					</DialogContent>
				</Dialog>
			</DialogContent>
		</Dialog>
	);
}
