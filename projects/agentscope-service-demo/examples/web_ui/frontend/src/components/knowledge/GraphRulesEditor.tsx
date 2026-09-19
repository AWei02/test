import { useEffect, useState } from 'react';
import { client } from '@/api/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

type EntityRule = { name: string; description: string; aliases: string[] };
type RelationRule = EntityRule & { source_types: string[]; target_types: string[] };
type Rules = { mode: 'free' | 'guided' | 'strict'; entities: EntityRule[]; relations: RelationRule[] };
type Proposal = { kind: 'entity' | 'relation'; name: string; example: string; source_type?: string; target_type?: string; filename: string; chunk_index: number };
type State = { rules: Rules; revision: number; built_revision: number | null; last_build: string | null; pending: Proposal[];
  build_report: { entities: number; relations: number; rejected: number; processed_chunks: number; pending_total: number } | null };
export type RuleStatus = { revision: number; dirty: boolean };
const fieldClass = 'rounded-md border bg-background px-2 py-1 text-sm min-w-0';
const emptyEntity = (): EntityRule => ({ name: '', description: '', aliases: [] });

export function GraphRulesEditor({ kbId, reloadKey, onStatus }: { kbId: string; reloadKey: number; onStatus: (s: RuleStatus | null) => void }) {
  const [state, setState] = useState<State | null>(null);
  const [draft, setDraft] = useState<Rules | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const dirty = !!state && JSON.stringify(state.rules) !== JSON.stringify(draft);
  useEffect(() => {
    let active = true;
    onStatus(null); setError('');
    client.get<State>(`/portal/knowledge-graph/${kbId}/rules`).then(s => {
      if (active) { setState(s); setDraft(s.rules); }
    }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [kbId, reloadKey, onStatus]);
  useEffect(() => { onStatus(state && !busy ? { revision:state.revision, dirty } : null); }, [state, dirty, busy, onStatus]);
  async function save() {
    setBusy(true); setError(''); setNotice('');
    try { const body = draft && { ...draft, entities:draft.entities.map(e => ({ ...e, aliases:e.aliases.map(a => a.trim()).filter(Boolean) })), relations:draft.relations.map(r => ({ ...r, aliases:r.aliases.map(a => a.trim()).filter(Boolean) })) }; const s = await client.patch<State>(`/portal/knowledge-graph/${kbId}/rules`, body); setState(s); setDraft(s.rules); setNotice('规则已保存，尚未重新抽取；请确认后点击构建图谱。'); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  function entity(index: number, patch: Partial<EntityRule>) {
    if (!draft) return;
    const before = draft.entities[index].name;
    setDraft({ ...draft, entities:draft.entities.map((x,i) => i === index ? { ...x, ...patch } : x),
      relations: patch.name !== undefined ? draft.relations.map(r => ({ ...r,
        source_types:r.source_types.map(n => n === before ? patch.name! : n), target_types:r.target_types.map(n => n === before ? patch.name! : n) })) : draft.relations });
  }
  function relation(index: number, patch: Partial<RelationRule>) {
    if (draft) setDraft({ ...draft, relations:draft.relations.map((r,i) => i === index ? { ...r, ...patch } : r) });
  }
  function addProposal(p: Proposal) {
    if (!draft) return;
    const entities = [...draft.entities], relations = [...draft.relations];
    for (const name of p.kind === 'entity' ? [p.name] : [p.source_type!,p.target_type!]) {
      if (!entities.some(e => e.name === name)) entities.push({ name, description:'', aliases:[] });
    }
    if (p.kind === 'relation' && !relations.some(r => r.name === p.name)) relations.push({ name:p.name, description:'', aliases:[], source_types:[p.source_type!], target_types:[p.target_type!] });
    setDraft({ ...draft, entities, relations }); setNotice('已加入规则草稿，请检查类型、方向和别名后保存，再重新抽取。');
  }
  if (!draft || !state) return <p role="status" className="mt-4 text-sm">{error || '正在读取图谱抽取规则…'}</p>;
  const proposals = state.pending.filter((p,i,list) => list.findIndex(q => q.kind === p.kind && q.name === p.name && q.source_type === p.source_type && q.target_type === p.target_type) === i);
  return <div className="mt-4 rounded-lg border bg-card p-4 space-y-3">
    <div className="flex flex-wrap items-center justify-between gap-2"><h4 className="text-sm font-medium">实体与关系抽取规则</h4><span className="text-xs text-muted-foreground">规则版本 {state.revision} · {state.built_revision === null ? '现有图谱未记录规则版本' : `图谱版本 ${state.built_revision}`}</span></div>
    <p className="text-xs text-muted-foreground">定义的是类型，不是具体实体名称。每个知识库独立配置；保存规则不会自动改变已有图谱。</p>
    {state.built_revision !== state.revision && <p className="text-sm text-amber-700">当前规则尚未完整应用到图谱，需要重新构建。</p>}
    <fieldset disabled={busy} className="space-y-4">
      <label className="flex flex-wrap items-center gap-3 text-sm">抽取模式<select aria-label="抽取模式" className={fieldClass} value={draft.mode} onChange={e => setDraft({ ...draft, mode:e.target.value as Rules['mode'] })}>
        <option value="free">自由抽取</option><option value="guided">引导抽取（推荐）</option><option value="strict">严格抽取</option></select></label>
      <Button size="sm" variant="outline" onClick={() => {
        setDraft({ mode:'guided', entities:['生物','栖息地','能力','物质','文献'].map(name => ({name,description:'',aliases:[]})),
          relations:[{name:'栖息于',source_types:['生物'],target_types:['栖息地'],aliases:['生活于']},
            {name:'以……为食',source_types:['生物'],target_types:['生物','物质'],aliases:['以之为食']},
            {name:'拥有能力',source_types:['生物'],target_types:['能力'],aliases:[]},
            {name:'记载于',source_types:['生物'],target_types:['文献'],aliases:['被记载于']}].map(r => ({...r,description:''})) });
        setNotice('生物资料示例已填入草稿，尚未保存；可继续调整，或撤销草稿修改。');
      }}>用生物资料示例替换草稿</Button>
      <p className="text-xs text-muted-foreground">{draft.mode === 'free' ? '模型自主识别类型；下方类型规则暂不参与校验，但仍检查关系端点是否存在。' : draft.mode === 'guided' ? '已定义类型正常入库；新类型列入待确认，确认并重建后才进入正式图谱。错误方向的关系直接过滤。' : '仅允许已定义类型及连接方向；不符合规则的实体和关系被过滤，不产生新类型候选。'}</p>
      <details open><summary className="cursor-pointer text-sm font-medium">实体类型（{draft.entities.length}）</summary>
        <div className="mt-3 max-h-72 space-y-2 overflow-y-auto pr-2">
          {draft.entities.map((item,i) => <div key={i} className="grid gap-2 rounded-md border p-2 md:grid-cols-[1fr_1fr_2fr_auto]">
            <Input aria-label={`实体类型 ${i+1}`} placeholder="标准类型，如生物" value={item.name} onChange={e => entity(i,{ name:e.target.value })} />
            <Input aria-label={`实体别名 ${i+1}`} placeholder="别名，逗号分隔" value={item.aliases.join(',')} onChange={e => entity(i,{ aliases:e.target.value.split(/[,，]/) })} />
            <Input aria-label={`实体说明 ${i+1}`} placeholder="含义说明，帮助模型判断" value={item.description} onChange={e => entity(i,{ description:e.target.value })} />
            <Button variant="ghost" onClick={() => setDraft({ ...draft, entities:draft.entities.filter((_,j) => i !== j), relations:draft.relations.map(r => ({ ...r,source_types:r.source_types.filter(n => n !== item.name),target_types:r.target_types.filter(n => n !== item.name) })) })}>移除</Button>
          </div>)}
        </div><Button className="mt-2" size="sm" variant="outline" onClick={() => setDraft({ ...draft, entities:[...draft.entities,emptyEntity()] })}>添加实体类型</Button>
      </details>
      <details open><summary className="cursor-pointer text-sm font-medium">关系类型与连接方向（{draft.relations.length}）</summary>
        <p className="mt-2 text-xs text-muted-foreground">方向：起点类型 → 关系 → 终点类型。每端至少勾选一种类型。</p>
        <div className="mt-3 max-h-96 space-y-3 overflow-y-auto pr-2">{draft.relations.map((r,i) => <div key={i} className="rounded-md border p-3 space-y-2">
          <div className="grid gap-2 md:grid-cols-[1fr_1fr_2fr_auto]"><Input aria-label={`关系类型 ${i+1}`} value={r.name} placeholder="关系，如栖息于" onChange={e => relation(i,{name:e.target.value})} />
            <Input aria-label={`关系别名 ${i+1}`} value={r.aliases.join(',')} placeholder="别名，逗号分隔" onChange={e => relation(i,{aliases:e.target.value.split(/[,，]/)})} />
            <Input aria-label={`关系说明 ${i+1}`} value={r.description} placeholder="关系含义" onChange={e => relation(i,{description:e.target.value})} />
            <Button variant="ghost" onClick={() => setDraft({ ...draft, relations:draft.relations.filter((_,j) => i !== j) })}>移除</Button></div>
          <div className="grid gap-3 md:grid-cols-2">{(['source_types','target_types'] as const).map(side => <div key={side}><p className="mb-1 text-xs text-muted-foreground">{side === 'source_types' ? '起点类型' : '终点类型'}</p><div className="flex flex-wrap gap-3">{draft.entities.filter(e => e.name).map(e => <label key={e.name} className="flex items-center gap-1 text-xs"><input type="checkbox" checked={r[side].includes(e.name)} onChange={event => relation(i,{ [side]:event.target.checked ? [...r[side],e.name] : r[side].filter(n => n !== e.name) })} />{e.name}</label>)}</div></div>)}</div>
        </div>)}</div><Button size="sm" variant="outline" className="mt-2" onClick={() => setDraft({ ...draft, relations:[...draft.relations,{...emptyEntity(),source_types:[],target_types:[]}] })}>添加关系类型</Button>
      </details>
      <div className="flex flex-wrap gap-2"><Button disabled={!dirty} onClick={save}>保存规则</Button><Button variant="outline" disabled={!dirty} onClick={() => {setDraft(state.rules);setError('');setNotice('');}}>撤销草稿修改</Button><span className="self-center text-xs text-muted-foreground">{dirty ? '有未保存修改，保存后才能构建' : '规则已保存'}</span></div>
    </fieldset>
    {notice && <p role="status" className="text-sm text-emerald-700">{notice}</p>}{error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {state.build_report && <p className="text-xs text-muted-foreground">上次构建：{state.build_report.processed_chunks} 分块，{state.build_report.entities} 实体，{state.build_report.relations} 关系，过滤 {state.build_report.rejected} 项。{state.last_build && new Date(state.last_build).toLocaleString()}</p>}
    <details open={proposals.length > 0}><summary className="cursor-pointer text-sm font-medium">待确认新类型（{proposals.length} 种候选）</summary>
      <p className="my-2 text-xs text-muted-foreground">这些候选未自动进入正式图谱。加入草稿后可修改或合并为已有类型的别名；保存并重建后重新验证。最多保留 500 条来源记录。</p>
      <div className="max-h-72 space-y-2 overflow-y-auto">{proposals.map((p,i) => <div key={i} className="flex flex-wrap items-center justify-between gap-2 rounded-md border p-2 text-sm"><div><span className="font-medium">{p.kind === 'entity' ? '实体类型' : '关系类型'}：{p.name}</span>{p.kind === 'relation' && <span> · {p.source_type} → {p.target_type}</span>}<p className="text-xs text-muted-foreground">示例：{p.example} · {p.filename} #{p.chunk_index+1}</p></div><Button size="sm" variant="outline" disabled={busy} onClick={() => addProposal(p)}>加入规则草稿</Button></div>)}{!proposals.length && <p className="text-xs text-muted-foreground">暂无待确认类型。</p>}</div>
    </details>
  </div>;
}
