import { useEffect, useState } from 'react';
import { client } from '@/api/client';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { toast } from 'sonner';
import { ParsedMarkdown } from './ParsedMarkdown';
import { ChunkingWorkbench, defaultChunking, configKey, chunkingError } from './ChunkingWorkbench';
import type { ChunkingConfig, ChunkDraft, DraftEdit } from './ChunkingWorkbench';

export type ParsingConfig = { engine: 'mineru' | 'llm'; mineru_mode: 'local' | 'api'; tier: 'flash' | 'standard' | 'advanced'; cloud_version: 'vlm' | 'pipeline'; credential_id: string; model: string; vision_confirmed: boolean; max_pages: number };
type Options = { models: {credential_id: string; credential_name: string; model: string}[]; local_url: string; cloud_configured: boolean };
const inputClass = 'w-full rounded-lg border bg-background px-3 py-2 text-sm';
type SelectOption = {value: string; label: string};
function ParsingSelect({value,onChange,options}: {value: string; onChange: (value: string) => void; options: SelectOption[]}) {
    return <Select value={value} onValueChange={onChange}><SelectTrigger className="h-10 w-full bg-background px-3"><SelectValue /></SelectTrigger><SelectContent position="popper" align="start">{options.map(option => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}</SelectContent></Select>;
}

export function ParsingFields({ value, onChange, disabled = false }: {value: ParsingConfig; onChange: (v: ParsingConfig) => void; disabled?: boolean}) {
    const [options, setOptions] = useState<Options>();
    const [error, setError] = useState('');
    useEffect(() => { let active = true; client.get<Options>('/portal/parsing/options').then(v => {if(active) setOptions(v);}).catch(() => {if(active) setError('解析选项加载失败，请重新打开');}); return () => {active = false;}; }, []);
    return <fieldset disabled={disabled} className="space-y-3 rounded-xl border p-3">
        <legend className="px-1 text-sm font-medium">文档解析 → Markdown → 切分</legend>
        <label className="block space-y-1 text-sm"><span>解析器</span><ParsingSelect value={value.engine} onChange={engine => onChange({...value, engine: engine as ParsingConfig['engine']})} options={[{value:'mineru',label:'MinerU'},{value:'llm',label:'视觉 LLM'}]} /></label>
        {value.engine === 'mineru' ? <>
            <label className="block space-y-1 text-sm"><span>运行方式</span><ParsingSelect value={value.mineru_mode} onChange={mineru_mode => onChange({...value, mineru_mode: mineru_mode as ParsingConfig['mineru_mode']})} options={[{value:'local',label:'本地 / 自部署服务'},{value:'api',label:'MinerU 云端 API'}]} /></label>
            {value.mineru_mode === 'local' ? <>
                <p className="break-all text-xs text-muted-foreground">MinerU 4.x V1 服务：{options?.local_url ?? '加载中…'}。地址由服务端 MINERU_LOCAL_URL 配置，不会自动切换云端。</p>
                <label className="block space-y-1 text-sm"><span>解析档位（Office 固定 Flash）</span><ParsingSelect value={value.tier} onChange={tier => onChange({...value, tier: tier as ParsingConfig['tier']})} options={[{value:'flash',label:'Flash'},{value:'standard',label:'Standard'},{value:'advanced',label:'Advanced'}]} /></label>
            </> : <>
                <label className="block space-y-1 text-sm"><span>云端解析模型</span><ParsingSelect value={value.cloud_version} onChange={cloud_version => onChange({...value, cloud_version: cloud_version as ParsingConfig['cloud_version']})} options={[{value:'vlm',label:'VLM'},{value:'pipeline',label:'Pipeline'}]} /></label>
                <p className="text-xs text-amber-700">原文件将发送至 MinerU 云端。{options?.cloud_configured ? '服务端 Token 已配置。' : '服务端尚未配置 MINERU_API_TOKEN，暂不可使用。'}</p>
            </>}
        </> : <>
            <label className="block space-y-1 text-sm"><span>视觉模型</span><ParsingSelect value={JSON.stringify([value.credential_id, value.model])} onChange={selected => {const [credential_id, model] = JSON.parse(selected); onChange({...value, credential_id, model, vision_confirmed: false});}} options={[{value:JSON.stringify(['','']),label:'选择已启用的模型'}, ...(options?.models ?? []).map(m => ({value:JSON.stringify([m.credential_id,m.model]),label:`${m.credential_name} · ${m.model}`}))]} /></label>
            <label className="flex gap-2 text-sm"><input type="checkbox" checked={value.vision_confirmed} onChange={e => onChange({...value, vision_confirmed: e.target.checked})} />我已确认该模型支持图像输入（LLM 类型本身不代表支持视觉）</label>
            <label className="block space-y-1 text-sm"><span>PDF 页数上限</span><input className={inputClass} type="number" min={1} max={200} value={value.max_pages} onChange={e => onChange({...value, max_pages: Number(e.target.value)})} /></label>
            <p className="text-xs text-amber-700">逐页发送图像到所选模型，可能产生费用。支持 PDF / PNG / JPEG / WebP，超限或截断会报错，不会按成功入库。</p>
        </>}
        <p className="text-xs text-muted-foreground">上传后仅解析。确认解析后生成分片，再确认分片才调用向量模型。UTF-8 Markdown / TXT 直接读取；单文件最大 50 MB。</p>
        {error && <p className="text-xs text-destructive" role="alert">{error}</p>}
    </fieldset>;
}

export function ParsingSettings({kbId}: {kbId: string}) {
    const [value, setValue] = useState<ParsingConfig>(); const [busy, setBusy] = useState(false); const [error, setError] = useState('');
    useEffect(() => { let active = true; client.get<ParsingConfig>(`/portal/parsing/${kbId}`).then(v => {if(active) setValue(v);}).catch(() => {if(active) setError('解析设置加载失败');}); return () => {active = false;}; }, [kbId]);
    async function action(check = false) {
        setBusy(true); setError('');
        try { if(check) {const v = await client.post<{message: string}>(`/portal/parsing/${kbId}/check`); toast.success(v.message);} else {await client.patch(`/portal/parsing/${kbId}`,value); toast.success('已保存解析默认设置');} }
        catch(e) {setError(e instanceof Error ? e.message : '操作失败');} finally {setBusy(false);}
    }
    return <section className="space-y-3 rounded-xl border p-4"><h3 className="font-medium">上传与解析默认设置</h3>
        {value ? <ParsingFields value={value} onChange={setValue} disabled={busy} /> : <p>加载解析设置…</p>}
        <div className="flex gap-2"><Button disabled={busy || !value} onClick={() => void action()}>保存解析设置</Button><Button variant="outline" disabled={busy} onClick={() => void action(true)}>检测本地 MinerU</Button></div>
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    </section>;
}

type Detail = {config: ParsingConfig; status: string; indexed_chunk_count?: number; draft_pending?: boolean; draft_editable?: boolean; engine?: string; model?: string; created_at?: string; version?: string; error?: string; manual_stages?: boolean; stage_action?: string; chunking_config?: ChunkingConfig; chunk_draft?: {version?: string; count?: number}; artifacts: {name: string; size: number; content_type: string}[]};
export function ParsingDetail({kbId, docId, editable}: {kbId: string; docId: string; editable: boolean}) {
    const [detail,setDetail] = useState<Detail>(); const [config,setConfig] = useState<ParsingConfig>();
    const [text,setText] = useState(''); const [error,setError] = useState(''); const [busy,setBusy] = useState(false);
    const [page,setPage] = useState(1);
    const [previewMode,setPreviewMode] = useState<'rendered'|'source'>('rendered');
    const [markdownOpen,setMarkdownOpen] = useState(false);
    const [markdownError,setMarkdownError] = useState('');
    const [draft,setDraft] = useState<ChunkDraft>();
    const [chunkConfig,setChunkConfig] = useState<ChunkingConfig>();
    const [previewOpen,setPreviewOpen] = useState(true);
    const [draftLoading,setDraftLoading] = useState(false);
    const path = `/portal/parsing/${kbId}/documents/${docId}`;
    useEffect(() => { let active = true;
        const update = () => client.get<Detail>(path).then(v => {if(active) {setDetail(v); setConfig(c => c ?? v.config); setChunkConfig(c => c ?? {...defaultChunking, ...v.chunking_config});}}).catch(e => {if(active) setError(String(e));});
        void update(); const timer = window.setInterval(() => {void update();}, 4000);
        return () => {active = false; window.clearInterval(timer);};
    }, [path]);
    useEffect(() => {let active = true;
        if(!detail?.chunk_draft?.version) setDraft(undefined);
        setDraftLoading(!!detail?.chunk_draft?.version);
        if(detail?.chunk_draft?.version) client.get<ChunkDraft>(path + '/draft', {page: String(page)}).then(v => {if(active) setDraft(v);}).catch(e => {if(active) setError(String(e));}).finally(() => {if(active) setDraftLoading(false);});
        return () => {active = false;};
    }, [path, detail?.chunk_draft?.version, page]);
    async function artifact(name: string, preview = false) {
        setBusy(true); setError('');
        if(preview) {setText(''); setMarkdownError(''); setPreviewMode('rendered');}
        try { const response = await client.stream(path + '/artifact', {params: {name}});
            if(preview) setText(await response.text());
            else {const blob = await response.blob(); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = name.split('/').pop() || name; a.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);}
        } catch(e) {if(preview) setMarkdownError(String(e)); else setError(String(e));} finally {setBusy(false);}
    }
    async function reparse(reuse = false) {
        if(!confirm('重新解析会调用所选解析服务，可能产生费用；完成后等待你确认，不会自动分片或向量化。继续？')) return;
        setBusy(true); setError('');
        try {await client.post(path + '/reparse', config, {reuse_markdown: String(reuse)}); setText(''); setPreviewOpen(true); setDraft(undefined); setDetail(d => d ? {...d,status:'pending'} : d); toast.success(reuse ? '已排队重新索引' : '已排队重新解析');}
        catch(e) {setError(String(e));} finally {setBusy(false);}
    }
    async function advance(action: 'chunk' | 'embed') {
        const version = action === 'chunk' ? detail?.version : draft?.version;
        if(!version || !chunkConfig) return;
        if(chunkingError(chunkConfig)) {setError(chunkingError(chunkConfig)); return;}
        if(action === 'embed' && configKey(chunkConfig) !== configKey(draft?.config)) {setError('设置已修改，请重新预览分片'); return;}
        if(!confirm(action === 'chunk' ? '确认 Markdown 解析正确，按当前设置生成新的分片预览？这会替换已有草稿（包括手工添加和修改），不调用向量模型，也不修改已入库内容。' : '确认当前全部分片没有问题，开始向量化入库？此步骤会调用向量模型。')) return;
        setBusy(true); setError('');
        try {const result = await client.post<{status: string}>(path + '/advance', {action,version,config:chunkConfig}); if(action === 'chunk') {setPage(1); setDraft(undefined); setPreviewOpen(true);} setDetail(d => d ? {...d,status:result.status} : d); setDetail(await client.get<Detail>(path)); toast.success(action === 'chunk' ? (result.status === 'ready' ? '分片草稿已更新，原有索引继续生效' : '已开始生成分片预览') : '已开始向量化');}
        catch(e) {setError(String(e));} finally {setBusy(false);}
    }
    async function editDraft(change: DraftEdit) {
        const removingAdded = change.action === 'delete' && draft?.chunks.find(chunk => chunk.chunk_index === change.chunk_index)?.metadata?.draft_change === 'added';
        setBusy(true); setError('');
        try {
            const result = await client.patch<{version: string; count: number; page: number}>(path + '/draft',change);
            const updatedDraft = await client.get<ChunkDraft>(path + '/draft', {page:String(result.page)});
            setPage(result.page);
            setDraft(updatedDraft);
            setDetail(d => d ? {...d,draft_pending:true,chunk_draft:{...d.chunk_draft,version:result.version,count:result.count}} : d);
            toast.success(removingAdded ? '已移除新增块' : change.action === 'restore' ? '已撤回删除' : change.action === 'delete' ? '已标记删除，确认向量化后生效' : change.action === 'insert' ? '已添加块，尚未向量化' : '已保存块，尚未向量化');
            return true;
        } catch(e) {setError(String(e)); return false;} finally {setBusy(false);}
    }
    async function resetToIndex() {
        if(!confirm('恢复当前已向量化的全部分片？这会替换当前草稿（包括新增、修改和删除），但不会修改向量索引。')) return;
        setBusy(true); setError('');
        try {
            const result = await client.post<{config: ChunkingConfig; settings_known: boolean}>(path + '/draft/reset', {});
            setChunkConfig(result.config); setPage(1); setDraft(undefined);
            setDetail(await client.get<Detail>(path));
            toast.success(result.settings_known ? '已恢复已入库分片，可以继续编辑' : '已恢复已入库分片。旧索引未保存切分参数，设置区显示默认值；不会重新切分。');
        } catch(e) {setError(String(e));} finally {setBusy(false);}
    }
    const terminal = detail && ['ready','error','awaiting_parse_confirmation','awaiting_chunk_confirmation'].includes(detail.status);
    const labels: Record<string,string> = {pending:'排队中',parsing:'解析中',awaiting_parse_confirmation:'等待你确认解析',chunking:'生成分片中',awaiting_chunk_confirmation:'等待你确认分片',indexing:'向量化入库中',ready:'已就绪',error:'失败'};
    const before = <div className="space-y-3 text-sm">
        <p className="rounded-lg border p-3 font-medium">1. 解析并审核 → 2. 分片并审核 → 3. 向量化入库</p>
        <p>状态：{labels[detail?.status ?? ''] ?? '加载中…'} · 实际解析器：{detail?.engine ?? '旧版 / 尚未解析'}</p>
        {detail?.status === 'ready' && detail.draft_pending && <p className="text-amber-700">已向量化的 {detail.indexed_chunk_count} 个分片仍然生效。当前预览是未入库草稿，确认并执行向量化后才会替换原索引。</p>}
        {(detail?.status === 'awaiting_parse_confirmation' || detail?.status === 'awaiting_chunk_confirmation') && <p className="text-amber-700">流程已暂停，等待你确认。不会自动执行下一步。</p>}
        {detail?.model && <p>模型：{detail.model}</p>}{detail?.created_at && <p>解析时间：{new Date(detail.created_at).toLocaleString()}</p>}
        {detail?.error && <p className="text-destructive">{detail.error}</p>}
        {!detail?.artifacts.length && <p className="text-muted-foreground">暂无 Markdown 产物，已有文件可手动重新解析。</p>}
        <details open={detail?.status === 'awaiting_parse_confirmation'}><summary className="cursor-pointer text-sm font-medium">解析产物与 Markdown 审核</summary><div className="mt-3 max-h-40 space-y-1 overflow-y-auto">{detail?.artifacts.map(a => <div key={a.name} className="flex items-center gap-2"><span className="min-w-0 flex-1 truncate">{a.name}</span>
            {a.name === 'document.md' && a.size <= 2*1024*1024 && <DialogTrigger asChild><Button variant="outline" size="sm" disabled={busy} onClick={() => void artifact(a.name,true)}>预览 Markdown</Button></DialogTrigger>}
            <Button variant="ghost" size="sm" disabled={busy} onClick={() => void artifact(a.name)}>下载</Button></div>)}</div>
        </details>
    </div>;
    return <Dialog open={markdownOpen} onOpenChange={setMarkdownOpen}><ChunkingWorkbench config={chunkConfig ?? defaultChunking} onChange={setChunkConfig}
        before={before} after={editable && config && <details className="rounded-xl border p-3"><summary className="cursor-pointer text-sm">重新解析设置</summary><div className="mt-3 space-y-3"><ParsingFields value={config} onChange={setConfig} disabled={busy || !terminal} /><Button variant="outline" disabled={busy || !terminal} onClick={() => void reparse()}>重新解析（完成后等待审核）</Button></div></details>}
        available={!!detail?.version} editable={editable} busy={busy || !terminal}
        canReset={editable && detail?.status === 'ready' && (detail.indexed_chunk_count ?? 0) > 0} onReset={() => void resetToIndex()}
        previewOpen={previewOpen} onClose={() => setPreviewOpen(false)} onOpen={() => setPreviewOpen(true)} onPreview={() => void advance('chunk')}
        draft={draft} pending={draftLoading || !!detail && !terminal} changed={configKey(chunkConfig) !== configKey(draft?.config)} page={page} onPage={setPage}
        canEmbed={!!detail && (['awaiting_chunk_confirmation','error'].includes(detail.status) || detail.status === 'ready' && !!detail.draft_pending)} onEmbed={() => void advance('embed')} error={error}
        canEditDraft={detail?.status === 'awaiting_chunk_confirmation' || detail?.status === 'ready' && !!detail.draft_editable} onEditDraft={editDraft} />
        <DialogContent className="flex h-[85dvh] max-h-[900px] min-h-0 w-[calc(100vw-2rem)] flex-col overflow-hidden sm:max-w-5xl">
            <DialogHeader className="shrink-0 pr-8"><DialogTitle>Markdown 预览</DialogTitle><DialogDescription>document.md · 解析结果预览，不会修改文档或分片。</DialogDescription></DialogHeader>
            <div className="flex shrink-0 gap-2 border-b pb-3"><Button size="sm" aria-pressed={previewMode === 'rendered'} variant={previewMode === 'rendered' ? 'default' : 'outline'} onClick={() => setPreviewMode('rendered')}>渲染</Button><Button size="sm" aria-pressed={previewMode === 'source'} variant={previewMode === 'source' ? 'default' : 'outline'} onClick={() => setPreviewMode('source')}>源码</Button></div>
            <div className="min-h-0 flex-1 overflow-auto pr-2" data-testid="markdown-preview-content">
                {busy ? <p role="status" className="text-muted-foreground">正在加载 Markdown…</p> : markdownError ? <p role="alert" className="text-destructive">{markdownError}</p> : !text ? <p className="text-muted-foreground">文档内容为空。</p> : previewMode === 'rendered'
                    ? <ParsedMarkdown key={detail?.version} text={text} path={path} assets={detail?.artifacts ?? []} />
                    : <pre className="whitespace-pre-wrap break-words text-xs">{text}</pre>}
            </div>
        </DialogContent>
    </Dialog>;
}
