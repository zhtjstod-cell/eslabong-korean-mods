"""Eslabong installable mods: reversible, resource-matched, no game files bundled."""
from __future__ import annotations
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import struct
import sys
import tempfile
import threading
import time
import traceback
import uuid

import bsdiff4
import psutil
from Crypto.Cipher import AES
from pck import Pack
from relic_contract import mismatches
from member_patch import apply as apply_members

# Development uses the existing local dependency; frozen builds bundle it.
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime/python_packages'))
import zstandard


def package_root():
    if getattr(sys,'frozen',False):
        return Path(sys._MEIPASS)/'package'
    alongside = Path(__file__).resolve().parent/'package'
    if alongside.is_dir():
        return alongside
    return Path(__file__).resolve().parents[1]/'output/mod-package'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while chunk := stream.read(4*1024*1024):
            h.update(chunk)
    return h.hexdigest()


def script_raw(data):
    if data[:4] != b'GDSC' or len(data)<12:
        raise ValueError('GDScript resource format does not match')
    version,size = struct.unpack_from('<2I',data,4)
    if version != 101:
        raise ValueError('GDScript resource format does not match')
    raw = zstandard.ZstdDecompressor().decompress(data[12:],max_output_size=size) if size else data[12:]
    if size and len(raw)!=size:
        raise ValueError('Invalid script size')
    return raw


def encode_script(raw):
    return b'GDSC'+struct.pack('<2I',101,len(raw))+zstandard.ZstdCompressor().compress(raw)


def require_closed():
    for process in psutil.process_iter(['name']):
        try:
            if (process.info['name'] or '').lower() == 'eslabong.exe':
                raise RuntimeError('게임을 저장하고 완전히 종료한 뒤 다시 실행해 주세요. 게임을 강제 종료하지는 않습니다.')
        except (psutil.NoSuchProcess,psutil.AccessDenied):
            continue


def plan(pack, korean: bool, relic: bool, package: Path | None = None):
    package = package or package_root()
    manifest = json.loads((package/'data/manifest.json').read_text(encoding='utf-8'))
    if manifest.get('format') != 2:
        raise ValueError('설치 데이터 형식이 맞지 않습니다. 새 배포 압축을 별도 폴더에 모두 풀어 주세요.')
    replacements = {}
    skipped = []
    matched = 0
    member_reports = {}
    if relic:
        contracts = {**manifest['relic_dependencies'],'UI/screens/myteam_screen.gdc':manifest['relic_ui_contract']}
        for name,expected in contracts.items():
            try:
                failed = mismatches(pack.read(name),expected)
            except (KeyError,ValueError,AssertionError,IndexError,struct.error,zstandard.ZstdError):
                failed = ['리소스 형식 또는 필수 항목 없음']
            if failed:
                raise RuntimeError('유물 장착·저장에 필요한 항목이 달라 안전하게 중단했습니다. 파일은 변경하지 않았습니다.\n'
                                   +name+'\n확인이 필요한 항목: '+', '.join(failed)
                                   +'\n한국어 보완만 설치하려면 유물 프리셋 체크를 해제해 주세요.')
    for record in manifest['resources']:
        name = record['path']
        if name not in pack.files:
            if relic and name == 'UI/screens/myteam_screen.gdc':
                raise RuntimeError('주전 저장 화면 리소스가 없어 유물 모드를 설치하지 않았습니다. 파일은 변경하지 않았습니다.')
            skipped.append(name)
            continue
        current = pack.read(name)
        try:
            raw = script_raw(current)
        except ValueError:
            raw = b''
        digest = sha(raw)
        base = None
        for candidate in [record,*record.get('alternatives',[])]:
            if digest == candidate['base']:
                base = raw
            else:
                for variant in candidate['variants'].values():
                    if digest == variant['sha256']:
                        base = bsdiff4.patch(raw,(package/'data'/variant['reverse']).read_bytes())
                        break
            if base is not None:
                record = candidate
                break
        if base is None:
            recipes = [member for candidate in [record,*record.get('alternatives',[])] for member in candidate.get('members',[])]
            if not recipes or not raw:
                if relic and name == 'UI/screens/myteam_screen.gdc':
                    raise RuntimeError('주전 저장 화면 형식을 읽을 수 없어 유물 모드를 설치하지 않았습니다. 파일은 변경하지 않았습니다.')
                skipped.append(name)
                continue
            target,detail = apply_members(current,recipes,korean,relic,package)
            member_reports[name] = detail
            if detail['skipped']:
                skipped.append(name)
            else:
                matched += 1
            if target != current:
                replacements[name] = target
            continue
        if sha(base) != record['base']:
            raise ValueError('Invalid reverse delta: '+name)
        profile = 'both' if korean and relic else 'korean' if korean else 'relic' if relic else None
        if profile == 'both' and profile not in record['variants']:
            profile = 'korean'
        variant = record['variants'].get(profile)
        target = bsdiff4.patch(base,(package/'data'/variant['forward']).read_bytes()) if variant else base
        if sha(target) != (variant['sha256'] if variant else record['base']):
            raise ValueError('Invalid forward delta: '+name)
        if target != raw:
            replacements[name] = encode_script(target)
        matched += 1
    translations = json.loads((package/'mods/KoreanSupplement/translations.json').read_text(encoding='utf-8'))
    en = json.loads(pack.read('Localization/en.json').decode('utf-8-sig'))
    original_ko = pack.read('Localization/ko.json')
    ko = json.loads(original_ko.decode('utf-8-sig'))
    state_path = 'KoreanSupplement/translation_state.json'
    previous_state = pack.read(state_path) if state_path in pack.files else None
    if previous_state is not None:
        state = json.loads(previous_state.decode('utf-8'))
        if state.get('format') != 1 or not isinstance(state.get('entries'),dict):
            raise ValueError('번역 복구 기록의 형식이 달라 중단했습니다.')
        owned = state['entries']
        if any(key not in translations or entry != translations[key] for key,entry in owned.items()):
            raise ValueError('번역 복구 기록에 알 수 없는 변경이 있어 중단했습니다.')
    else:
        owned = {}
        # v1.0.0 and our pre-mod patch did not carry per-key ownership metadata.
        # Adopt only their exact known complete Korean table, never infer from
        # a value that may now also be supplied by the game itself.
        digest = sha(json.dumps(ko,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())
        if digest == manifest.get('legacy_korean_content_sha256'):
            owned = {key:entry for key,entry in translations.items() if ko.get(key)==entry['after']}
    language_matches,language_skips,language_changes = 0,0,0
    for key,entry in translations.items():
        current = ko.get(key)
        if en.get(key) != entry['en'] or current not in (entry['before'],entry['after']):
            language_skips += 1
            continue
        language_matches += 1
        # Restore only text this mod owns. The updated game can independently
        # ship the same Korean value; removing the mod must not delete that text.
        if not korean and key not in owned:
            continue
        desired = entry['after'] if korean else owned[key]['before']
        if desired == current:
            if not korean:
                owned.pop(key,None)
            continue
        language_changes += 1
        if desired is None:
            ko.pop(key,None)
        else:
            ko[key] = desired
        if korean:
            owned[key] = entry
        else:
            owned.pop(key,None)
    if language_changes:
        replacements['Localization/ko.json'] = (json.dumps(ko,ensure_ascii=False,indent='\t')+'\n').encode()
    if owned or previous_state is not None:
        payload = (json.dumps({'format':1,'entries':owned},ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
        if payload != previous_state:
            replacements[state_path] = payload
    # Added helper resources are inert without matching hooks. Keep them on uninstall
    # so save/resource references and unrelated concurrent mods cannot be broken.
    for extra in manifest['extras']:
        enabled = korean if extra['module']=='korean' else relic
        if not enabled:
            continue
        payload = (package/extra['file']).read_bytes()
        if sha(payload) != extra['sha256']:
            raise ValueError('Mod payload checksum mismatch')
        if extra['path'] in pack.files and pack.read(extra['path'])!=payload:
            raise RuntimeError('같은 경로의 보조 파일에 다른 수정이 있어 보호를 위해 중단했습니다: '+extra['path'])
        if extra['path'] not in pack.files:
            replacements[extra['path']] = payload
    report = {'korean':korean,'relic_presets':relic,'matched_scripts':matched,'skipped_scripts':skipped,
              'installer_version':'1.0.1',
              'member_matching':member_reports,
              'relic_contract_members':sum(map(len,manifest['relic_dependencies'].values()))+len(manifest['relic_ui_contract']) if relic else 0,
              'matched_translation_entries':language_matches,'skipped_translation_entries':language_skips,
              'changed_resources':list(replacements)}
    return replacements,report


def stage(pack, target, replacements):
    shutil.copy2(pack.path,target)
    directory = bytearray(pack.directory_plain)
    count = pack.count
    with Path(target).open('r+b') as out:
        out.seek(0,2)
        for name,data in replacements.items():
            out.write(bytes((-out.tell())%16))
            offset = out.tell()
            out.write(data)
            record = struct.pack('<2Q16sI',offset-pack.base,len(data),hashlib.md5(data).digest(),0)
            if name in pack.entry_positions:
                pos = pack.entry_positions[name]
                directory[pos:pos+len(record)] = record
            else:
                path = name.encode()
                path += bytes((-len(path))%4)
                directory += struct.pack('<I',len(path))+path+record
                count += 1
        out.write(bytes((-out.tell())%16))
        directory_offset = out.tell()
        out.write(struct.pack('<I',count))
        if pack.flags & 1:
            iv = os.urandom(16)
            out.write(hashlib.md5(directory).digest()+struct.pack('<Q',len(directory))+iv)
            out.write(AES.new(pack.key,AES.MODE_CFB,iv=iv,segment_size=128).encrypt(bytes(directory)+bytes((-len(directory))%16)))
        else:
            out.write(directory)
        out.seek(32)
        out.write(struct.pack('<Q',directory_offset))
        out.flush()
        os.fsync(out.fileno())


def install(game, korean=True, relic=True, verify_only=False, log=print, package=None):
    game = Path(game).resolve()
    if not (game/'eslabong.exe').is_file() or not (game/'eslabong.pck').is_file():
        raise RuntimeError('eslabong.exe와 eslabong.pck가 있는 게임 폴더를 선택해 주세요.')
    require_closed()
    lock = game/'.eslabong-community-mods.lock'
    try:
        handle = lock.open('x')
    except FileExistsError:
        raise RuntimeError('다른 모드 설치가 실행 중이거나 이전 설치가 비정상 종료되었습니다. 설치 창을 모두 닫고 잠금 파일을 확인해 주세요.')
    pack = None
    candidate = None
    temp_path = None
    try:
        handle.write(str(os.getpid()))
        handle.flush()
        log('게임 데이터와 기존 모드 상태를 확인합니다...')
        before = file_sha(game/'eslabong.pck')
        pack = Pack(game)
        replacements,report = plan(pack,korean,relic,package)
        report['game'] = str(game)
        log('스크립트 매칭 %d개 / 제외 %d개, 번역 매칭 %d개 / 제외 %d개' % (report['matched_scripts'],len(report['skipped_scripts']),report['matched_translation_entries'],report['skipped_translation_entries']))
        if verify_only:
            log('검사 완료. 게임 파일은 변경하지 않았습니다.')
            return report
        if not replacements:
            log('이미 선택한 상태로 적용되어 있습니다.')
            return report
        if shutil.disk_usage(game).free < 2*(game/'eslabong.pck').stat().st_size+64*1024*1024:
            raise RuntimeError('백업과 안전한 설치에 필요한 디스크 여유 공간이 부족합니다.')
        log('새 모드 구성을 만들고 변경된 리소스를 검증합니다...')
        fd,name = tempfile.mkstemp(prefix='.eslabong-mod-',suffix='.tmp',dir=game)
        os.close(fd)
        temp_path = Path(name)
        stage(pack,temp_path,replacements)
        candidate = Pack(game,path=temp_path,key=pack.key)
        if set(candidate.files) != set(pack.files)|set(replacements):
            raise ValueError('Resource directory mismatch')
        for name in candidate.files:
            verified_data = candidate.read(name)
            if name in replacements:
                if verified_data != replacements[name]:
                    raise ValueError('Patched resource verification failed')
            elif candidate.files[name] != pack.files[name]:
                raise ValueError('Unrelated resource changed: '+name)
        after = file_sha(temp_path)
        candidate.stream.close()
        candidate = None
        pack.stream.close()
        pack = None
        require_closed()
        if file_sha(game/'eslabong.pck') != before:
            raise RuntimeError('작업 중 게임 파일이 바뀌어 설치를 중단했습니다.')
        backup_dir = game/'KoreanPatchBackup'/('mods-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
        backup_dir.mkdir(parents=True,exist_ok=False)
        backup = backup_dir/'eslabong.pck'
        shutil.copy2(game/'eslabong.pck',backup)
        if file_sha(backup) != before:
            raise ValueError('Backup verification failed')
        require_closed()
        if file_sha(game/'eslabong.pck') != before:
            raise RuntimeError('게임 파일이 변경되어 설치를 중단했습니다.')
        report.update(before_sha256=before,after_sha256=after,backup=str(backup),installed_at=time.strftime('%Y-%m-%dT%H:%M:%S'))
        (backup_dir/'receipt.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        log('검증된 원본 백업을 만들었습니다. 모드를 적용합니다...')
        os.replace(temp_path,game/'eslabong.pck')
        temp_path = None
        if file_sha(game/'eslabong.pck') != after:
            rollback = game/'.eslabong-mod-rollback.tmp'
            shutil.copy2(backup,rollback)
            os.replace(rollback,game/'eslabong.pck')
            raise RuntimeError('설치 후 검증에 실패해 백업으로 복구했습니다.')
        config_dir = game/'mods/EslabongCommunityMods'
        try:
            config_dir.mkdir(parents=True,exist_ok=True)
            (config_dir/'installed.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        except OSError as error:
            log('모드는 적용되었지만 설치 기록을 저장하지 못했습니다: '+str(error))
        log('적용 완료. 게임을 실행해 주세요.\n백업: '+str(backup))
        return report
    finally:
        if candidate:
            candidate.stream.close()
        if pack:
            pack.stream.close()
        if temp_path is not None and temp_path.exists():
            temp_path.unlink() # Only this invocation's mkstemp file inside the game directory.
        handle.close()
        lock.unlink()


def guess_game():
    candidates = [Path.cwd(),Path(sys.executable).parent] if getattr(sys,'frozen',False) else [Path.cwd()]
    candidates += [p.parent for p in list(candidates)]
    candidates += [Path('H:/Games/Eslabong')]
    if os.name=='nt':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Valve\Steam') as key:
                steam = Path(winreg.QueryValueEx(key,'SteamPath')[0])
            candidates.append(steam/'steamapps/common/Eslabong')
            import re
            text = (steam/'steamapps/libraryfolders.vdf').read_text(encoding='utf-8')
            candidates.extend(Path(path.replace('\\\\','\\'))/'steamapps/common/Eslabong' for path in re.findall(r'"path"\s+"([^"]+)"',text))
        except (OSError,ValueError):
            pass
    return next((str(p.resolve()) for p in candidates if (p/'eslabong.exe').is_file() and (p/'eslabong.pck').is_file()),'')


def gui():
    import tkinter as tk
    from tkinter import ttk,filedialog,messagebox
    root = tk.Tk()
    root.title('Eslabong 한국어 보완 · 유물 프리셋 모드 v1.0.1')
    root.geometry('780x540')
    root.minsize(700,480)
    frame = ttk.Frame(root,padding=18)
    frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='Eslabong 모드 설치 / 구성 변경',font=('Malgun Gothic',16,'bold')).pack(anchor='w')
    ttk.Label(frame,text='게임을 종료한 상태에서 적용하세요. 체크를 해제하고 적용하면 해당 모드가 제거됩니다.').pack(anchor='w',pady=(8,12))
    path = tk.StringVar(value=guess_game())
    row = ttk.Frame(frame)
    row.pack(fill='x')
    entry = ttk.Entry(row,textvariable=path)
    entry.pack(side='left',fill='x',expand=True)
    def browse():
        selected = filedialog.askdirectory(title='eslabong.exe가 있는 게임 폴더 선택')
        if selected:
            path.set(selected)
    browse_button = ttk.Button(row,text='게임 폴더 선택',command=browse)
    browse_button.pack(side='right',padx=(8,0))
    korean = tk.BooleanVar(value=True)
    relic = tk.BooleanVar(value=True)
    check_ko = ttk.Checkbutton(frame,text='한국어 보완: 미번역 · 기존/신규 인물 이름 · 직업 이름',variable=korean)
    check_ko.pack(anchor='w',pady=(16,5))
    check_relic = ttk.Checkbutton(frame,text='유물 프리셋: 주전 저장 창에 유물 함께 저장/불러오기 추가',variable=relic)
    check_relic.pack(anchor='w',pady=5)
    ttk.Label(frame,text='유물은 보유한 개별 물건만 이동합니다. 기존 슬롯은 게임에서 체크 후 한 번 덮어써 주세요.').pack(anchor='w',pady=(0,12))
    output = tk.Text(frame,height=12,wrap='word',font=('Malgun Gothic',10),state='disabled')
    output.pack(fill='both',expand=True)
    messages = queue.Queue()
    busy = [False]
    buttons = ttk.Frame(frame)
    buttons.pack(fill='x',pady=(12,0))
    controls = [entry,browse_button,check_ko,check_relic]
    def start(verify_only):
        if busy[0]:
            return
        if not path.get().strip():
            browse()
            if not path.get().strip(): return
        game,ko,rel = path.get(),korean.get(),relic.get()
        if not verify_only and not messagebox.askokcancel('선택한 모드 적용','게임이 종료되어 있는지 확인해 주세요.\n현재 게임 파일을 백업한 뒤 선택한 구성으로 변경합니다.'):
            return
        busy[0] = True
        for control in controls: control.configure(state='disabled')
        def work():
            try:
                report = install(game,ko,rel,verify_only,log=lambda s:messages.put(('log',s)))
                messages.put(('done',report))
            except Exception as error:
                messages.put(('error',str(error)))
        threading.Thread(target=work,daemon=True).start()
    apply = ttk.Button(buttons,text='선택한 구성 적용',command=lambda:start(False))
    apply.pack(side='right')
    verify = ttk.Button(buttons,text='변경 없이 검사',command=lambda:start(True))
    verify.pack(side='right',padx=8)
    controls += [apply,verify]
    def poll():
        while not messages.empty():
            kind,value = messages.get_nowait()
            if kind=='log' or kind=='error':
                output.configure(state='normal')
                output.insert('end',str(value)+'\n')
                output.see('end')
                output.configure(state='disabled')
            if kind in ('error','done'):
                busy[0] = False
                for control in controls: control.configure(state='normal')
                if kind=='error': messagebox.showerror('작업 중단',value)
                else:
                    warning = '\n매칭되지 않은 일부 항목은 변경하지 않았습니다.' if value['skipped_scripts'] or value['skipped_translation_entries'] else ''
                    messagebox.showinfo('완료','작업을 마쳤습니다. 아래 기록을 확인해 주세요.'+warning)
        root.after(100,poll)
    def close():
        if busy[0]: messagebox.showinfo('작업 중','파일을 안전하게 처리하고 있습니다. 완료될 때까지 기다려 주세요.')
        else: root.destroy()
    root.protocol('WM_DELETE_WINDOW',close)
    root.after(100,poll)
    root.mainloop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--game')
    parser.add_argument('--korean',type=int,choices=[0,1],default=1)
    parser.add_argument('--relic',type=int,choices=[0,1],default=1)
    parser.add_argument('--verify-only',action='store_true')
    parser.add_argument('--report',type=Path)
    args = parser.parse_args()
    if args.game:
        try:
            report = install(args.game,bool(args.korean),bool(args.relic),args.verify_only)
            if args.report:
                args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        except Exception:
            if args.report:
                args.report.write_text(json.dumps({'error':traceback.format_exc()},ensure_ascii=False),encoding='utf-8')
            raise
    else:
        gui()
