from __future__ import annotations
import os, queue, threading, tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
try:
    from .core import Settings, discover_jobs, process_job, detect_video_codec, CancelledError
except ImportError:
    from core import Settings, discover_jobs, process_job, detect_video_codec, CancelledError

CONFIG=Path.home()/'.small-things-auto-fansub'/'config.json'
class App(tk.Tk):
    def __init__(self):
        super().__init__(); self.title('自动烤肉与嵌字'); self.geometry('1050x760'); self.minsize(900,650)
        self.s=Settings.from_file(CONFIG); self.jobs=[]; self.q=queue.Queue(); self.cancel_evt=threading.Event(); self.running=False
        self.vars={
            'input':tk.StringVar(), 'output':tk.StringVar(), 'target':tk.StringVar(value=self.s.target_language),
            'base':tk.StringVar(value=self.s.translation_base_url), 'key':tk.StringVar(value=os.getenv('OPENAI_API_KEY','')),
            'model':tk.StringVar(value=self.s.translation_model), 'glossary':tk.StringVar(value=self.s.glossary_path),
            'recursive':tk.BooleanVar(value=self.s.recursive), 'bilingual':tk.BooleanVar(value=self.s.keep_source),
            'tm':tk.BooleanVar(value=self.s.use_translation_memory), 'cache':tk.BooleanVar(value=self.s.cache_intermediate),
            'skip':tk.BooleanVar(value=self.s.skip_unchanged), 'codec':tk.StringVar(value=self.s.video_codec),
            'font':tk.StringVar(value=self.s.font_name), 'cps':tk.DoubleVar(value=self.s.max_cps), 'line':tk.IntVar(value=self.s.max_chars_per_line)
        }
        self._build(); self.after(100,self._poll); self.protocol('WM_DELETE_WINDOW',self._close)
    def _row(self,parent,label,var,browse=None,show=None):
        f=ttk.Frame(parent); f.pack(fill='x',pady=3); ttk.Label(f,text=label,width=17).pack(side='left'); ttk.Entry(f,textvariable=var,show=show).pack(side='left',fill='x',expand=True)
        if browse: ttk.Button(f,text='选择',command=browse).pack(side='left',padx=(6,0))
    def _build(self):
        root=ttk.Frame(self,padding=12); root.pack(fill='both',expand=True)
        io=ttk.LabelFrame(root,text='项目'); io.pack(fill='x'); self._row(io,'输入文件夹',self.vars['input'],self._pick_input); self._row(io,'输出文件夹',self.vars['output'],self._pick_output); self._row(io,'术语表',self.vars['glossary'],self._pick_glossary)
        opts=ttk.LabelFrame(root,text='翻译 / 排版 / 编码'); opts.pack(fill='x',pady=8)
        self._row(opts,'目标语言',self.vars['target']); self._row(opts,'API Base URL',self.vars['base']); self._row(opts,'API Key',self.vars['key'],show='•'); self._row(opts,'模型',self.vars['model']); self._row(opts,'字体',self.vars['font'])
        f=ttk.Frame(opts); f.pack(fill='x',pady=3); ttk.Label(f,text='视频编码器',width=17).pack(side='left'); ttk.Combobox(f,textvariable=self.vars['codec'],values=['auto','libx264','h264_nvenc','h264_videotoolbox','h264_vaapi'],state='readonly').pack(side='left'); self.codec_label=ttk.Label(f,text=f'自动探测: {detect_video_codec("auto")}'); self.codec_label.pack(side='left',padx=12)
        qf=ttk.Frame(opts); qf.pack(fill='x',pady=3); ttk.Label(qf,text='QC 阈值',width=17).pack(side='left'); ttk.Label(qf,text='CPS').pack(side='left'); ttk.Spinbox(qf,from_=5,to=60,textvariable=self.vars['cps'],width=7).pack(side='left',padx=4); ttk.Label(qf,text='每行字符').pack(side='left'); ttk.Spinbox(qf,from_=10,to=80,textvariable=self.vars['line'],width=7).pack(side='left',padx=4)
        flags=ttk.Frame(root); flags.pack(fill='x');
        for text,key in [('递归扫描','recursive'),('双语字幕','bilingual'),('Translation Memory','tm'),('缓存中间结果','cache'),('跳过未变化','skip')]: ttk.Checkbutton(flags,text=text,variable=self.vars[key]).pack(side='left',padx=(0,14))
        actions=ttk.Frame(root); actions.pack(fill='x',pady=8); ttk.Button(actions,text='扫描',command=self.scan).pack(side='left'); self.run_btn=ttk.Button(actions,text='一键烤肉并嵌字',command=self.run); self.run_btn.pack(side='left',padx=6); self.cancel_btn=ttk.Button(actions,text='取消',command=self.cancel,state='disabled'); self.cancel_btn.pack(side='left'); self.progress=ttk.Progressbar(actions,maximum=100); self.progress.pack(side='left',fill='x',expand=True,padx=12)
        self.tree=ttk.Treeview(root,columns=('src','status','msg'),show='headings',height=12); self.tree.heading('src',text='素材/字幕'); self.tree.heading('status',text='状态'); self.tree.heading('msg',text='信息'); self.tree.column('src',width=420); self.tree.column('status',width=90); self.tree.column('msg',width=400); self.tree.pack(fill='both',expand=True)
        self.log=tk.Text(root,height=8,wrap='word'); self.log.pack(fill='both',expand=True,pady=(8,0))
    def _pick_input(self):
        p=filedialog.askdirectory();
        if p: self.vars['input'].set(p); self.vars['output'].set(str(Path(p)/'fansub-output'))
    def _pick_output(self):
        p=filedialog.askdirectory();
        if p:self.vars['output'].set(p)
    def _pick_glossary(self):
        p=filedialog.askopenfilename(filetypes=[('Glossary','*.json *.tsv *.txt'),('All','*')]);
        if p:self.vars['glossary'].set(p)
    def settings(self):
        s=self.s; s.target_language=self.vars['target'].get().strip(); s.translation_base_url=self.vars['base'].get().strip(); s.translation_api_key=self.vars['key'].get(); s.translation_model=self.vars['model'].get().strip(); s.glossary_path=self.vars['glossary'].get().strip(); s.recursive=self.vars['recursive'].get(); s.keep_source=self.vars['bilingual'].get(); s.use_translation_memory=self.vars['tm'].get(); s.cache_intermediate=self.vars['cache'].get(); s.skip_unchanged=self.vars['skip'].get(); s.video_codec=self.vars['codec'].get(); s.font_name=self.vars['font'].get().strip(); s.max_cps=float(self.vars['cps'].get()); s.max_chars_per_line=int(self.vars['line'].get()); return s
    def scan(self):
        try:
            inp=Path(self.vars['input'].get()).expanduser(); out=Path(self.vars['output'].get() or inp/'fansub-output').expanduser(); self.vars['output'].set(str(out)); self.jobs=discover_jobs(inp,self.vars['recursive'].get(),out)
        except Exception as e: messagebox.showerror('扫描失败',str(e)); return
        for x in self.tree.get_children(): self.tree.delete(x)
        for i,j in enumerate(self.jobs): self.tree.insert('', 'end', iid=str(i), values=(f'{j.relative_path} | {j.subtitle.name if j.subtitle else "ASR"}','pending',''))
        self._log(f'扫描到 {len(self.jobs)} 个视频')
    def run(self):
        if self.running:return
        if not self.jobs:self.scan()
        if not self.jobs:return
        self.running=True; self.cancel_evt.clear(); self.run_btn.config(state='disabled'); self.cancel_btn.config(state='normal'); s=self.settings(); s.save(CONFIG); out=Path(self.vars['output'].get())
        threading.Thread(target=self._worker,args=(s,out),daemon=True).start()
    def _worker(self,s,out):
        total=len(self.jobs)
        for idx,j in enumerate(self.jobs):
            if self.cancel_evt.is_set(): break
            self.q.put(('row',idx,'running',''))
            try:
                def cb(stage,v,msg): self.q.put(('progress',(idx+v)/total*100,f'{j.media.name}: {stage} {msg}'))
                process_job(j,out,s,cb,self.cancel_evt.is_set); self.q.put(('row',idx,j.status,j.message))
            except CancelledError: self.q.put(('row',idx,'cancelled','已取消')); break
            except Exception as e: self.q.put(('row',idx,'failed',str(e)))
        self.q.put(('done',))
    def cancel(self): self.cancel_evt.set(); self._log('正在取消…')
    def _poll(self):
        try:
            while True:
                e=self.q.get_nowait()
                if e[0]=='row': self.tree.set(str(e[1]),'status',e[2]); self.tree.set(str(e[1]),'msg',e[3]); self._log(f'[{e[2]}] {e[3]}')
                elif e[0]=='progress': self.progress['value']=e[1]; self._log(e[2])
                elif e[0]=='done': self.running=False; self.run_btn.config(state='normal'); self.cancel_btn.config(state='disabled'); self.progress['value']=100
        except queue.Empty: pass
        self.after(100,self._poll)
    def _log(self,x): self.log.insert('end',x+'\n'); self.log.see('end')
    def _close(self):
        if self.running:self.cancel_evt.set()
        self.destroy()
if __name__=='__main__': App().mainloop()
