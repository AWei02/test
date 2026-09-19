import { useEffect, useState } from 'react';
import { client } from '@/api/client';
import { Button } from '@/components/ui/button';
import { PermissionScopeSelect, permissionSummary, type Permissions } from './DocumentPermissions';

type History = { filename: string; actor: string; at: string; after: Permissions };
export function KnowledgePermissionSettings({ kbId }: { kbId: string }) {
    const [mode, setMode] = useState<'inherit' | 'private'>('inherit');
    const [history, setHistory] = useState<History[]>([]);
    const [busy, setBusy] = useState(true); const [message, setMessage] = useState('');
    useEffect(() => { client.get<{ access_mode: 'inherit' | 'private'; history: History[] }>(`/portal/knowledge-permissions/${kbId}`)
        .then(r => { setMode(r.access_mode); setHistory(r.history); }).catch(() => setMessage('权限设置加载失败，请重新打开页面'))
        .finally(() => setBusy(false)); }, [kbId]);
    const save = async () => {
        setBusy(true); setMessage('');
        try { await client.patch(`/portal/knowledge-permissions/${kbId}`, { access_mode: mode }); setMessage('默认规则已保存，仅影响后续上传'); }
        catch (e) { setMessage(e instanceof Error ? e.message : '保存失败'); } finally { setBusy(false); }
    };
    return <section className="mb-6 space-y-4 rounded-xl border p-4">
        <h3 className="text-sm font-medium">文件权限</h3>
        <label className="block space-y-2 text-sm"><span>新上传文件的默认范围</span><PermissionScopeSelect value={mode} onChange={next => setMode(next as typeof mode)} disabled={busy} allowCustom={false} className="max-w-sm" /></label>
        <p className="text-xs text-muted-foreground">现有文件的权限保持各自配置。在文档页可筛选继承、私有和自定义权限。</p>
        <Button size="sm" disabled={busy} onClick={save}>保存默认规则</Button>
        {message && <p role="status" className="text-sm">{message}</p>}
        <div className="space-y-2 border-t pt-4"><h4 className="text-sm font-medium">最近权限修改</h4>
            {!history.length && <p className="text-xs text-muted-foreground">暂无修改记录</p>}
            {history.map((row, i) => <div key={i} className="rounded-lg bg-muted/40 p-3 text-xs">
                <p>{row.filename} · {permissionSummary(row.after)}</p><p className="mt-1 text-muted-foreground">{row.actor} · {new Date(row.at).toLocaleString()}</p>
            </div>)}
        </div>
    </section>;
}
