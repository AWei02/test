// Render real provider/consumer before and after module invalidation. No browser or backend required.
import assert from 'node:assert/strict';
import React from 'react';
import { renderToString } from 'react-dom/server';
import { createServer } from 'vite';

const server = await createServer({ server: { middlewareMode: true }, appType: 'custom' });
try {
    const path = '/src/context/UploadContext.tsx';
    const first = await server.ssrLoadModule(path);
    const getHook = async () => {
        try { return (await server.ssrLoadModule('/src/context/uploadContextState.ts')).useUploadContext; }
        catch { return (await server.ssrLoadModule(path)).useUploadContext; }
    };
    const before = await getHook();
    const probe = hook => function Probe() { return React.createElement('span', null, `tasks:${hook().tasks.length}`); };
    assert.match(renderToString(React.createElement(first.UploadProvider, null, React.createElement(probe(before)))), /tasks:0/);
    const module = await server.moduleGraph.getModuleByUrl(path);
    server.moduleGraph.invalidateModule(module);
    const updated = await server.ssrLoadModule(path);
    const after = await getHook();
    // A mounted provider and a refreshed consumer must share the same context.
    assert.match(renderToString(React.createElement(first.UploadProvider, null, React.createElement(probe(after)))), /tasks:0/);
    assert.match(renderToString(React.createElement(updated.UploadProvider, null, React.createElement(probe(before)))), /tasks:0/);
    assert.throws(() => renderToString(React.createElement(probe(after))), /UploadProvider/);
    console.log('PASS: provider/consumer identity survives provider reload; missing provider still fails explicitly');
} finally { await server.close(); }
