"""Read a publisher's article image for an explicitly authorized local preview."""
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from PIL import Image, ImageOps

LIMIT=10_000_000

def _checked(engine, article_url, image_url):
    source=engine.publisher(engine.checked_url(article_url,article=True))
    image=engine.checked_url(image_url,article=True)
    parts=urlsplit(image)
    if not source or engine.publisher(image)!=source or parts.scheme!='https' or parts.username or parts.password or parts.port not in (None,443):
        raise ValueError('Image host is not verified for this publisher')
    return image

def fetch(engine, article_url, image_url, destination):
    if not image_url: raise ValueError('The article does not expose a main image')
    first=_checked(engine,article_url,image_url)
    class Redirects(HTTPRedirectHandler):
        def redirect_request(self,req,fp,code,msg,headers,newurl):
            _checked(engine,article_url,newurl)
            return super().redirect_request(req,fp,code,msg,headers,newurl)
    request=Request(first,headers={'User-Agent':'KianiExchange-NewsSelectorTrial/1.0','Accept':'image/jpeg,image/png,image/webp'})
    with build_opener(Redirects()).open(request,timeout=20) as response:
        _checked(engine,article_url,response.geturl())
        if response.headers.get_content_type() not in {'image/jpeg','image/png','image/webp'}:
            raise ValueError('Unsupported image content type')
        raw=response.read(LIMIT+1)
    if not raw or len(raw)>LIMIT: raise ValueError('Image is empty or too large')
    with Image.open(BytesIO(raw)) as image:
        if image.width<256 or image.height<128 or image.width*image.height>40_000_000:
            raise ValueError('Image dimensions are not suitable')
        image.verify()
    with Image.open(BytesIO(raw)) as image:
        rendered=ImageOps.exif_transpose(image).convert('RGB')
        rendered.thumbnail((1920,1920),Image.Resampling.LANCZOS)
        target=Path(destination)
        if target.exists() or target.is_symlink(): raise ValueError('Image destination already exists')
        rendered.save(target,format='JPEG',quality=93)
        target.chmod(0o600)
    return target

