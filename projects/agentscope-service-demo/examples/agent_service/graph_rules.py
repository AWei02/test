"""Per-knowledge-base extraction schemas and deterministic validation."""
import asyncio
from datetime import datetime, timezone
from typing import Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field, model_validator

BUILD_LOCKS: dict[str, asyncio.Lock] = {}


class EntityRule(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default='', max_length=400)
    aliases: list[str] = Field(default_factory=list, max_length=30)


class RelationRule(EntityRule):
    source_types: list[str] = Field(min_length=1, max_length=100)
    target_types: list[str] = Field(min_length=1, max_length=100)


class GraphRules(BaseModel):
    mode: Literal['free', 'guided', 'strict'] = 'guided'
    entities: list[EntityRule] = Field(default_factory=list, max_length=100)
    relations: list[RelationRule] = Field(default_factory=list, max_length=150)

    @model_validator(mode='after')
    def check(self):
        for group in (self.entities, self.relations):
            used = set()
            for item in group:
                item.name = item.name.strip()
                item.aliases = [a.strip() for a in item.aliases]
                for token in [item.name, *item.aliases]:
                    if not token or len(token) > 80 or token.casefold() in used:
                        raise ValueError('类型名称和别名不能为空、超过80字或重复')
                    used.add(token.casefold())
        names = {e.name for e in self.entities}
        for relation in self.relations:
            if not set(relation.source_types + relation.target_types) <= names:
                raise ValueError('关系的起点/终点类型必须先在实体类型中定义')
        if self.mode != 'free' and (not self.entities or not self.relations):
            raise ValueError('引导/严格模式至少定义一种实体类型和一种关系类型')
        return self


def default_rules():
    return GraphRules(entities=[EntityRule(name=n) for n in ('人物', '组织', '地点', '事物', '概念', '事件')],
        relations=[RelationRule(name='关联', source_types=['人物','组织','地点','事物','概念','事件'],
                                target_types=['人物','组织','地点','事物','概念','事件'])])


def state_for(kb_id):
    from portal import load
    stored = load().get('graph_rules', {}).get(kb_id, {})
    return {'rules': stored.get('rules', default_rules().model_dump()),
            'revision': stored.get('revision', 0), 'built_revision': stored.get('built_revision'),
            'last_build': stored.get('last_build'), 'pending': stored.get('pending', []),
            'build_report': stored.get('build_report')}


def rule_prompt(rules):
    if rules.mode == 'free':
        return '自由抽取：可自行识别实体类型和关系类型；关系两端必须是本次输出的实体。'
    guidance = ('发现定义外的新类型可以如实输出，系统会作为待确认项隔离，不会直接写入正式图谱。'
                if rules.mode == 'guided' else '只输出定义内的类型，无法匹配的内容应省略，禁止强行套用类型。')
    return (guidance + '\n按以下规则抽取，别名归一为标准名称；严格遵守关系的起点和终点类型及方向。\n'
            + rules.model_dump_json() + '\n实体名称来自原文，不要把实体类型当成实体名称。')


def validate_extraction(extraction, rules):
    """Unknown guided types are quarantined; invalid edges never reach Neo4j."""
    from graph_rag import GraphExtraction, GraphEntity, GraphRelation
    entity_map = {a.casefold(): e.name for e in rules.entities for a in [e.name, *e.aliases]}
    relation_map = {a.casefold(): r for r in rules.relations for a in [r.name, *r.aliases]}
    accepted, raw_types, pending, rejected = {}, {}, [], 0
    for entity in extraction.entities:
        name, kind = entity.name.strip(), entity.type.strip()
        if not name or not kind:
            rejected += 1
            continue
        normalized = kind if rules.mode == 'free' else entity_map.get(kind.casefold())
        raw_types[name] = normalized or kind
        if not normalized:
            rejected += 1
            if rules.mode == 'guided':
                pending.append({'kind':'entity', 'name':kind, 'example':name})
            continue
        if name in accepted and accepted[name].type != normalized:
            rejected += 1
            continue
        accepted[name] = GraphEntity(name=name, type=normalized)
    relations, seen = [], set()
    for edge in extraction.relations:
        source, target, label = edge.source.strip(), edge.target.strip(), edge.relation.strip()
        if not label or source not in raw_types or target not in raw_types:
            rejected += 1
            continue
        rule = relation_map.get(label.casefold())
        if rules.mode != 'free' and not rule:
            rejected += 1
            if rules.mode == 'guided':
                pending.append({'kind':'relation', 'name':label, 'source_type':raw_types[source],
                                'target_type':raw_types[target], 'example':f'{source} → {target}'})
            continue
        if source not in accepted or target not in accepted:
            rejected += 1
            continue
        if rules.mode != 'free' and (accepted[source].type not in rule.source_types or accepted[target].type not in rule.target_types):
            rejected += 1
            continue
        name = label if rules.mode == 'free' else rule.name
        key = (source, name, target)
        if key not in seen:
            seen.add(key)
            relations.append(GraphRelation(source=source, target=target, relation=name))
    return GraphExtraction(entities=list(accepted.values()), relations=relations), pending, rejected


def finish_build(kb_id, revision, pending, report):
    from portal import load, save, LOCK
    with LOCK:
        data = load()
        state = data.setdefault('graph_rules', {}).setdefault(kb_id, {})
        state.update(built_revision=revision, last_build=datetime.now(timezone.utc).isoformat(),
                     pending=pending[:500], build_report={**report, 'pending_total':len(pending)})
        save(data)


def install_routes(router, app, require_admin):
    @router.get('/knowledge-graph/{kb_id}/rules')
    async def get_rules(kb_id: str, request: Request):
        from portal import ADMIN
        require_admin(request)
        await app.state.resource_access_service.resolve_knowledge_base(ADMIN, kb_id)
        return state_for(kb_id)

    @router.patch('/knowledge-graph/{kb_id}/rules')
    async def save_rules(kb_id: str, body: GraphRules, request: Request):
        from portal import ADMIN, load, save, LOCK
        require_admin(request)
        await app.state.resource_access_service.resolve_knowledge_base(ADMIN, kb_id)
        if BUILD_LOCKS.setdefault(kb_id, asyncio.Lock()).locked():
            raise HTTPException(409, '图谱正在构建，请完成后再修改规则')
        with LOCK:
            data = load()
            state = data.setdefault('graph_rules', {}).setdefault(kb_id, {})
            if state.get('rules') != body.model_dump():
                state['rules'] = body.model_dump()
                state['revision'] = state.get('revision', 0) + 1
            save(data)
        return state_for(kb_id)
