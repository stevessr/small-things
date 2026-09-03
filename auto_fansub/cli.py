from __future__ import annotations
import argparse, os
from pathlib import Path
try:
    from .core import CancelledError, Settings, discover_jobs, job_output_paths, process_job, detect_video_codec
except ImportError:
    from core import CancelledError, Settings, discover_jobs, job_output_paths, process_job, detect_video_codec

def build_parser():
    p=argparse.ArgumentParser(description='Batch ASR/translation/typesetting/hardsub pipeline')
    p.add_argument('folder',type=Path); p.add_argument('-o','--output',type=Path); p.add_argument('--recursive',action='store_true'); p.add_argument('--scan-only',action='store_true')
    p.add_argument('--target'); p.add_argument('--provider',choices=('openai_compatible','none')); p.add_argument('--base-url'); p.add_argument('--api-key'); p.add_argument('--model'); p.add_argument('--batch-size',type=int); p.add_argument('--retries',type=int)
    p.add_argument('--asr-model'); p.add_argument('--asr-language'); p.add_argument('--glossary',type=Path); p.add_argument('--font'); p.add_argument('--mono',action='store_true')
    p.add_argument('--force',action='store_true'); p.add_argument('--no-cache',action='store_true'); p.add_argument('--no-skip',action='store_true'); p.add_argument('--no-tm',action='store_true')
    p.add_argument('--codec',choices=('auto','libx264','h264_nvenc','h264_videotoolbox','h264_vaapi')); p.add_argument('--max-cps',type=float); p.add_argument('--max-line',type=int); p.add_argument('--min-duration',type=float)
    return p

def main(argv=None):
    a=build_parser().parse_args(argv); s=Settings(); s.recursive=a.recursive; s.translation_api_key=a.api_key if a.api_key is not None else os.getenv('OPENAI_API_KEY','')
    if a.target:s.target_language=a.target
    if a.provider:s.translation_provider=a.provider
    if a.base_url:s.translation_base_url=a.base_url
    if a.model:s.translation_model=a.model
    if a.batch_size is not None:s.translation_batch_size=max(1,a.batch_size)
    if a.retries is not None:s.translation_retries=max(0,a.retries)
    if a.asr_model:s.asr_model=a.asr_model
    if a.asr_language:s.asr_language=a.asr_language
    if a.glossary:s.glossary_path=str(a.glossary.expanduser().resolve())
    if a.font:s.font_name=a.font
    if a.mono:s.keep_source=False
    if a.no_cache:s.cache_intermediate=False
    if a.no_skip:s.skip_unchanged=False
    if a.no_tm:s.use_translation_memory=False
    if a.codec:s.video_codec=a.codec
    if a.max_cps is not None:s.max_cps=max(1,a.max_cps)
    if a.max_line is not None:s.max_chars_per_line=max(1,a.max_line)
    if a.min_duration is not None:s.min_duration=max(.05,a.min_duration)
    folder=a.folder.expanduser(); out=(a.output or folder/'fansub-output').expanduser(); jobs=discover_jobs(folder,a.recursive,out)
    if not jobs: print('No media files found.'); return 2
    if a.scan_only:
        print('encoder:',detect_video_codec(s.video_codec))
        for i,j in enumerate(jobs,1):
            ass,video=job_output_paths(j,out,s); print(f'[{i}/{len(jobs)}] {j.media} | source={j.subtitle.name if j.subtitle else "ASR"} | output={video}')
        return 0
    failed=skipped=0
    try:
        for i,j in enumerate(jobs,1):
            print(f'[{i}/{len(jobs)}] {j.media}')
            try:
                process_job(j,out,s,lambda stage,v,msg: print(f'  {stage:10} {v:6.1%} {msg[:100]:100}',end='\r',flush=True),force=a.force)
                if j.status=='skipped': skipped+=1
                print(f'\n  -> {j.status}: {j.message}')
            except CancelledError: print('\nCancelled.'); return 130
            except Exception as e: failed+=1; print(f'\n  FAILED: {e}')
    except KeyboardInterrupt: print('\nCancelled.'); return 130
    print(f'Done: {len(jobs)-failed-skipped} processed, {skipped} skipped, {failed} failed; output={out}')
    return 1 if failed else 0
if __name__=='__main__': raise SystemExit(main())
