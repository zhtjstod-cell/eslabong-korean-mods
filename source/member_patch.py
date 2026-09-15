"""Resource-independent reversible patches for matching GDScript members.

Absolute line numbers and identifier-table positions may change between game
builds. Each operation still requires an exact typed-token/indentation match.
Unknown bodies are preserved; only recognized bodies receive small deltas.
"""
import hashlib
import json
import bsdiff4
from gdc import Script, NAMES
from relic_contract import canonical, members


def serialize(script, span):
    return json.dumps(canonical(script,*span),ensure_ascii=False,separators=(',',':')).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def signature(script, span):
    depth = 0
    start,stop = span
    for i in range(start,stop):
        kind = NAMES[script.tokens[i][0]&0x7f]
        if kind in ('PARENTHESIS_OPEN','BRACKET_OPEN','BRACE_OPEN'): depth += 1
        if kind in ('PARENTHESIS_CLOSE','BRACKET_CLOSE','BRACE_CLOSE'): depth -= 1
        if kind=='COLON' and depth==0:
            return digest(serialize(script,(start,i+1)))
    raise ValueError('Function signature not found')


def _line_bytes(line):
    column,tokens = line
    return json.dumps([['line',column],*tokens],ensure_ascii=False,separators=(',',':')).encode()


def _delta_record(label, raw, targets, output):
    row = {'base':digest(raw),'variants':{}}
    for profile,value in targets.items():
        if value==raw: continue
        key = digest((label+row['base']+profile).encode())[:24]
        forward,reverse = bsdiff4.diff(raw,value),bsdiff4.diff(value,raw)
        assert bsdiff4.patch(raw,forward)==value and bsdiff4.patch(value,reverse)==raw
        (output/(key+'.delta')).write_bytes(forward)
        (output/(key+'.reverse')).write_bytes(reverse)
        row['variants'][profile] = {'sha256':digest(value),'forward':key+'.delta','reverse':key+'.reverse'}
    return row


def build_recipes(path, original, variants, output):
    base = Script(original)
    bases = members(base)
    parsed = {key:Script(value) for key,value in variants.items()}
    spans = {key:members(value) for key,value in parsed.items()}
    result = []
    for name,span in bases.items():
        raw = serialize(base,span)
        targets = {key:serialize(script,spans[key][name]) for key,script in parsed.items()}
        changed = {key:value for key,value in targets.items() if value!=raw}
        if not changed:
            continue
        if base.spelling(base.tokens[span[0]][0]) not in ('func','static'):
            raise ValueError('Only reviewed function edits are supported: '+name)
        record = {'name':name,**_delta_record('member:'+path+name,raw,changed,output),'relic_required':'relic' in changed}
        # Pure presentation can also tolerate changes elsewhere in this same
        # function. Save/load transaction hooks deliberately require the entire
        # function. The popup hook only adds controls and can use line matching.
        if not record['relic_required'] or name=='_show_save_active_popup':
            source_lines = [_line_bytes(line) for line in _lines(raw)]
            variant_lines = {key:[_line_bytes(line) for line in _lines(value)] for key,value in targets.items()}
            assert all(len(lines)==len(source_lines) for lines in variant_lines.values())
            rows = {}
            ambiguous = False
            for i,line in enumerate(source_lines):
                modified = {key:lines[i] for key,lines in variant_lines.items()}
                if all(value==line for value in modified.values()): continue
                indices = [j for j,value in enumerate(source_lines) if value==line]
                if any(any(lines[j]!=lines[i] for j in indices) for lines in variant_lines.values()):
                    ambiguous = True
                    break
                row = _delta_record('line:'+path+name,line,modified,output)
                row['count'] = len(indices)
                rows[row['base']] = row
            if not ambiguous:
                record['line_fallback'] = {'signature':signature(base,span),'lines':list(rows.values())}
        result.append(record)
    return result


def _lines(canonical_data):
    result = []
    for kind,value in json.loads(canonical_data):
        if kind=='line':
            result.append((value,[]))
        else:
            if not result:
                raise ValueError('Missing canonical line boundary')
            result[-1][1].append((kind,value))
    return result


def _codes(script, tokens):
    result = []
    for kind,value in tokens:
        if kind in (1,2):
            result.append((script.identifier(value)&~0x7f)|kind)
        elif kind==3:
            data = bytes.fromhex(value)
            if data not in script.constant_bytes:
                script.constant_bytes.append(data)
                # encode() uses raw constant bytes, never this placeholder.
                script.constants.append(None)
            result.append(3|(script.constant_bytes.index(data)<<8))
        else:
            if not isinstance(value,int) or value & 0x7f != kind or kind>=len(NAMES):
                raise ValueError('Invalid canonical token')
            result.append(value)
    return result


def _transform(raw, row, korean, relic, package):
    current = digest(raw)
    base = raw if current==row['base'] else None
    if base is None:
        for variant in row['variants'].values():
            if current==variant['sha256']:
                base = bsdiff4.patch(raw,(package/'data'/variant['reverse']).read_bytes())
                break
    if base is None: return None
    if digest(base)!=row['base']: raise ValueError('Invalid reverse member delta')
    profile = 'both' if korean and relic else 'korean' if korean else 'relic' if relic else None
    if profile=='both' and profile not in row['variants']: profile='korean'
    variant = row['variants'].get(profile)
    target = bsdiff4.patch(base,(package/'data'/variant['forward']).read_bytes()) if variant else base
    if digest(target)!=(variant['sha256'] if variant else row['base']): raise ValueError('Invalid forward member delta')
    return target


def _line_fallback(script, span, raw, candidates, korean, relic, package):
    current_lines = [_line_bytes(line) for line in _lines(raw)]
    header = signature(script,span)
    for record in candidates:
        fallback = record.get('line_fallback')
        if not fallback or fallback['signature']!=header: continue
        replacements = {}
        valid = True
        for row in fallback['lines']:
            hashes = {row['base']} | {v['sha256'] for v in row['variants'].values()}
            indices = [i for i,line in enumerate(current_lines) if digest(line) in hashes]
            if len(indices)!=row['count'] or any(i in replacements for i in indices):
                valid = False
                break
            for i in indices:
                replacements[i] = _transform(current_lines[i],row,korean,relic,package)
        if valid:
            flat = []
            for i,line in enumerate(current_lines): flat.extend(json.loads(replacements.get(i,line)))
            return json.dumps(flat,ensure_ascii=False,separators=(',',':')).encode()
    return None


def _partial_display_fallback(script, span, raw, candidates, korean, relic, package):
    """Independent exact display lines, even if another line/signature changed.

    Never use this for inventory/save transactions or combine conflicting edits.
    Unknown lines remain byte-for-byte canonical equivalents of the input.
    """
    current_lines = [_line_bytes(line) for line in _lines(raw)]
    replacements = {}
    for record in candidates:
        fallback = record.get('line_fallback')
        if record.get('relic_required') or not fallback:
            continue
        for row in fallback['lines']:
            hashes = {row['base']} | {v['sha256'] for v in row['variants'].values()}
            indices = [i for i,line in enumerate(current_lines) if digest(line) in hashes]
            if len(indices) != row['count']:
                continue
            for i in indices:
                target = _transform(current_lines[i], row, korean, False, package)
                if i in replacements and replacements[i] != target:
                    raise ValueError('Conflicting display line recipes')
                replacements[i] = target
    if not replacements:
        return None
    flat = []
    for i,line in enumerate(current_lines):
        flat.extend(json.loads(replacements.get(i, line)))
    return json.dumps(flat, ensure_ascii=False, separators=(',', ':')).encode()


def apply(data, recipes, korean, relic, package):
    script = Script(data)
    spans = members(script)
    grouped = {}
    for row in recipes:
        grouped.setdefault(row['name'],[]).append(row)
    edits, skipped, matched, changed = [], [], [], []
    expected_targets = {}
    for name,candidates in grouped.items():
        required = relic and any(r['relic_required'] for r in candidates)
        if name not in spans:
            if required:
                raise RuntimeError('유물 프리셋에 필요한 함수가 없습니다: '+name)
            skipped.append(name)
            continue
        raw = serialize(script,spans[name])
        current_hash = digest(raw)
        selected,base = None,None
        for row in candidates:
            if current_hash==row['base']:
                selected,base = row,raw
                break
            for variant in row['variants'].values():
                if current_hash==variant['sha256']:
                    selected,base = row,bsdiff4.patch(raw,(package/'data'/variant['reverse']).read_bytes())
                    break
            if selected is not None:
                break
        if selected is None:
            target = _line_fallback(script,spans[name],raw,candidates,korean,relic,package)
            if target is None and not required:
                target = _partial_display_fallback(script,spans[name],raw,candidates,korean,relic,package)
                if target is not None:
                    # A partial match is useful but must not be reported as
                    # complete coverage of every former edit in this function.
                    skipped.append(name)
            if target is None:
                if required:
                    raise RuntimeError('유물 프리셋에 필요한 함수의 동작이 달라 중단했습니다: '+name+'\n파일은 변경하지 않았습니다.')
                skipped.append(name)
                continue
        else:
            target = _transform(raw,selected,korean,relic,package)
        matched.append(name)
        if raw==target:
            continue
        old_lines,new_lines = _lines(raw),_lines(target)
        if len(old_lines)!=len(new_lines):
            raise ValueError('Member patch changes source line boundaries: '+name)
        start,stop = spans[name]
        physical = []
        for i in range(start,stop):
            if not physical or script.tokens[i][1]!=script.tokens[physical[-1][0]][1]:
                physical.append([i,i+1])
            else:
                physical[-1][1]=i+1
        if len(physical)!=len(old_lines):
            raise ValueError('Physical line count mismatch: '+name)
        for (before,after,(a,b)) in zip(old_lines,new_lines,physical):
            if before==after:
                continue
            if before[0]!=after[0]:
                raise ValueError('Member patch changes indentation: '+name)
            edits.append((a,(b-a,_codes(script,after[1]))))
        changed.append(name)
        expected_targets[name] = target
    if not edits:
        return data,{'matched':matched,'skipped':skipped,'changed':changed}
    script.replace_tokens(sorted(edits))
    encoded = script.encode()
    verified = Script(encoded)
    final_spans = members(verified)
    for name,target in expected_targets.items():
        if serialize(verified,final_spans[name])!=target:
            raise ValueError('Member patch verification failed: '+name)
    return encoded,{'matched':matched,'skipped':skipped,'changed':changed}
