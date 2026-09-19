import { useEffect, useState } from 'react';

import { client, serviceUrl, getAuthHeaders } from '@/api/client';
import { portalWrite } from '@/api/portal';
import { FileUploadButton } from '@/components/FileUploadButton';
import { Button } from '@/components/ui/button';
import {
	Dialog,
	DialogContent,
	DialogTitle,
	DialogDescription,
	DialogFooter,
} from '@/components/ui/dialog';
import { useProjects } from '@/hooks/useProjects';
import { beijingTime } from '@/lib/beijingTime';
export function ProjectFileManager({ projectId }: { projectId: string }) {
	const { data } = useProjects();
	const isOwner = data?.projects.find((p) => p.id === projectId)?.is_owner;
	const [deletion, setDeletion] = useState<{
		name: string;
		version?: string;
		time?: number;
	} | null>(null);
	const [deleteError, setDeleteError] = useState('');
	async function confirmDelete() {
		if (!deletion || busy) return;
		setBusy(true);
		setDeleteError('');
		try {
			await portalWrite(
				base + (deletion.version ? '/history/delete' : '/file-actions/delete'),
				'POST',
				{ ...deletion, confirmed: true },
			);
			setDeletion(null);
			await refresh();
		} catch (e) {
			setDeleteError(String(e));
		} finally {
			setBusy(false);
		}
	}
	const [files, setFiles] = useState<{ name: string; size: number }[]>([]);
	const [history, setHistory] = useState<{ name: string; version: string; time: number }[]>([]);
	const [busy, setBusy] = useState(false),
		[message, setMessage] = useState('');
	const [rename, setRename] = useState(''),
		[nextName, setNextName] = useState('');
	const base = '/portal/projects/' + projectId;
	async function refresh() {
		const [f, h] = await Promise.all([
			client.get<{ files: typeof files }>(base + '/files'),
			client.get<typeof history>(base + '/history'),
		]);
		setFiles(f.files);
		setHistory(h);
	}
	useEffect(() => {
		void refresh().catch((e) => setMessage(String(e)));
	}, [projectId]);
	async function action(task: () => Promise<unknown>) {
		setBusy(true);
		setMessage('');
		try {
			await task();
			await refresh();
			setRename('');
		} catch (e) {
			setMessage(String(e));
		} finally {
			setBusy(false);
		}
	}
	async function upload(selected: FileList | null) {
		if (!selected) return;
		await action(async () => {
			for (const file of Array.from(selected)) {
				const body = new FormData();
				body.append('file', file);
				const response = await fetch(serviceUrl(base + '/files'), {
					method: 'POST',
					headers: { ...getAuthHeaders() },
					body,
				});
				if (!response.ok) {
					const error = await response.json();
					throw new Error(error.detail || '上传失败');
				}
			}
		});
	}
	async function download(name: string) {
		await action(async () => {
			const r = await fetch(serviceUrl(base + '/files/' + encodeURIComponent(name)), {
				headers: { ...getAuthHeaders() },
			});
			if (!r.ok) throw new Error('下载失败');
			const url = URL.createObjectURL(await r.blob());
			const a = document.createElement('a');
			a.href = url;
			a.download = name;
			a.click();
			setTimeout(() => URL.revokeObjectURL(url), 1000);
		});
	}
	return (
		<section className="rounded-xl border bg-background p-5 space-y-4">
			<div className="flex items-center justify-between">
				<h2 className="font-semibold">项目文件</h2>
				<Button variant="outline" disabled={busy} onClick={() => void action(refresh)}>
					刷新
				</Button>
			</div>
			<p className="text-sm text-muted-foreground">
				项目内所有会话共享这些文件。AI 的工作目录为 /work；上传和下载单文件最大 20MB。
			</p>
			<FileUploadButton
				aria-label="上传项目文件"
				type="file"
				multiple
				disabled={busy}
				onChange={(e) => void upload(e.target.files)}
			/>
			{busy && <p role="status">处理中，项目正在执行脚本时会等待文件锁…</p>}
			{message && (
				<p role="alert" className="text-red-600">
					{message}
				</p>
			)}
			<div className="divide-y">
				{files.map((f) => (
					<div key={f.name} className="py-3 flex flex-wrap items-center gap-3">
						<button
							className="text-left flex-1 underline break-all"
							onClick={() => void download(f.name)}
						>
							{f.name}
						</button>
						<span className="text-xs text-muted-foreground">
							{(f.size / 1024).toFixed(1)} KB
						</span>
						<Button
							size="sm"
							variant="ghost"
							disabled={busy}
							onClick={() => {
								setRename(f.name);
								setNextName(f.name);
							}}
						>
							重命名
						</Button>
						<Button
							size="sm"
							variant="ghost"
							disabled={busy}
							onClick={() => {
								setDeleteError('');
								setDeletion({ name: f.name });
							}}
						>
							删除（可恢复）
						</Button>
					</div>
				))}
			</div>
			{!files.length && (
				<p className="text-muted-foreground text-sm">
					尚无文件，先上传资料，再新建会话让 AI 处理。
				</p>
			)}
			{rename && (
				<form
					className="flex gap-2"
					onSubmit={(e) => {
						e.preventDefault();
						void action(() =>
							portalWrite(base + '/file-actions/rename', 'POST', {
								name: rename,
								new_name: nextName,
							}),
						);
					}}
				>
					<input
						aria-label="新的文件名"
						className="border rounded px-3 min-w-0 flex-1"
						value={nextName}
						onChange={(e) => setNextName(e.target.value)}
					/>
					<Button disabled={busy}>保存文件名</Button>
				</form>
			)}
			<details>
				<summary className="cursor-pointer text-sm">
					历史文件 / 恢复（{history.length}）
				</summary>
				<p className="text-xs text-muted-foreground py-2">
					每次修改前保留备份；恢复同名文件也会先备份当前版本。
				</p>
				<div className="max-h-60 overflow-auto">
					{history.map((h) => (
						<div
							key={h.version + h.name}
							className="flex items-center gap-2 py-2 text-xs"
						>
							<span className="flex-1 break-all">
								{h.name} · {beijingTime(new Date(h.time * 1000).toISOString())}
							</span>
							<Button
								size="sm"
								variant="outline"
								disabled={busy}
								onClick={() =>
									void action(() =>
										portalWrite(base + '/file-actions/restore', 'POST', h),
									)
								}
							>
								恢复
							</Button>
							{isOwner && (
								<Button
									size="sm"
									variant="ghost"
									className="text-destructive"
									disabled={busy}
									onClick={() => {
										setDeleteError('');
										setDeletion(h);
									}}
								>
									彻底删除
								</Button>
							)}
						</div>
					))}
				</div>
			</details>
			{deletion && (
				<Dialog
					open
					onOpenChange={(open) => {
						if (!open && !busy) setDeletion(null);
					}}
				>
					<DialogContent>
						<DialogTitle>
							{deletion.version ? '确认彻底删除历史版本？' : '确认删除文件？'}
						</DialogTitle>
						<DialogDescription>
							{deletion.version
								? `将永久删除“${deletion.name}”的这个历史版本（${beijingTime(new Date(deletion.time! * 1000).toISOString())}），不可恢复。不会删除当前文件或其他历史版本。`
								: `将删除项目文件“${deletion.name}”，影响所有项目成员；删除前会保存可恢复的历史备份。`}
						</DialogDescription>
						{deleteError && (
							<p role="alert" className="text-destructive">
								{deleteError}
							</p>
						)}
						<DialogFooter>
							<Button
								autoFocus
								variant="outline"
								disabled={busy}
								onClick={() => setDeletion(null)}
							>
								取消
							</Button>
							<Button
								variant="destructive"
								disabled={busy}
								onClick={() => void confirmDelete()}
							>
								{busy ? '删除中…' : deletion.version ? '确认彻底删除' : '确认删除'}
							</Button>
						</DialogFooter>
					</DialogContent>
				</Dialog>
			)}
		</section>
	);
}
