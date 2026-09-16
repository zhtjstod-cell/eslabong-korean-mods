"""Reversible call-site matching; unrelated native members stay unchanged."""
from gdc import Script
from hook_tokens import locate,codes
from relic_contract import members,fingerprint

def rewrite(data,rules,enable=True):
    s=Script(data);before={n:fingerprint(s,v) for n,v in members(s).items()};edits=[]
    for fn,old,new in rules:
        hits,size=locate(s,fn,new)
        if hits:
            if len(hits)!=1:raise ValueError('중복된 모드 연결: '+fn)
            if not enable:edits.append((hits[0],(size,codes(s,old))))
        elif enable:
            hits,size=locate(s,fn,old)
            if len(hits)!=1:raise ValueError('안전하게 연결할 위치를 찾지 못했습니다: '+fn)
            edits.append((hits[0],(size,codes(s,new))))
    s.replace_tokens(edits);encoded=s.encode() if edits else data;after=Script(encoded)
    changed={fn for fn,_,_ in rules}
    for n,v in members(after).items():
        if n not in changed and fingerprint(after,v)!=before[n]:raise ValueError('관계없는 함수가 변경됨: '+n)
    return encoded

def require_members(pack,path,required):
    missing=set(required)-set(members(Script(pack.read(path))))
    if missing:raise ValueError('필수 게임 기능 변경: '+path+' / '+', '.join(sorted(missing)))

def require_calls(pack,path,calls):
    s=Script(pack.read(path))
    for name,count in calls.items():
        if name not in members(s):
            raise ValueError('필수 게임 함수가 없습니다: '+path+' / '+name)
        start,stop=s.function_span(name);words=[s.spelling(c) for c,_ in s.tokens[start:stop]]
        depth=0;parts=[[]]
        for word in words[words.index('(')+1:]:
            if word==')' and depth==0:break
            if word==',' and depth==0:parts.append([]);continue
            parts[-1].append(word)
            if word in ('(','[','{'):depth+=1
            if word in (')',']','}'):depth-=1
        parts=[p for p in parts if p]
        if not sum('=' not in p for p in parts)<=count<=len(parts):raise ValueError('게임 함수의 인자가 변경됨: '+name)
