#!/usr/bin/env python3
"""Offline tests for the targeted automatic-news changes."""
import argparse
import ast
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import types
from unittest.mock import patch

p=argparse.ArgumentParser()
p.add_argument('--runtime',required=True,type=Path)
p.add_argument('--repo',type=Path,default=Path.home()/'telegram_bot_repo')
p.add_argument('--original',type=Path)
args=p.parse_args()
root=args.runtime.resolve()
patched=root/'deploy/instagram-trial-reels/automatic_ranked_news_images.py'
old=(args.original.read_text(encoding='utf-8') if args.original else
     subprocess.check_output(['git','-C',str(args.repo),'show',
        'a22cb107c66c366a50127aee49d13cb6bb44f7f2:instagram_ranked_news.py'],timeout=20).decode())
original=ast.parse(old); modified=ast.parse(patched.read_text(encoding='utf-8'))
def functions(tree):
    return {n.name:n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))}
a,b=functions(original),functions(modified)
if set(a)!=set(b): raise RuntimeError('Automatic selection structure changed.')
for name in set(a)-{'prepare','run'}:
    if ast.dump(a[name]) != ast.dump(b[name]):
        raise RuntimeError('Unrelated automatic-news function changed: '+name)

class RemoveUsageMark(ast.NodeTransformer):
    count=0
    def visit_Try(self,node):
        node=self.generic_visit(node)
        output=[]
        i=0
        while i < len(node.body):
            item=node.body[i]
            if (isinstance(item,ast.Assign) and len(item.targets)==1 and
                isinstance(item.targets[0],ast.Name) and item.targets[0].id=='used' and
                i+1<len(node.body) and isinstance(node.body[i+1],ast.If) and
                isinstance(node.body[i+1].test,ast.Name) and node.body[i+1].test.id=='used'):
                self.count+=1; i+=2; continue
            output.append(item); i+=1
        node.body=output
        return node

transform=RemoveUsageMark()
run=transform.visit(b['run'])
if transform.count != 1 or ast.dump(run)!=ast.dump(a['run']):
    raise RuntimeError('Automatic publication flow changed beyond image history.')

class NewsError(Exception): pass
class SlideImageError(Exception): pass
images=types.ModuleType('instagram_news_slide_images')
images.SlideImageError=SlideImageError
calls=[]
def collect(engine, story, directory, *, origin, minimum):
    calls.append((origin,minimum))
    return [dict(path=directory/'one.jpg',kind='publisher'),
            dict(path=directory/'two.jpg',kind='publisher')]
images.collect=collect
images.caption_credit=lambda items:''
renderer=types.ModuleType('instagram_news_renderer')
renderer.metadata=lambda story:story
def render(stories, output, assets, **kwargs):
    if kwargs.get('minimum_slide_images') != 2 or len(kwargs.get('slide_images',[])) != 2:
        raise RuntimeError('Two required automatic images were not supplied.')
    return ['slide1.jpg','slide2.jpg'],'caption',{'used_slide_images':2}
renderer.render_news=render
with tempfile.TemporaryDirectory(prefix='auto-news-unit-') as tmp:
    scope={'time':time,'NewsError':NewsError,'translate':lambda con,row:('عنوان فارسی','خلاصه فارسی'),
           'engine':object(),'Path':Path,'STATE':Path(tmp),'tempfile':tempfile,'os':os,'VERSION':'test'}
    code=ast.Module(body=[functions(modified)['prepare']],type_ignores=[])
    exec(compile(code,str(patched),'exec'),scope)
    row=dict(article_published_at=time.time(),source_url='https://example.com/news',source_name='Example',
             image_url=None,article_date='',title_original='Example',trial_score=10,components={},coverage_outlets=['Example'])
    with patch.dict(sys.modules,{'instagram_news_renderer':renderer,'instagram_news_slide_images':images}):
        saved,paths,caption,manifest=scope['prepare'](None,row,'crypto',Path(tmp),Path(tmp))
    if calls != [('automatic',2)] or len(paths)!=2 or len(manifest['slide_images'])!=2:
        raise RuntimeError('Automatic news image preflight failed.')
print('Automatic ranking, scheduling, and publication guards unchanged; two-image preparation passed.')
print('Offline check only; no network or publication.')

