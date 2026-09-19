import { Pencil } from 'lucide-react';
import { useState } from 'react';

import { client } from '@/api/client';
import { portalWrite } from '@/api/portal';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';

type Entry = {
	id: string;
	name: string;
	description: string;
	enabled: boolean;
	client: {
		is_stateful: boolean;
		mcp_config: {
			type: string;
			url?: string;
			command?: string;
			args?: string[];
			headers?: Record<string, string>;
			env?: Record<string, string>;
			cwd?: string;
		};
	};
};
const empty = {
	name: '',
	description: '',
	transport: 'http',
	url: '',
	command: '',
	cwd: '',
	enabled: true,
	stateful: true,
};
export function CustomMCPDialog({ onSaved, editId }: { onSaved: () => void; editId?: string }) {
	const [open, setOpen] = useState(false),
		[busy, setBusy] = useState(false);
	const [entries, setEntries] = useState<Entry[]>([]);
	const [id, setId] = useState(''),
		[form, setForm] = useState(empty);
	const [args, setArgs] = useState('[]'),
		[extras, setExtras] = useState('{}');
	const [message, setMessage] = useState('');
	async function load() {
		const rows = await client.get<Entry[]>('/portal/custom-mcps');
		setEntries(rows);
		return rows;
	}
	async function show() {
		setBusy(true);
		setMessage('');
		try {
			const rows = await load();
			const entry = editId ? rows.find((row) => row.id === editId) : undefined;
			if (editId && !entry) throw new Error('此 MCP 已不存在，请刷新列表');
			edit(entry);
			setOpen(true);
		} catch (e) {
			setMessage(e instanceof Error ? e.message : '加载配置失败');
		} finally {
			setBusy(false);
		}
	}
	function edit(entry?: Entry) {
		setId(entry?.id ?? '');
		setMessage('');
		const c = entry?.client.mcp_config;
		setForm(
			entry && c
				? {
						name: entry.name,
						description: entry.description,
						enabled: entry.enabled,
						stateful: entry.client.is_stateful,
						transport: c.type === 'stdio_mcp' ? 'stdio' : 'http',
						url: c.url ?? '',
						command: c.command ?? '',
						cwd: c.cwd ?? '',
					}
				: empty,
		);
		setArgs(JSON.stringify(c?.args ?? [], null, 2));
		setExtras(JSON.stringify(c?.headers ?? c?.env ?? {}, null, 2));
	}
	async function save() {
		setBusy(true);
		setMessage('');
		try {
			const values = JSON.parse(extras),
				parameters = JSON.parse(args);
			if (
				!values ||
				Array.isArray(values) ||
				typeof values !== 'object' ||
				Object.values(values).some((v) => typeof v !== 'string')
			)
				throw new Error('Headers / 环境变量必须是字符串键值 JSON 对象');
			if (!Array.isArray(parameters) || parameters.some((v) => typeof v !== 'string'))
				throw new Error('参数必须是 JSON 字符串数组');
			const result = await portalWrite(
				'/portal/custom-mcps' + (id ? '/' + id : ''),
				id ? 'PUT' : 'POST',
				{
					...form,
					cwd: form.cwd || null,
					args: parameters,
					headers: form.transport === 'http' ? values : {},
					env: form.transport === 'stdio' ? values : {},
				},
			);
			setId(result.id);
			await load();
			onSaved();
			setMessage('已保存到 MCP 资源库，可在管理后台分配权限。');
		} catch (e) {
			setMessage(e instanceof Error ? e.message : '保存失败');
		} finally {
			setBusy(false);
		}
	}
	async function test() {
		setBusy(true);
		setMessage('正在连接并读取工具列表…');
		try {
			const result = await portalWrite(`/portal/custom-mcps/${id}/test`, 'POST');
			setMessage(
				`连接成功，${result.tools.length} 个工具：${result.tools.join('、') || '无'}`,
			);
		} catch (e) {
			setMessage(e instanceof Error ? e.message : '测试失败');
		} finally {
			setBusy(false);
		}
	}
	return (
		<>
			<Button
				variant={editId ? 'ghost' : 'outline'}
				size={editId ? 'icon-sm' : 'default'}
				className={editId ? 'text-muted-foreground' : undefined}
				title={editId ? '编辑 MCP' : '自定义 MCP'}
				aria-label={editId ? '编辑 MCP' : '自定义 MCP'}
				disabled={busy}
				onClick={() => void show()}
			>
				{editId ? <Pencil /> : '自定义 MCP'}
			</Button>
			{!open && message && (
				<span role="alert" className="text-sm text-destructive">
					{message}
				</span>
			)}
			<Dialog
				open={open}
				onOpenChange={(next) => {
					if (busy) return;
					setOpen(next);
					if (!next) setMessage('');
				}}
			>
				<DialogContent
					showCloseButton={!busy}
					aria-describedby={undefined}
					className="bg-background shadow-xl p-6 sm:max-w-2xl max-h-[calc(100dvh-2rem)] overflow-y-auto block space-y-3"
				>
					<DialogTitle className="font-semibold text-lg pr-6">
						自定义 MCP · 添加 / 编辑
					</DialogTitle>
					<select
						aria-label="选择已有自定义 MCP"
						className="border rounded p-2 w-full"
						value={id}
						disabled={busy}
						onChange={(e) => edit(entries.find((r) => r.id === e.target.value))}
					>
						<option value="">＋ 新建 MCP</option>
						{entries.map((r) => (
							<option key={r.id} value={r.id}>
								{r.name}
							</option>
						))}
					</select>
					<label className="block text-sm">
						名称
						<Input
							value={form.name}
							disabled={busy || !!id}
							placeholder="my-mcp（字母、数字、下划线、连字符）"
							onChange={(e) => setForm({ ...form, name: e.target.value })}
						/>
					</label>
					<label className="block text-sm">
						描述
						<Input
							value={form.description}
							onChange={(e) => setForm({ ...form, description: e.target.value })}
						/>
					</label>
					<label className="block text-sm">
						连接方式
						<select
							className="border rounded p-2 w-full"
							value={form.transport}
							onChange={(e) => {
								setForm({ ...form, transport: e.target.value });
								setExtras('{}');
							}}
						>
							<option value="http">HTTP / SSE 服务地址</option>
							<option value="stdio">STDIO 本地程序</option>
						</select>
					</label>
					{form.transport === 'http' ? (
						<>
							<label className="block text-sm">
								MCP 地址
								<Input
									value={form.url}
									placeholder="https://example.com/mcp"
									onChange={(e) => setForm({ ...form, url: e.target.value })}
								/>
							</label>
							<p className="text-xs text-muted-foreground">
								使用完整服务端点；路径以 /sse 或 /messages/ 结尾时，SDK 按 SSE
								连接。
							</p>
							<label className="text-sm flex gap-2">
								<input
									type="checkbox"
									checked={form.stateful}
									onChange={(e) =>
										setForm({ ...form, stateful: e.target.checked })
									}
								/>
								保持有状态连接
							</label>
						</>
					) : (
						<>
							<label className="block text-sm">
								启动程序
								<Input
									value={form.command}
									placeholder="/absolute/path/to/python 或 npx"
									onChange={(e) => setForm({ ...form, command: e.target.value })}
								/>
							</label>
							<label className="block text-sm">
								参数（JSON 数组）
								<textarea
									className="border rounded w-full p-2 font-mono"
									value={args}
									onChange={(e) => setArgs(e.target.value)}
									placeholder={'["/path/server.py"]'}
								/>
							</label>
							<label className="block text-sm">
								虚拟机工作目录（可选）
								<Input
									value={form.cwd}
									placeholder="/workspace/projects/my-mcp"
									onChange={(e) => setForm({ ...form, cwd: e.target.value })}
								/>
							</label>
							<p className="text-xs text-amber-700">
								本地 MCP 按服务器账号权限运行，不是技能 Docker
								沙箱。仅配置可信程序；依赖需预先安装。命令和参数分开填写，不自动使用
								Shell。
							</p>
						</>
					)}
					<label className="block text-sm">
						{form.transport === 'http' ? '认证 Headers' : '环境变量'}（JSON
						对象，仅管理员可见）
						<textarea
							className="border rounded w-full p-2 font-mono"
							value={extras}
							onChange={(e) => setExtras(e.target.value)}
						/>
					</label>
					<label className="text-sm flex gap-2">
						<input
							type="checkbox"
							checked={form.enabled}
							onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
						/>
						启用
					</label>
					<p role="status" className="text-sm break-words">
						{message}
					</p>
					<p className="text-xs text-muted-foreground">
						保存不启动程序。测试连接会使用已保存配置连接服务/启动程序并读取工具清单，不调用业务工具。修改配置后请在下一轮对话或新会话使用。
					</p>
					<div className="flex justify-end gap-2">
						<Button
							variant="outline"
							disabled={busy}
							onClick={() => {
								setOpen(false);
								setMessage('');
							}}
						>
							关闭
						</Button>
						<Button
							variant="outline"
							disabled={busy || !id}
							onClick={() => void test()}
						>
							测试已保存连接
						</Button>
						<Button disabled={busy || !form.name} onClick={() => void save()}>
							{busy ? '处理中…' : '保存'}
						</Button>
					</div>
				</DialogContent>
			</Dialog>
		</>
	);
}
