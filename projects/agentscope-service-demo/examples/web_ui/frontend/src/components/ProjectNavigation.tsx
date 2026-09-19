import { useQueryClient } from '@tanstack/react-query';
import {
	ChevronDown,
	ChevronRight,
	Folder,
	Folders,
	Bot,
	Plus,
	Settings2,
	Trash2,
	Ellipsis,
	SquarePen,
	Users,
	MessageSquare,
} from 'lucide-react';
import { useEffect, useState, useRef } from 'react';
import { Link, useParams, useNavigate } from 'react-router-dom';

import { ProjectDialog } from './ProjectDialog';
import { ProjectSessionMenu } from './ProjectSessionMenu';
import { sidebarHeadingClass, sidebarAddButtonClass } from './sidebarHeading';
import { sessionApi } from '@/api';
import { portalWrite } from '@/api/portal';
import { Button } from '@/components/ui/button';
import {
	Dialog,
	DialogContent,
	DialogTitle,
	DialogDescription,
	DialogFooter,
} from '@/components/ui/dialog';
import {
	DropdownMenu,
	DropdownMenuTrigger,
	DropdownMenuContent,
	DropdownMenuItem,
} from '@/components/ui/dropdown-menu';
import { useAgents } from '@/hooks/useAgents';
import type { Project } from '@/hooks/useProjects';
import { useProjects } from '@/hooks/useProjects';
import { useSessionPins } from '@/hooks/useSessionPins';
import { sessionDisplayName, beijingClock, beijingTime, isBeijingToday } from '@/lib/beijingTime';

export function ProjectNavigation({ initialAgentId }: { initialAgentId?: string }) {
	const { data, isPending, isError, refetch } = useProjects();
	const navigate = useNavigate();
	const cache = useQueryClient();
	const pins = useSessionPins();
	const { agents } = useAgents();
	const creatingSession = useRef(false);
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState('');
	const [editingProject, setEditingProject] = useState<Project | null>(null);
	const [deletingProject, setDeletingProject] = useState<Project | null>(null);
	const [deleting, setDeleting] = useState(false);
	const [deleteError, setDeleteError] = useState('');
	async function deleteProject() {
		if (!deletingProject || deleting) return;
		setDeleting(true);
		setDeleteError('');
		try {
			await portalWrite(`/portal/projects/${deletingProject.id}/delete`, 'POST', {
				confirmed: true,
			});
			if (current === deletingProject.id) navigate('/chat?ordinary=1');
			await refetch();
			setDeletingProject(null);
		} catch (e) {
			setDeleteError(String(e));
		} finally {
			setDeleting(false);
		}
	}
	async function newSession(p: Project) {
		if (creatingSession.current) return;
		const candidates = [
			p.agent_id,
			initialAgentId,
			...(data?.bindings.filter((b) => b.project_id === p.id).map((b) => b.agent_id) ?? []),
			agents[0]?.id,
		];
		const selected = p.agent_id || candidates.find((id) => agents.some((a) => a.id === id));
		if (!selected) {
			setError('暂无可用智能体，请联系管理员授权后重试');
			return;
		}
		creatingSession.current = true;
		setBusy(true);
		setError('');
		try {
			const result = await sessionApi.create({ agent_id: selected });
			await portalWrite(`/portal/projects/${p.id}/sessions`, 'POST', {
				agent_id: selected,
				session_id: result.session_id,
			});
			await Promise.all([refetch(), cache.invalidateQueries({ queryKey: ['sessions'] })]);
			navigate(`/chat/${selected}/${result.session_id}`);
		} catch (e) {
			setError(String(e));
		} finally {
			setBusy(false);
			creatingSession.current = false;
		}
	}
	const { projectId, agentId, sessionId } = useParams();
	const current =
		projectId ||
		data?.bindings.find((b) => b.agent_id === agentId && b.session_id === sessionId)
			?.project_id;
	const [tab, setTab] = useState<'mine' | 'shared'>('mine');
	const [showAllProjects, setShowAllProjects] = useState(false);
	const [expanded, setExpanded] = useState<Record<string, boolean>>({});
	const [creating, setCreating] = useState(false);
	const currentProject = data?.projects.find((p) => p.id === current);
	useEffect(() => {
		if (currentProject) {
			setTab(currentProject.is_owner ? 'mine' : 'shared');
			setExpanded((prev) => ({ ...prev, [currentProject.id]: true }));
		}
	}, [currentProject?.id, currentProject?.is_owner]);
	const projects =
		data?.projects.filter(
			(p) =>
				(tab === 'mine' ? p.is_owner : p.shared) &&
				(showAllProjects || (!!initialAgentId && p.agent_id === initialAgentId)),
		) ?? [];
	const scopeHint = showAllProjects
		? '当前显示所有智能体的项目，点击只显示当前智能体'
		: '当前仅显示当前智能体的项目，点击显示所有项目';
	return (
		<section aria-label="项目导航" className="px-3 py-3">
			<div className="flex items-center justify-between px-1 mb-2">
				<span className={sidebarHeadingClass}>项目</span>
				<div className="flex items-center gap-1">
					<button
						type="button"
						title={scopeHint}
						aria-label={scopeHint}
						aria-pressed={showAllProjects}
						className={
							'rounded-md p-1.5 hover:bg-accent focus-visible:ring-2 ' +
							(showAllProjects
								? 'bg-accent text-foreground'
								: 'text-muted-foreground')
						}
						onClick={() => setShowAllProjects((value) => !value)}
					>
						{showAllProjects ? (
							<Folders className="size-4" />
						) : (
							<Bot className="size-4" />
						)}
					</button>
					<button
						title="新建项目"
						aria-label="新建项目"
						className={sidebarAddButtonClass}
						onClick={() => setCreating(true)}
					>
						<Plus className="size-4" />
					</button>
				</div>
			</div>
			<div
				role="tablist"
				aria-label="项目范围"
				className="grid grid-cols-2 rounded-lg bg-muted/70 p-1 mb-3"
			>
				{(['mine', 'shared'] as const).map((value) => (
					<button
						key={value}
						role="tab"
						aria-selected={tab === value}
						className={
							'rounded-md py-1 text-xs transition-colors ' +
							(tab === value
								? 'bg-background shadow-sm font-medium'
								: 'text-muted-foreground hover:text-foreground')
						}
						onClick={() => setTab(value)}
					>
						{value === 'mine' ? '我的' : '共享'}
					</button>
				))}
			</div>
			<div className="max-h-[38vh] overflow-y-auto space-y-1">
				{error && (
					<p role="alert" className="text-xs text-destructive">
						{error}
					</p>
				)}
				{isPending && <p className="text-xs p-2 text-muted-foreground">加载项目…</p>}
				{isError && (
					<button className="text-xs p-2 text-destructive" onClick={() => void refetch()}>
						项目加载失败，点击重试
					</button>
				)}
				{!isPending && !isError && !projects.length && (
					<p className="text-xs px-2 py-4 leading-relaxed text-muted-foreground">
						{!showAllProjects
							? tab === 'mine'
								? '当前智能体暂无项目，可点击 ＋ 创建或切换显示所有项目。'
								: '当前智能体暂无共享项目，可切换显示所有项目。'
							: tab === 'mine'
								? '还没有项目，点击上方 ＋ 创建。'
								: '暂无共享项目。有权限的共享项目会显示在这里。'}
					</p>
				)}
				{projects.map((p) => {
					const sessions = (
						data?.bindings.filter((b) => b.project_id === p.id) ?? []
					).sort(
						(a, b) =>
							Number(pins.isPinned(b.agent_id, b.session_id)) -
							Number(pins.isPinned(a.agent_id, a.session_id)),
					);
					return (
						<div key={p.id}>
							<div
								className={
									'group flex items-center rounded-lg ' +
									(current === p.id ? 'bg-accent' : 'hover:bg-accent/60')
								}
							>
								<button
									className="p-1.5 shrink-0 rounded"
									aria-label={'展开项目 ' + p.name}
									aria-expanded={!!expanded[p.id]}
									onClick={() =>
										setExpanded((prev) => ({ ...prev, [p.id]: !prev[p.id] }))
									}
								>
									{expanded[p.id] ? (
										<ChevronDown className="size-3.5" />
									) : (
										<ChevronRight className="size-3.5" />
									)}
								</button>
								<button
									aria-expanded={!!expanded[p.id]}
									onClick={() =>
										setExpanded((prev) => ({ ...prev, [p.id]: !prev[p.id] }))
									}
									className="min-w-0 flex flex-1 items-center gap-2 py-2 text-sm"
								>
									<Folder className="size-4 shrink-0 text-muted-foreground" />
									<span className="truncate">{p.name}</span>
									{p.shared && (
										<Users className="size-3 shrink-0 text-muted-foreground" />
									)}
								</button>
								<div className="flex shrink-0 items-center md:opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 has-[[data-state=open]]:opacity-100">
									{
										<DropdownMenu>
											<DropdownMenuTrigger asChild>
												<button
													title="项目菜单"
													aria-label={'项目菜单 ' + p.name}
													className="rounded-md p-1.5 hover:bg-background"
												>
													<Ellipsis className="size-4" />
												</button>
											</DropdownMenuTrigger>
											<DropdownMenuContent className="w-auto" align="start">
												<DropdownMenuItem
													onClick={() => navigate('/projects/' + p.id)}
												>
													<Folder className="size-4" />
													进入项目
												</DropdownMenuItem>
												{p.is_owner && (
													<DropdownMenuItem
														onClick={() => setEditingProject(p)}
													>
														<Settings2 className="size-4" />
														编辑项目
													</DropdownMenuItem>
												)}
												{p.is_owner && (
													<DropdownMenuItem
														variant="destructive"
														onClick={() => {
															setDeleteError('');
															setDeletingProject(p);
														}}
													>
														<Trash2 className="size-4" />
														删除项目
													</DropdownMenuItem>
												)}
											</DropdownMenuContent>
										</DropdownMenu>
									}
									<button
										disabled={busy}
										title="新建项目会话"
										aria-label={'新建项目会话 ' + p.name}
										onClick={() => void newSession(p)}
										className="rounded-md p-1.5 hover:bg-background disabled:opacity-50"
									>
										<SquarePen className="size-4" />
									</button>
								</div>
							</div>
							{expanded[p.id] && (
								<div className="ml-4 pl-3 border-l my-1 space-y-0.5">
									{sessions.map((s) => (
										<div
											key={s.agent_id + '/' + s.session_id}
											className={
												'relative flex items-center group/session rounded-full hover:bg-sidebar-accent ' +
												(sessionId === s.session_id
													? 'bg-sidebar-accent'
													: '')
											}
										>
											<Link
												key={s.agent_id + '/' + s.session_id}
												aria-current={
													sessionId === s.session_id ? 'page' : undefined
												}
												to={`/chat/${s.agent_id}/${s.session_id}`}
												className={
													'min-w-0 flex-1 flex gap-2 items-center rounded-full px-2 py-2 text-sm ' +
													(sessionId === s.session_id
														? 'text-foreground'
														: 'text-muted-foreground')
												}
											>
												<MessageSquare className="size-3 shrink-0" />
												<span className="truncate">
													{sessionDisplayName(s.name, s.created_at) ||
														'未命名会话'}
													{pins.isPinned(s.agent_id, s.session_id)
														? ' · 置顶'
														: ''}
												</span>
											</Link>
											<span
												className="w-14 shrink-0 pr-2 text-right text-xs font-mono text-text-tertiary max-md:invisible group-hover/session:invisible group-has-focus-visible/session:invisible group-has-[[data-state=open]]/session:invisible"
												title={
													s.created_at
														? `创建时间（北京时间）：${beijingTime(s.created_at)}`
														: undefined
												}
											>
												{s.created_at
													? isBeijingToday(s.created_at)
														? beijingClock(s.created_at)
														: beijingTime(s.created_at).slice(5, 10)
													: ''}
											</span>
											<div className="absolute right-1 shrink-0 md:opacity-0 group-hover/session:opacity-100 group-has-focus-visible/session:opacity-100 focus-within:opacity-100 has-[[data-state=open]]:opacity-100">
												<ProjectSessionMenu
													agentId={s.agent_id}
													sessionId={s.session_id}
													name={
														sessionDisplayName(s.name, s.created_at) ||
														'未命名会话'
													}
													projectId={p.id}
												/>
											</div>
										</div>
									))}
									{!sessions.length && (
										<p className="px-2 py-2 text-xs text-muted-foreground">
											你还没有项目会话
										</p>
									)}
								</div>
							)}
						</div>
					);
				})}
			</div>
			{creating && (
				<ProjectDialog initialAgentId={initialAgentId} onClose={() => setCreating(false)} />
			)}
			{editingProject && (
				<ProjectDialog project={editingProject} onClose={() => setEditingProject(null)} />
			)}
			{deletingProject && (
				<Dialog
					open
					onOpenChange={(open) => {
						if (!open && !deleting) setDeletingProject(null);
					}}
				>
					<DialogContent>
						<DialogTitle>确认删除项目“{deletingProject.name}”？</DialogTitle>
						<DialogDescription>
							项目将从列表移除，所有成员将无法继续访问其文件目录。服务器保留文件和历史会话，不会立即物理清除；恢复需联系管理员。
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
								disabled={deleting}
								onClick={() => setDeletingProject(null)}
							>
								取消
							</Button>
							<Button
								variant="destructive"
								disabled={deleting}
								onClick={() => void deleteProject()}
							>
								{deleting ? '删除中…' : '确认删除'}
							</Button>
						</DialogFooter>
					</DialogContent>
				</Dialog>
			)}
		</section>
	);
}
