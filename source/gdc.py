"""Inspect and surgically rewrite Godot 4.6 tokenizer buffers locally.

Format: Godot's modules/gdscript/gdscript_tokenizer_buffer.cpp (MIT).
Game scripts and recovered source are private build inputs, not patch sources.
"""
from pathlib import Path
import json
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime/python_packages'))
import zstandard

NAMES = '''EMPTY ANNOTATION IDENTIFIER LITERAL LESS LESS_EQUAL GREATER GREATER_EQUAL EQUAL_EQUAL BANG_EQUAL AND OR NOT AMPERSAND_AMPERSAND PIPE_PIPE BANG AMPERSAND PIPE TILDE CARET LESS_LESS GREATER_GREATER PLUS MINUS STAR STAR_STAR SLASH PERCENT EQUAL PLUS_EQUAL MINUS_EQUAL STAR_EQUAL STAR_STAR_EQUAL SLASH_EQUAL PERCENT_EQUAL LESS_LESS_EQUAL GREATER_GREATER_EQUAL AMPERSAND_EQUAL PIPE_EQUAL CARET_EQUAL IF ELIF ELSE FOR WHILE BREAK CONTINUE PASS RETURN MATCH WHEN AS ASSERT AWAIT BREAKPOINT CLASS CLASS_NAME TK_CONST ENUM EXTENDS FUNC TK_IN IS NAMESPACE PRELOAD SELF SIGNAL STATIC SUPER TRAIT VAR TK_VOID YIELD BRACKET_OPEN BRACKET_CLOSE BRACE_OPEN BRACE_CLOSE PARENTHESIS_OPEN PARENTHESIS_CLOSE COMMA SEMICOLON PERIOD PERIOD_PERIOD PERIOD_PERIOD_PERIOD COLON DOLLAR FORWARD_ARROW UNDERSCORE NEWLINE INDENT DEDENT CONST_PI CONST_TAU CONST_INF CONST_NAN VCS_CONFLICT_MARKER BACKTICK QUESTION_MARK ERROR TK_EOF TK_MAX'''.split()
SPELLINGS = '< <= > >= == != and or not && || ! & | ~ ^ << >> + - * ** / % = += -= *= **= /= %= <<= >>= &= |= ^='.split()
LEX = dict(zip(NAMES[4:40], SPELLINGS))
LEX.update(dict(zip(NAMES[73:88], ['[', ']', '{', '}', '(', ')', ',', ';', '.', '..', '...', ':', '$', '->', '_'])))
LEX.update({'TK_CONST':'const','TK_IN':'in','TK_VOID':'void', 'CONST_PI':'PI','CONST_TAU':'TAU','CONST_INF':'INF','CONST_NAN':'NAN'})


class Script:
    def __init__(self, data):
        assert data[:4] == b'GDSC'
        self.version, size = struct.unpack_from('<2I', data, 4)
        assert self.version == 101
        self.raw = zstandard.ZstdDecompressor().decompress(data[12:], max_output_size=size) if size else data[12:]
        if size:
            assert len(self.raw) == size
        ni, nc, nl, nt = struct.unpack_from('<4I', self.raw)
        pos = 16
        self.identifiers = []
        for _ in range(ni):
            size = struct.unpack_from('<I', self.raw, pos)[0]
            pos += 4
            self.identifiers.append(bytes(x ^ 0xb6 for x in self.raw[pos:pos+4*size]).decode('utf-32-le'))
            pos += 4*size
        self.constants = []
        self.constant_bytes = []
        for _ in range(nc):
            start = pos
            tag = struct.unpack_from('<I', self.raw, pos)[0]
            pos += 4
            kind = tag & 0xffff
            wide = bool(tag & (1 << 16))
            if kind == 0:
                value = None
            elif kind in (1, 2, 3):
                fmt = '<d' if kind == 3 and wide else '<f' if kind == 3 else '<q' if wide else '<i'
                value = struct.unpack_from(fmt, self.raw, pos)[0]
                pos += struct.calcsize(fmt)
                if kind == 1:
                    value = bool(value)
            elif kind in (4, 21):
                size = struct.unpack_from('<I', self.raw, pos)[0]
                pos += 4
                value = self.raw[pos:pos+size].decode('utf-8')
                pos += (size+3) & ~3
            else:
                raise ValueError(f'Unsupported constant variant {tag} at {pos-4}')
            self.constants.append(value)
            self.constant_bytes.append(self.raw[start:pos])
        self.lines = dict(struct.unpack_from('<2I', self.raw, pos+8*i) for i in range(nl))
        pos += nl*8
        self.columns = dict(struct.unpack_from('<2I', self.raw, pos+8*i) for i in range(nl))
        pos += nl*8
        self.tokens = []
        for _ in range(nt):
            wide = self.raw[pos] & 0x80
            code = struct.unpack_from('<I', self.raw, pos)[0] & ~0x80 if wide else self.raw[pos]
            pos += 4 if wide else 1
            line = struct.unpack_from('<I', self.raw, pos)[0]
            pos += 4
            self.tokens.append((code, line))
        assert pos == len(self.raw), (pos, len(self.raw))

    def spelling(self, code):
        kind = code & 0x7f
        if kind in (1, 2):
            return self.identifiers[code >> 8]
        if kind == 3:
            return json.dumps(self.constants[code >> 8], ensure_ascii=False)
        return LEX.get(NAMES[kind], NAMES[kind].lower())

    def source(self):
        lines = {}
        for i, (code, line) in enumerate(self.tokens):
            if line not in lines:
                lines[line] = ' ' * max(0, self.columns.get(i, 1)-1)
            lines[line] += self.spelling(code) + ' '
        return '\n'.join(lines.get(i, '').rstrip() for i in range(1, max(lines)+1)) + '\n'

    def encode(self):
        raw = bytearray(struct.pack('<4I', len(self.identifiers), len(self.constants), len(self.lines), len(self.tokens)))
        for value in self.identifiers:
            raw += struct.pack('<I', len(value))
            raw += bytes(x ^ 0xb6 for x in value.encode('utf-32-le'))
        raw += b''.join(self.constant_bytes)
        for table in (self.lines, self.columns):
            for index, value in table.items():
                raw += struct.pack('<2I', index, value)
        for code, line in self.tokens:
            raw += struct.pack('<2I', code | 0x80, line) if code & 0x7f else struct.pack('<BI', code, line)
        return b'GDSC' + struct.pack('<2I', self.version, len(raw)) + zstandard.ZstdCompressor().compress(raw)

    def identifier(self, value):
        if value not in self.identifiers:
            self.identifiers.append(value)
        return 2 | (self.identifiers.index(value) << 8)

    def literal(self, value):
        assert isinstance(value, str)
        if value not in self.constants:
            data = value.encode('utf-8')
            self.constants.append(value)
            self.constant_bytes.append(struct.pack('<2I', 4, len(data)) + data + bytes((-len(data)) % 4))
        return 3 | (self.constants.index(value) << 8)

    def function_span(self, name):
        functions = [(i, self.identifiers[self.tokens[i+1][0] >> 8]) for i, (code, _) in enumerate(self.tokens) if code == NAMES.index('FUNC') and (self.tokens[i+1][0] & 0x7f) == 2]
        start = next(i for i, n in functions if n == name)
        stop = next((i for i, _ in functions if i > start and self.columns.get(i, 1) == 1), len(self.tokens))
        return start, stop

    def replace_tokens(self, edits):
        """Apply non-overlapping edits and relocate line/indent metadata exactly."""
        edits = dict(edits)
        tokens, mapping = [], {}
        i = 0
        while i < len(self.tokens):
            mapping[i] = len(tokens)
            if i in edits:
                count, codes = edits[i]
                tokens.extend((c, self.tokens[i][1]) for c in codes)
                assert not any(j in self.lines for j in range(i+1,i+count)), 'Cannot delete a line boundary'
                i += count
            else:
                tokens.append(self.tokens[i])
                i += 1
        self.lines = {mapping[i]:v for i,v in self.lines.items()}
        self.columns = {mapping[i]:v for i,v in self.columns.items()}
        self.tokens = tokens


if __name__ == '__main__':
    for name in sys.argv[1:]:
        path = Path(name)
        script = Script(path.read_bytes())
        assert Script(script.encode()).raw == script.raw
        destination = ROOT / 'work/decoded' / path.relative_to(ROOT / 'work/extracted').with_suffix('.gd')
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(script.source(), encoding='utf-8')
        print(destination)
