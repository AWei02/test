import { useEffect, useState, type ReactNode } from 'react';
import { Search, Save, Columns2 } from 'lucide-react';
import type { VectorSearchResult } from '@/api';
import { client } from '@/api/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';

type Strategy = 'vector' | 'keyword' | 'hybrid';
type Settings = {
  strategy: Strategy; top_k: number; candidate_k: number; vector_weight: number;
  score_threshold: number | null; rerank_enabled: boolean;
  credential_id: string | null; model: string | null;
};
type Model = { credential_id: string; credential_name: string; model: string };
type Run = { results: VectorSearchResult[]; elapsed_ms: number; score_kind: string; settings: Settings; query: string };
const defaults: Settings = { strategy: 'vector', top_k: 5, candidate_k: 20, vector_weight: .5,
  score_threshold: null, rerank_enabled: false, credential_id: null, model: null };
const strategies: { id: Strategy; name: string; hint: string }[] = [
  { id: 'vector', name: '向量检索', hint: '按语义匹配，适合自然语言提问、同义表达。' },
  { id: 'keyword', name: '全文检索 · BM25', hint: '按关键词匹配，适合名称、术语、编号等精确内容。' },
  { id: 'hybrid', name: '混合检索', hint: '同时检索语义和关键词，通过加权 RRF 融合排名。' },
];
const nameOf = (s: Strategy) => strategies.find(x => x.id === s)?.name;
const selectClass = 'h-9 rounded-md border bg-background px-2 text-sm min-w-0';

export function RetrievalWorkbench({ knowledgeBaseId, editable = false }: { knowledgeBaseId: string; editable?: boolean }) {
  const [config, setConfig] = useState<Settings>(defaults);
  const [saved, setSaved] = useState<Settings>(defaults);
  const [models, setModels] = useState<Model[]>([]);
  const [query, setQuery] = useState('');
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [runs, setRuns] = useState<Run[]>([]);
  const [baseline, setBaseline] = useState<Run | null>(null);
  const [history, setHistory] = useState<Run[]>([]);
  useEffect(() => {
    let active = true;
    setReady(false); setRuns([]); setHistory([]); setBaseline(null); setError(''); setNotice('');
    Promise.all([client.get<Settings>(`/portal/retrieval/${knowledgeBaseId}`), client.get<{ models: Model[] }>('/portal/retrieval/models')])
      .then(([s, m]) => { if (active) { setConfig(s); setSaved(s); setModels(m.models); setReady(true); } })
      .catch(e => { if (active) setError(String(e.message)); });
    return () => { active = false; };
  }, [knowledgeBaseId]);
  const update = (patch: Partial<Settings>) => { setConfig(c => ({ ...c, ...patch })); setNotice(''); };
  const missingModel = config.rerank_enabled && !models.some(m => m.credential_id === config.credential_id && m.model === config.model);
  const invalid = missingModel || config.candidate_k < config.top_k;
  const dirty = JSON.stringify(config) !== JSON.stringify(saved);
  async function run(compare: boolean) {
    setBusy(true); setError(''); setNotice('');
    try {
      const variants = compare ? strategies.map(s => ({ ...config, strategy: s.id,
        score_threshold: s.id === 'keyword' && !config.rerank_enabled ? null : config.score_threshold })) : [config];
      const completed: Run[] = [];
      for (const settings of variants) {
        completed.push(await client.post<Run>(`/portal/retrieval/${knowledgeBaseId}/test`, { ...settings, query: query.trim() }));
      }
      setRuns(completed); setHistory(h => [...completed, ...h].slice(0, 12));
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function save() {
    setBusy(true); setError(''); setNotice('');
    try {
      const value = await client.patch<Settings>(`/portal/retrieval/${knowledgeBaseId}`, config);
      setSaved(value); setConfig(value); setNotice('默认策略已保存。后续知识库检索和问答将使用此配置。');
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <div className="flex min-h-0 flex-1 flex-col gap-5">
    <div className="rounded-xl border bg-muted/10 p-4 space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div><h3 className="text-sm font-medium">检索策略与效果测试</h3><p className="mt-1 text-xs text-muted-foreground">先试用不同策略，再保存为默认。测试不会自动修改问答配置，所有策略都遵循文件权限。</p></div>
        <Badge variant="outline">{dirty ? '未保存的测试配置' : '知识库默认配置'}</Badge>
      </div>
      <fieldset disabled={!ready || busy} className="space-y-4 disabled:opacity-60">
        <div className="grid gap-3 md:grid-cols-3">{strategies.map(s => <button key={s.id} type="button" aria-pressed={config.strategy === s.id}
          className={`rounded-lg border p-3 text-left transition-colors ${config.strategy === s.id ? 'border-emerald-600 bg-emerald-50 dark:bg-emerald-950/30' : 'bg-background hover:bg-muted/50'}`}
          onClick={() => update({ strategy: s.id, ...(s.id === 'keyword' && !config.rerank_enabled ? { score_threshold: null } : {}) })}>
          <div className="text-sm font-medium">{s.name}</div><p className="mt-1 text-xs text-muted-foreground">{s.hint}</p></button>)}</div>
        {config.strategy === 'hybrid' && <div className="rounded-lg border p-3 space-y-2">
          <label htmlFor="retrieval-weight" className="text-sm">混合权重：语义 {Math.round(config.vector_weight * 100)}% / 关键词 {Math.round((1-config.vector_weight)*100)}%</label>
          <input id="retrieval-weight" className="block w-full accent-emerald-600" type="range" min="0" max="1" step="0.05" value={config.vector_weight} onChange={e => update({ vector_weight: Number(e.target.value) })} />
          <p className="text-xs text-muted-foreground">偏语义适合问法变化，偏关键词适合术语和编号。融合分数不是命中概率。</p></div>}
        <div className="flex flex-wrap items-center gap-3 rounded-lg border p-3">
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="accent-emerald-600" checked={config.rerank_enabled}
            onChange={e => update({ rerank_enabled: e.target.checked, ...(!e.target.checked && config.strategy === 'keyword' ? { score_threshold: null } : {}) })} />启用 Rerank 重排</label>
          {config.rerank_enabled && <select aria-label="重排模型" className={`${selectClass} flex-1`} value={JSON.stringify([config.credential_id, config.model])}
            onChange={e => { const [credential_id, model] = JSON.parse(e.target.value); update({ credential_id, model }); }}>
            <option value={JSON.stringify([null, null])}>选择已配置并启用的 Rerank 模型</option>
            {models.map(m => <option key={`${m.credential_id}/${m.model}`} value={JSON.stringify([m.credential_id, m.model])}>{m.credential_name} · {m.model} · {m.credential_id.slice(0,8)}</option>)}</select>}
          <p className="w-full text-xs text-muted-foreground">对候选内容再次排序，会增加耗时和模型调用费用。兼容 /rerank 接口，如 SiliconFlow；不是 LLM 对话接口。</p>
          {config.rerank_enabled && models.length === 0 && <p className="text-sm text-amber-700">暂无可用重排模型。请在“凭证”页刷新模型、选择 Rerank 类型、配置上下文长度并启用。</p>}
          {missingModel && models.length > 0 && <p className="text-sm text-destructive">请选择可用模型；之前的模型可能已禁用或无权限。</p>}
        </div>
        <div className="flex flex-wrap items-end gap-4">
          <label className="text-xs space-y-1">Top K · 最终返回数<Input aria-label="Top K" className="w-28" type="number" min="1" max="50" value={config.top_k}
            onChange={e => { const k = Math.max(1,Math.min(50,Number(e.target.value)||1)); update({ top_k:k, candidate_k:Math.max(k,config.candidate_k) }); }} /></label>
          <label className="text-xs space-y-1">候选数 · 每路召回<Input aria-label="候选数" className="w-28" type="number" min={config.top_k} max="100" value={config.candidate_k}
            onChange={e => update({ candidate_k:Math.max(config.top_k,Math.min(100,Number(e.target.value)||config.top_k)) })} /></label>
          <div className="flex items-center gap-2"><label className="flex shrink-0 items-center gap-2 whitespace-nowrap text-xs"><input type="checkbox" checked={config.score_threshold !== null}
            disabled={config.strategy === 'keyword' && !config.rerank_enabled} onChange={e => update({ score_threshold:e.target.checked ? .5 : null })} />分数阈值</label>
            <Input aria-label="分数阈值" type="number" className="w-28" min="0" max="1" step="0.05" disabled={config.score_threshold === null} value={config.score_threshold ?? ''}
              onChange={e => update({ score_threshold:Math.max(0,Math.min(1,Number(e.target.value)||0)) })} /></div>
        </div>
        <p className="text-xs text-muted-foreground">各策略分数含义不同，不能直接横向比较大小。BM25 不设 0–1 阈值；开启重排后阈值作用于重排分数。</p>
        <label className="block text-sm space-y-2">测试问题<Textarea value={query} maxLength={4000} rows={3} placeholder="输入同一个问题，比较不同策略命中的文档与分块…" onChange={e => setQuery(e.target.value)} /></label>
        <div className="flex flex-wrap gap-2">
          <Button disabled={invalid || !query.trim()} onClick={() => run(false)}><Search className="size-4" />测试当前策略</Button>
          <Button variant="outline" disabled={invalid || !query.trim()} onClick={() => run(true)}><Columns2 className="size-4" />三种策略对比</Button>
          {editable && <Button variant="outline" disabled={invalid || !dirty} onClick={save} className="md:ml-auto"><Save className="size-4" />保存为知识库默认</Button>}
        </div>
      </fieldset>
      {busy && <p role="status" className="text-sm text-muted-foreground">正在处理，请稍候…</p>}
      {notice && <p role="status" className="text-sm text-emerald-700">{notice}</p>}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    </div>
    <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-medium">测试结果</h3>
      {history.length > 0 && <select aria-label="本页测试历史" className={selectClass} value="" onChange={e => { const item = history[Number(e.target.value)]; if (item) setRuns([item]); }}>
        <option value="">查看本页最近 {history.length} 次测试</option>{history.map((r,i) => <option key={i} value={i}>{nameOf(r.settings.strategy)} · {r.query.slice(0,25)} · {r.elapsed_ms}ms</option>)}</select>}
    </div>
    {runs.length === 0 ? <div className="rounded-xl border border-dashed p-10 text-center text-sm text-muted-foreground">输入问题后开始测试。重点观察是否命中正确来源、内容完整性和耗时。</div> :
      <div className={`grid gap-4 ${runs.length + (baseline ? 1 : 0) > 1 ? 'xl:grid-cols-2' : ''} ${runs.length === 3 && !baseline ? '2xl:grid-cols-3' : ''}`}>
        {baseline && <Results run={baseline} title="固定对照" action={<Button size="sm" variant="ghost" onClick={() => setBaseline(null)}>取消固定</Button>} />}
        {runs.map((r,i) => <Results key={i} run={r} action={<Button size="sm" variant="ghost" onClick={() => setBaseline(r)}>固定为对照</Button>} />)}</div>}
    <p className="text-xs text-muted-foreground">全文检索使用中文字符/双字词及英文词的 BM25 倒排索引；当前每次按可访问分块构建，最多 20000 块。测试历史仅保留在本页内存，刷新后清除。</p>
  </div>;
}

function Results({ run, title, action }: { run: Run; title?: string; action: ReactNode }) {
  return <section className="min-w-0 rounded-xl border p-3 space-y-3">
    <div className="flex flex-wrap items-center justify-between gap-2"><h4 className="text-sm font-medium">{title && `${title} · `}{nameOf(run.settings.strategy)}{run.settings.rerank_enabled && ' + Rerank'}</h4>{action}</div>
    <p className="text-xs text-muted-foreground break-words">问题：{run.query}</p>
    <p className="text-xs text-muted-foreground">{run.results.length} 条 · {run.elapsed_ms} ms · Top K {run.settings.top_k} · 候选 {run.settings.candidate_k} · 阈值 {run.settings.score_threshold ?? '关闭'}{run.settings.strategy === 'hybrid' && ` · 语义权重 ${run.settings.vector_weight}`}{run.settings.rerank_enabled && ` · ${run.settings.model}`}</p>
    {run.results.length === 0 && <p className="py-8 text-center text-sm text-muted-foreground">没有匹配结果。可检查文件就绪状态、权限、问题关键词及分数阈值。</p>}
    {run.results.map((hit,i) => <div key={`${hit.document_id}/${hit.chunk.chunk_index}`} className="rounded-lg border bg-muted/10 p-3 space-y-2">
      <div className="flex flex-wrap gap-2 text-xs"><Badge variant="secondary">#{i+1}</Badge><Badge variant="outline">{run.score_kind} {hit.score.toFixed(4)}</Badge></div>
      <p className="text-xs font-medium break-all">{hit.chunk.source} · 分块 {hit.chunk.chunk_index+1}/{hit.chunk.total_chunks}</p>
      <p className="max-h-80 overflow-y-auto whitespace-pre-wrap break-words text-sm">{hit.chunk.content && typeof hit.chunk.content === 'object' && 'text' in hit.chunk.content ? String(hit.chunk.content.text ?? '') : JSON.stringify(hit.chunk.content)}</p>
      <p className="text-[10px] text-muted-foreground break-all">文件 ID：{hit.document_id}</p></div>)}
  </section>;
}
