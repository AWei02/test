import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { getAuthHeaders } from '@/api/client';
import { client, getUserId, serviceUrl } from '@/api/client';
import AgentScope from '@/assets/images/agentscope_mono.svg?react';
import { FileUploadButton } from '@/components/FileUploadButton';
import { Button } from '@/components/ui/button';

export function useBranding() {
	return useQuery({
		queryKey: ['branding', getUserId()],
		queryFn: () => client.get<{ logo: string | null }>('/portal/branding'),
		retry: false,
		refetchInterval: 30000,
	});
}
export function BrandLogo() {
	const { data } = useBranding();
	return data?.logo ? (
		<img src={data.logo} alt="站点 Logo" className="size-full object-contain bg-transparent" />
	) : (
		<span className="size-full flex items-center justify-center rounded-full bg-primary">
			<AgentScope className="size-5 text-primary-foreground" />
		</span>
	);
}
export function BrandingSettings() {
	const cache = useQueryClient();
	const [busy, setBusy] = useState(false);
	const [message, setMessage] = useState('');
	async function update(file?: File) {
		setBusy(true);
		setMessage('');
		try {
			if (file && file.size > 2 * 1024 * 1024) throw new Error('图片最大 2MB');
			const body = new FormData();
			if (file) body.append('file', file);
			const res = await fetch(serviceUrl('/portal/branding/logo'), {
				method: file ? 'POST' : 'DELETE',
				headers: { ...getAuthHeaders() },
				...(file ? { body } : {}),
			});
			const data = await res.json();
			if (!res.ok) throw new Error(data.detail || '保存失败');
			await cache.invalidateQueries({ queryKey: ['branding'] });
			setMessage(file ? 'Logo 已更新' : '已恢复默认 Logo');
		} catch (e) {
			setMessage(String(e));
		} finally {
			setBusy(false);
		}
	}
	return (
		<section className="mb-6 rounded-2xl border bg-white p-5 space-y-3">
			<h2 className="text-sm font-semibold">站点 Logo</h2>
			<div className="flex flex-wrap items-center gap-4">
				<div className="size-10 flex items-center justify-center">
					<BrandLogo />
				</div>
				<FileUploadButton
					aria-label="上传站点 Logo"
					type="file"
					accept="image/png,image/jpeg,image/webp"
					disabled={busy}
					onChange={(e) => {
						const file = e.target.files?.[0];
						if (file) void update(file);
						e.target.value = '';
					}}
				/>
				<Button variant="outline" disabled={busy} onClick={() => void update()}>
					恢复默认 Logo
				</Button>
			</div>
			<p className="text-xs text-slate-500">
				支持 PNG、JPG、WebP，最大 2MB。点击侧栏 Logo 进入管理后台。
			</p>
			{message && (
				<p role="status" className="text-sm">
					{message}
				</p>
			)}
		</section>
	);
}
