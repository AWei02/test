import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { FolderPlus, Users, LockKeyhole } from 'lucide-react';
import { useAgents } from '@/hooks/useAgents';
import { useProjects, type Project } from '@/hooks/useProjects';
import { portalWrite } from '@/api/portal';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import {
	Dialog,
	DialogContent,
	DialogTitle,
	DialogDescription,
	DialogHeader,
	DialogFooter,
} from '@/components/ui/dialog';

// Mounted only when opened; form values belong to one project, never the last edited one.
export function ProjectDialog({
	project,
	onClose,
	initialAgentId,
}: {
	project?: Project;
	onClose: () => void;
	initialAgentId?: string;
}) {
	const { agents } = useAgents();
	const { refetch } = useProjects();
	const navigate = useNavigate();
	const [name, setName] = useState(project?.name ?? '');
	const [description, setDescription] = useState(project?.description ?? '');
	const [agent, setAgent] = useState(project?.agent_id || initialAgentId || '');
	const [shared, setShared] = useState(project?.shared ?? false);
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState('');
	const selected = agent || agents[0]?.id || '';
	async function save() {
		setBusy(true);
		setError('');
		try {
			const result = await portalWrite(
				'/portal/projects' + (project ? '/' + project.id : ''),
				project ? 'PUT' : 'POST',
				{
					name: name.trim(),
					description,
					agent_id: selected,
					shared,
				},
			);
			await refetch();
			onClose();
			if (!project) navigate('/projects/' + result.id);
		} catch (e) {
			setError(String(e));
		} finally {
			setBusy(false);
		}
	}
	return (
		<Dialog
			open
			onOpenChange={(open) => {
				if (!open && !busy) onClose();
			}}
		>
			<DialogContent className="sm:max-w-lg p-6 gap-5">
				<DialogHeader>
					<FolderPlus className="size-7 mb-2 text-muted-foreground" />
					<DialogTitle>{project ? '项目设置' : '新建项目'}</DialogTitle>
					<DialogDescription>集中管理文件，在项目内开启多个独立会话。</DialogDescription>
				</DialogHeader>
				<label className="space-y-2">
					项目名称
					<input
						autoFocus
						aria-label="项目名称"
						maxLength={100}
						className="block w-full rounded-lg border bg-background px-3 py-2"
						placeholder="例如：销售数据分析"
						value={name}
						onChange={(e) => setName(e.target.value)}
					/>
				</label>
				<label className="space-y-2">
					项目说明
					<textarea
						aria-label="项目说明"
						maxLength={4000}
						className="block w-full rounded-lg border bg-background px-3 py-2"
						placeholder="这个项目用来做什么？（可选）"
						value={description}
						onChange={(e) => setDescription(e.target.value)}
					/>
				</label>
				<div className="space-y-2">
					<label htmlFor="project-agent">项目智能体</label>
					{project?.agent_id ? (
						<input
							id="project-agent"
							aria-label="项目智能体"
							readOnly
							className="block h-8 w-full rounded-lg border border-input bg-background px-3 text-sm"
							value={agents.find((a) => a.id === project.agent_id)?.data.name ?? '原智能体（当前不可用）'}
						/>
					) : (
						<Select value={selected} onValueChange={setAgent} disabled={!agents.length}>
							<SelectTrigger id="project-agent" aria-label="项目智能体" className="h-10 w-full bg-background px-3">
								<SelectValue placeholder="暂无可用智能体" />
							</SelectTrigger>
							<SelectContent position="popper" align="start">
								{agent && !agents.some((a) => a.id === agent) && (
									<SelectItem value={agent} disabled>原智能体（当前不可用）</SelectItem>
								)}
								{agents.map((a) => (
									<SelectItem key={a.id} value={a.id}>{a.data.name}</SelectItem>
								))}
							</SelectContent>
						</Select>
					)}
				</div>
				<div className="rounded-xl border p-4 space-y-2">
					<label className="flex items-center gap-3 cursor-pointer">
						<input
							type="checkbox"
							checked={shared}
							onChange={(e) => setShared(e.target.checked)}
							aria-label="共享项目文件"
						/>
						{shared ? <Users className="size-4" /> : <LockKeyhole className="size-4" />}
						<span className="font-medium">共享项目文件</span>
					</label>
					<p className="text-xs leading-relaxed text-muted-foreground">
						默认仅自己可见。开启后，有该智能体权限的用户可看到并修改同一目录的文件。聊天记录、会话和工具选择不共享。
					</p>
					{project?.shared && !shared && (
						<p className="text-xs text-amber-700">
							保存后，其他用户将无法继续访问这个目录；他们已有的聊天记录保留。
						</p>
					)}
				</div>
				{error && (
					<p role="alert" className="text-destructive text-sm">
						{error}
					</p>
				)}
				<DialogFooter className="m-0 p-0 border-0 bg-transparent">
					<Button variant="outline" disabled={busy} onClick={onClose}>
						取消
					</Button>
					<Button
						disabled={busy || !name.trim() || !selected}
						onClick={() => void save()}
					>
						{busy ? '保存中…' : project ? '保存设置' : '创建项目'}
					</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}
