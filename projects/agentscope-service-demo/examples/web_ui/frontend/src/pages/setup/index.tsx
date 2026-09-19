import { ArrowRight, BotMessageSquare, Loader2 } from 'lucide-react';
import { useState } from 'react';

import { serviceUrl } from '@/api/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { queryClient } from '@/lib/query-client';

export function SetupPage({ onComplete }: { onComplete: () => void; className?: string }) {
	const [loginKey, setLoginKey] = useState('');
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState('');
	return (
		<div className="min-h-screen bg-slate-50 flex items-center justify-center p-6">
			<form
				className="w-full max-w-md rounded-3xl border bg-white p-9 shadow-sm"
				onSubmit={async (e) => {
					e.preventDefault();
					setBusy(true);
					setError('');
					try {
						const response = await fetch(serviceUrl('/portal/me'), {
							headers: { Authorization: `Bearer ${loginKey.trim()}` },
						});
						const result = await response.json();
						if (!response.ok) throw new Error(result.detail ?? '连接失败');
						queryClient.clear();
						localStorage.setItem('username', result.username);
						localStorage.setItem('login_key', loginKey.trim());
						localStorage.setItem('server_url', window.location.origin);
						localStorage.removeItem('chat_last_agent');
						localStorage.removeItem('chat_last_session');
						onComplete();
					} catch (err) {
						setError(err instanceof Error ? err.message : '连接失败');
					} finally {
						setBusy(false);
					}
				}}
			>
				<div className="mb-8 flex size-12 items-center justify-center rounded-2xl bg-slate-900 text-white">
					<BotMessageSquare />
				</div>
				<h1 className="text-2xl font-semibold">欢迎使用智能体工作台</h1>
				<p className="mt-3 mb-8 text-sm leading-6 text-slate-500">
					输入登录 Key；管理员也可输入管理员用户名进入工作台。
				</p>
				<label className="block text-sm font-medium mb-2" htmlFor="login-key">
					登录 Key / 管理员用户名
				</label>
				<Input
					id="login-key"
					type="password"
					autoComplete="current-password"
					value={loginKey}
					onChange={(e) => setLoginKey(e.target.value)}
					required
					autoFocus
					placeholder="请输入登录 Key 或管理员用户名"
					className="h-11"
				/>
				{error && (
					<p role="alert" className="mt-4 text-sm text-red-600">
						{error}
					</p>
				)}
				<Button className="mt-6 h-11 w-full" disabled={busy}>
					{busy ? <Loader2 className="animate-spin" /> : <ArrowRight />}进入工作台
				</Button>
			</form>
		</div>
	);
}
