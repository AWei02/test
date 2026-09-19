import { useEffect, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';

import { client } from '@/api/client';
import { FileCatalogPanel } from '@/components/FileCatalogPanel';
import { Button } from '@/components/ui/button';
import {
	Dialog,
	DialogContent,
	DialogTrigger,
	DialogTitle,
	DialogDescription,
} from '@/components/ui/dialog';

export function SkillFiles({
	agentId,
	sessionId,
	sessionName,
	actions,
}: {
	agentId: string;
	sessionId: string;
	sessionName?: string;
	actions?: ReactNode;
}) {
	const [project, setProject] = useState<{ id: string; name: string } | null | undefined>();
	const [error, setError] = useState('');
	useEffect(() => {
		let active = true;
		setProject(undefined);
		setError('');
		client
			.get<{ project: { id: string; name: string } | null }>(
				`/portal/session-project/${agentId}/${sessionId}`,
			)
			.then((result) => {
				if (active) setProject(result.project);
			})
			.catch(() => {
				if (active) setError('文件区加载失败，请刷新页面重试');
			});
		return () => {
			active = false;
		};
	}, [agentId, sessionId]);
	if (project === undefined)
		return error ? (
			<p role="alert" className="text-sm text-destructive">
				{error}
			</p>
		) : null;
	return (
		<div className="flex min-w-0 flex-1 flex-wrap items-center justify-between gap-3 text-sm">
			{project ? (
				<Link className="truncate font-medium underline" to={'/projects/' + project.id}>
					项目：{project.name}
				</Link>
			) : (
				<span className="min-w-0 flex-1 truncate font-medium" title={sessionName}>
					{sessionName || '新会话'}
				</span>
			)}
			<div className="ml-auto flex shrink-0 items-center gap-2">
				{actions}
				<Dialog>
					<DialogTrigger asChild>
						<Button variant="outline" size="sm">
							{project ? '项目文件' : '会话文件'}
						</Button>
					</DialogTrigger>
					<DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-4xl">
						<DialogTitle>{project?.name || sessionName || '会话文件'}</DialogTitle>
						<DialogDescription>
							{project
								? '文件在项目内共享，聊天记录仍各自独立。'
								: '本次会话的文件，统一保存上传原件与生成成果。'}
						</DialogDescription>
						<FileCatalogPanel
							key={project?.id || sessionId}
							scope={project ? 'project' : 'session'}
							resource={project?.id || sessionId}
							agentId={project ? undefined : agentId}
						/>
					</DialogContent>
				</Dialog>
			</div>
		</div>
	);
}
