import json,tempfile,unittest
from pathlib import Path
from unittest import mock
import core
from core import Settings,SubtitleItem,Job,parse_srt,parse_vtt,parse_ass_dialogues,normalize_subtitles,discover_jobs,qc_subtitles,render_ass,detect_video_codec,translate_items
class Tests(unittest.TestCase):
 def test_srt(self): self.assertEqual(parse_srt('1\n00:00:01,000 --> 00:00:02,500\nhello\n')[0].source,'hello')
 def test_vtt(self): self.assertEqual(parse_vtt('WEBVTT\n\n00:01.000 --> 00:02.000\n<b>x</b>')[0].source,'x')
 def test_ass(self): self.assertEqual(parse_ass_dialogues('[Events]\nDialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,{\\i1}Hi\\Nthere')[0].source,'Hi\nthere')
 def test_scan_excludes_output(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d); (p/'a.mkv').touch(); out=p/'fansub-output'; out.mkdir(); (out/'x.mp4').touch(); self.assertEqual([x.media.name for x in discover_jobs(p,True,out)],['a.mkv'])
 def test_relative_paths(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d); (p/'s').mkdir(); (p/'s'/'01.mkv').touch(); self.assertEqual(str(discover_jobs(p,True)[0].relative_path),'s/01.mkv')
 def test_normalize(self): self.assertGreater(normalize_subtitles([SubtitleItem(-1,-1,' hi  there ')])[0].end,0)
 def test_qc(self):
  s=Settings(max_cps=3,max_chars_per_line=4,min_duration=.5); kinds={x['kind'] for x in qc_subtitles([SubtitleItem(0,.2,'abcdef')],s)}; self.assertEqual(kinds,{'short_duration','high_cps','long_line'})
 def test_ass_render(self): self.assertIn('Translation',render_ass([SubtitleItem(1,2,'hi','你好')],Settings()))
 def test_settings_key_not_saved(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'c.json'; Settings(translation_api_key='secret').save(p); self.assertEqual(json.loads(p.read_text())['translation_api_key'],'')
 def test_codec_explicit(self): self.assertEqual(detect_video_codec('libx264'),'libx264')
 def test_codec_nvenc(self):
  with mock.patch('subprocess.check_output',return_value=' V..... h264_nvenc NVIDIA'):
   self.assertEqual(detect_video_codec('auto'),'h264_nvenc')
 def test_tm_reuse(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d); s=Settings(translation_provider='none',use_translation_memory=True); a=[SubtitleItem(0,1,'hello')]; translate_items(a,s,p); self.assertEqual(a[0].translated,'hello'); self.assertTrue((p/core.TM_FILE).exists())
if __name__=='__main__': unittest.main()
