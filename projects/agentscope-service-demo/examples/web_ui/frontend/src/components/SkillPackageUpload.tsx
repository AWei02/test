import { useState } from 'react';

import { serviceUrl, getAuthHeaders } from '@/api/client';
import { FileUploadButton } from '@/components/FileUploadButton';
import { Button } from '@/components/ui/button';

export function SkillPackageUpload({ onInstalled }: { onInstalled: () => void }) {
	const [open, setOpen] = useState(false);
	const [file, setFile] = useState<File>();
	const [busy, setBusy] = useState(false);
	const [message, setMessage] = useState('');
	async function upload() {
		if (!file) return;
		setBusy(true);
		setMessage('正在校验、安装依赖并构建独立运行环境，可能需要几分钟…');
		try {
			const body = new FormData();
			body.append('file', file);
			const response = await fetch(serviceUrl('/portal/skill-packages'), {
				method: 'POST',
				headers: { ...getAuthHeaders() },
				body,
			});
			const result = await response.json();
			if (!response.ok)
				throw new Error(typeof result.detail === 'string' ? result.detail : '上传失败');
			setMessage(`已安装 ${result.name}，可在管理后台授权给用户。`);
			onInstalled();
		} catch (e) {
			setMessage(e instanceof Error ? e.message : '上传失败');
		} finally {
			setBusy(false);
		}
	}
	return (
		<>
			<Button variant="outline" onClick={() => setOpen(true)}>
				上传完整技能包
			</Button>
			{open && (
				<div className="fixed inset-0 z-50 bg-black/30 flex items-center justify-center p-6">
					<section
						role="dialog"
						aria-modal="true"
						aria-label="上传完整技能包"
						className="bg-background rounded-xl p-6 max-w-lg w-full space-y-4 shadow-xl"
					>
						<h2 className="text-lg font-semibold">上传完整技能包</h2>
						<p className="text-sm text-muted-foreground">
							ZIP 最大 20MB，根目录或单一顶层目录包含
							SKILL.md（name、description）。完整保留 scripts、references、assets。
						</p>
						<p className="text-sm text-muted-foreground">
							支持 Python / Shell 执行入口。requirements.txt 自动安装 Python
							依赖；runtime.json 可声明
							apt_packages。依赖安装会执行包内构建代码，请仅上传你信任的技能。
						</p>
						<p className="text-sm text-muted-foreground">
							执行环境：Docker、无网络、512MB 内存、60
							秒超时；不挂载宿主机密钥或其他用户目录。
						</p>
						<FileUploadButton
							type="file"
							accept=".zip"
							aria-label="选择技能 ZIP"
							disabled={busy}
							onChange={(e) => {
								setFile(e.target.files?.[0]);
								setMessage('');
							}}
						/>
						<p role="status" className="text-sm break-words">
							{message}
						</p>
						<div className="flex justify-end gap-2">
							<Button
								variant="outline"
								disabled={busy}
								onClick={() => setOpen(false)}
							>
								关闭
							</Button>
							<Button disabled={busy || !file} onClick={() => void upload()}>
								{busy ? '正在安装…' : '上传并安装依赖'}
							</Button>
						</div>
					</section>
				</div>
			)}
		</>
	);
}
