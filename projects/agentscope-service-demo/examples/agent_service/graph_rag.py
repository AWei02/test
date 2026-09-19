"""Optional, provenance-preserving GraphRAG support for the demo portal.

The vector index remains the canonical RAG index.  This module adds a Neo4j
projection of entities and relations extracted from those already-indexed
chunks, so graph retrieval can expand a question through explicit relations
without losing the source document/chunk that justified every edge.
"""
from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, Field

from agentscope.message import TextBlock, ToolResultState, UserMsg
from agentscope.tool import ToolBase, ToolChunk
from agentscope.permission import PermissionBehavior, PermissionDecision


class GraphEntity(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    type: str = Field(default="概念", max_length=80)


class GraphRelation(BaseModel):
    source: str = Field(min_length=1, max_length=160)
    target: str = Field(min_length=1, max_length=160)
    relation: str = Field(min_length=1, max_length=120)


class GraphExtraction(BaseModel):
    entities: list[GraphEntity] = Field(default_factory=list)
    relations: list[GraphRelation] = Field(default_factory=list)


class GraphSearchInput(BaseModel):
    """Input deliberately kept small: the agent supplies the entity/topic."""

    query: str = Field(min_length=1, max_length=300, description="Entity or concise topic to look up in the knowledge graph.")


_EXTRACTION_PROMPT = """从下面的知识库分块中抽取可复用的实体与关系。
只保留文本明确表达的事实；不要补充常识、不要猜测。实体名称保持原文语言，
关系用简短动词短语。若没有可靠关系，返回空列表。

分块：
{chunk}
"""


class GraphRagStore:
    """A minimal Neo4j projection with per-edge document provenance."""

    def __init__(self, uri: str, username: str, password: str, database: str) -> None:
        self._uri = uri
        self._username = username
        self._password = password
        self._database = database

    @classmethod
    def from_env(cls) -> "GraphRagStore | None":
        uri = os.getenv("NEO4J_URI")
        password = os.getenv("NEO4J_PASSWORD")
        if not uri or not password:
            return None
        return cls(uri, os.getenv("NEO4J_USERNAME", "neo4j"), password, os.getenv("NEO4J_DATABASE", "neo4j"))

    def _driver(self) -> Any:
        try:
            from neo4j import AsyncGraphDatabase
        except ImportError as exc:
            raise RuntimeError("GraphRAG 依赖 neo4j 驱动，请安装 neo4j Python 包。") from exc
        return AsyncGraphDatabase.driver(self._uri, auth=(self._username, self._password))

    async def ensure_ready(self) -> None:
        driver = self._driver()
        try:
            await driver.verify_connectivity()
            async with driver.session(database=self._database) as session:
                await session.run(
                    "CREATE CONSTRAINT kb_entity_identity IF NOT EXISTS "
                    "FOR (n:KbEntity) REQUIRE (n.kb_id, n.name) IS UNIQUE"
                )
        finally:
            await driver.close()

    async def replace_document(
        self,
        knowledge_base_id: str,
        document_id: str,
        filename: str,
        chunk_index: int,
        extraction: GraphExtraction,
    ) -> int:
        """Replace one chunk's extracted graph, returning relation count."""
        entities = {entity.name.strip(): entity.type.strip() or "概念" for entity in extraction.entities if entity.name.strip()}
        relations = [
            relation for relation in extraction.relations
            if relation.source.strip() and relation.target.strip() and relation.relation.strip()
        ]
        driver = self._driver()
        try:
            async with driver.session(database=self._database) as session:
                await session.run(
                    "MATCH ()-[r:KB_RELATION {kb_id:$kb_id, document_id:$document_id, chunk_index:$chunk_index}]->() DELETE r",
                    kb_id=knowledge_base_id, document_id=document_id, chunk_index=chunk_index,
                )
                for name, kind in entities.items():
                    await session.run(
                        "MERGE (e:KbEntity {kb_id:$kb_id, name:$name}) "
                        "SET e.type=$type",
                        kb_id=knowledge_base_id, name=name, type=kind,
                    )
                for relation in relations:
                    await session.run(
                        "MERGE (source:KbEntity {kb_id:$kb_id, name:$source}) "
                        "MERGE (target:KbEntity {kb_id:$kb_id, name:$target}) "
                        "CREATE (source)-[:KB_RELATION {kb_id:$kb_id, document_id:$document_id, filename:$filename, chunk_index:$chunk_index, relation:$relation}]->(target)",
                        kb_id=knowledge_base_id,
                        source=relation.source.strip(), target=relation.target.strip(),
                        document_id=document_id, filename=filename,
                        chunk_index=chunk_index, relation=relation.relation.strip(),
                    )
        finally:
            await driver.close()
        return len(relations)

    async def clear_document(self, knowledge_base_id: str, document_id: str) -> None:
        """Remove old edges before rebuilding a document's graph."""
        driver = self._driver()
        try:
            async with driver.session(database=self._database) as session:
                await session.run(
                    "MATCH ()-[r:KB_RELATION {kb_id:$kb_id, document_id:$document_id}]->() DELETE r",
                    kb_id=knowledge_base_id, document_id=document_id,
                )
        finally:
            await driver.close()

    async def replace_knowledge(self, knowledge_base_id, chunks):
        """Commit a complete extracted graph atomically; failures keep the old graph."""
        driver = self._driver()
        try:
            async with driver.session(database=self._database) as session:
                async def write(tx):
                    await tx.run('MATCH (n:KbEntity {kb_id:$kb_id}) DETACH DELETE n', kb_id=knowledge_base_id)
                    for document_id, filename, chunk_index, extraction in chunks:
                        for entity in extraction.entities:
                            await tx.run('MERGE (n:KbEntity {kb_id:$kb_id, name:$name}) SET n.type=$type',
                                kb_id=knowledge_base_id, name=entity.name, type=entity.type)
                        for edge in extraction.relations:
                            await tx.run('MATCH (s:KbEntity {kb_id:$kb_id, name:$source}), (t:KbEntity {kb_id:$kb_id, name:$target}) '
                                'CREATE (s)-[:KB_RELATION {kb_id:$kb_id, document_id:$document_id, filename:$filename, chunk_index:$chunk_index, relation:$relation}]->(t)',
                                kb_id=knowledge_base_id, source=edge.source, target=edge.target, relation=edge.relation,
                                document_id=document_id, filename=filename, chunk_index=chunk_index)
                await session.execute_write(write)
        finally:
            await driver.close()

    async def snapshot(self, knowledge_base_id: str, limit: int = 160) -> dict[str, list[dict[str, Any]]]:
        """Return a bounded graph suitable for the portal visualisation."""
        driver = self._driver()
        try:
            async with driver.session(database=self._database) as session:
                result = await session.run(
                    "MATCH (source:KbEntity {kb_id:$kb_id})-[r:KB_RELATION]->(target:KbEntity {kb_id:$kb_id}) "
                    "RETURN source.name AS source, source.type AS source_type, target.name AS target, target.type AS target_type, "
                    "r.relation AS relation, r.document_id AS document_id, r.filename AS filename, r.chunk_index AS chunk_index "
                    "LIMIT $limit",
                    kb_id=knowledge_base_id, limit=limit,
                )
                rows = [record.data() async for record in result]
        finally:
            await driver.close()
        names: dict[str, str] = {}
        edges: list[dict[str, Any]] = []
        for row in rows:
            names[row["source"]] = row.get("source_type") or "概念"
            names[row["target"]] = row.get("target_type") or "概念"
            edges.append({
                "source": row["source"], "target": row["target"],
                "relation": row["relation"], "document_id": row["document_id"],
                "filename": row["filename"], "chunk_index": row["chunk_index"],
            })
        return {
            "nodes": [{"id": name, "label": name, "type": kind} for name, kind in names.items()],
            "edges": edges,
        }

    async def search(
        self,
        knowledge_base_ids: list[str],
        query: str,
        limit: int = 8,
        document_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Find source-grounded graph facts relevant to an entity/topic.

        Graph retrieval is intentionally separate from vector retrieval: the
        agent can use it to connect entities, while the vector tool remains
        better for long passages and natural-language similarity.
        """
        if not knowledge_base_ids or not query.strip():
            return []
        driver = self._driver()
        try:
            async with driver.session(database=self._database) as session:
                result = await session.run(
                    "MATCH (source:KbEntity)-[r:KB_RELATION]->(target:KbEntity) "
                    "WHERE source.kb_id IN $kb_ids AND target.kb_id = source.kb_id "
                    "AND r.document_id IN $document_ids "
                    "AND (toLower(source.name) CONTAINS toLower($search_term) "
                    "OR toLower(target.name) CONTAINS toLower($search_term) "
                    "OR toLower(r.relation) CONTAINS toLower($search_term)) "
                    "RETURN source.name AS source, source.type AS source_type, "
                    "target.name AS target, target.type AS target_type, "
                    "r.relation AS relation, r.filename AS filename, "
                    "r.chunk_index AS chunk_index, r.document_id AS document_id "
                    "LIMIT $limit",
                    kb_ids=knowledge_base_ids, search_term=query.strip(), limit=limit,
                    document_ids=document_ids or [],
                )
                return [record.data() async for record in result]
        finally:
            await driver.close()


class GraphSearchTool(ToolBase):
    """Expose graph facts beside the standard semantic-search RAG tool."""

    name = "search_knowledge_graph"
    is_read_only = True
    is_concurrency_safe = True
    is_external_tool = False
    is_state_injected = False
    is_mcp = False

    def __init__(self, store: GraphRagStore, knowledge_base_ids: list[str], workspace=None) -> None:
        super().__init__()
        self._store = store
        self._knowledge_base_ids = knowledge_base_ids
        self._workspace = workspace
        self.description = (
            "Search explicit entity relationships extracted from the equipped "
            "knowledge bases. Use this together with search_knowledge when a "
            "question asks how people, concepts, systems, or events relate. "
            "Search with a concise entity name or topic. Every result includes "
            "its source filename and chunk number; do not state a graph fact "
            "without retaining that provenance."
        )
        self.input_schema = GraphSearchInput.model_json_schema()

    async def check_permissions(self, tool_input: dict[str, Any], context: Any) -> PermissionDecision:
        del tool_input, context
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="Knowledge-graph search is read-only.",
        )

    async def call(self, query: str) -> ToolChunk:
        try:
            from portal import PortalPolicy, ADMIN
            ws = self._workspace
            if ws is None:
                facts = []
            else:
                ids = set(self._knowledge_base_ids) & ws.selected('knowledge')
                allowed_docs = []
                for kb_id in ids:
                    allowed_docs.extend(d.id for d in await ws.storage.list_knowledge_documents(ADMIN, kb_id)
                                        if PortalPolicy().can_read_document(ws.username, d))
                facts = await self._store.search(sorted(ids), query, document_ids=allowed_docs)
        except Exception as exc:  # pylint: disable=broad-except
            return ToolChunk(
                content=[TextBlock(text=f"Knowledge-graph search failed: {exc}")],
                state=ToolResultState.ERROR,
                is_last=True,
            )
        if not facts:
            return ToolChunk(
                content=[TextBlock(text="No relevant graph facts found. Use semantic knowledge search if needed.")],
                state=ToolResultState.SUCCESS,
                is_last=True,
            )
        lines = ["Source-grounded knowledge-graph facts:"]
        for fact in facts:
            lines.append(
                f"- {fact['source']} — {fact['relation']} → {fact['target']} "
                f"[source: {fact.get('filename') or 'unknown'}, chunk {fact.get('chunk_index', '?')}]"
            )
        return ToolChunk(
            content=[TextBlock(text="\n".join(lines))],
            state=ToolResultState.SUCCESS,
            is_last=True,
        )


async def extract_chunk_graph(model: Any, text: str, rules=None) -> GraphExtraction:
    """Use the explicitly selected chat model to create a typed extraction."""
    from graph_rules import rule_prompt
    instructions = rule_prompt(rules) + '\n' if rules is not None else ''
    response = await model.generate_structured_output(
        messages=[UserMsg(name="user", content=instructions + _EXTRACTION_PROMPT.format(chunk=text[:12000]))],
        structured_model=GraphExtraction,
    )
    return GraphExtraction.model_validate(response.content)
