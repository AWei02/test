import type { ReactNode } from 'react';
import { useState, useRef, useLayoutEffect } from 'react';
import { Eye, Layers, RotateCcw, X, Loader2, Plus, Pencil, Trash2, Undo2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';

export type ChunkingConfig = {
    mode: 'general' | 'parent_child'; separator: string; max_length: number; overlap: number;
    normalize_whitespace: boolean; remove_urls_emails: boolean;
    parent_mode: 'paragraph' | 'full'; parent_separator: string; parent_max_length: number;
    child_separator: string; child_max_length: number;
};
export const defaultChunking: ChunkingConfig = {
    mode: 'general', separator: '\\n', max_length: 1024, overlap: 50,
    normalize_whitespace: true, remove_urls_emails: false,
    parent_mode: 'paragraph', parent_separator: '\\n\\n', parent_max_length: 2048,
    child_separator: '\\n', child_max_length: 512,
};
export type ChunkDraft = {chunks: {chunk_index: number; content: {text?: string}; metadata?: {heading_path?: string[]; parent_index?: number; parent_text?: string; draft_change?: 'added' | 'modified' | 'deleted'}}[]; total: number; active_total?: number; version: string; config?: ChunkingConfig | null};
export type DraftEdit = {version: string; action: 'edit' | 'insert' | 'delete' | 'restore'; chunk_index: number; text: string};
export function configKey(value?: ChunkingConfig | null) {
    return value ? JSON.stringify({...defaultChunking, ...value}) : '';
}
export function chunkingError(c: ChunkingConfig) {
    const sizes = c.mode === 'general' ? [c.max_length] : c.parent_mode === 'full' ? [c.child_max_length] : [c.parent_max_length, c.child_max_length];
    if (sizes.some(n => !Number.isInteger(n) || n < 50 || n > 16000)) return '分段长度须为 50–16000 之间的整数。';
    if (c.mode === 'general' && (!Number.isInteger(c.overlap) || c.overlap < 0 || c.overlap > 8000 || c.overlap >= c.max_length)) return '重叠长度须为非负整数，最多 8000，且小于最大长度。';
    if (c.mode === 'parent_child' && c.parent_mode === 'paragraph' && c.child_max_length > c.parent_max_length) return '子块最大长度不能大于父块最大长度。';
    return '';
}
const inputClass = 'w-full min-w-0 rounded-lg border bg-muted/40 px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

function TextField({label, value, onChange}: {label: string; value: string; onChange: (s: string) => void}) {
    return <label className="block min-w-0 space-y-2 text-sm"><span>{label}</span><input className={inputClass} maxLength={50} value={value} onChange={e => onChange(e.target.value)} /></label>;
}
function NumberField({label, value, onChange, min = 50, max = 16000}: {label: string; value: number; onChange: (n: number) => void; min?: number; max?: number}) {
    return <label className="block min-w-0 space-y-2 text-sm"><span>{label}</span><div className="relative"><input className={inputClass + ' pr-12'} type="number" step={1} min={min} max={max} value={Number.isNaN(value) ? '' : value} onChange={e => onChange(e.target.value === '' ? NaN : Number(e.target.value))} /><span className="pointer-events-none absolute right-6 top-2.5 text-xs text-muted-foreground">字符</span></div></label>;
}

type Props = {
    config: ChunkingConfig; onChange: (v: ChunkingConfig) => void;
    before: ReactNode; after: ReactNode; available: boolean; editable: boolean; busy: boolean;
    previewOpen: boolean; onClose: () => void; onOpen: () => void; onPreview: () => void;
    draft?: ChunkDraft; pending: boolean; changed: boolean; page: number; onPage: (p: number) => void;
    canEmbed: boolean; onEmbed: () => void; error?: string;
    canEditDraft: boolean; onEditDraft: (change: DraftEdit) => Promise<boolean>;
    canReset?: boolean; onReset?: () => void;
};
export function ChunkingWorkbench(p: Props) {
    const [editor,setEditor] = useState<DraftEdit>();
    const [saving,setSaving] = useState(false);
    const scrollRef = useRef<HTMLDivElement>(null);
    const savedPosition = useRef<{index:number; offset:number; top:number; version?:string} | null>(null);
    const rememberPosition = (index: number, inserting = false) => {
        const container = scrollRef.current;
        if(!container) return;
        const anchor = container.querySelector<HTMLElement>(inserting ? `[data-insert-after="${index}"]` : `[data-chunk-index="${index}"]`);
        savedPosition.current = {index:inserting ? index+1 : index, offset:anchor ? anchor.getBoundingClientRect().top-container.getBoundingClientRect().top : 0, top:container.scrollTop, version:p.draft?.version};
    };
    useLayoutEffect(() => {
        const position = savedPosition.current, container = scrollRef.current;
        if(!position || !container || p.pending || p.busy || saving || editor) return;
        const anchor = container.querySelector<HTMLElement>(`[data-chunk-index="${position.index}"]`);
        if(position.version !== p.draft?.version && anchor) {
            container.scrollTop += anchor.getBoundingClientRect().top-container.getBoundingClientRect().top-position.offset;
        } else container.scrollTop = position.top;
        savedPosition.current = null;
    }, [p.draft, p.pending, p.busy, saving, editor]);
    const c = p.config, validation = chunkingError(c);
    const set = (v: Partial<ChunkingConfig>) => p.onChange({...c, ...v});
    const canEdit = p.editable && p.canEditDraft && !p.changed && !p.busy && !p.pending;
    const startEdit = (action: DraftEdit['action'], index: number, text = '') => {
        rememberPosition(index, action === 'insert');
        if(p.draft) setEditor({action,chunk_index:index,text,version:p.draft.version});
    };
    const editorView = <Dialog open={!!editor} onOpenChange={open => {if(!open && !saving) setEditor(undefined);}}>
      <DialogContent className="flex h-[80dvh] max-h-[900px] min-h-0 w-[calc(100vw-2rem)] flex-col overflow-hidden sm:max-w-5xl" showCloseButton={!saving} onCloseAutoFocus={e => {e.preventDefault(); scrollRef.current?.focus({preventScroll:true});}} onInteractOutside={e => e.preventDefault()} onEscapeKeyDown={e => {if(saving) e.preventDefault();}} data-testid="chunk-editor">
        <DialogHeader className="shrink-0 pr-8"><DialogTitle>{editor?.action === 'insert' ? '插入新块' : `编辑分片 ${(editor?.chunk_index ?? 0)+1}`}</DialogTitle><DialogDescription>修改分片草稿内容，保存后仍需确认才能执行向量化。</DialogDescription></DialogHeader>
        <textarea aria-label="分片内容" className="min-h-0 w-full flex-1 resize-none rounded-lg border bg-background p-4 font-mono text-sm leading-relaxed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" value={editor?.text ?? ''} onChange={e => setEditor(v => v ? {...v,text:e.target.value} : v)} disabled={saving} />
        {p.error && <p role="alert" className="shrink-0 text-sm text-destructive">{p.error}</p>}
        <p className="text-xs text-muted-foreground">{[...(editor?.text ?? '')].length} / 16000 字符 · 保存后不自动重切或向量化。父子模式会同步重组所属父块。</p>
        <div className="flex shrink-0 justify-end gap-2"><Button size="sm" variant="outline" disabled={saving} onClick={() => setEditor(undefined)}>取消编辑</Button><Button size="sm" disabled={!canEdit || saving || !editor?.text.trim() || [...editor.text].length>16000} onClick={async () => {if(!editor) return;setSaving(true);try {if(await p.onEditDraft(editor)) setEditor(undefined);} finally {setSaving(false);}}}>{saving ? '保存中…' : '保存块'}</Button></div>
      </DialogContent>
    </Dialog>;
    const insertion = (index: number) => p.editable && p.canEditDraft ? <div data-insert-after={index} className="flex justify-center"><Button disabled={!canEdit || !!editor || saving} variant="ghost" size="icon-sm" className="border border-dashed text-muted-foreground" title={index<0 ? '在开头添加块' : `在分片 ${index+1} 后添加块`} aria-label={index<0 ? '在开头添加块' : `在分片 ${index+1} 后添加块`} onClick={() => startEdit('insert',index)}><Plus className="size-4" /></Button></div> : null;
    const actions = (index: number, text: string) => p.editable && p.canEditDraft && <fieldset disabled={!canEdit || !!editor || saving} className="flex shrink-0 items-center gap-1">
        <Button size="icon-sm" variant="ghost" title="编辑分片" aria-label={`编辑分片 ${index+1}`} onClick={() => startEdit('edit',index,text)}><Pencil className="size-4" /></Button>
        <Button size="icon-sm" variant="ghost" className="text-red-600 hover:bg-red-50 hover:text-red-700" title={(p.draft?.active_total ?? p.draft?.total) === 1 ? '至少保留一个分片' : '删除分片'} aria-label={`删除分片 ${index+1}`} disabled={(p.draft?.active_total ?? p.draft?.total) === 1 || saving} onClick={async () => {
            if(!p.draft) return;
            const added = p.draft.chunks.find(chunk => chunk.chunk_index === index)?.metadata?.draft_change === 'added';
            if(!added && !window.confirm(`确定将分片 ${index+1} 标记删除吗？草稿中保留红色删除标记，确认向量化时才从新索引排除。`)) return;
            rememberPosition(index);
            setSaving(true);
            try {await p.onEditDraft({version:p.draft.version,action:'delete',chunk_index:index,text:''});} finally {setSaving(false);}
        }}><Trash2 className="size-4" /></Button>
    </fieldset>;
    const restore = (index: number) => p.editable && p.canEditDraft && <Button size="icon-sm" variant="ghost" className="text-red-600 hover:text-red-700" title="撤回删除" aria-label={`撤回删除分片 ${index+1}`} disabled={!canEdit || !!editor || saving} onClick={async () => {
        if(!p.draft) return;
        rememberPosition(index);
        setSaving(true);
        try {await p.onEditDraft({version:p.draft.version,action:'restore',chunk_index:index,text:''});} finally {setSaving(false);}
    }}><Undo2 className="size-4" /></Button>;
    return <><div className="flex h-full min-h-0 flex-col gap-4 overflow-hidden lg:grid lg:grid-cols-2" data-testid="chunking-workbench">
        <div className={'min-h-0 min-w-0 flex-1 space-y-4 overflow-y-auto pl-1 pr-2 pb-4 ' + (p.previewOpen ? 'hidden lg:block' : '')} data-testid="chunking-settings">
            {p.before}
            {p.available && <section className="space-y-3">
                <div><h3 className="font-medium">分段设置</h3><p className="mt-1 text-xs text-muted-foreground">仅应用于当前文件，长度单位为字符（不是 Token）。修改后需重新预览。</p></div>
                <fieldset disabled={!p.editable || p.busy || !!editor} className="space-y-3 disabled:opacity-70">
                    <div className="grid grid-cols-2 gap-3" role="group" aria-label="分段模式">
                        {(['general','parent_child'] as const).map(mode => <button key={mode} type="button" aria-pressed={c.mode === mode} onClick={() => set({mode})} className={'flex min-w-0 items-start gap-2 rounded-xl border p-3 text-left transition-colors hover:bg-muted/50 ' + (c.mode === mode ? 'border-primary bg-primary/5 ring-1 ring-inset ring-primary' : '')}>
                            <Layers className="mt-0.5 size-4 shrink-0" /><span><span className="block text-sm font-medium">{mode === 'general' ? '通用' : '父子分段'}</span><span className="mt-1 block text-xs text-muted-foreground">{mode === 'general' ? '检索与返回使用相同分片' : '子块用于检索，父块提供上下文'}</span></span>
                        </button>)}
                    </div>
                    <div className="space-y-5 rounded-xl border p-4">
                        {c.mode === 'general' ? <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
                            <TextField label="分段标识符" value={c.separator} onChange={separator => set({separator})} />
                            <NumberField label="分段最大长度" value={c.max_length} onChange={max_length => set({max_length})} />
                            <NumberField label="分段重叠长度" value={c.overlap} min={0} max={Math.min(8000,c.max_length-1)} onChange={overlap => set({overlap})} />
                        </div> : <>
                            <div className="space-y-3"><h4 className="text-sm font-medium">父块用作上下文</h4>
                                <div className="flex gap-4 text-sm"><label className="flex items-center gap-2"><input type="radio" name="parent-mode" checked={c.parent_mode === 'paragraph'} onChange={() => set({parent_mode:'paragraph'})} />段落</label><label className="flex items-center gap-2"><input type="radio" name="parent-mode" checked={c.parent_mode === 'full'} onChange={() => set({parent_mode:'full'})} />全文</label></div>
                                {c.parent_mode === 'paragraph' ? <div className="grid grid-cols-1 gap-4 xl:grid-cols-2"><TextField label="父块分段标识符" value={c.parent_separator} onChange={parent_separator => set({parent_separator})} /><NumberField label="父块最大长度" value={c.parent_max_length} onChange={parent_max_length => set({parent_max_length})} /></div> : <p className="text-xs text-muted-foreground">整个文件作为父块，最多 40000 字符。超限会提示改用段落模式，不会截断内容。</p>}
                            </div>
                            <div className="space-y-3 border-t pt-4"><h4 className="text-sm font-medium">子块用于检索</h4><div className="grid grid-cols-1 gap-4 xl:grid-cols-2"><TextField label="子块分段标识符" value={c.child_separator} onChange={child_separator => set({child_separator})} /><NumberField label="子块最大长度" value={c.child_max_length} onChange={child_max_length => set({child_max_length})} /></div></div>
                        </>}
                        <p className="text-xs leading-relaxed text-muted-foreground">先按标识符分段，短段独立保留，不合并；仅超长段落按最大长度继续拆分。通用模式的重叠只用于同一超长段落内部，不跨段落。支持 \n 换行、\n\n 空行和自定义文本；留空按长度切分。保留 Markdown 标题边界。</p>
                        <div className="space-y-3 border-t pt-4 text-sm"><h4 className="font-medium">文本预处理规则</h4>
                            <label className="flex items-start gap-2"><input className="mt-0.5" type="checkbox" checked={c.normalize_whitespace} onChange={e => set({normalize_whitespace:e.target.checked})} />合并连续空格、制表符和多余空行（保留段落换行）</label>
                            <label className="flex items-start gap-2"><input className="mt-0.5" type="checkbox" checked={c.remove_urls_emails} onChange={e => set({remove_urls_emails:e.target.checked})} />删除 URL 和电子邮件地址</label>
                        </div>
                        {validation && <p role="alert" className="text-sm text-destructive">{validation}</p>}
                        <div className="flex flex-wrap gap-2"><Button type="button" variant="outline" disabled={!!validation} onClick={p.onPreview}><Eye className="size-4" />预览分片</Button><Button type="button" variant="ghost" onClick={() => p.onChange({...defaultChunking})}><RotateCcw className="size-4" />重置</Button></div>
                    </div>
                </fieldset>
                <Button className="lg:hidden" variant="ghost" onClick={p.onOpen}>查看分片预览{p.draft ? ` · ${p.draft.total} 个` : ''}</Button>
                {p.changed && p.draft && <p className="text-xs text-amber-700">设置与已有草稿不一致，请重新预览后再确认入库。</p>}
                <p className="text-xs text-muted-foreground">预览只生成并保存分片草稿，不会调用向量模型，也不会重新调用 MinerU。</p>
            </section>}
            {p.error && <p className="text-sm text-destructive" role="alert">{p.error}</p>}
            {p.after}
        </div>
        <aside aria-label="分片预览" className={'min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-xl border bg-background lg:absolute lg:top-3 lg:right-[18px] lg:bottom-6 lg:w-[calc(50%-26px)] ' + (p.previewOpen ? 'flex' : 'hidden lg:flex')} data-testid="chunking-preview">
            <div className="flex shrink-0 items-center justify-between border-b p-4"><div><h3 className="text-sm font-medium">分片预览</h3><p className="mt-1 text-xs text-muted-foreground">{p.draft ? `共 ${p.draft.total} 个${p.draft.config?.mode === 'parent_child' ? '子块' : '分片'}` : '生成后在这里检查分片内容'}</p><p className="mt-1 text-xs"><span className="text-blue-600">蓝色：已修改</span> · <span className="text-green-600">绿色：新增</span></p></div><div className="flex gap-2">{p.canReset && <Button variant="outline" size="sm" disabled={!!editor || p.busy || p.pending} onClick={p.onReset} title="恢复已向量化的分片"><RotateCcw className="size-4" />重置</Button>}<Button className="lg:hidden" aria-label="返回分段设置" variant="ghost" size="sm" disabled={!!editor} onClick={p.onClose}><X className="size-4" />设置</Button></div></div>
            <div ref={scrollRef} tabIndex={-1} className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4 outline-none" aria-busy={p.pending} data-testid="chunk-preview-scroll">
                {p.error && <p className="text-sm text-destructive" role="alert">{p.error}</p>}
                {p.pending && !p.draft ? <p className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" />正在生成或加载分片…</p> : !p.draft ? <p className="text-sm text-muted-foreground">点击左侧“预览分片”，检查结果后再向量化。</p> : <>
                    {p.changed && <p className="rounded-lg bg-amber-50 p-3 text-xs text-amber-800">这是旧参数生成的草稿，请重新预览。此时不能确认入库。</p>}
                    {insertion((p.draft.chunks[0]?.chunk_index ?? 0)-1)}
                    {p.draft.chunks.map(chunk => <div key={chunk.chunk_index} data-chunk-index={chunk.chunk_index} className="space-y-3"><article className={'space-y-2 rounded-lg border p-3 ' + (chunk.metadata?.draft_change === 'deleted' ? 'border-red-300 bg-red-50 dark:bg-red-950/30' : chunk.metadata?.draft_change === 'added' ? 'border-green-300 bg-green-50 dark:bg-green-950/30' : chunk.metadata?.draft_change === 'modified' ? 'border-blue-300 bg-blue-50 dark:bg-blue-950/30' : '')}><div className="flex items-center justify-between gap-2"><p className="text-xs text-muted-foreground">{chunk.metadata?.parent_text ? `父块 ${(chunk.metadata.parent_index ?? 0)+1} · 子块` : '分片'} {chunk.chunk_index+1} · {[...(chunk.content.text ?? '')].length} 字符{chunk.metadata?.draft_change === 'deleted' ? ' · 待删除（不会入库）' : chunk.metadata?.draft_change === 'added' ? ' · 新增' : chunk.metadata?.draft_change === 'modified' ? ' · 已修改' : ''}</p>{chunk.metadata?.draft_change === 'deleted' ? restore(chunk.chunk_index) : actions(chunk.chunk_index,chunk.content.text ?? '')}</div>{!!chunk.metadata?.heading_path?.length && <p className="text-xs text-muted-foreground">{chunk.metadata.heading_path.join(' / ')}</p>}<pre className={'whitespace-pre-wrap break-words text-xs leading-relaxed ' + (chunk.metadata?.draft_change === 'deleted' ? 'line-through text-red-700 dark:text-red-300' : '')}>{chunk.content.text ?? JSON.stringify(chunk.content)}</pre>
                        {chunk.metadata?.parent_text && <details className="border-t pt-2"><summary className="cursor-pointer text-xs">查看父块上下文</summary><pre className="mt-2 whitespace-pre-wrap break-words text-xs leading-relaxed">{chunk.metadata.parent_text}</pre></details>}
                    </article>{insertion(chunk.chunk_index)}</div>)}
                </>}
            </div>
            <div className="shrink-0 space-y-3 border-t p-4">
                {p.draft && <div className="flex items-center justify-between gap-2"><Button size="sm" variant="outline" disabled={!!editor || p.pending || p.page<=1} onClick={() => p.onPage(p.page-1)}>上一页</Button><span className="text-xs">{p.page} / {Math.max(1,Math.ceil(p.draft.total/20))}</span><Button size="sm" variant="outline" disabled={!!editor || p.pending || p.page*20>=p.draft.total} onClick={() => p.onPage(p.page+1)}>下一页</Button></div>}
                {p.editable && <Button className="w-full" disabled={!!editor || !p.canEmbed || p.changed || p.busy || p.pending || !p.draft} onClick={p.onEmbed}>确认分片并执行向量化</Button>}
                <p className="text-xs text-muted-foreground">确认的是全部分片，而非仅当前页；向量化会调用已配置的模型。</p>
                {!p.canEditDraft && !p.canEmbed && !p.pending && <p className="text-xs text-muted-foreground">已入库预览为只读；如需修改，请先重新生成分片。</p>}
            </div>
        </aside>
    </div>{editorView}</>;
}
