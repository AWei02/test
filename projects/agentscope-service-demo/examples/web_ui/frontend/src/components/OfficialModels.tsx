import { useQuery, useQueryClient } from '@tanstack/react-query';
import { RefreshCw } from 'lucide-react';
import { useState } from 'react';

import { client, getBaseUrl, getUserId } from '@/api/client';
import { portalWrite } from '@/api/portal';
import { Button } from '@/components/ui/button';

type RefreshResult = { models: string[]; fetched_at: string };

export function OfficialModels({ credentialId }: { credentialId: string }) {
	return (
		<OfficialModelsStatus
			key={`${getBaseUrl()}:${getUserId()}:${credentialId}`}
			credentialId={credentialId}
		/>
	);
}

function OfficialModelsStatus({ credentialId }: { credentialId: string }) {
	const queryClient = useQueryClient();
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState('');
	const queryKey = ['official-model-status', getBaseUrl(), getUserId(), credentialId];
	const {
		data: result,
		isPending,
		error: loadError,
	} = useQuery({
		queryKey,
		queryFn: async (): Promise<RefreshResult | null> => {
			const saved = await client.get<{
				models: { name: string }[];
				fetched_at: string | null;
			}>(`/portal/models/${encodeURIComponent(credentialId)}`);
			return saved.fetched_at
				? { models: saved.models.map((model) => model.name), fetched_at: saved.fetched_at }
				: null;
		},
	});
	async function refresh() {
		setBusy(true);
		setError('');
		try {
			const saved = await portalWrite(
				`/portal/models/${encodeURIComponent(credentialId)}/refresh`,
				'POST',
			);
			await queryClient.cancelQueries({ queryKey });
			queryClient.setQueryData(queryKey, saved);
			await queryClient.invalidateQueries({ queryKey: ['available-models'] });
		} catch (e) {
			setError(e instanceof Error ? e.message : '查询失败，请稍后重试');
		} finally {
			setBusy(false);
		}
	}
	return (
		<section
			className="mx-[18px] mt-6 rounded-xl border p-4 space-y-3"
			aria-label="官方最新模型"
		>
			<div className="flex flex-wrap items-center justify-between gap-3">
				<h3 className="text-sm font-medium">
					官方最新模型{result ? ` · ${result.models.length}` : ''}
				</h3>
				<Button variant="outline" size="sm" disabled={busy} onClick={() => void refresh()}>
					<RefreshCw className={busy ? 'size-4 animate-spin' : 'size-4'} />
					{busy ? '正在查询官方…' : '刷新官方模型'}
				</Button>
			</div>
			<p className="text-xs text-muted-foreground">
				使用当前凭据查询 DeepSeek 官方 /models
				接口。刷新成功后同步到聊天模型下拉框；不修改已有会话当前选中的模型。
			</p>
			{error && (
				<p role="alert" className="text-sm text-red-600">
					{error}
					{result ? '；以下保留上次成功结果，尚未更新。' : ''}
				</p>
			)}
			{loadError && !error && (
				<p role="alert" className="text-sm text-red-600">
					读取上次刷新记录失败，请重新进入页面或点击刷新。
					{result ? '以下保留已读取的结果。' : ''}
				</p>
			)}
			<div aria-live="polite">
				{result ? (
					<>
						<p className="text-xs text-muted-foreground mb-2">
							已刷新 · 上次成功刷新：
							{new Date(result.fetched_at).toLocaleString('zh-CN', {
								timeZone: 'Asia/Shanghai',
								hour12: false,
							})}
							（北京时间）
						</p>
						{result.models.length ? (
							<ul className="space-y-1">
								{result.models.map((id) => (
									<li
										key={id}
										className="font-mono text-sm rounded bg-muted px-3 py-2"
									>
										{id}
									</li>
								))}
							</ul>
						) : (
							<p className="text-sm">官方返回的模型列表为空。</p>
						)}
					</>
				) : (
					<p className="text-sm text-muted-foreground">
						{isPending
							? '正在读取上次刷新记录…'
							: loadError
								? '暂时无法确认上次刷新状态。'
								: '尚未刷新，点击刷新获取当前官方返回的模型 ID。'}
					</p>
				)}
			</div>
			<p className="text-xs text-muted-foreground">
				下方为项目内置模型配置，不会自动同步。官方接口未返回上下文、视觉能力及价格，请以{' '}
				<a
					className="underline"
					href="https://api-docs.deepseek.com/quick_start/pricing/"
					target="_blank"
					rel="noreferrer"
				>
					官方说明
				</a>{' '}
				为准。
			</p>
		</section>
	);
}
