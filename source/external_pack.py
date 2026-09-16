"""Small, local-only boot/overlay packs. Never rewrite the owned game pack."""
import hashlib
import struct
from pathlib import Path


def write_pack(path, files):
    with Path(path).open('wb') as out:
        out.write(bytes(112)); records=[]
        for name,data in sorted(files.items()):
            if name.startswith(('/', '\\')) or '..' in name.split('/'):
                raise ValueError('Unsafe resource path: '+name)
            out.write(bytes((-out.tell())%16)); offset=out.tell()-112
            out.write(data); encoded=name.encode('utf-8')
            encoded+=bytes((-len(encoded))%4)
            records.append(struct.pack('<I',len(encoded))+encoded+
                struct.pack('<2Q',offset,len(data))+hashlib.md5(data).digest()+struct.pack('<I',0))
        directory=out.tell()
        out.write(struct.pack('<I',len(records))+b''.join(records))
        out.seek(0);out.write(struct.pack('<6I2Q',0x43504447,3,4,6,0,2,112,directory))


def read_settings(data):
    if data[:4]!=b'ECFG':raise ValueError('Unknown project settings format')
    count,=struct.unpack_from('<I',data,4);pos=8;result=[]
    for _ in range(count):
        n,=struct.unpack_from('<I',data,pos);pos+=4
        name=data[pos:pos+n].decode('utf-8');pos+=n
        n,=struct.unpack_from('<I',data,pos);pos+=4
        value=data[pos:pos+n];pos+=n
        result.append((name,value))
    if pos!=len(data) or len(set(k for k,v in result))!=len(result):
        raise ValueError('Invalid project settings directory')
    return result


def settings_string(value):
    raw=value.encode('utf-8')
    return struct.pack('<2I',4,len(raw))+raw+bytes((-len(raw))%4)


def decode_string(value):
    if struct.unpack_from('<I',value)[0] not in (4,21):return None
    n,=struct.unpack_from('<I',value,4)
    return value[8:8+n].decode('utf-8')


def settings_bool(value):return struct.pack('<2I',1,int(value))


def write_settings(rows):
    data=b'ECFG'+struct.pack('<I',len(rows))
    for name,value in rows:
        raw=name.encode('utf-8')
        data+=struct.pack('<I',len(raw))+raw+struct.pack('<I',len(value))+value
    return data
