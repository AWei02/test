import assert from 'node:assert/strict';
import React from 'react';
import { renderToString } from 'react-dom/server';
import { createServer } from 'vite';

const server = await createServer({ server: { middlewareMode: true }, appType: 'custom' });
try {
    const {ChunkingWorkbench, defaultChunking} = await server.ssrLoadModule('/src/components/knowledge/ChunkingWorkbench.tsx');
    const noop = () => {};
    const props = {config:defaultChunking,onChange:noop,before:null,after:null,available:true,editable:true,
        busy:false,previewOpen:true,onClose:noop,onOpen:noop,onPreview:noop,pending:false,changed:false,
        page:2,onPage:noop,canEmbed:true,onEmbed:noop,canEditDraft:true,onEditDraft:async()=>true,
        draft:{version:'v1',total:42,chunks:Array.from({length:20},(_,i)=>({chunk_index:i+20,content:{text:`Block ${i+20}`},metadata:{}}))}};
    const render = extra => renderToString(React.createElement(ChunkingWorkbench,{...props,...extra}));
    const idle=render({}), refreshing=render({busy:true,pending:true});
    for(const html of [idle,refreshing]) {
        assert.equal((html.match(/data-chunk-index=/g)||[]).length,20);
        assert.equal((html.match(/data-insert-after=/g)||[]).length,21);
        assert.match(html,/data-chunk-index="30"/);
        assert.match(html,/Block 30/);
        assert.match(html,/data-testid="chunk-preview-scroll"/);
    }
    assert.match(refreshing,/fieldset disabled/);
    assert.doesNotMatch(refreshing,/正在生成或加载分片/);
    assert.match(render({draft:undefined,pending:true}),/正在生成或加载分片/);
    console.log('PASS: background draft refresh retains all chunk anchors and insertion controls; editing is disabled without collapsing the list');
} finally {await server.close();}
