from __future__ import annotations
import hashlib, json, os, re, shutil, subprocess, tempfile, time, urllib.error, urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Optional

MEDIA_EXTENSIONS={'.mp4','.mkv','.mov','.webm','.m4v','.avi','.ts','.mts','.m2ts'}
SUBTITLE_EXTENSIONS=('.srt','.ass','.vtt')
STATE_FILE='.auto-fansub-state.json'; CACHE_DIR='.auto-fansub-cache'; TM_FILE='.auto-fansub-tm.json'
Progress=Callable[[str,float,str],None]; Cancel=Callable[[],bool]
class CancelledError(RuntimeError): pass

@dataclass
class SubtitleItem:
    start: float; end: float; source: str; translated: str=''
@dataclass
class Job:
    media: Path; subtitle: Optional[Path]=None; relative_path: Optional[Path]=None; status: str='pending'; message: str=''
@dataclass
class Settings:
    target_language:str='Simplified Chinese'; recursive:bool=False; keep_source:bool=True
    translation_provider:str='openai_compatible'; translation_base_url:str='https://api.openai.com/v1'; translation_api_key:str=''; translation_model:str='gpt-4.1-mini'; translation_batch_size:int=24; translation_retries:int=3; translation_timeout:int=180
    translation_prompt:str='You are a professional fansub translator. Translate naturally and concisely for on-screen subtitles. Return only a JSON array of translated strings in the same order.'
    glossary_path:str=''; asr_model:str='small'; asr_device:str='auto'; asr_compute_type:str='auto'; asr_language:str='auto'
    font_name:str='Noto Sans CJK SC'; translation_font_size:int=54; source_font_size:int=32; outline:float=3.2; shadow:float=0.8
    video_codec:str='auto'; crf:int=18; preset:str='medium'; audio_bitrate:str='192k'; output_suffix:str='.fansub'; skip_unchanged:bool=True; cache_intermediate:bool=True; use_translation_memory:bool=True
    max_cps:float=20.0; max_chars_per_line:int=24; min_duration:float=0.35
    @classmethod
    def from_file(cls,p:Path):
        try: raw=json.loads(p.read_text('utf-8')) if p.exists() else {}
        except Exception: raw={}
        allowed=cls.__dataclass_fields__; return cls(**{k:v for k,v in raw.items() if k in allowed})
    def save(self,p:Path):
        d=asdict(self); d['translation_api_key']=''; _atomic_json(p,d)
    def public_dict(self):
        d=asdict(self); d.pop('translation_api_key',None); return d

def _cancel(c):
    if c and c(): raise CancelledError('Cancelled')
def _sha(x): return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def _sig(p:Optional[Path]):
    if not p:return None
    s=p.stat(); return {'path':str(p.resolve()),'size':s.st_size,'mtime_ns':s.st_mtime_ns}
def _atomic_json(p:Path,obj):
    p.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=p.parent,delete=False) as f:
        json.dump(obj,f,ensure_ascii=False,indent=2,sort_keys=True); name=f.name
    Path(name).replace(p)

def find_sidecar_subtitle(media:Path):
    for ext in SUBTITLE_EXTENSIONS:
        p=media.with_suffix(ext)
        if p.exists(): return p
    cand=[p for p in media.parent.glob(media.stem+'.*') if p.suffix.lower() in SUBTITLE_EXTENSIONS]
    pref=('ja','jp','en','zh-cn','zh-hans','zh','chs')
    def rank(p):
        parts=re.split(r'[._\-\s]+',p.stem.lower()); return next((i for i,t in enumerate(pref) if t in parts or t in p.stem.lower()),999),p.name.lower()
    return sorted(cand,key=rank)[0] if cand else None

def discover_jobs(folder:Path,recursive=False,output_dir:Path|None=None):
    folder=folder.resolve(); out=output_dir.resolve() if output_dir else None
    it=folder.rglob('*') if recursive else folder.iterdir(); rows=[]
    for p in it:
        if not p.is_file() or p.suffix.lower() not in MEDIA_EXTENSIONS or p.stem.lower().endswith('.fansub'): continue
        rp=p.resolve()
        if out and (rp==out or out in rp.parents): continue
        rel=rp.relative_to(folder); rows.append(Job(p,find_sidecar_subtitle(p),rel))
    return sorted(rows,key=lambda j:str(j.media).lower())

def parse_timestamp(s:str):
    parts=s.strip().replace(',','.').split(':');
    if len(parts)==2: parts=['0']+parts
    if len(parts)!=3: raise ValueError(s)
    return int(parts[0])*3600+int(parts[1])*60+float(parts[2])
def parse_srt(text:str):
    out=[]; pat=re.compile(r'(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})')
    for b in re.split(r'\n\s*\n',text.replace('\r','\n').strip()):
        ls=[x for x in b.splitlines() if x.strip()]; idx=next((i for i,x in enumerate(ls) if pat.search(x)),None)
        if idx is None: continue
        m=pat.search(ls[idx]); body='\n'.join(ls[idx+1:]).strip()
        if body: out.append(SubtitleItem(parse_timestamp(m.group(1)),parse_timestamp(m.group(2)),body))
    return out
def parse_vtt(text:str):
    text=re.sub(r'^\ufeff?WEBVTT[^\n]*\n+','',text.replace('\r','\n')); out=[]
    pat=re.compile(r'((?:\d{1,2}:)?\d{2}:\d{2}\.\d{1,3})\s*-->\s*((?:\d{1,2}:)?\d{2}:\d{2}\.\d{1,3})')
    for b in re.split(r'\n\s*\n',text.strip()):
        ls=b.splitlines(); idx=next((i for i,x in enumerate(ls) if pat.search(x)),None)
        if idx is None: continue
        m=pat.search(ls[idx]); body=re.sub(r'<[^>]+>','','\n'.join(ls[idx+1:])).strip()
        if body: out.append(SubtitleItem(parse_timestamp(m.group(1)),parse_timestamp(m.group(2)),body))
    return out
def parse_ass_dialogues(text:str):
    out=[]; events=False
    for l in text.replace('\r','').splitlines():
        if l.strip().lower()=='[events]': events=True; continue
        if l.startswith('[') and l.strip().lower()!='[events]': events=False
        if events and l.lower().startswith('dialogue:'):
            parts=l.split(':',1)[1].lstrip().split(',',9)
            if len(parts)==10:
                body=re.sub(r'\{[^}]*\}','','%s'%parts[9]).replace('\\N','\n').strip()
                if body: out.append(SubtitleItem(parse_timestamp(parts[1]),parse_timestamp(parts[2]),body))
    return out
def load_subtitles(p:Path):
    t=p.read_text('utf-8-sig',errors='replace'); return {'.srt':parse_srt,'.vtt':parse_vtt,'.ass':parse_ass_dialogues}[p.suffix.lower()](t)
def normalize_subtitles(items):
    out=[]; seen=set()
    for x in items:
        src=re.sub(r'[ \t]+',' ',x.source.strip()); start=max(0,float(x.start)); end=max(start+.05,float(x.end)); k=(round(start,2),round(end,2),src)
        if src and k not in seen: seen.add(k); out.append(SubtitleItem(start,end,src,x.translated.strip()))
    return out

def load_glossary(path:str):
    if not path:return {}
    p=Path(path).expanduser();
    if not p.exists(): return {}
    if p.suffix.lower()=='.json':
        raw=json.loads(p.read_text('utf-8')); return {str(k):str(v) for k,v in raw.items()}
    out={}
    for l in p.read_text('utf-8').splitlines():
        l=l.strip()
        if not l or l.startswith('#'):continue
        if '\t' in l:a,b=l.split('\t',1)
        elif '=' in l:a,b=l.split('=',1)
        else:continue
        out[a.strip()]=b.strip()
    return out

def load_tm(output:Path):
    p=output/TM_FILE
    try:r=json.loads(p.read_text('utf-8')) if p.exists() else {}; return r if isinstance(r,dict) else {}
    except Exception:return {}
def save_tm(output:Path,tm): _atomic_json(output/TM_FILE,tm)
def _tm_key(src,target): return _sha({'s':re.sub(r'\s+',' ',src.strip()),'t':target})

def transcribe(media:Path,s:Settings,progress=None,cancel=None):
    _cancel(cancel)
    try: from faster_whisper import WhisperModel
    except ImportError as e: raise RuntimeError('Install faster-whisper or provide sidecar subtitles') from e
    m=WhisperModel(s.asr_model,device=s.asr_device,compute_type=s.asr_compute_type); lang=None if s.asr_language=='auto' else s.asr_language
    segs,_=m.transcribe(str(media),language=lang,vad_filter=True); out=[]
    for i,x in enumerate(segs):
        _cancel(cancel); out.append(SubtitleItem(float(x.start),float(x.end),x.text.strip()));
        if progress: progress('asr',0.0,f'{i+1} segments')
    return out

def _translate_batch(texts,s,glossary,cancel):
    if s.translation_provider=='none': return list(texts)
    glossary_text='\n'.join(f'{k} => {v}' for k,v in glossary.items())
    prompt=s.translation_prompt+(f'\nMandatory glossary:\n{glossary_text}' if glossary_text else '')+'\nInput JSON array:\n'+json.dumps(texts,ensure_ascii=False)
    payload=json.dumps({'model':s.translation_model,'messages':[{'role':'user','content':prompt}],'temperature':0.2}).encode()
    url=s.translation_base_url.rstrip('/')+'/chat/completions'; headers={'Content-Type':'application/json'}
    if s.translation_api_key: headers['Authorization']='Bearer '+s.translation_api_key
    last=None
    for n in range(max(1,s.translation_retries+1)):
        _cancel(cancel)
        try:
            with urllib.request.urlopen(urllib.request.Request(url,payload,headers),timeout=s.translation_timeout) as r: raw=json.loads(r.read())
            content=raw['choices'][0]['message']['content'].strip(); m=re.search(r'\[[\s\S]*\]',content); vals=json.loads(m.group(0) if m else content)
            if not isinstance(vals,list) or len(vals)!=len(texts): raise ValueError('Translation count mismatch')
            return [str(x).strip() for x in vals]
        except Exception as e:
            last=e
            if n<s.translation_retries: time.sleep(min(8,2**n))
    raise RuntimeError(f'Translation failed: {last}')

def translate_items(items,s,output:Path,progress=None,cancel=None):
    tm=load_tm(output) if s.use_translation_memory else {}; glossary=load_glossary(s.glossary_path); misses=[]
    for i,x in enumerate(items):
        k=_tm_key(x.source,s.target_language)
        if k in tm: x.translated=str(tm[k]['translation'])
        else: misses.append(i)
    for off in range(0,len(misses),max(1,s.translation_batch_size)):
        _cancel(cancel); ids=misses[off:off+s.translation_batch_size]; vals=_translate_batch([items[i].source for i in ids],s,glossary,cancel)
        for i,v in zip(ids,vals):
            items[i].translated=v; tm[_tm_key(items[i].source,s.target_language)]={'source':items[i].source,'translation':v,'target':s.target_language,'updated_at':int(time.time())}
        if progress: progress('translate',(off+len(ids))/max(1,len(misses)),f'{off+len(ids)}/{len(misses)} translated')
    if s.use_translation_memory: save_tm(output,tm)

def qc_subtitles(items,s:Settings):
    issues=[]
    for i,x in enumerate(items,1):
        text=x.translated or x.source; dur=max(.001,x.end-x.start); chars=len(re.sub(r'\s+','',text)); cps=chars/dur
        if dur<s.min_duration: issues.append({'index':i,'kind':'short_duration','value':round(dur,3),'limit':s.min_duration})
        if cps>s.max_cps: issues.append({'index':i,'kind':'high_cps','value':round(cps,1),'limit':s.max_cps})
        if any(len(line)>s.max_chars_per_line for line in text.splitlines()): issues.append({'index':i,'kind':'long_line','value':max(map(len,text.splitlines())),'limit':s.max_chars_per_line})
    return issues

def _ass_time(x):
    cs=round(x*100); h,cs=divmod(cs,360000); m,cs=divmod(cs,6000); sec,cs=divmod(cs,100); return f'{h}:{m:02}:{sec:02}.{cs:02}'
def _esc(s): return s.replace('{','（').replace('}','）').replace('\n','\\N')
def render_ass(items,s:Settings,title='Fansub'):
    head=f'''[Script Info]\nTitle: {title}\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\n\n[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\nStyle: Translation,{s.font_name},{s.translation_font_size},&H00FFFFFF,&H000000FF,&H00101010,&H64000000,0,0,0,0,100,100,0,0,1,{s.outline},{s.shadow},2,80,80,68,1\nStyle: Source,{s.font_name},{s.source_font_size},&H00D8D8D8,&H000000FF,&H00101010,&H64000000,0,0,0,0,100,100,0,0,1,{s.outline},{s.shadow},2,80,80,28,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'''
    lines=[]
    for x in items:
        tr=x.translated or x.source; lines.append(f'Dialogue: 0,{_ass_time(x.start)},{_ass_time(x.end)},Translation,,0,0,0,,{_esc(tr)}')
        if s.keep_source and x.translated and x.translated!=x.source: lines.append(f'Dialogue: 1,{_ass_time(x.start)},{_ass_time(x.end)},Source,,0,0,0,,{_esc(x.source)}')
    return head+'\n'.join(lines)+'\n'

def detect_video_codec(requested='auto'):
    if requested!='auto': return requested
    try: enc=subprocess.check_output(['ffmpeg','-hide_banner','-encoders'],text=True,stderr=subprocess.STDOUT,errors='ignore')
    except Exception:return 'libx264'
    for codec in ('h264_nvenc','h264_videotoolbox','h264_vaapi'):
        if re.search(r'\b'+re.escape(codec)+r'\b',enc): return codec
    return 'libx264'
def require_ffmpeg():
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'): raise RuntimeError('ffmpeg/ffprobe not found in PATH')
def probe_duration(media:Path):
    try:return float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(media)],text=True).strip())
    except Exception:return 0.0

def burn_subtitles(media:Path,ass:Path,out:Path,s:Settings,progress=None,cancel=None):
    require_ffmpeg(); out.parent.mkdir(parents=True,exist_ok=True); dur=probe_duration(media); codec=detect_video_codec(s.video_codec)
    with tempfile.TemporaryDirectory(prefix='auto-fansub-',dir=ass.parent) as td:
        tmp=Path(td)/'subtitle.ass'; shutil.copyfile(ass,tmp)
        cmd=['ffmpeg','-y','-hide_banner','-loglevel','error','-i',str(media.resolve()),'-vf','ass=subtitle.ass','-c:v',codec]
        if codec=='libx264': cmd+=['-preset',s.preset,'-crf',str(s.crf)]
        elif codec=='h264_nvenc': cmd+=['-preset','p5','-cq',str(s.crf)]
        cmd+=['-c:a','aac','-b:a',s.audio_bitrate,'-movflags','+faststart','-progress','pipe:1','-nostats',str(out.resolve())]
        p=subprocess.Popen(cmd,cwd=td,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace')
        last=''
        try:
            for line in p.stdout or []:
                _cancel(cancel); line=line.strip(); last=line or last
                if progress and line.startswith('out_time=') and dur:
                    try: progress('burn',min(.99,parse_timestamp(line.split('=',1)[1])/dur),f'codec={codec}')
                    except: pass
            rc=p.wait()
        except CancelledError:
            p.terminate(); out.unlink(missing_ok=True); raise
        if rc: out.unlink(missing_ok=True); raise RuntimeError(f'ffmpeg failed: {last}')

def job_output_paths(job,output,s):
    parent=job.relative_path.parent if job.relative_path else Path('.'); d=output/parent; stem=job.media.stem
    tag={'simplified chinese':'zh-CN','traditional chinese':'zh-TW','english':'en','japanese':'ja'}.get(s.target_language.lower(),'translated')
    return d/f'{stem}.{tag}.ass', d/f'{stem}{s.output_suffix}.mp4'
def _fingerprint(job,s):
    return _sha({'media':_sig(job.media),'subtitle':_sig(job.subtitle),'settings':s.public_dict()})
def process_job(job:Job,output:Path,s:Settings,progress=None,cancel=None,force=False):
    output.mkdir(parents=True,exist_ok=True); _cancel(cancel); ass,video=job_output_paths(job,output,s); fp=_fingerprint(job,s)
    state_path=output/STATE_FILE
    try: state=json.loads(state_path.read_text('utf-8')) if state_path.exists() else {'jobs':{}}
    except: state={'jobs':{}}
    prev=state.get('jobs',{}).get(str(job.media.resolve()),{})
    if s.skip_unchanged and not force and prev.get('fingerprint')==fp and ass.exists() and video.exists(): job.status='skipped'; job.message=str(video); return ass,video
    cache=output/CACHE_DIR/(fp+'.json'); items=None
    if s.cache_intermediate and cache.exists() and not force:
        try: items=[SubtitleItem(**x) for x in json.loads(cache.read_text('utf-8'))['items']]
        except: items=None
    if not items:
        items=normalize_subtitles(load_subtitles(job.subtitle) if job.subtitle else transcribe(job.media,s,progress,cancel)); translate_items(items,s,output,progress,cancel)
        if s.cache_intermediate: _atomic_json(cache,{'items':[asdict(x) for x in items]})
    issues=qc_subtitles(items,s); ass.parent.mkdir(parents=True,exist_ok=True); ass.write_text(render_ass(items,s,job.media.name),'utf-8-sig'); _atomic_json(ass.with_suffix('.qc.json'),{'issues':issues})
    burn_subtitles(job.media,ass,video,s,progress,cancel)
    state.setdefault('jobs',{})[str(job.media.resolve())]={'fingerprint':fp,'video':str(video),'updated_at':int(time.time()),'qc_issues':len(issues)}; _atomic_json(state_path,state)
    job.status='done'; job.message=f'{video} ({len(issues)} QC issues)'; return ass,video
