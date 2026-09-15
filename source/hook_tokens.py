"""Small-token encoder used by public reversible integration hooks."""
import json,re,struct
from gdc import NAMES,LEX
def codes(s,source):
    result=[]
    for word in re.findall(r'"(?:[^"\\]|\\.)*"|[A-Za-z_][A-Za-z_0-9]*|[0-9]+|<=|>=|==|!=|[^\s]',source):
        if word.startswith('"'):code=s.literal(json.loads(word))
        elif word.isdigit():
            value=int(word);index=next((i for i,v in enumerate(s.constants) if type(v) is int and v==value),None)
            if index is None:
                index=len(s.constants);s.constants.append(value);s.constant_bytes.append(struct.pack('<2I',2,value))
            code=3|(index<<8)
        elif word in ('self','preload','return','if','and','not','var'):code=NAMES.index(word.upper())
        elif word in LEX.values():code=NAMES.index(next(k for k,v in LEX.items() if v==word))
        else:code=s.identifier(word)
        result.append(code)
    return result
def locate(s,function,source,last=False):
    start,stop=s.function_span(function);words=[s.spelling(c) for c,_ in s.tokens]
    expected=[s.spelling(c) for c in codes(s,source)]
    found=[i for i in range(start,stop-len(expected)+1) if words[i:i+len(expected)]==expected]
    return (found[-1:] if last and found else found),len(expected)
