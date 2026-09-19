import type { ContentBlock } from '@agentscope-ai/agentscope/message';
import mime from 'mime';

import { client, getAuthHeaders, serviceUrl } from '@/api/client';
import { createMessageId } from '@/lib/messageId';

export async function saveChatAttachment(
	file: File,
	agentId: string,
	sessionId: string,
	inputTypes: string[],
): Promise<ContentBlock[]> {
	if (file.size > 20 * 1024 * 1024) throw new Error('单文件最大 20MB');
	const mediaType = file.type || mime.getType(file.name) || 'application/octet-stream';
	const blocks: ContentBlock[] = [];
	// Images are the only binary payload forwarded directly to the model.
	// Documents stay on disk so the agent can choose an appropriate tool.
	if (
		mediaType.startsWith('image/') &&
		inputTypes.some((type) => type === 'image/*' || type === mediaType)
	) {
		const bytes = new Uint8Array(await file.arrayBuffer());
		let binary = '';
		for (let i = 0; i < bytes.length; i += 8192)
			binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
		blocks.push({
			id: createMessageId(),
			type: 'data',
			name: file.name,
			created_at: new Date().toISOString(),
			source: { type: 'base64', media_type: mediaType, data: btoa(binary) },
		});
	}
	const { project } = await client.get<{ project: { id: string; name: string } | null }>(
		`/portal/session-project/${encodeURIComponent(agentId)}/${encodeURIComponent(sessionId)}`,
	);
	const url = project
		? `/portal/projects/${encodeURIComponent(project.id)}/files`
		: `/portal/skill-files/${encodeURIComponent(agentId)}/${encodeURIComponent(sessionId)}`;
	const body = new FormData();
	body.append('file', file);
	const response = await fetch(serviceUrl(url), {
		method: 'POST',
		headers: { ...getAuthHeaders() },
		body,
	});
	const result = await response.json();
	if (!response.ok) throw new Error(result.detail || '附件保存失败');
	blocks.push({
		id: createMessageId(),
		type: 'text',
		created_at: new Date().toISOString(),
		text: `附件原文件已保存到${project ? '当前项目共享文件区' : '当前会话文件区'}：${JSON.stringify({ name: file.name, size: file.size, media_type: mediaType, skill_path: '/work/' + file.name })}。可用 ProjectFiles 列出文件、读写文本；二进制文档按任务选择已授权工具或 RunSkill 处理。/work 是技能容器内路径，不是宿主机路径。输出也应保存到同一文件区；只有工具确认成功才报告已保存。`,
	});
	window.dispatchEvent(
		new CustomEvent('session-files-changed', { detail: { agentId, sessionId } }),
	);
	return blocks;
}
