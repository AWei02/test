"""Admin-managed logo. Decode raster uploads and persist a small sanitized PNG."""
import base64
import io
from fastapi import Request, HTTPException, UploadFile, File
from PIL import Image, UnidentifiedImageError

def normalize_logo(raw):
    if len(raw) > 2 * 1024 * 1024:
        raise HTTPException(400, '图片最大 2MB')
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.format not in ('PNG', 'JPEG', 'WEBP'):
                raise ValueError('format')
            if source.width * source.height > 16_000_000:
                raise ValueError('dimensions')
            source.thumbnail((256, 256))
            output = io.BytesIO()
            source.convert('RGBA').save(output, format='PNG')
            return 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode()
    except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError):
        raise HTTPException(400, '请选择有效的 PNG、JPG 或 WebP 图片（不超过 1600 万像素）') from None

def install_routes(router, require_admin):
    @router.get('/branding')
    async def get_branding(request: Request):
        from portal import user_for, load
        user_for(request.headers.get('x-user-id', ''))
        return {'logo': load().get('branding', {}).get('logo')}

    @router.post('/branding/logo')
    async def upload_logo(request: Request, file: UploadFile = File(...)):
        from portal import load, save, LOCK
        require_admin(request)
        logo = normalize_logo(await file.read(2 * 1024 * 1024 + 1))
        with LOCK:
            data = load()
            data['branding'] = {'logo': logo}
            save(data)
        return {'logo': logo}

    @router.delete('/branding/logo')
    async def reset_logo(request: Request):
        from portal import load, save, LOCK
        require_admin(request)
        with LOCK:
            data = load()
            data.pop('branding', None)
            save(data)
        return {'logo': None}
