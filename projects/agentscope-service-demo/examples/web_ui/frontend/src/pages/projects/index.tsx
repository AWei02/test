import {
	Files,
	Folder,
	ListChecks,
	LockKeyhole,
	MessagesSquare,
	Settings2,
	Users,
} from 'lucide-react';
import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { ProjectAudit } from '@/components/ExecutionAudit';
import { FileCatalogPanel } from '@/components/FileCatalogPanel';
import { ProjectDialog } from '@/components/ProjectDialog';
import { ProjectSessionMenu } from '@/components/ProjectSessionMenu';
import { ProjectTransfer } from '@/components/ProjectTransfer';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useAgents } from '@/hooks/useAgents';
import { usePortal } from '@/hooks/usePortal';
import { useProjects } from '@/hooks/useProjects';
import { sessionDisplayName } from '@/lib/beijingTime';

export function ProjectsPage() {
	const { isAdmin } = usePortal();
	const { projectId } = useParams();
	const navigate = useNavigate();
	const { data, refetch, isPending, isError } = useProjects();
	const { agents } = useAgents();
	const [editing, setEditing] = useState(false);
	const project = data?.projects.find((p) => p.id === projectId);
	const selected =
		project?.agent_id || data?.bindings.find((b) => b.project_id === projectId)?.agent_id || '';
	const available = agents.find((a) => a.id === selected);
	const sessions = data?.bindings.filter((b) => b.project_id === projectId) ?? [];
	return (
		<div className="flex h-full w-full gap-2 p-2">
			<main className="min-w-0 flex-1 overflow-auto rounded-[22px] bg-background p-6 md:p-10">
				<div className="max-w-4xl mx-auto space-y-6">
					{!projectId ? (
						<div className="flex flex-col items-center justify-center min-h-[65vh] text-center gap-4">
							<Folder className="size-10 text-muted-foreground" />
							<h1 className="text-2xl font-semibold">把文件和会话放进项目</h1>
							<p className="max-w-md text-sm leading-7 text-muted-foreground">
								从左侧打开项目，或点击“项目”旁的 ＋ 新建。
								<br />
								不需要项目时，直接使用普通对话。
							</p>
						</div>
					) : isPending ? (
						<p>正在加载项目…</p>
					) : isError ? (
						<button onClick={() => void refetch()}>加载失败，点击重试</button>
					) : !project ? (
						<p role="alert">项目不存在、已取消共享，或你已无访问权限。</p>
					) : (
						<>
							<header className="flex items-start justify-between gap-4">
								<div className="min-w-0">
									<div className="flex items-center gap-2 text-xs text-muted-foreground mb-3">
										{project.shared ? (
											<Users className="size-3.5" />
										) : (
											<LockKeyhole className="size-3.5" />
										)}
										{project.shared ? '共享文件 · 会话仅自己可见' : '私有项目'}
										{!project.is_owner && <span>· 来自 {project.owner}</span>}
									</div>
									<h1 className="text-2xl font-semibold break-words">
										{project.name}
									</h1>
									<p className="text-sm text-muted-foreground mt-3 whitespace-pre-wrap">
										{project.description}
									</p>
								</div>
								<div className="flex flex-wrap gap-2">
									{(project.is_owner || isAdmin) && (
										<ProjectTransfer projectId={project.id} />
									)}
									{project.is_owner && (
										<Button variant="outline" onClick={() => setEditing(true)}>
											<Settings2 className="size-4" />
											项目设置
										</Button>
									)}
								</div>
							</header>
							<div className="flex flex-wrap items-center gap-3 rounded-xl bg-muted/50 p-4">
								<span className="text-sm">
									<span className="text-muted-foreground">智能体：</span>
									<strong className="ml-1 text-base font-semibold text-foreground">
										{available?.data.name || '未指定'}
									</strong>
								</span>
							</div>
							<Tabs key={project.id} defaultValue="files" className="gap-5">
								<TabsList
									aria-label="项目内容"
									className="h-auto max-w-full flex-wrap"
								>
									<TabsTrigger value="files">
										<Files className="size-3.5" />
										项目文件
									</TabsTrigger>
									<TabsTrigger value="audit">
										<ListChecks className="size-3.5" />
										审计记录
									</TabsTrigger>
									<TabsTrigger value="sessions">
										<MessagesSquare className="size-3.5" />
										我的项目会话
									</TabsTrigger>
								</TabsList>
								<TabsContent value="files">
									<FileCatalogPanel
										key={project.id}
										scope="project"
										resource={project.id}
									/>
								</TabsContent>
								<TabsContent value="audit">
									<ProjectAudit projectId={project.id} />
								</TabsContent>
								<TabsContent value="sessions">
									<section className="space-y-3">
										<h2 className="font-medium text-sm">
											我的项目会话{' '}
											<span className="text-muted-foreground">
												{sessions.length}
											</span>
										</h2>
										<p className="text-xs text-muted-foreground">
											共享的是文件目录，不是聊天记录。其他用户看不到下面的会话。
										</p>
										{sessions.length === 0 && (
											<p className="rounded-xl border border-dashed p-6 text-sm text-muted-foreground">
												暂无项目会话。
											</p>
										)}
										{sessions.map((s) => (
											<div
												key={s.agent_id + s.session_id}
												className="flex items-center gap-2 rounded-xl border p-2"
											>
												<button
													className="min-w-0 flex-1 text-left rounded-lg p-2 hover:bg-accent text-sm"
													key={s.agent_id + s.session_id}
													onClick={() =>
														navigate(
															`/chat/${s.agent_id}/${s.session_id}`,
														)
													}
												>
													{sessionDisplayName(s.name, s.created_at) ||
														'未命名会话'}
												</button>
												<ProjectSessionMenu
													deleteOnly
													agentId={s.agent_id}
													sessionId={s.session_id}
													projectId={project.id}
													name={
														sessionDisplayName(s.name, s.created_at) ||
														'未命名会话'
													}
												/>
											</div>
										))}
									</section>
								</TabsContent>
							</Tabs>
							{editing && (
								<ProjectDialog
									key={project.id}
									project={project}
									onClose={() => setEditing(false)}
								/>
							)}
						</>
					)}
				</div>
			</main>
		</div>
	);
}
