"""Live document authorization, shared by HTTP and chat retrieval."""
from copy import copy


def can_read_document(access, viewer, document):
    policy = getattr(access._policy, 'can_read_document', None)
    if policy:
        return policy(viewer, document)
    return (viewer == document.user_id or document.data.access_mode == 'inherit'
            or (document.data.access_mode == 'custom' and viewer in document.data.access_users))


class AuthorizedKnowledge:
    def __init__(self, knowledge, access, storage, viewer, owner, kb_id):
        self._knowledge, self._access, self._storage = knowledge, access, storage
        self._viewer, self._owner, self._kb_id = viewer, owner, kb_id

    def __getattr__(self, name):
        return getattr(self._knowledge, name)

    async def search(self, *args, **kwargs):
        retrieval_options = kwargs.pop('retrieval_options', None)
        # Re-evaluate grants and ACLs for every tool call, including long turns.
        await self._access.resolve_knowledge_base(self._viewer, self._kb_id)
        documents = await self._storage.list_knowledge_documents(self._owner, self._kb_id)
        ids = [d.id for d in documents if can_read_document(self._access, self._viewer, d)]
        if not ids:
            return []
        from ...rag._vdb._qdrant import QdrantStore
        if not isinstance(self._knowledge._vector_store, QdrantStore):
            raise RuntimeError('Document ACL requires a vector backend with document prefilter support.')
        scoped = copy(self._knowledge)
        scoped._metadata_filter = {**(scoped._metadata_filter or {}), '$document_ids': ids}
        search_policy = getattr(self._access._policy, 'search_knowledge', None)
        async def filter_hits(hits):
            await self._access.resolve_knowledge_base(self._viewer, self._kb_id)
            current = await self._storage.list_knowledge_documents(self._owner, self._kb_id)
            allowed = {d.id for d in current if can_read_document(self._access, self._viewer, d)}
            return [h for h in hits if h.document_id in allowed]
        if search_policy:
            results = await search_policy(scoped, [d for d in documents if d.id in ids],
                self._access, self._viewer, self._kb_id, retrieval_options, *args,
                filter_hits=filter_hits, **kwargs)
        else:
            if retrieval_options is not None:
                raise RuntimeError('Retrieval strategies are not configured.')
            results = await scoped.search(*args, **kwargs)
        await self._access.resolve_knowledge_base(self._viewer, self._kb_id)
        documents = await self._storage.list_knowledge_documents(self._owner, self._kb_id)
        allowed = {d.id for d in documents if can_read_document(self._access, self._viewer, d)}
        return [r for r in results if r.document_id in allowed]
