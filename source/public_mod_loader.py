"""Public Korean/name and relic-preset loader: native game and user saves are read-only.

An unchanged local EXE copy starts a tiny pack, mounts the original PCK, then
mounts a cached overlay before any native autoload is instantiated.
"""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback

import psutil
from pck import Pack
from gdc import ROOT
import mod_installer as community
from external_pack import write_pack,read_settings,write_settings,settings_string,settings_bool,decode_string

VERSION='1.3.0'
MODULES={
 'korean':('KoreanSupplement','한국어 보완 · 이름 한글화'),
 'relic':('RelicPresets','유물 프리셋'),
}

def assets():
    if getattr(sys,'frozen',False):return Path(sys._MEIPASS)/'external-loader'
    alongside=Path(__file__).resolve().parent/'loader'
    return alongside if alongside.is_dir() else ROOT/'mods/loader'

def distribution_root():
    return Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else ROOT

def default_mod_root(game):
    alongside=distribution_root()/'mods'
    if any((alongside/directory/'mod.json').is_file() for directory,_ in MODULES.values()):
        return alongside
    return Path(game)/'mods'

def hash_file(path):return community.file_sha(path)
def digest(data):return hashlib.sha256(data).hexdigest()
def encoded(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
def json_read(path,default=None):
    return json.loads(Path(path).read_text(encoding='utf-8-sig')) if Path(path).is_file() else default

def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.loader-',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as out:out.write(encoded(value))
        os.replace(name,path)
    finally:
        if Path(name).exists():Path(name).unlink()

def ensure_closed():
    for proc in psutil.process_iter(['name']):
        try:
            if (proc.info['name'] or '').lower() in ('eslabong.exe','eslabongmodded.exe'):
                raise RuntimeError('게임을 저장하고 완전히 종료한 뒤 실행해 주세요. 실행 중인 게임은 종료하지 않습니다.')
        except (psutil.NoSuchProcess,psutil.AccessDenied):pass

def modules(root):
    result={}
    for key,(directory,title) in MODULES.items():
        folder=root/directory;manifest=json_read(folder/'mod.json')
        if manifest is None:continue
        if manifest.get('format')!=1 or manifest.get('id')!=key:
            raise ValueError('모드 정보 형식이 맞지 않습니다: '+str(folder/'mod.json'))
        # Only our known adapters are executable; manifests cannot import Python.
        result[key]={'folder':folder,'manifest':manifest,'title':title}
    return result

def file_inventory(root):
    result={}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():raise ValueError('모드 안의 심볼릭 링크는 지원하지 않습니다: '+str(path))
        if path.is_file() and path.name!='installed.json' and '__pycache__' not in path.parts:
            result[path.relative_to(root).as_posix()]=hash_file(path)
    return result

def module_payload(entry,relative):
    folder=entry['folder'];path=(folder/relative).resolve()
    if not path.is_relative_to(folder.resolve()) or not path.is_file():
        raise ValueError('모드 구성 파일이 없습니다: '+str(path))
    return path

def plan_overlay(pack,enabled,found):
    package=None
    if enabled['korean']:
        package=found['korean']['folder']/'package'
        if not (package/'data/manifest.json').is_file():raise ValueError('한국어 모드 데이터를 찾지 못했습니다.')
    change,report=community.plan(pack,enabled['korean'],enabled['relic'],package)
    if enabled['relic']:
        payload=module_payload(found['relic'],'RelicPresets.gd').read_bytes()
        change['RelicPresets/RelicPresets.gd']=payload
    return change,report

def extension_files(pack,game):
    result={}
    listing=pack.read('.godot/extension_list.cfg') if '.godot/extension_list.cfg' in pack.files else b''
    result['.godot/extension_list.cfg']=listing
    for line in listing.decode('utf-8').splitlines():
        name=line.strip().removeprefix('res://')
        if not name:continue
        source=pack.read(name).decode('utf-8')
        def relocate(match):
            relative=match[1].removeprefix('res://')
            if not relative.lower().endswith('.dll'):return match[0]
            options=[game/relative,game/Path(relative).name]
            path=next((p.resolve() for p in options if p.is_file()),None)
            if path is None:raise ValueError('게임 확장 라이브러리를 찾지 못했습니다: '+relative)
            return json.dumps(path.as_posix(),ensure_ascii=False)
        result[name]=re.sub(r'"(res://[^"\n]+)"',relocate,source).encode('utf-8')
    return result

def boot_files(pack,game,generation,overlay,changes,preflight=False):
    rows=read_settings(pack.read('project.binary'))
    if any(k=='autoload/EslabongExternalLoader' for k,v in rows):
        raise ValueError('동일한 외부 로더가 게임 데이터 안에 이미 있습니다.')
    replacements={}
    if preflight:
        replacements={
            'application/config/name':settings_string('EslabongExternalLoaderPreflight'),
            'application/config/use_custom_user_dir':settings_bool(True),
            'application/config/custom_user_dir_name':settings_string('EslabongExternalLoaderPreflight'),
            'application/run/main_scene':settings_string('res://EslabongLoader/preflight.tscn'),
            'steam/initialization/initialize_on_startup':settings_bool(False),
            'steam/achievements/enabled':settings_bool(False),
            'application/run/disable_stdout.release':settings_bool(False),
        }
        rows=[(k,v) for k,v in rows if not k.startswith('autoload/')]
    rows=[(k,replacements.pop(k,v)) for k,v in rows]+list(replacements.items())
    rows.insert(0,('autoload/EslabongExternalLoader',settings_string('*res://EslabongLoader/Bootstrap.gd')))
    files=extension_files(pack,game)
    for name in ('.godot/global_script_class_cache.cfg','.godot/uid_cache.bin'):
        if name in pack.files:files[name]=pack.read(name)
    # Icon is read before the first autoload; all other resources mount at init.
    icon=next((decode_string(v) for k,v in rows if k=='application/config/icon'),None)
    if icon and icon.startswith('res://') and icon[6:] in pack.files:files[icon[6:]]=pack.read(icon[6:])
    files['project.binary']=write_settings(rows)
    files['EslabongLoader/Bootstrap.gd']=(assets()/'Bootstrap.gd').read_bytes()
    files['EslabongLoader/boot.json']=encoded({'base':str(pack.path.resolve()),'overlay':str(overlay.resolve()),
        'generation':generation,'verify_resources':{k:digest(v) for k,v in changes.items()}})
    if preflight:
        files['EslabongLoader/Preflight.gd']=(assets()/'Preflight.gd').read_bytes()
        files['EslabongLoader/preflight.tscn']=b'[gd_scene load_steps=2 format=3]\n[ext_resource type="Script" path="res://EslabongLoader/Preflight.gd" id="1"]\n[node name="Preflight" type="Node"]\nscript=ExtResource("1")\n'
    return files

def probe(exe,log_path):
    result=subprocess.run([str(exe),'--headless','--quit-after','120','--log-file',str(log_path)],cwd=exe.parent,
        capture_output=True,timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
    out=result.stdout.decode('utf-8','replace');err=result.stderr.decode('utf-8','replace')
    if result.returncode or 'EXTERNAL_PREFLIGHT_RESULT OK' not in out or 'ERROR:' in err or 'SCRIPT ERROR:' in err:
        raise RuntimeError('외부 모드 시작 검증에 실패했습니다. 게임 원본은 변경하지 않았습니다.\n'+(err or out)[-2500:])
    return {'ok':True,'checks':'native encrypted pack + overlay mounted before autoloads','stdout':out}

@contextlib.contextmanager
def loader_lock(root):
    import msvcrt
    root.mkdir(parents=True,exist_ok=True)
    path=root/'prepare.lock'
    handle=path.open('a+b')
    handle.seek(0,2)
    if handle.tell()==0:handle.write(b'0');handle.flush()
    handle.seek(0)
    try:msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
    except OSError:
        handle.close()
        raise RuntimeError('다른 로더가 준비 중입니다. 중복 실행한 창을 닫아 주세요.')
    try:
        yield
    finally:
        handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1);handle.close()


def engine_dependencies(game):
    files=list(game.glob('*.dll'))
    if (game/'addons').is_dir():files.extend((game/'addons').rglob('*.dll'))
    return {p.relative_to(game).as_posix():hash_file(p) for p in sorted(files)}


def adapter_identity():
    if getattr(sys,'frozen',False):return hash_file(Path(sys.executable))
    # Include all imported adapters, not just the front-end version string.
    return {p.name:hash_file(p) for p in sorted(Path(__file__).parent.glob('*.py'))}


def steam_app_id(game):
    # Installed Steam manifest, not a guessed/full-game App ID or license change.
    library=game.parent.parent
    for path in library.glob('appmanifest_*.acf'):
        data=path.read_text(encoding='utf-8',errors='replace')
        directory=re.search(r'"installdir"\s+"([^"\r\n]+)"',data)
        app=re.search(r'"appid"\s+"(\d+)"',data)
        if directory and app and directory[1].casefold()==game.name.casefold():return int(app[1])
    return None


def cache_entry(index_dir,cache,inputs):
    try:
        index=json_read(index_dir/'index.json',{})
        name=index.get('directory','')
        if not re.fullmatch(r'build-[A-Za-z0-9_-]+',name):return None
        folder=cache/name
        if folder.is_symlink() or folder.resolve().parent!=cache.resolve():return None
        report=json_read(folder/'ready.json',{})
        required={'EslabongModded.exe','EslabongModded.pck','overlay.pck'}
        if report.get('inputs')!=inputs or set(report.get('outputs',{}))!=required:return None
        for n,d in report['outputs'].items():
            if not (folder/n).is_file() or (folder/n).is_symlink() or hash_file(folder/n)!=d:return None
        return folder,report
    except (ValueError,OSError,TypeError):return None

def prepare(game,mods_root=None,selected=None,log=print,force=False):
    game=Path(game).resolve();root=Path(mods_root).resolve() if mods_root else default_mod_root(game).resolve()
    for name in ('eslabong.exe','eslabong.pck'):
        if not (game/name).is_file():raise ValueError('eslabong.exe와 eslabong.pck가 있는 폴더를 선택해 주세요.')
    ensure_closed()
    state_root=root/'EslabongCommunityLoader';cache=state_root/'cache'
    if (game/'.eslabong-community-mods.lock').exists():raise RuntimeError('기존 설치기가 작업 중입니다. 완료 후 실행해 주세요.')
    with loader_lock(state_root):
        found=modules(root);settings=json_read(state_root/'settings.json',{})
        if not found and not settings:
            raise ValueError('모드 폴더를 찾지 못했습니다. ZIP 전체를 풀어 실행기 옆에 mods 폴더가 있도록 해 주세요.')
        flags=settings.get('enabled',{}) if selected is None else selected
        enabled={k:k in found and bool(flags.get(k,found[k]['manifest'].get('enabled',True))) if k in found else False for k in MODULES}
        log('게임 원본과 모드 폴더를 확인합니다...')
        inputs={'loader':VERSION,'game':str(game),'base':hash_file(game/'eslabong.pck'),
            'exe':hash_file(game/'eslabong.exe'),'enabled':enabled,'modules':{k:file_inventory(e['folder']) for k,e in found.items()},
            'adapters':adapter_identity(),'dependencies':engine_dependencies(game),'steam_app_id':steam_app_id(game)}
        # Render override is a game preference; read/copy, never overwrite it.
        if (game/'override.cfg').is_file():inputs['override']=hash_file(game/'override.cfg')
        inputs['bootstrap']=digest((assets()/'Bootstrap.gd').read_bytes())
        inputs['preflight']=digest((assets()/'Preflight.gd').read_bytes())
        generation=digest(encoded(inputs))[:32];folder=cache/generation
        cached=cache_entry(folder,cache,inputs)
        if not force and cached:
            actual,report=cached
            log('변경 없음: 준비된 모드를 바로 사용합니다.')
            report['cache_hit']=True
            atomic_json(state_root/'settings.json',{'game':str(game),'enabled':enabled})
            return actual/'EslabongModded.exe',report
        # Never replace an in-use cache. A fresh private directory is committed
        # only once its complete output has passed the isolated engine check.
        cache.mkdir(parents=True,exist_ok=True)
        work=Path(tempfile.mkdtemp(prefix='build-',dir=cache))
        pack=Pack(game)
        try:
            log('변경된 게임에 모드를 연결합니다. 원본 파일은 덮어쓰지 않습니다...')
            changes,detail=plan_overlay(pack,enabled,found)
            write_pack(work/'overlay.pck',changes)
            # Paths must remain valid if this completed directory is renamed.
            # Keep the unique build directory as the generation and use an index.
            executable=work/'EslabongModded.exe'
            shutil.copy2(game/'eslabong.exe',executable)
            if hash_file(executable)!=inputs['exe']:raise RuntimeError('준비 중 게임 실행 파일이 변경되었습니다.')
            files=boot_files(pack,game,generation,work/'overlay.pck',changes,True)
            write_pack(executable.with_suffix('.pck'),files)
            log('세이브·게임 자동실행 기능 없이 시작 순서를 검사합니다...')
            qa=probe(executable,work/'preflight.log')
            write_pack(executable.with_suffix('.pck'),boot_files(pack,game,generation,work/'overlay.pck',changes,False))
            if (game/'override.cfg').is_file():shutil.copy2(game/'override.cfg',work/'override.cfg')
            if hash_file(game/'eslabong.pck')!=inputs['base'] or hash_file(game/'eslabong.exe')!=inputs['exe']:
                raise RuntimeError('준비 중 게임이 업데이트되었습니다. 다시 실행해 주세요.')
            if {k:file_inventory(e['folder']) for k,e in modules(root).items()}!=inputs['modules'] or engine_dependencies(game)!=inputs['dependencies']:
                raise RuntimeError('준비 중 모드 또는 게임 라이브러리가 변경되었습니다. 다시 실행해 주세요.')
            outputs={n:hash_file(work/n) for n in ('EslabongModded.exe','EslabongModded.pck','overlay.pck')}
            report={'format':1,'loader_version':VERSION,'inputs':inputs,'outputs':outputs,'cache_hit':False,
                'directory':str(work),'generation':generation,'enabled':enabled,'preflight':qa,
                'overlay_resources':len(changes),'overlay_bytes':(work/'overlay.pck').stat().st_size,
                'game_files_modified':False,'detail':detail}
            atomic_json(work/'ready.json',report)
            folder.mkdir(exist_ok=True)
            atomic_json(folder/'index.json',{'directory':work.name})
            atomic_json(state_root/'settings.json',{'game':str(game),'enabled':enabled})
            log('외부 모드 준비 완료. 게임 원본은 그대로 유지했습니다.')
            return executable,report
        finally:pack.stream.close()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--game');parser.add_argument('--mods',type=Path);parser.add_argument('--prepare-only',action='store_true')
    parser.add_argument('--report',type=Path);parser.add_argument('--force',action='store_true')
    parser.add_argument('--settings',action='store_true');parser.add_argument('--steam',nargs=argparse.REMAINDER)
    args=parser.parse_args()
    if not args.game and not args.prepare_only:
        import ctypes
        if ctypes.windll.user32.GetAsyncKeyState(0x10)&0x8000:args.settings=True
    if args.steam:
        original=Path(args.steam[0]).resolve()
        if original.name.casefold()!='eslabong.exe' or not original.is_file():raise ValueError('Steam의 원본 실행 경로가 올바르지 않습니다.')
        args.game=str(original.parent)
    if args.settings:
        here=Path(sys.executable).parent if getattr(sys,'frozen',False) else ROOT
        located=json_read(here/'EslabongCommunityLoader.location.json',{})
        guessed=args.game or (str(here) if (here/'eslabong.pck').is_file() else located.get('game'))
        gui(args.mods,guessed);return
    if not args.game:
        here=Path(sys.executable).parent if getattr(sys,'frozen',False) else ROOT
        located=json_read(here/'EslabongCommunityLoader.location.json',{})
        game=here if (here/'eslabong.pck').is_file() else Path(located['game']) if located.get('game') else None
        if game and ((args.mods or default_mod_root(game))/'EslabongCommunityLoader/settings.json').is_file():
            gui(args.mods,str(game),auto_start=True);return
        gui(args.mods,str(game) if game else None);return
    try:
        exe,report=prepare(args.game,args.mods,force=args.force)
        if args.report:atomic_json(args.report,report)
        if not args.prepare_only:launch(exe,Path(args.game),report,args.steam[1:] if args.steam else None)
    except Exception:
        if args.report:atomic_json(args.report,{'error':traceback.format_exc()})
        if getattr(sys,'frozen',False) and not args.prepare_only:
            import tkinter as tk
            from tkinter import messagebox
            window=tk.Tk();window.withdraw();messagebox.showerror('외부 모드 실행 중단',traceback.format_exc()[-2500:]);window.destroy()
        raise

def launch(exe,game,report,game_args=None):
    ensure_closed()
    if hash_file(game/'eslabong.pck')!=report['inputs']['base'] or hash_file(game/'eslabong.exe')!=report['inputs']['exe']:
        raise RuntimeError('게임 데이터가 바뀌었습니다. 다시 준비해 주세요.')
    # Keep all native Steam authentication intact. A wrapper launched by Steam
    # inherits its environment; direct launch uses the installed manifest ID.
    # This is identification, not an ownership substitute: native steamInitEx
    # and all original failure checks still run unmodified.
    env=os.environ.copy();app_id=report['inputs'].get('steam_app_id')
    if app_id:
        env['SteamAppId']=str(app_id);env['SteamGameId']=str(app_id)
    return subprocess.Popen([str(exe),*(game_args or [])],cwd=game,env=env)

def gui(mods_override=None,game_hint=None,auto_start=False):
    import tkinter as tk
    from tkinter import ttk,filedialog,messagebox
    root=tk.Tk();root.title('Eslabong 한국어 · 유물 모드 로더 '+VERSION);root.geometry('790x650')
    frame=ttk.Frame(root,padding=18);frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='Eslabong 한국어 · 유물 모드 로더',font=('Malgun Gothic',17,'bold')).pack(anchor='w')
    ttk.Label(frame,text='원본 게임을 덮어쓰지 않고 mods 폴더의 모드를 불러옵니다.\n처음 또는 업데이트 직후에만 새 데이터를 준비합니다.').pack(anchor='w',pady=10)
    path=tk.StringVar(value=game_hint or community.guess_game());bar=ttk.Frame(frame);bar.pack(fill='x')
    entry=ttk.Entry(bar,textvariable=path);entry.pack(side='left',fill='x',expand=True)
    def browse():
        chosen=filedialog.askdirectory(title='Eslabong 게임 폴더')
        if chosen:path.set(chosen)
    pick=ttk.Button(bar,text='게임 폴더',command=browse);pick.pack(side='right')
    options={k:tk.BooleanVar(value=True) for k in MODULES};controls=[entry,pick];checks={}
    for k,(_,title) in MODULES.items():
        c=ttk.Checkbutton(frame,text=title,variable=options[k]);c.pack(anchor='w',pady=4);controls.append(c);checks[k]=c
    def refresh(*_):
        try:
            modroot=mods_override or default_mod_root(Path(path.get()));found=modules(modroot)
            saved=json_read(modroot/'EslabongCommunityLoader/settings.json',{}).get('enabled',{})
            for key,var in options.items():
                var.set(key in found and saved.get(key,found[key]['manifest'].get('enabled',True)))
                checks[key].configure(state='normal' if key in found else 'disabled')
        except (OSError,ValueError):pass
    path.trace_add('write',refresh);refresh()
    ttk.Label(frame,text='모드 파일은 실행기 옆의 mods 폴더에 둡니다. Steam은 로그인한 상태로 켜 두세요.\n게임 시작 화면·저장·온라인 검사는 게임 원래 기능을 그대로 사용합니다.').pack(anchor='w',pady=6)
    def steam_option():
        loader=Path(sys.executable) if getattr(sys,'frozen',False) else ROOT/'output/public-loader-v1.3.0/EslabongCommunityLoader.exe'
        option='"'+str(loader)+'" --steam %command%'
        root.clipboard_clear();root.clipboard_append(option)
        messagebox.showinfo('Steam 실행 옵션 복사', 'Steam → Eslabong 속성 → 일반 → 실행 옵션에 붙여넣으면\nSteam의 플레이 버튼도 이 로더를 거칩니다.\n기존 실행 옵션이 있다면 보관 후 수정하세요.\n\n'+option)
    c=ttk.Button(frame,text='Steam 플레이 버튼 연결용 문구 복사',command=steam_option);c.pack(anchor='w');controls.append(c)
    output=tk.Text(frame,state='disabled',height=10,wrap='word');output.pack(fill='both',expand=True,pady=10)
    events=queue.Queue();busy=[False]
    def start(play):
        if busy[0]:return
        if not path.get():browse()
        if not path.get():return
        game=Path(path.get());selected={k:v.get() for k,v in options.items()};busy[0]=True
        for c in controls:c.configure(state='disabled')
        def work():
            try:
                exe,report=prepare(game,mods_override,selected,lambda s:events.put(('log',s)))
                here=Path(sys.executable).parent if getattr(sys,'frozen',False) else ROOT/'work'
                try:atomic_json(here/'EslabongCommunityLoader.location.json',{'game':str(game.resolve())})
                except OSError:pass
                if play:launch(exe,game,report)
                events.put(('launched' if play else 'done','게임 실행을 요청했습니다.' if play else '준비 / 검사를 마쳤습니다.'))
            except Exception as error:events.put(('error',str(error)))
        threading.Thread(target=work,daemon=True).start()
    bar=ttk.Frame(frame);bar.pack(fill='x')
    for title,play in [('모드로 게임 실행',True),('실행하지 않고 준비 / 검사',False)]:
        c=ttk.Button(bar,text=title,command=lambda p=play:start(p));c.pack(side='left',padx=4);controls.append(c)
    def poll():
        while not events.empty():
            kind,value=events.get()
            if value:
                output.configure(state='normal');output.insert('end',value+'\n');output.see('end');output.configure(state='disabled')
            if kind in ('done','error','launched'):
                busy[0]=False
                for c in controls:c.configure(state='normal')
                if kind=='error':messagebox.showerror('게임 원본을 유지하고 중단',value)
                if kind=='launched':root.destroy();return
        root.after(100,poll)
    root.protocol('WM_DELETE_WINDOW',lambda:None if busy[0] else root.destroy())
    root.after(100,poll)
    if auto_start:root.after(250,lambda:start(True))
    root.mainloop()

if __name__=='__main__':main()
