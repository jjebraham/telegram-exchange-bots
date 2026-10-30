import io
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import instagram_reel_stock as stock

def image_bytes(n):
    b=io.BytesIO()
    Image.new('RGB',(600,400),(n*17%255,n*33%255,n*55%255)).save(b,'JPEG')
    return b.getvalue()

class StockChecks(unittest.TestCase):
    def setUp(self):
        self.requests=[]
        self.pexels = {'photos': [
            {'id':i,'photographer':'Photographer '+str(i),
             'url':'https://www.pexels.com/photo/test-'+str(i)+'/',
             'src':{'large2x':'https://images.pexels.com/photos/'+str(i)+'/img.jpg'}}
            for i in range(1,11)]}
        self.pixabay = {'hits': [
            {'id':i,'user':'Creator '+str(i),
             'pageURL':'https://pixabay.com/photos/test-'+str(i)+'/',
             'largeImageURL':'https://pixabay.com/get/'+str(i)+'.jpg'}
            for i in range(11,16)]}
    def read(self,url,**kwargs):
        self.requests.append(url)
        host=urlsplit(url).hostname
        if host=='api.pexels.com':
            return json.dumps(self.pexels).encode()
        if host=='pixabay.com' and urlsplit(url).path=='/api/':
            return json.dumps(self.pixabay).encode()
        number=int(urlsplit(url).path.split('/')[-2] if host=='images.pexels.com'
                   else urlsplit(url).path.rsplit('/',1)[-1].split('.')[0])
        return image_bytes(number)
    def test_admin_uses_both_providers_and_avoids_recent_images(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(stock,'_read',side_effect=self.read), \
             patch.object(stock,'_key',return_value='test-api-key'):
            root=Path(tmp); first=root/'first'; first.mkdir()
            story={'title_original':'Bitcoin crypto security concerns'}
            images=stock.collect(story,first,origin='admin_direct',state=root,limit=7)
            self.assertEqual(len(images),7)
            self.assertEqual({item['kind'] for item in images},{'illustrative'})
            self.assertTrue(any('api.pexels.com' in u for u in self.requests))
            self.assertTrue(any('pixabay.com/api/' in u for u in self.requests))
            stock.mark_used(images,state=root)
            previous={(v['provider'],v['id']) for v in images}
            second=root/'second'; second.mkdir()
            self.requests=[]
            again=stock.collect(story,second,origin='admin_direct',state=root,limit=5)
            self.assertTrue(previous.isdisjoint({(v['provider'],v['id']) for v in again}))
            self.assertFalse(any('/api/' in url or 'api.pexels.com' in url for url in self.requests))
            with closing(sqlite3.connect(root/'stock-images.sqlite3')) as con:
                data=' '.join(str(r) for r in con.execute('SELECT * FROM search_cache'))
                self.assertNotIn('test-api-key',data)
    def test_scheduled_reels_do_not_query_pixabay(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(stock,'_read',side_effect=self.read), \
             patch.object(stock,'_key',return_value='test-api-key'):
            root=Path(tmp)
            result=stock.collect({'title_original':'Bitcoin news'},root,origin='daily_top_story',state=root,limit=3)
            self.assertEqual(len(result),3)
            self.assertTrue(all(v['provider']=='pexels' for v in result))
            self.assertFalse(any('pixabay.com' in u for u in self.requests))
    def test_host_restrictions_and_unknown_topic(self):
        self.pexels['photos'][0]['src']['large2x']='https://evil.example/file.jpg'
        self.assertNotIn('1',{v['id'] for v in stock._candidates('pexels',self.pexels)})
        self.assertEqual(stock.queries({'title_original':'A completely unrelated headline'}),[])
        self.assertFalse(stock._safe_url('https://images.pexels.com.evil.test/file','images.pexels.com'))

if __name__ == '__main__':
    unittest.main()
