import * as React from 'react';
import type { ScheduleRecord, UpdateScheduleRequest } from '@/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from '@/components/ui/dialog';
import { TimezoneSelect } from '@/components/select/TimezoneSelect';
import { PermissionModeSelect } from '@/components/select/PermissionModeSelect';

function initial(schedule: ScheduleRecord): UpdateScheduleRequest {
	return {
		name: schedule.data.name,
		description: schedule.data.description,
		cron_expression: schedule.data.cron_expression,
		timezone: schedule.data.timezone,
		enabled: schedule.data.enabled,
		stateful: schedule.data.stateful,
		permission_mode: schedule.data.permission_mode,
		ended_at: schedule.data.ended_at ? schedule.data.ended_at.slice(0, 16) : null,
	};
}
export function EditScheduleDialog({
	schedule,
	open,
	onOpenChange,
	onSave,
}: {
	schedule: ScheduleRecord | null;
	open: boolean;
	onOpenChange: (open: boolean) => void;
	onSave: (body: UpdateScheduleRequest) => Promise<unknown>;
}) {
	const [form, setForm] = React.useState<UpdateScheduleRequest>();
	const [busy, setBusy] = React.useState(false);
	const [error, setError] = React.useState('');
	React.useEffect(() => {
		if (schedule && open) {
			setForm(initial(schedule));
			setError('');
		}
	}, [schedule, open]);
	if (!schedule || !form) return null;
	const set = <K extends keyof UpdateScheduleRequest>(key: K, value: UpdateScheduleRequest[K]) =>
		setForm((v) => ({ ...v!, [key]: value }));
	async function save() {
		const body = form!;
		setBusy(true);
		setError('');
		try {
			await onSave(body);
			onOpenChange(false);
		} catch (e) {
			setError(e instanceof Error ? e.message : '保存失败');
		} finally {
			setBusy(false);
		}
	}
	return (
		<Dialog open={open} onOpenChange={(v) => !busy && onOpenChange(v)}>
			<DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-xl">
				<DialogHeader>
					<DialogTitle>编辑日程</DialogTitle>
					<DialogDescription>
						修改后会立即重新计算下一次执行时间。智能体和模型保持创建时的配置。
					</DialogDescription>
				</DialogHeader>
				<div className="space-y-4">
					<label className="block text-sm space-y-1">
						<span>名称</span>
						<Input
							value={form.name ?? ''}
							onChange={(e) => set('name', e.target.value)}
						/>
					</label>
					<label className="block text-sm space-y-1">
						<span>描述</span>
						<Textarea
							value={form.description ?? ''}
							onChange={(e) => set('description', e.target.value)}
						/>
					</label>
					<label className="block text-sm space-y-1">
						<span>Cron 表达式</span>
						<Input
							value={form.cron_expression ?? ''}
							onChange={(e) => set('cron_expression', e.target.value)}
						/>
						<span className="text-xs text-muted-foreground">
							例如每天 10:30：30 10 * * *
						</span>
					</label>
					<label className="block text-sm space-y-1">
						<span>时区</span>
						<TimezoneSelect
							size="default"
							value={form.timezone ?? 'Asia/Shanghai'}
							onChange={(v) => set('timezone', v)}
						/>
					</label>
					<label className="block text-sm space-y-1">
						<span>结束日期和时间</span>
						<Input
							type="datetime-local"
							value={form.ended_at ?? ''}
							onChange={(e) => set('ended_at', e.target.value || null)}
						/>
					</label>
					<label className="block text-sm space-y-1">
						<span>权限模式</span>
						<PermissionModeSelect
							size="default"
							value={form.permission_mode!}
							onChange={(v) => set('permission_mode', v)}
						/>
					</label>
					<label className="flex items-center justify-between text-sm">
						<span>启用日程</span>
						<Switch
							checked={!!form.enabled}
							onCheckedChange={(v) => set('enabled', v)}
						/>
					</label>
					<label className="flex items-center justify-between text-sm">
						<span>有状态（连续执行使用同一会话）</span>
						<Switch
							checked={!!form.stateful}
							onCheckedChange={(v) => set('stateful', v)}
						/>
					</label>
					{error && (
						<p role="alert" className="text-sm text-destructive">
							{error}
						</p>
					)}
				</div>
				<DialogFooter>
					<Button variant="outline" disabled={busy} onClick={() => onOpenChange(false)}>
						取消
					</Button>
					<Button
						disabled={busy || !form.name?.trim() || !form.cron_expression?.trim()}
						onClick={() => void save()}
					>
						{busy ? '保存中…' : '保存修改'}
					</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}
