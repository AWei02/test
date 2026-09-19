import { useEffect, useMemo, useRef, useState } from 'react';
import { math } from '@streamdown/math';
import { cjk } from '@streamdown/cjk';
import { Markdown } from '@/components/markdown';
import { defaultRehypePlugins } from 'streamdown';
import { client } from '@/api/client';

export type ParsedAsset = {name: string; size: number; content_type: string};
const raster = new Set(['image/png', 'image/jpeg', 'image/webp']);
// Only manifest-owned relative images are allowed. No external tracking images,
// SVG, data URLs, signed cloud URLs or arbitrary server paths are ever fetched.
export function resolveParsedImage(src: string, assets: ParsedAsset[]) {
    let name: string;
    try {name = decodeURIComponent(src);} catch {return undefined;}
    if (/^(?:[a-z][a-z0-9+.-]*:|\/|\\)/i.test(name) || name.includes('\\')) return undefined;
    name = name.replace(/^(\.\/)+/, '');
    if (name.split('/').includes('..')) return undefined;
    return assets.find(a => a.name === name && raster.has(a.content_type) && a.size <= 20 * 1024 * 1024);
}

function PrivateImage({src, alt, path, assets}: {src?: string; alt?: string; path: string; assets: ParsedAsset[]}) {
    const host = useRef<HTMLSpanElement>(null);
    const [url,setUrl] = useState(''); const [error,setError] = useState('');
    const asset = resolveParsedImage(src ?? '', assets);
    useEffect(() => {
        setUrl(''); setError('');
        if (!asset || !host.current) return;
        let cancelled = false, objectUrl = '', started = false;
        const controller = new AbortController();
        const load = async () => {
            if(started) return; started = true;
            try {
                const response = await client.stream(path + '/artifact', {params:{name:asset.name},signal:controller.signal,silent:true});
                const blob = await response.blob();
                if(cancelled) return;
                if(!raster.has(blob.type) || blob.size > 20*1024*1024) throw new Error('不支持的图片格式或图片过大');
                objectUrl = URL.createObjectURL(blob); setUrl(objectUrl);
            } catch(e) {if(!cancelled) setError(e instanceof Error ? e.message : '图片加载失败');}
        };
        const observer = new IntersectionObserver(entries => {if(entries.some(e => e.isIntersecting)) {observer.disconnect(); void load();}}, {rootMargin:'200px'});
        observer.observe(host.current);
        return () => {cancelled=true; observer.disconnect(); controller.abort(); if(objectUrl) URL.revokeObjectURL(objectUrl);};
    }, [path,asset?.name,asset?.size]);
    return <span ref={host} className="my-2 block min-h-8">
        {url ? <img src={url} alt={alt ?? ''} className="h-auto max-w-full rounded border" onError={() => {setUrl(''); setError('图片无法解码，请下载原图检查');}} />
            : <span className="text-xs text-muted-foreground">{!asset ? `图片未载入（外部链接或资源不存在）：${alt || src || '图片'}` : error || `加载图片：${alt || asset.name}`}</span>}
    </span>;
}

export function ParsedMarkdown({text,path,assets}: {text:string; path:string; assets:ParsedAsset[]}) {
    const components = useMemo(() => ({
        img: ({src,alt}: {src?: string; alt?: string}) => <PrivateImage src={src} alt={alt} path={path} assets={assets} />,
        a: ({children,href}: {children?: React.ReactNode; href?: string}) => href
            ? <a href={href} target="_blank" rel="noopener noreferrer" className="underline">{children}</a> : <span>{children}</span>,
    }), [path,assets]);
    return <Markdown mode="static" plugins={{math,cjk}} components={components}
        rehypePlugins={[defaultRehypePlugins.raw, defaultRehypePlugins.sanitize]}
        allowedElements={['p','br','hr','h1','h2','h3','h4','h5','h6','strong','em','del','s','u','sup','sub','blockquote','ul','ol','li','pre','code','table','thead','tbody','tfoot','tr','th','td','div','span','img','a']}
        urlTransform={(url,key) => key === 'src' ? (resolveParsedImage(url,assets) ? url : '') : (/^https?:\/\//i.test(url) ? url : '')}
    >{text}</Markdown>;
}
