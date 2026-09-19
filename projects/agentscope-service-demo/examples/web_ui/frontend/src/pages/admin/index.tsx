import {
	ArrowUpRight,
	Bot,
	Check,
	Database,
	ListChecks,
	Plus,
	RefreshCw,
	Search,
	ShieldCheck,
	Users,
} from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';

import type { AgentView } from '@/api';
import { client } from '@/api/client';
import { portalWrite } from '@/api/portal';
import { BrandingSettings } from '@/components/BrandingSettings';
import { AgentDialog } from '@/components/dialog/AgentDialog';
import { DeleteDialog } from '@/components/dialog/DeleteDialog';
import { EditAgentDialog } from '@/components/dialog/EditAgentDialog';
import { ProjectAudit } from '@/components/ExecutionAudit';
import { RoleManager } from '@/components/RoleManager';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { UserLoginKey } from '@/components/UserLoginKey';
import { useAgents } from '@/hooks/useAgents';

type Resource = { id: string; name: string };
type User = { username: string; email: string; role: string; enabled: boolean; login_key?: string };
type Field = 'mcps' | 'skills' | 'knowledge' | 'credentials';
type Grant = Record<Field, string[]> & {
	id?: string;
	subject_type: 'user' | 'role';
	subject: string;
	agent_id: string;
};
type State = {
	users: User[];
	roles: string[];
	grants: Grant[];
	catalog: Record<Field | 'agents', Resource[]>;
};
const labels: Record<Field, string> = {
	mcps: 'MCP 服务',
	skills: '技能',
	knowledge: '知识库',
	credentials: '模型凭据',
};
const emptyGrant: Grant = {
	subject_type: 'user',
	subject: '',
	agent_id: '',
	mcps: [],
	skills: [],
	knowledge: [],
	credentials: [],
};
const inputClass = 'h-10 w-full rounded-lg border bg-white px-3 text-sm';

export function AdminPage() {
	const [state, setState] = useState<State>();
	const [tab, setTab] = useState(() =>
		new URLSearchParams(window.location.search).get('tab') === 'audit' ? 'audit' : 'users',
	);
	const [search, setSearch] = useState('');
	const [error, setError] = useState('');
	const [busy, setBusy] = useState(false);
	const [user, setUser] = useState<User>();
	const [grant, setGrant] = useState<Grant>();
	const [editingAgent, setEditingAgent] = useState<AgentView | null>(null);
	const [deletingAgent, setDeletingAgent] = useState<AgentView | null>(null);
	const { agents, refetch: refreshAgents, remove: removeAgent } = useAgents();
	async function refresh() {
		try {
			setState(await client.get<State>('/portal/admin'));
			setError('');
		} catch (e) {
			setError(e instanceof Error ? e.message : '加载失败');
		}
	}
	useEffect(() => {
		void refresh();
	}, []);
	async function save(path: string, method: string, body?: unknown) {
		setBusy(true);
		try {
			await portalWrite(path, method, body);
			await refresh();
			setUser(undefined);
			setGrant(undefined);
			toast.success('已保存');
		} catch (e) {
			toast.error(e instanceof Error ? e.message : '保存失败');
		} finally {
			setBusy(false);
		}
	}
	const tabs = [
		['users', '用户管理', Users],
		['agents', '智能体', Bot],
		['grants', '访问授权', ShieldCheck],
		['resources', '资源中心', Database],
		['audit', '全站审计', ListChecks],
	] as const;
	const counts = [
		state?.users.length ?? 0,
		state?.catalog.agents.length ?? 0,
		state?.grants.length ?? 0,
		state
			? state.catalog.mcps.length +
				state.catalog.skills.length +
				state.catalog.knowledge.length
			: 0,
	];
	return (
		<div className="h-full overflow-auto [scrollbar-gutter:stable] bg-slate-50 text-slate-900">
			<div className="mx-auto max-w-7xl px-6 py-8 md:px-10">
				<header className="flex flex-wrap items-start justify-between gap-4 mb-8">
					<div>
						<p className="text-xs font-semibold tracking-widest text-slate-400 mb-2">
							AGENTSCOPE · CONTROL CENTER
						</p>
						<h1 className="text-3xl font-semibold tracking-tight">管理工作台</h1>
						<p className="mt-2 text-sm text-slate-500">
							配置智能体，为每个人分配恰当的能力。
						</p>
					</div>
					<div className="flex gap-2">
						<Button variant="outline" onClick={() => void refresh()}>
							<RefreshCw className="size-4" />
							刷新
						</Button>
						<Button asChild>
							<Link to="/chat">
								进入聊天
								<ArrowUpRight className="size-4" />
							</Link>
						</Button>
					</div>
				</header>
				<BrandingSettings />
				<div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
					{tabs
						.filter(([id]) => id !== 'audit')
						.map(([id, title, Icon], i) => (
							<button
								key={id}
								onClick={() => setTab(id)}
								className="text-left rounded-2xl border bg-white p-5 hover:border-slate-400 transition-colors"
							>
								<div className="flex justify-between text-sm text-slate-500">
									{title}
									<Icon className="size-4" />
								</div>
								<div className="mt-4 text-3xl font-semibold">{counts[i]}</div>
							</button>
						))}
				</div>
				<div className="rounded-2xl border bg-white shadow-sm overflow-hidden">
					<nav className="flex flex-wrap border-b px-4">
						{tabs.map(([id, title, Icon]) => (
							<button
								key={id}
								onClick={() => {
									setTab(id);
									setSearch('');
								}}
								className={`flex items-center gap-2 px-4 py-4 text-sm border-b-2 ${tab === id ? 'border-slate-900 font-semibold' : 'border-transparent text-slate-500'}`}
							>
								<Icon className="size-4" />
								{title}
							</button>
						))}
					</nav>
					<div className="p-6">
						{error && (
							<p role="alert" className="text-red-600 mb-4">
								{error}
							</p>
						)}
						{!state ? (
							<p className="py-12 text-center text-slate-400">正在读取配置…</p>
						) : tab === 'audit' ? (
							<ProjectAudit />
						) : (
							<>
								<div className="flex flex-wrap gap-3 justify-between mb-6">
									<div className="flex items-center gap-2 w-64">
										<Search className="size-4 text-slate-400" />
										<Input
											aria-label="搜索"
											placeholder={
												tab === 'grants'
													? '搜索授权对象或编码'
													: '搜索名称或用户名'
											}
											value={search}
											onChange={(e) => setSearch(e.target.value)}
										/>
									</div>
									{tab === 'users' && (
										<div className="flex gap-2">
											<RoleManager roles={state.roles} refresh={refresh} />
											<Button
												onClick={() =>
													setUser({
														username: '',
														email: '',
														role:
															state.roles.find(
																(r) => r === '普通用户',
															) ??
															state.roles.find(
																(r) => r !== '管理员',
															) ??
															'',
														enabled: true,
													})
												}
											>
												<Plus />
												新增用户
											</Button>
										</div>
									)}
									{tab === 'agents' && (
										<AgentDialog
											onCreated={() => {
												void refresh();
												void refreshAgents();
											}}
										>
											<Button>
												<Plus />
												创建智能体
											</Button>
										</AgentDialog>
									)}
									{tab === 'grants' && (
										<Button
											onClick={() =>
												setGrant({
													...emptyGrant,
													subject: state.users[0]?.username ?? '',
													agent_id: state.catalog.agents[0]?.id ?? '',
												})
											}
										>
											<Plus />
											添加授权
										</Button>
									)}
								</div>
								{tab === 'users' && (
									<div className="overflow-x-auto">
										<table className="w-full text-left text-sm">
											<thead className="text-slate-400 border-b">
												<tr>
													{['用户名 / 邮箱', '角色', '状态', '操作'].map(
														(t) => (
															<th
																className="pb-3 font-normal"
																key={t}
															>
																{t}
															</th>
														),
													)}
												</tr>
											</thead>
											<tbody>
												{state.users
													.filter((u) =>
														`${u.username} ${u.email}`.includes(search),
													)
													.map((u) => (
														<tr
															className="border-b last:border-0"
															key={u.username}
														>
															<td className="py-4">
																<div className="font-medium">
																	{u.username}
																</div>
																<div className="text-xs text-slate-400 mt-1">
																	{u.email || '未填写邮箱'}
																</div>
															</td>
															<td>{u.role}</td>
															<td>
																<span
																	className={`rounded-full px-2 py-1 text-xs ${u.enabled ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}
																>
																	{u.enabled
																		? '已启用'
																		: '已停用'}
																</span>
															</td>
															<td>
																<Button
																	variant="ghost"
																	onClick={() =>
																		setUser({ ...u })
																	}
																>
																	编辑
																</Button>
																<Button
																	variant="ghost"
																	onClick={() => {
																		setTab('grants');
																		setGrant({
																			...emptyGrant,
																			subject: u.username,
																			agent_id:
																				state.catalog
																					.agents[0]
																					?.id ?? '',
																		});
																	}}
																>
																	分配权限
																</Button>
															</td>
														</tr>
													))}
											</tbody>
										</table>
									</div>
								)}
								{tab === 'agents' && (
									<div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
										{agents
											.filter((a) => a.data.name.includes(search))
											.map((a) => (
												<div className="rounded-xl border p-5" key={a.id}>
													<Bot className="size-5 mb-4 text-slate-500" />
													<h3 className="font-semibold">{a.data.name}</h3>
													<p className="line-clamp-2 text-sm text-slate-500 my-3">
														{a.data.system_prompt}
													</p>
													<Button
														variant="outline"
														onClick={() => setEditingAgent(a)}
													>
														编辑配置
													</Button>
													<Button
														variant="ghost"
														className="ml-2 text-destructive"
														onClick={() => setDeletingAgent(a)}
													>
														删除
													</Button>
												</div>
											))}
										{!agents.length && (
											<p className="text-slate-400">
												还没有智能体，点击“创建智能体”开始。
											</p>
										)}
									</div>
								)}
								{tab === 'grants' && (
									<div className="space-y-3">
										<p className="text-xs text-slate-500 mb-4">
											用户授权与所属角色授权合并生效。空的能力列表表示不授予该类能力。
										</p>
										{state.grants
											.filter(
												(g) =>
													g.subject.includes(search.trim()) ||
													(g.id ?? '')
														.toLowerCase()
														.includes(search.trim().toLowerCase()),
											)
											.map((g) => (
												<div
													key={g.id}
													className="rounded-xl border p-4 flex flex-wrap justify-between gap-4"
												>
													<div>
														<div className="font-medium">
															{g.subject}{' '}
															<span className="text-xs text-slate-400">
																{g.subject_type === 'role'
																	? '角色'
																	: '用户'}
															</span>{' '}
															<span className="text-slate-300 mx-2">
																→
															</span>
															{state.catalog.agents.find(
																(a) => a.id === g.agent_id,
															)?.name ?? '已删除的智能体'}
														</div>
														<p className="mt-1 text-xs text-slate-400 break-all select-text">
															授权编码：
															<span className="font-mono">
																{g.id}
															</span>
														</p>
														<div className="flex flex-wrap gap-2 mt-3">
															{(Object.keys(labels) as Field[]).map(
																(k) => (
																	<span
																		className="rounded-md bg-slate-50 px-2 py-1 text-xs text-slate-500"
																		key={k}
																	>
																		{labels[k]} {g[k].length}
																	</span>
																),
															)}
														</div>
													</div>
													<div className="flex gap-2">
														<Button
															variant="outline"
															onClick={() => setGrant({ ...g })}
														>
															编辑
														</Button>
														<Button
															variant="ghost"
															disabled={busy}
															onClick={() =>
																void save(
																	`/portal/grants/${g.id}`,
																	'DELETE',
																)
															}
														>
															撤销
														</Button>
													</div>
												</div>
											))}
										{!state.grants.length && (
											<p className="py-10 text-center text-slate-400">
												暂无授权。添加一条授权，让用户开始使用智能体。
											</p>
										)}
									</div>
								)}
								{tab === 'resources' && (
									<div className="grid md:grid-cols-2 gap-4">
										{(
											[
												['mcps', '/mcp'],
												['skills', '/skill'],
												['knowledge', '/knowledge'],
												['credentials', '/credential'],
											] as const
										).map(([k, url]) => (
											<div className="rounded-xl border p-5" key={k}>
												<div className="flex justify-between">
													<h3 className="font-semibold">{labels[k]}</h3>
													<Button variant="ghost" asChild>
														<Link to={url}>
															管理
															<ArrowUpRight />
														</Link>
													</Button>
												</div>
												<p className="mt-1 mb-4 text-sm text-slate-400">
													配置完成后，可在访问授权中勾选。
												</p>
												<div className="space-y-2">
													{state.catalog[k]
														.filter((r) => r.name.includes(search))
														.map((r) => (
															<div key={r.id} className="text-sm">
																{r.name}
															</div>
														))}
													{!state.catalog[k].length && (
														<span className="text-sm text-slate-400">
															暂无资源
														</span>
													)}
												</div>
											</div>
										))}
									</div>
								)}
							</>
						)}
					</div>
				</div>
			</div>
			{(user || grant) && state && (
				<div
					className="fixed inset-0 z-50 flex justify-end bg-black/30"
					onClick={() => {
						if (!busy) {
							setUser(undefined);
							setGrant(undefined);
						}
					}}
				>
					<section
						role="dialog"
						aria-modal="true"
						aria-label={user ? '编辑用户' : '配置授权'}
						className="w-full max-w-xl h-full bg-white shadow-xl overflow-y-auto p-7"
						onClick={(e) => e.stopPropagation()}
					>
						<h2 className="text-xl font-semibold mb-2">
							{user ? '用户资料' : '配置访问授权'}
						</h2>
						<p className="text-sm text-slate-500 mb-7">
							{user
								? '用户名用于标识用户，登录使用 Key；角色用于批量分配权限。'
								: '选择一个智能体，以及该用户或角色能够使用的资源。'}
						</p>
						<form
							className="space-y-5"
							onSubmit={(e) => {
								e.preventDefault();
								void save(
									user ? '/portal/users' : '/portal/grants',
									'PUT',
									user ?? grant,
								);
							}}
						>
							{user && (
								<>
									{(['username', 'email'] as const).map((k, i) => (
										<label key={k} className="block text-sm space-y-2">
											<span>{['用户名', '邮箱', '角色'][i]}</span>
											<Input
												className="h-10"
												required={k !== 'email'}
												type={k === 'email' ? 'email' : 'text'}
												value={user[k]}
												disabled={
													k === 'username' &&
													state.users.some(
														(u) => u.username === user.username,
													)
												}
												onChange={(e) =>
													setUser({ ...user, [k]: e.target.value })
												}
											/>
										</label>
									))}
									<label className="block text-sm space-y-2">
										<span>角色</span>
										<select
											required
											className={inputClass}
											value={user.role}
											onChange={(e) =>
												setUser({ ...user, role: e.target.value })
											}
										>
											<option value="" disabled>
												请选择角色
											</option>
											{state.roles.map((role) => (
												<option key={role} value={role}>
													{role}
												</option>
											))}
										</select>
									</label>
									<UserLoginKey
										key={user.username}
										username={user.username}
										loginKey={user.login_key}
										saved={state.users.some(
											(u) => u.username === user.username,
										)}
										disabled={busy}
										onChanged={(login_key) => {
											setUser({ ...user, login_key });
											void refresh();
										}}
									/>
									<label className="flex gap-2 items-center text-sm">
										<input
											type="checkbox"
											checked={user.enabled}
											onChange={(e) =>
												setUser({ ...user, enabled: e.target.checked })
											}
										/>
										启用用户
									</label>
								</>
							)}
							{grant && (
								<>
									<label className="block text-sm space-y-2">
										<span>授权对象</span>
										<select
											className={inputClass}
											value={grant.subject_type}
											onChange={(e) =>
												setGrant({
													...grant,
													subject_type: e.target.value as 'user' | 'role',
													subject: '',
												})
											}
										>
											<option value="user">单个用户</option>
											<option value="role">整个角色</option>
										</select>
									</label>
									<select
										required
										aria-label="选择用户或角色"
										className={inputClass}
										value={grant.subject}
										onChange={(e) =>
											setGrant({ ...grant, subject: e.target.value })
										}
									>
										<option value="">请选择</option>
										{(grant.subject_type === 'user'
											? state.users.map((u) => u.username)
											: state.roles
										).map((v) => (
											<option key={v}>{v}</option>
										))}
									</select>
									<label className="block text-sm space-y-2">
										<span>可用智能体</span>
										<select
											required
											className={inputClass}
											value={grant.agent_id}
											onChange={(e) =>
												setGrant({ ...grant, agent_id: e.target.value })
											}
										>
											<option value="">请选择智能体</option>
											{state.catalog.agents.map((a) => (
												<option value={a.id} key={a.id}>
													{a.name}
												</option>
											))}
										</select>
									</label>
									{(Object.keys(labels) as Field[]).map((k) => (
										<fieldset key={k} className="rounded-xl border p-4">
											<legend className="px-1 text-sm font-medium">
												{labels[k]}
											</legend>
											<div className="space-y-3">
												{state.catalog[k].map((r) => (
													<label
														className="flex gap-3 items-center text-sm"
														key={r.id}
													>
														<input
															type="checkbox"
															checked={grant[k].includes(r.id)}
															onChange={(e) =>
																setGrant({
																	...grant,
																	[k]: e.target.checked
																		? [...grant[k], r.id]
																		: grant[k].filter(
																				(id) => id !== r.id,
																			),
																})
															}
														/>
														{r.name}
													</label>
												))}
												{!state.catalog[k].length && (
													<p className="text-xs text-slate-400">
														请先到资源中心添加。
													</p>
												)}
											</div>
										</fieldset>
									))}
								</>
							)}
							<div className="flex justify-end gap-2 pt-4">
								<Button
									variant="outline"
									type="button"
									disabled={busy}
									onClick={() => {
										setUser(undefined);
										setGrant(undefined);
									}}
								>
									取消
								</Button>
								<Button disabled={busy}>
									<Check />
									{busy ? '保存中…' : '保存配置'}
								</Button>
							</div>
						</form>
					</section>
				</div>
			)}
			{deletingAgent && (
				<DeleteDialog
					open
					title={`确认删除智能体“${deletingAgent.data.name}”？`}
					description="删除前会检查访问授权引用；有引用时禁止删除。删除会级联清理该智能体关联的会话，且不可恢复，关联项目与频道也可能无法继续运行。"
					confirmLabel="确认删除"
					onOpenChange={(open) => {
						if (!open) setDeletingAgent(null);
					}}
					onConfirm={async () => {
						await removeAgent(deletingAgent.id);
						await refresh();
					}}
				/>
			)}
			{editingAgent && (
				<EditAgentDialog
					open
					onOpenChange={(open) => {
						if (!open) setEditingAgent(null);
					}}
					agent={editingAgent}
					onUpdated={() => {
						void refreshAgents();
						void refresh();
					}}
				/>
			)}
		</div>
	);
}
