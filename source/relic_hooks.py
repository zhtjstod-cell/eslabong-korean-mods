"""Discover preset integration from native calls, not function hashes/locals.

The only game tokens changed are the call sites below. Unknown or ambiguous
structures fail before writing; equipment operations remain the native methods.
"""
from dataclasses import dataclass
from gdc import Script, NAMES
from hook_tokens import codes
from relic_contract import members, fingerprint, canonical

HELPER = 'RelicPresets/RelicPresets.gd'
R = 'preload("res://' + HELPER + '").'
LEGACY_SIZE = 'Vector2i(704,86+70*CampaignSave.SAVED_ACTIVE_LINEUP_SLOT_COUNT)'


@dataclass
class Call:
    name: str
    at: int
    opening: int
    closing: int
    args: list


class Syntax:
    def __init__(self, script):
        self.s = script
        self.words = [script.spelling(c) for c, _ in script.tokens]
        self.spans = members(script)
        self.pairs = {}
        stack = []
        for i, word in enumerate(self.words):
            if word in ('(', '[', '{'):
                stack.append((word, i))
            elif word in (')', ']', '}'):
                if not stack or stack[-1][0] != {')':'(', ']':'[', '}':'{'}[word]:
                    raise ValueError('유물 연결: 게임 코드의 괄호 구조를 읽을 수 없습니다.')
                _, start = stack.pop()
                self.pairs[start] = i
        if stack:
            raise ValueError('유물 연결: 닫히지 않은 게임 코드입니다.')

    def calls(self, name, span=None):
        begin, end = span or (0, len(self.words))
        result = []
        for i in range(begin, end - 1):
            if self.words[i:i+2] != [name, '(']:
                continue
            if i > 0 and self.words[i-1] == 'func':
                continue
            close = self.pairs[i+1]
            args = []
            start = cursor = i + 2
            while cursor < close:
                if self.words[cursor] == ',':
                    args.append((start, cursor))
                    start = cursor + 1
                cursor = self.pairs.get(cursor, cursor) + 1
            if start < close:
                args.append((start, close))
            result.append(Call(name, i, i+1, close, args))
        return result

    def owner(self, index):
        return one([name for name, (a,b) in self.spans.items() if a <= index < b], '함수 소유 범위')

    def text(self, span):
        return ' '.join(self.words[slice(*span)])

    def identifier(self, span):
        a, b = span
        if b != a+1 or self.s.tokens[a][0] & 0x7f != NAMES.index('IDENTIFIER'):
            raise ValueError('유물 연결: 단순 참조가 아닌 인수는 자동 변경하지 않습니다.')
        return self.words[a]

    def receiver(self, call):
        if call.at < 2 or self.words[call.at-1] != '.':
            raise ValueError('유물 연결: 저장 객체 참조를 찾지 못했습니다.')
        return self.identifier((call.at-2, call.at-1))


def one(values, label):
    if len(values) != 1:
        raise ValueError(f'유물 연결: {label} 후보 {len(values)}개. 모호한 코드는 변경하지 않습니다.')
    return values[0]


class Edits:
    def __init__(self, script):
        self.s = script
        self.replacements = []
        self.edges = {}

    def replace(self, start, stop, source):
        self.replacements.append((start, (stop-start, codes(self.s, source))))

    def wrap(self, span, prefix, suffix=')'):
        a, b = span
        self.edges.setdefault(a, [[], []])[0] += codes(self.s, prefix)
        edge = self.edges.setdefault(b-1, [[], []])
        edge[1] = codes(self.s, suffix) + edge[1]

    def finish(self):
        for i, (pre, post) in self.edges.items():
            self.replacements.append((i, (1, pre + [self.s.tokens[i][0]] + post)))
        occupied = set()
        for i, (count, _) in self.replacements:
            if any(j in occupied for j in range(i, i+count)):
                raise ValueError('유물 연결: 서로 겹치는 수정입니다.')
            occupied.update(range(i, i+count))
        self.s.replace_tokens(self.replacements)
        return self.s.encode() if self.replacements else None


def remove(data):
    """Unwrap only calls to our resource; no dependence on native function names."""
    s = Script(data)
    q = Syntax(s)
    helper = ['preload', '(', '"res://' + HELPER + '"', ')', '.']
    starts = [i for i in range(len(q.words)-4) if q.words[i:i+5] == helper]
    if not starts:
        return data
    e = Edits(s)
    arities = {'attach':3, 'capture_preset':3, 'commit':2, 'message':2, 'undo':2, 'popup_size':1}
    for i in starts:
        name = q.words[i+5]
        if name not in arities:
            raise ValueError('알 수 없는 유물 모드 연결은 유지하고 중단합니다: ' + name)
        call = one([c for c in q.calls(name) if c.at == i+5], name)
        if len(call.args) != arities[name] or (name != 'popup_size' and q.text(call.args[0]) != 'self'):
            raise ValueError('유물 모드 연결의 인수 구조가 변경되었습니다: ' + name)
        if name == 'popup_size':
            q.identifier(call.args[0])
            # Exact inverse of the fixed-size hook shipped in the first release.
            e.replace(i, call.closing+1, LEGACY_SIZE)
        elif name == 'attach':
            parent = q.identifier(call.args[1])
            # Retain the original child expression and its line metadata.
            e.replace(i, call.args[2][0], parent + '.add_child(')
        elif name == 'commit':
            e.replace(i, call.closing+1, '_commit_pending_lineup_changes()')
        else:
            start, stop = call.args[-1]
            e.replace(i, start, '')
            e.replace(stop, call.closing+1, '')
    result = e.finish()
    if any(c & 0x7f == 3 and s.constants[c >> 8] == 'res://'+HELPER for c,_ in s.tokens):
        raise ValueError('알 수 없는 유물 보조 파일 참조가 남아 있습니다.')
    return result


def connect(data):
    """Find the label, native preset setter/getter, commit and success toast."""
    original = Script(data)
    plain = remove(data)
    s = Script(plain)
    q = Syntax(s)
    before = {name:fingerprint(s,span) for name,span in q.spans.items()}
    e = Edits(s)
    changed = set()

    # A stable localization key identifies the explanatory label. It does not
    # depend on the current locale, English prose, function name, or local name.
    loc = one([c for c in q.calls('_loc') if c.args and
               q.text(c.args[0]) == '"ui.myteam.saved_active.description"'], '주전 저장 안내')
    if q.words[loc.at-2:loc.at] != ['text', '='] or q.words[loc.at-3] != '.':
        raise ValueError('유물 연결: 저장 안내 라벨 구조가 변경되었습니다.')
    label = q.identifier((loc.at-4, loc.at-3))
    popup = q.owner(loc.at)
    add = one([c for c in q.calls('add_child', q.spans[popup])
               if c.args and q.text(c.args[0]) == label], '주전 저장 안내 배치')
    if len(add.args) != 1:
        raise ValueError('유물 연결: 안내 배치 인수가 변경되었습니다.')
    parent = q.receiver(add)
    e.replace(add.at-2, add.opening+1, R+'attach(self,'+parent+',')
    # Old releases have no content-driven popup layout. Retain their one known
    # sizing hook; current scroll-container sizing is deliberately untouched.
    size_words = [s.spelling(c) for c in codes(s, LEGACY_SIZE)]
    legacy_sizes = [c for c in q.calls('Vector2i', q.spans[popup])
                    if q.words[c.at:c.closing+1] == size_words]
    if len(legacy_sizes) > 1:
        raise ValueError('유물 연결: 이전 팝업 크기 연결이 모호합니다.')
    if legacy_sizes:
        c = legacy_sizes[0]
        e.replace(c.at,c.closing+1,R+'popup_size('+parent+')')
    changed.add(popup)

    setter = one(q.calls('set_saved_active_lineup'), '주전 저장 호출')
    if len(setter.args) != 2:
        raise ValueError('유물 연결: 주전 저장 인수가 변경되었습니다.')
    receiver = q.receiver(setter)
    e.wrap(setter.args[1], R+'capture_preset(self,'+receiver+',')
    changed.add(q.owner(setter.at))

    # The loading function is selected by its data flow, not a hardcoded name.
    candidates = []
    for getter in q.calls('get_saved_active_lineup'):
        name = q.owner(getter.at)
        commits = q.calls('_commit_pending_lineup_changes', q.spans[name])
        snapshots = q.calls('_capture_lineup_snapshot', q.spans[name])
        if commits and snapshots:
            candidates.append((getter, name, commits))
    getter, loading, commits = one(candidates, '주전 불러오기 흐름')
    if len(getter.args) != 1:
        raise ValueError('유물 연결: 주전 조회 인수가 변경되었습니다.')
    slot = q.identifier(getter.args[0])
    commit = one(commits, '주전 적용 호출')
    if commit.args or q.words[commit.at-1] == '.':
        raise ValueError('유물 연결: 주전 적용 호출 구조가 변경되었습니다.')
    e.replace(commit.at, commit.closing+1, R+'commit(self,'+slot+')')
    toast = one([c for c in q.calls('_show_roster_toast', q.spans[loading])
                 if len(c.args) == 2 and c.at > commit.at], '주전 적용 완료 알림')
    # Undo must come from the game's snapshot, not an arbitrary second argument.
    undo = q.identifier(toast.args[1])
    snap = one(q.calls('_capture_lineup_snapshot', q.spans[loading]), '주전 되돌리기 기록')
    line_start = max(i for i in range(snap.at) if s.tokens[i][1] != s.tokens[snap.at][1]) + 1
    if undo not in q.words[line_start:snap.at] or '=' not in q.words[line_start:snap.at]:
        raise ValueError('유물 연결: 되돌리기 기록 참조가 변경되었습니다.')
    e.wrap(toast.args[0], R+'message(self,')
    e.wrap(toast.args[1], R+'undo(self,')
    changed.add(loading)
    result = e.finish()
    after = Script(result)
    after_spans = members(after)
    for name in q.spans:
        if name not in changed and before[name] != fingerprint(after, after_spans[name]):
            raise ValueError('관계없는 게임 기능이 변경되어 중단했습니다: '+name)
    # Reinstall does not grow the pack or change unused constant tables.
    if canonical(original,0,len(original.tokens)) == canonical(after,0,len(after.tokens)):
        return data
    return result
