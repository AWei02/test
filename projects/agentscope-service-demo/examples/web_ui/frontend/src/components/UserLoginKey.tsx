import { Copy, RefreshCw } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { portalWrite } from '@/api/portal';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

export function UserLoginKey({
	username,
	loginKey,
	saved,
	disabled,
	onChanged,
}: {
	username: string;
	loginKey?: string;
	saved: boolean;
	disabled: boolean;
	onChanged: (key: string) => void;
}) {
	const [busy, setBusy] = useState(false);
	async function generate() {
		if (
			loginKey &&
			!window.confirm(
				'重新生成后，旧 Key 将立即失效，使用旧 Key 的用户需要重新登录。确定继续？',
			)
		)
			return;
		setBusy(true);
		try {
			const result = await portalWrite<{ login_key: string }>(
				`/portal/users/${encodeURIComponent(username)}/key`,
				'POST',
			);
			if (localStorage.getItem('username') === username) {
				localStorage.setItem('login_key', result.login_key);
			}
			onChanged(result.login_key);
			toast.success('登录 Key 已生效，管理员可随时在此查看');
		} catch (error) {
			toast.error(error instanceof Error ? error.message : '生成失败');
		} finally {
			setBusy(false);
		}
	}
	async function copy() {
		if (!loginKey) return;
		try {
			if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(loginKey);
			else {
				const input = document.getElementById('user-login-key') as HTMLInputElement;
				input.focus();
				input.select();
				if (!document.execCommand('copy')) throw new Error('请选中 Key 后手动复制');
			}
			toast.success('Key 已复制');
		} catch {
			toast.error('请选中 Key 后手动复制');
		}
	}
	return (
		<div className="space-y-3 rounded-xl border bg-slate-50/60 p-4">
			<label htmlFor="user-login-key" className="text-sm font-medium">
				登录 Key
			</label>
			<Input
				id="user-login-key"
				className="font-mono text-xs bg-white"
				readOnly
				value={loginKey ?? ''}
				placeholder={saved ? '尚未生成登录 Key' : '请先保存用户资料，再生成 Key'}
				autoComplete="off"
			/>
			<div className="flex gap-2">
				<Button
					type="button"
					variant="outline"
					disabled={!saved || busy || disabled}
					onClick={() => void generate()}
				>
					<RefreshCw className={busy ? 'animate-spin' : ''} />
					{busy ? '生成中…' : loginKey ? '重新生成 Key' : '生成 Key'}
				</Button>
				<Button
					type="button"
					variant="outline"
					disabled={!loginKey}
					onClick={() => void copy()}
				>
					<Copy />
					复制
				</Button>
			</div>
			<p className="text-xs leading-5 text-slate-500">
				用于登录工作台，管理员可随时查看和复制。生成后立即保存并生效，重新生成会使旧 Key
				失效。
			</p>
		</div>
	);
}
