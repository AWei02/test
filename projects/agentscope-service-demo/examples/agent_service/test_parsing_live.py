"""Opt-in live smoke test. Creates and deletes only its own temporary KB.

Usage: python test_parsing_live.py
Uses the existing KB's embedding configuration, so two tiny embedding calls
may be billed. Never reparses or deletes existing user documents.
"""
import json
import time
import uuid
import httpx


def run():
    c = httpx.Client(base_url='http://127.0.0.1:8000',headers={'X-User-ID':'wei'},timeout=30)
    source = '397c349e6a1346b4ad7150d7df5b610a'
    original = c.get('/knowledge_bases/',params={'id':source}).json()['knowledge_bases'][0]
    name = '__parsing_smoke_' + uuid.uuid4().hex
    response = c.post('/knowledge_bases/',json={'name':name,'embedding_model_config':original['embedding_model_config'],
        'chunker_config':original['chunker_config']})
    response.raise_for_status(); kb = response.json()['knowledge_base_id']
    assert kb != source
    doc = None
    def wait(expected):
        for _ in range(40):
            detail = c.get(f'/portal/parsing/{kb}/documents/{doc}'); detail.raise_for_status(); data=detail.json()
            if data['status'] in ('ready','error','awaiting_parse_confirmation','awaiting_chunk_confirmation'):
                assert data['status']==expected,data.get('error') or data['status']; return data
            time.sleep(1)
        raise AssertionError('Timed out waiting for indexing')
    try:
        config = {'engine':'mineru','mineru_mode':'api','tier':'standard','cloud_version':'vlm',
                  'credential_id':'','model':'','vision_confirmed':False,'max_pages':100}
        raw='# Parser smoke\n\nThis temporary document verifies private Markdown indexing.\n\n## Section two\n\nRetrieval keeps source headings.'
        response=c.post(f'/knowledge_bases/{kb}/documents',files={'file':('smoke.md',raw.encode(),'text/markdown')},
            data={'access_mode':'private','parsing_config':json.dumps(config)})
        response.raise_for_status(); doc=response.json()['document_id']
        detail=wait('awaiting_parse_confirmation'); assert detail['engine']=='direct'; assert detail['config']['mineru_mode']=='api'
        response=c.get(f'/portal/parsing/{kb}/documents/{doc}/artifact'); response.raise_for_status()
        assert response.text==raw; assert response.headers['cache-control']=='private, no-store'
        assert c.get(f'/portal/parsing/{kb}/documents/{doc}/artifact',params={'name':'../../outside'}).status_code==404
        path=f'/portal/parsing/{kb}/documents/{doc}'
        chunks_path=f'/knowledge_bases/{kb}/documents/{doc}/chunks'
        assert len(c.get(chunks_path).json()['chunks'])==0
        time.sleep(3)
        assert c.get(path).json()['status']=='awaiting_parse_confirmation'
        response=c.post(path+'/advance',json={'action':'embed','version':detail['version']}); assert response.status_code==409
        response=c.post(path+'/advance',json={'action':'chunk','version':detail['version']}); response.raise_for_status()
        detail=wait('awaiting_chunk_confirmation')
        draft=c.get(path+'/draft').json(); assert draft['total']>0
        assert len(c.get(chunks_path).json()['chunks'])==0
        time.sleep(3)
        assert c.get(path).json()['status']=='awaiting_chunk_confirmation'
        response=c.post(path+'/advance',json={'action':'embed','version':draft['version']}); response.raise_for_status()
        detail=wait('ready')
        assert len(c.get(chunks_path).json()['chunks'])==draft['total']
        print('PASS: parse pauses with ZERO indexed chunks; chunk pauses with ZERO indexed chunks; reviewed draft indexed ONLY after confirmation')
    finally:
        if doc:
            response=c.delete(f'/knowledge_bases/{kb}/documents/{doc}'); response.raise_for_status()
        response=c.delete(f'/knowledge_bases/{kb}'); response.raise_for_status()
        print('Removed only temporary smoke document/KB:', kb)
        after=c.get('/knowledge_bases/',params={'id':source}).json()['knowledge_bases'][0]
        assert after['document_count']==original['document_count'] and after['chunk_count']==original['chunk_count']
        print('Existing KB document and chunk counts unchanged')


if __name__ == '__main__': run()
