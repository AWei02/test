import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI, APIRouter, HTTPException
from fastapi.testclient import TestClient
from PIL import Image
import portal
from branding import install_routes

class BrandingTests(unittest.TestCase):
    def test_upload_auth_validation_persistence_reset(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(portal, 'FILE', Path(temp)/'portal.json'):
            portal.save({'users':[{'username':'admin','enabled':True},{'username':'member','enabled':True}]})
            def admin(request):
                if request.headers.get('x-user-id')!='admin': raise HTTPException(403)
            app=FastAPI();router=APIRouter(prefix='/portal');install_routes(router,admin);app.include_router(router)
            c=TestClient(app);a={'X-User-ID':'admin'};u={'X-User-ID':'member'}
            image=io.BytesIO();Image.new('RGB',(512,512),'blue').save(image,'PNG')
            self.assertEqual(c.post('/portal/branding/logo',headers=u,files={'file':('logo.png',image.getvalue())}).status_code,403)
            self.assertEqual(c.post('/portal/branding/logo',headers=a,files={'file':('logo.svg',b'<svg/>')}).status_code,400)
            self.assertEqual(c.post('/portal/branding/logo',headers=a,files={'file':('large.png',b'x'*(2*1024*1024+1))}).status_code,400)
            r=c.post('/portal/branding/logo',headers=a,files={'file':('logo.png',image.getvalue())})
            self.assertEqual(r.status_code,200)
            self.assertTrue(r.json()['logo'].startswith('data:image/png;base64,'))
            self.assertEqual(c.get('/portal/branding',headers=u).json(),r.json())
            self.assertEqual(portal.load()['branding']['logo'],r.json()['logo'])
            self.assertEqual(c.delete('/portal/branding/logo',headers=u).status_code,403)
            self.assertEqual(c.delete('/portal/branding/logo',headers=a).json(),{'logo':None})
            self.assertEqual(c.get('/portal/branding',headers=u).json(),{'logo':None})

if __name__=='__main__':unittest.main()
