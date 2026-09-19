import assert from 'node:assert/strict';
import React from 'react';
import { renderToString } from 'react-dom/server';
import { createServer } from 'vite';
const server = await createServer({server:{middlewareMode:true},appType:'custom'});
try {
    const {ParsedMarkdown,resolveParsedImage} = await server.ssrLoadModule('/src/components/knowledge/ParsedMarkdown.tsx');
    const assets=[{name:'images/test.png',size:10,content_type:'image/png'}];
    assert.equal(resolveParsedImage('./images/test.png',assets)?.name,'images/test.png');
    for(const src of ['https://external.test/a.png','//external.test/a.png','data:image/png;base64,AAA','../images/test.png','%2e%2e/images/test.png','/images/test.png','images/missing.png']) assert.equal(resolveParsedImage(src,assets),undefined);
    const html=renderToString(React.createElement(ParsedMarkdown,{path:'/portal/parsing/k/documents/d',assets,
        text:'# Title\n\nAuthor<sup>1</sup> and **bold**\n\n| A | B |\n|---|---|\n| one | two |\n\n![Figure](images/test.png)\n\n![External](https://external.test/tracker.png)\n\n<script>alert(1)</script>\n<iframe src="https://external.test"></iframe>\n\n[Bad](javascript:alert(1))'}));
    assert.match(html,/<h1/); assert.match(html,/<sup[^>]*>1<\/sup>/); assert.match(html,/<table/);
    assert.doesNotMatch(html,/Image blocked: Figure/);
    assert.match(html,/加载图片：Figure/);
    assert.match(html,/Figure/); assert.doesNotMatch(html,/<script|<iframe|href="javascript:|src="https:\/\/external/);
    console.log('PASS: headings, superscripts, GFM tables render; images restricted to private manifest; active HTML and unsafe URLs blocked');
} finally {await server.close();}
