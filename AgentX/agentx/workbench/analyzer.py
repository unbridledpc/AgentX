from __future__ import annotations
import ast, json, os, re, shutil, time, zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

SKIP_DIRS={'.git','node_modules','venv','.venv','__pycache__','.cache','dist','build','target','logs'}
BINARY={'.zip','.rar','.7z','.exe','.dll','.so','.png','.jpg','.jpeg','.gif','.webp','.mp4','.db','.sqlite','.pyc'}
RISK=[('critical','possible_secret',r'(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*[\'\"][^\'\"]{8,}'),('high','python_eval_exec',r'\b(eval|exec)\s*\('),('high','python_shell_true',r'shell\s*=\s*True'),('high','lua_shell_execution',r'\b(os\.execute|io\.popen)\s*\('),('high','lua_dynamic_code',r'\b(loadstring|load)\s*\('),('medium','raw_sql_concat',r'(?i)(SELECT|UPDATE|DELETE|INSERT).*(\+|\.\.|format\(|f[\'\"]|%s)'),('medium','tibia_money_flow',r'\b(deposit|withdraw|transfer|addMoney|removeMoney|setBankBalance|getBankBalance)\b'),('medium','tibia_item_creation',r'\b(addItem|createItem|doCreateItem|Game\.createItem)\b')]
CONV=[('auto_generated',r'Auto-generated from'),('todo_implement_converted_logic',r'TODO:\s*Implement logic converted from TFS script'),('todo_map_tfs_api',r'TODO:\s*Map TFS API call'),('devnexus_api_stub',r'from\s+devnexus\s+import\s+api\s+as\s+dn'),('not_implemented',r'NotImplementedError'),('pass_stub',r'^\s*pass\s*(#.*)?$')]

def _safe(base:Path,name:str)->Path:
    n=name.replace('\\','/')
    if n.startswith('/') or n.startswith('../') or '/../' in n: raise ValueError(f'Unsafe ZIP member: {name}')
    p=(base/n).resolve(False); p.relative_to(base.resolve(False)); return p

def _kind(p:Path)->str:
    s=p.suffix.lower(); return {'.py':'python','.lua':'lua','.xml':'xml','.sql':'sql','.json':'json','.yml':'yaml','.yaml':'yaml','.cpp':'cpp_c','.c':'cpp_c','.h':'cpp_c','.hpp':'cpp_c','.sh':'shell','.bat':'windows_script','.ps1':'windows_script','.md':'text','.txt':'text','.toml':'config','.ini':'config','.cfg':'config','.conf':'config'}.get(s,'binary' if s in BINARY else 'unknown')

def _line(t:str,i:int)->int: return t[:i].count('\n')+1

def _snip(t:str,l:int|None)->str:
    if not l: return ''
    a=t.splitlines(); return a[l-1].strip()[:220] if 0<l<=len(a) else ''

def _read(p:Path,limit:int=1000000)->str|None:
    try:
        if p.stat().st_size>limit: return None
        return p.read_text('utf-8','replace')
    except Exception: return None

def extract_zip(zip_path:str|Path,workspace:str|Path,name:str|None=None)->dict[str,Any]:
    zp=Path(zip_path).expanduser().resolve(True); stem=re.sub(r'[^a-zA-Z0-9_.-]+','-',(name or zp.stem)).strip('-._') or 'project'
    root=Path(workspace).expanduser().resolve(False)/'imports'/f'{stem}-{int(time.time())}'
    original=root/'original'; extracted=root/'extracted'; analysis=root/'analysis'
    original.mkdir(parents=True,exist_ok=True); extracted.mkdir(parents=True,exist_ok=True); analysis.mkdir(parents=True,exist_ok=True)
    oz=original/zp.name; shutil.copy2(zp,oz)
    files=0; total=0
    with zipfile.ZipFile(oz) as z:
        for info in z.infolist():
            total+=info.file_size
            if total>4_000_000_000: raise ValueError('ZIP uncompressed size is too large')
            target=_safe(extracted,info.filename)
            if info.is_dir(): target.mkdir(parents=True,exist_ok=True); continue
            target.parent.mkdir(parents=True,exist_ok=True)
            with z.open(info) as src, target.open('wb') as dst: shutil.copyfileobj(src,dst)
            files+=1
    return {'project_id':root.name,'root':str(root),'original_zip':str(oz),'extracted_dir':str(extracted),'analysis_dir':str(analysis),'files_extracted':files,'uncompressed_bytes':total}

def inventory(root:Path)->dict[str,Any]:
    entries=[]; counts={}; total=0; largest=[]
    for cur,dirs,files in os.walk(root):
        dirs[:]=[d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            p=Path(cur)/f; rel=p.relative_to(root).as_posix(); size=p.stat().st_size if p.exists() else 0; kind=_kind(p); ext=p.suffix.lower() or p.name.lower(); deep=ext not in BINARY
            total+=size; counts[kind]=counts.get(kind,0)+1; entries.append({'path':rel,'size':size,'kind':kind,'extension':ext,'deep_scan':deep}); largest.append({'path':rel,'size':size,'kind':kind})
    largest.sort(key=lambda x:x['size'],reverse=True)
    return {'root':str(root),'total_files':len(entries),'total_bytes':total,'counts_by_kind':dict(sorted(counts.items())),'largest_files':largest[:25],'entries':entries}

def analyze_project(project_root:str|Path,analysis_dir:str|Path|None=None)->dict[str,Any]:
    root=Path(project_root).expanduser().resolve(True); analysis=Path(analysis_dir).expanduser().resolve(False) if analysis_dir else root/'analysis'; analysis.mkdir(parents=True,exist_ok=True)
    inv=inventory(root); syntax=[]; risk=[]; conv=[]; stubs=[]; analyzed=0
    for e in inv['entries']:
        if not e['deep_scan']: continue
        p=root/e['path']; text=_read(p)
        if text is None: continue
        analyzed+=1; kind=e['kind']
        try:
            if kind=='python': ast.parse(text,filename=e['path'])
            elif kind=='json': json.loads(text)
            elif kind=='xml': ElementTree.fromstring(text)
        except Exception as ex:
            l=getattr(ex,'lineno',None) or (ex.position[0] if hasattr(ex,'position') else None); syntax.append({'severity':'critical','kind':f'{kind}_syntax','path':e['path'],'line':l,'message':str(ex),'snippet':_snip(text,l)})
        for sev,k,pat in RISK:
            for m in re.finditer(pat,text,re.MULTILINE):
                l=_line(text,m.start()); risk.append({'severity':sev,'kind':k,'path':e['path'],'line':l,'message':f'Matched risk pattern: {k}','snippet':_snip(text,l)})
        for k,pat in CONV:
            for m in re.finditer(pat,text,re.MULTILINE):
                l=_line(text,m.start()); conv.append({'severity':'high' if k.startswith('todo_') else 'medium','kind':k,'path':e['path'],'line':l,'message':f'Converted/server completion marker: {k}','snippet':_snip(text,l)})
        if not text.strip(): stubs.append({'severity':'medium','kind':'empty_file','path':e['path'],'line':None,'message':'File is empty.','snippet':''})
        elif kind=='python' and 'TODO' in text and ('pass' in text or 'Implement logic converted' in text): stubs.append({'severity':'high','kind':'likely_python_stub','path':e['path'],'line':None,'message':'Python file appears to be a placeholder/stub.','snippet':''})
    summary={'root':str(root),'analysis_dir':str(analysis),'analyzed_files':analyzed,'total_files':inv['total_files'],'total_bytes':inv['total_bytes'],'syntax_errors':len(syntax),'risk_findings':len(risk),'conversion_findings':len(conv),'stub_findings':len(stubs),'counts_by_kind':inv['counts_by_kind']}
    for name,payload in {'inventory':inv,'syntax_findings':syntax,'risk_findings':risk,'conversion_findings':conv,'stub_findings':stubs,'summary':summary}.items(): (analysis/f'{name}.json').write_text(json.dumps(payload,indent=2),encoding='utf-8')
    report=render_report(summary,inv,syntax,risk,conv,stubs); (analysis/'final_report.md').write_text(report,encoding='utf-8')
    return {'summary':summary,'final_report_path':str(analysis/'final_report.md')}

def _section(title:str,items:list[dict[str,Any]])->str:
    if not items: return f'## {title}\n\nNo findings.\n'
    rows=[f'## {title}\n','| Severity | Kind | File | Line | Message |','|---|---|---|---:|---|']
    for x in items[:50]: rows.append(f"| {x.get('severity','')} | {x.get('kind','')} | `{x.get('path','')}` | {x.get('line') or ''} | {str(x.get('message',''))[:160]} |")
    if len(items)>50: rows.append(f'\nShowing first 50 of {len(items)} findings.')
    return '\n'.join(rows)+'\n'

def render_report(s:dict[str,Any],inv:dict[str,Any],syntax:list[dict[str,Any]],risk:list[dict[str,Any]],conv:list[dict[str,Any]],stubs:list[dict[str,Any]])->str:
    out=['# AgentX Workbench Project Analysis Report','', '> Private experimental read-only analyzer. No project files were edited.','', '## Summary','',f"- Root: `{s['root']}`",f"- Total files: {s['total_files']}",f"- Analyzed files: {s['analyzed_files']}",f"- Syntax errors: {s['syntax_errors']}",f"- Risk findings: {s['risk_findings']}",f"- Converted-TFS/completion findings: {s['conversion_findings']}",f"- Stub/empty findings: {s['stub_findings']}",'','## Language / File Type Counts','','| Type | Count |','|---|---:|']
    out += [f'| {k} | {v} |' for k,v in inv['counts_by_kind'].items()]
    out += ['',_section('Syntax Findings',syntax),_section('Converted TFS / Completion Findings',conv),_section('Risk Findings',risk),_section('Stub / Empty File Findings',stubs),'## Recommended Next Steps','','1. Fix syntax errors first.','2. Review converted TFS TODO/API mapping markers.','3. Review high/critical risks before patch generation.','4. Only allow sandbox patch proposals after approval.']
    return '\n'.join(out)+'\n'

def analyze_zip(zip_path:str|Path,workspace:str|Path,name:str|None=None)->dict[str,Any]:
    project=extract_zip(zip_path,workspace,name); report=analyze_project(project['extracted_dir'],project['analysis_dir']); return {'project':project,**report}
