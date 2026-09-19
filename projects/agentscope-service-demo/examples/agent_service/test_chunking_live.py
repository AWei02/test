"""Opt-in UI/API fixture. Only mutates prefix-validated temporary resources."""
import argparse
import json
import time
import uuid
import httpx
from document_chunking import ChunkingConfig

PREFIX = '__chunking_ui_test_'
SOURCE = '397c349e6a1346b4ad7150d7df5b610a'
client = httpx.Client(base_url='http://127.0.0.1:8000',headers={'X-User-ID':'wei'},timeout=60)

def call(method,path,**kwargs):
    r=client.request(method,path,**kwargs);r.raise_for_status();return r.json() if r.content else None

def wait(kb,doc):
    for _ in range(40):
        d=call('GET',f'/portal/parsing/{kb}/documents/{doc}')
        if d['status'] in ('ready','error','awaiting_parse_confirmation','awaiting_chunk_confirmation'):
            assert d['status']!='error',d.get('error');return d
        time.sleep(1)
    raise AssertionError('Timed out')

def validate(kb):
    assert kb != SOURCE
    record=call('GET','/knowledge_bases/',params={'id':kb})['knowledge_bases'][0]
    assert record['id']==kb and record['name'].startswith(PREFIX), 'Not a test knowledge base'

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','verify','cleanup']);parser.add_argument('--kb');parser.add_argument('--doc');args=parser.parse_args()
    if args.action=='prepare':
        original=call('GET','/knowledge_bases/',params={'id':SOURCE})['knowledge_bases'][0]
        kb=call('POST','/knowledge_bases/',json={'name':PREFIX+uuid.uuid4().hex[:8],'embedding_model_config':original['embedding_model_config'],'chunker_config':original['chunker_config']})['knowledge_base_id']
        raw=('# 分片设置测试\n\n'+('岩壳巨鼹是地下生物。它通过震动感知岩层，具有坚硬甲壳，并在地下寻找食物。\n'*30)+'\n联络 test@example.com，说明 https://example.com/info\n')
        doc=call('POST',f'/knowledge_bases/{kb}/documents',files={'file':('分片测试.md',raw.encode(),'text/markdown')},data={'access_mode':'private'})['document_id']
        assert wait(kb,doc)['status']=='awaiting_parse_confirmation'
        print(json.dumps({'kb':kb,'doc':doc,'url':f'http://127.0.0.1:59370/knowledge/{kb}','original_counts':[original['document_count'],original['chunk_count']]},ensure_ascii=False))
    else:
        validate(args.kb)
        path=f'/portal/parsing/{args.kb}/documents/{args.doc}'
        if args.action=='cleanup':
            call('DELETE',f'/knowledge_bases/{args.kb}/documents/{args.doc}')
            call('DELETE',f'/knowledge_bases/{args.kb}')
            print('Removed only prefix-validated temporary test document and KB')
        else:
            detail=wait(args.kb,args.doc)
            config=ChunkingConfig(mode='parent_child',parent_mode='paragraph',parent_max_length=300,child_max_length=100,remove_urls_emails=True).model_dump()
            call('POST',path+'/advance',json={'action':'chunk','version':detail['version'],'config':config})
            assert wait(args.kb,args.doc)['status']=='awaiting_chunk_confirmation'
            draft=call('GET',path+'/draft');assert draft['config']==config
            assert all(len(c['content']['text'])<=100 and len(c['metadata']['parent_text'])<=300 for c in draft['chunks'])
            indexed=f'/knowledge_bases/{args.kb}/documents/{args.doc}/chunks'
            assert not call('GET',indexed)['chunks'], 'Preview must not embed'
            old_version=draft['version']
            changed=call('PATCH',path+'/draft',json={'version':old_version,'action':'edit','chunk_index':0,
                'text':'人工校对：岩壳巨鼹通过震动感知环境。NOTEBOOK_PARENT_EDIT_CHECK'})
            draft=call('GET',path+'/draft');assert draft['version']==changed['version']!=old_version
            assert 'NOTEBOOK_PARENT_EDIT_CHECK' in draft['chunks'][0]['metadata']['parent_text']
            assert client.patch(path+'/draft',json={'version':old_version,'action':'insert','chunk_index':-1,'text':'stale'}).status_code==409
            assert not call('GET',indexed)['chunks'], 'Editing must not embed'
            response=client.post(path+'/advance',json={'action':'embed','version':draft['version'],'config':{**config,'child_max_length':80}})
            assert response.status_code==409
            call('POST',path+'/advance',json={'action':'embed','version':draft['version'],'config':config})
            assert wait(args.kb,args.doc)['status']=='ready'
            found=call('POST',f'/portal/retrieval/{args.kb}/test',json={'query':'NOTEBOOK_PARENT_EDIT_CHECK','strategy':'keyword','top_k':5,'candidate_k':20})['results']
            assert found and all(h['document_id']==args.doc for h in found)
            for hit in found:
                c=hit['chunk'];assert c['content']['text']==c['metadata']['parent_text'];assert len(c['metadata']['matched_child_text'])<=100
            assert len({h['chunk']['metadata']['parent_index'] for h in found})==len(found)
            assert 'NOTEBOOK_PARENT_EDIT_CHECK' in found[0]['chunk']['content']['text']
            print('PASS: persisted config, preview/edit have ZERO indexed chunks, stale-version/changed-config rejection, edited draft embedded, child retrieval expands parent with manual edit')
