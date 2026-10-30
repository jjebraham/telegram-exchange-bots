"""Read a publisher's article image for an explicitly authorized local preview."""
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from PIL import Image, ImageOps

LIMIT=10_000_000

def _checked(engine, article_url, image_url):
    source=engine.publisher(engine.checked_url(article_url,article=True))
    image=engine.checked_url(image_url,article=False)
    parts=urlsplit(image)
    approved_cdns = {
        'Cointelegraph': {'s3-images.ctmedia.io'},
        'CNBC': {'image.cnbcfm.com'},
        'Reuters via TradingView': {'s.tradingview.com'},
        'ABC News US': {'i.abcnewsfe.com'},
    }
    coindesk_cdn = (source == 'CoinDesk' and parts.hostname == 'cdn.sanity.io'
                    and parts.path.startswith('/images/s3y3vcno/production/'))
    trusted_host = (engine.publisher(image) == source or coindesk_cdn
                    or parts.hostname in approved_cdns.get(source, set()))
    if not source or not trusted_host or parts.scheme!='https' or parts.username or parts.password or parts.port not in (None,443):
        raise ValueError('Image host is not verified for this publisher')
    return image

def fetch(engine, article_url, image_url, destination, *, timeout=20):
    if not image_url: raise ValueError('The article does not expose a main image')
    first=_checked(engine,article_url,image_url)
    class Redirects(HTTPRedirectHandler):
        def redirect_request(self,req,fp,code,msg,headers,newurl):
            _checked(engine,article_url,newurl)
            return super().redirect_request(req,fp,code,msg,headers,newurl)
    request=Request(first,headers={'User-Agent':'KianiExchange-NewsSelectorTrial/1.0','Accept':'image/jpeg,image/png,image/webp'})
    with build_opener(Redirects()).open(request,timeout=timeout) as response:
        _checked(engine,article_url,response.geturl())
        content_type = response.headers.get_content_type()
        raw=response.read(LIMIT+1)
    if not raw or len(raw)>LIMIT: raise ValueError('Image is empty or too large')
    # CryptoSlate serves WebP bytes as text/plain; require an exact WebP
    # signature and verify the actual image with Pillow below.
    webp = len(raw) >= 12 and raw[:4] == b'RIFF' and raw[8:12] == b'WEBP'
    if content_type not in {'image/jpeg','image/png','image/webp'}:
        if not (engine.publisher(article_url) == 'CryptoSlate' and content_type == 'text/plain' and webp):
            raise ValueError('Unsupported image content type')
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




