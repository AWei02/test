import { useEffect, useState } from 'react';
import { client } from '@/api/client';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import type { KnowledgeDocumentView } from '@/api';
import { ParsingFields, type ParsingConfig } from './DocumentParsing';

export type Permissions = { access_mode: 'inherit' | 'private' | 'custom'; access_users: string[]; access_roles: string[] };
export const inheritedPermissions: Permissions = { access_mode: 'inherit', access_users: [], access_roles: [] };
export function permissionSummary(doc: Partial<Permissions>) {
    if (doc.access_mode === 'private') return '仅所有者';
    if (doc.access_mode === 'custom') return `${doc.access_users?.length ?? 0} 个用户 · ${doc.access_roles?.length ?? 0} 个角色`;
    return '继承知识库权限';
}

export function PermissionScopeSelect({ value, onChange, disabled = false, allowCustom = true, className = '' }: {
    value: Permissions['access_mode']; onChange: (value: Permissions['access_mode']) => void; disabled?: boolean; allowCustom?: boolean; className?: string;
}) {
    const options: { value: Permissions['access_mode']; label: string }[] = [
        { value: 'inherit', label: '继承知识库权限（不额外限制）' },
        { value: 'private', label: '仅所有者' },
        ...(allowCustom ? [{ value: 'custom' as const, label: '指定用户或角色' }] : []),
    ];
    return <Select value={value} onValueChange={next => onChange(next as Permissions['access_mode'])} disabled={disabled}>
        <SelectTrigger className={`h-10 w-full bg-background px-3 ${className}`}><SelectValue /></SelectTrigger>
        <SelectContent position="popper" align="start">{options.map(option => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}</SelectContent>
    </Select>;
}

export function PermissionFields({ value, onChange }: { value: Permissions; onChange: (value: Permissions) => void }) {
    const [options, setOptions] = useState<{ users: string[]; roles: string[] }>({ users: [], roles: [] });
    const [error, setError] = useState('');
    useEffect(() => { client.get<{ users: string[]; roles: string[] }>('/portal/document-permissions/options')
        .then(setOptions).catch(() => setError('无法加载用户和角色，请关闭后重试')); }, []);
    return <div className="space-y-4">
        <label className="block space-y-2 text-sm"><span>访问范围</span><PermissionScopeSelect value={value.access_mode} onChange={access_mode => onChange({ ...value, access_mode })} /></label>
        <p className="text-xs text-muted-foreground">文件权限仅收窄已有知识库授权。管理员和所有者始终可访问。</p>
        {value.access_mode === 'custom' && <div className="grid grid-cols-2 gap-3">
            {(['users', 'roles'] as const).map(kind => <fieldset key={kind} className="min-w-0 rounded-lg border p-3">
                <legend className="px-1 text-sm">{kind === 'users' ? '可读用户' : '可读角色'}</legend>
                <div className="max-h-40 space-y-2 overflow-y-auto">{options[kind].map(name => {
                    const field = kind === 'users' ? 'access_users' : 'access_roles';
                    return <label key={name} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={value[field].includes(name)}
                        onChange={e => onChange({ ...value, [field]: e.target.checked ? [...value[field], name] : value[field].filter(v => v !== name) })} />{name}</label>;
                })}</div>
            </fieldset>)}
        </div>}
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    </div>;
}

export function PermissionDialog({ document, files, kbId, onClose, onSaved, onUpload, defaultMode = 'inherit' }: {
    document?: KnowledgeDocumentView; files?: File[]; kbId: string; defaultMode?: 'inherit' | 'private';
    onClose: () => void; onSaved: () => void; onUpload?: (permissions: Permissions, parsing: ParsingConfig) => void;
}) {
    const [value, setValue] = useState<Permissions>({ access_mode: document?.access_mode ?? defaultMode,
        access_users: document?.access_users ?? [], access_roles: document?.access_roles ?? [] });
    const [saving, setSaving] = useState(false); const [error, setError] = useState('');
    const [parsing, setParsing] = useState<ParsingConfig>();
    useEffect(() => {if(!document) {let active = true; client.get<ParsingConfig>(`/portal/parsing/${kbId}`).then(v => {if(active) setParsing(v);}).catch(() => {if(active) setError('解析配置加载失败，请重新打开');}); return () => {active = false;};}}, [document, kbId]);
    const save = async () => {
        const body = value.access_mode === 'custom' ? value : { ...value, access_users: [], access_roles: [] };
        if (body.access_mode === 'custom' && !body.access_users.length && !body.access_roles.length) { setError('请至少选择一个用户或角色'); return; }
        setSaving(true); setError('');
        try {
            if (document) await client.patch(`/portal/document-permissions/${kbId}/${document.id}`, body);
            else if (parsing) onUpload?.(body, parsing);
            else throw new Error('请等待解析配置加载完成');
            onSaved(); onClose();
        } catch (e) { setError(e instanceof Error ? e.message : '保存失败，请重试'); } finally { setSaving(false); }
    };
    return <Dialog open onOpenChange={open => { if (!open && !saving) onClose(); }}><DialogContent className="sm:max-w-lg max-h-[90vh] overflow-y-auto">
        <DialogHeader><DialogTitle>{document ? '编辑文件权限' : '上传文件'}</DialogTitle>
            <DialogDescription>{document?.filename ?? `已选择 ${files?.length ?? 0} 个文件，以下权限应用于本次上传。`}</DialogDescription></DialogHeader>
        {files && <div className="max-h-24 overflow-y-auto text-sm text-muted-foreground">{files.map((file, i) => <div key={i} className="truncate">{file.name}</div>)}</div>}
        <PermissionFields value={value} onChange={setValue} />
        {!document && parsing && <ParsingFields value={parsing} onChange={setParsing} disabled={saving} />}
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <DialogFooter><Button variant="outline" disabled={saving} onClick={onClose}>取消</Button><Button disabled={saving || (!document && !parsing)} onClick={save}>{saving ? '保存中…' : document ? '保存权限' : '开始上传'}</Button></DialogFooter>
    </DialogContent></Dialog>;
}
