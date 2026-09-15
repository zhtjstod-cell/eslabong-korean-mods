"""Content matching and conservative per-key ownership; never change other locales."""
import hashlib
import json
import re
import unicodedata
from collections import defaultdict

STATE_PATH = 'KoreanSupplement/translation_state.json'


def normal(text):
    if not isinstance(text, str):
        return None
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFC', text)).strip()


def table_hash(table):
    return hashlib.sha256(json.dumps(table, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def sources(entry):
    return {normal(v) for v in [entry.get('en'), *entry.get('also_match_en', [])] if isinstance(v, str)}


def source_matches(en, key, entry):
    # Earlier releases include explicit mod-owned keys (e.g. patch.team_name)
    # whose original English key did not exist. They are not fuzzy candidates.
    if entry.get('en') is None:
        return key not in en
    return normal(en.get(key)) in sources(entry)


def apply(en, ko, catalog, enabled, previous=None, legacy_hash=None):
    ko = dict(ko)
    originals = dict(ko)
    state = json.loads(previous.decode('utf-8-sig')) if previous else {}
    if state and (state.get('format') not in (1, 2) or not isinstance(state.get('entries'), dict)):
        raise ValueError('번역 복구 기록을 읽을 수 없어 중단했습니다.')
    accepted = {entry['after'] for entry in catalog.values()}
    accepted.update(old['after'] for entry in catalog.values() for old in entry.get('previous_entries', []))
    owned = {}
    stale = state.get('format') == 2 and state.get('table_sha256') != table_hash(ko)
    if state and not stale:
        for key, item in state['entries'].items():
            if not isinstance(item, dict) or item.get('after') not in accepted:
                raise ValueError('알 수 없는 번역 복구 기록을 보호하기 위해 중단했습니다: '+key)
            if state.get('format') == 1:
                known = catalog.get(key, {})
                versions = [known, *known.get('previous_entries', [])]
                clean = lambda row: {k:v for k,v in row.items() if k!='previous_entries'}
                if not any(clean(item) == clean(version) for version in versions):
                    raise ValueError('알 수 없는 이전 번역 복구 기록: '+key)
            if item.get('before') is not None and not isinstance(item['before'], str):
                raise ValueError('잘못된 번역 복구 값: '+key)
            # Do not overwrite independently changed Korean text.
            if ko.get(key) == item['after']:
                owned[key] = dict(item)
    elif not state and legacy_hash and table_hash(ko) == legacy_hash:
        owned = {k:dict(v) for k,v in catalog.items() if ko.get(k) == v['after']}

    matched, skipped, relocated, preserved = set(), set(), [], []
    if not enabled:
        for key, item in owned.items():
            if item.get('before') is None:
                ko.pop(key, None)
            else:
                ko[key] = item['before']
        matched.update(owned)
        owned = {}
    else:
        # If the original changed meaning, remove a verified old overlay first.
        # A stale table is disowned, not restored: a game update may now supply
        # the same Korean phrase natively, and deleting it would lose game text.
        for key, item in list(owned.items()):
            source_key = item.get('source_key', key)
            if not source_matches(en, source_key, item):
                if item.get('before') is None: ko.pop(key, None)
                else: ko[key] = item['before']
                owned.pop(key)

        candidates = {}
        for key, entry in catalog.items():
            source_key = entry.get('source_key', key)
            if source_matches(en, source_key, entry):
                candidates[key] = (key, entry, source_key)
            else:
                skipped.add(key)
        # A renamed/new key can reuse a translation only when all matching
        # sources in the same top-level domain agree on one Korean value.
        index = defaultdict(list)
        for key, entry in catalog.items():
            for text in sources(entry):
                if text: index[(key.split('.')[0], text)].append((key, entry))
        for key, english in en.items():
            if key in candidates or key in catalog:
                continue
            choices = index.get((key.split('.')[0], normal(english)), [])
            if len({entry['after'] for _, entry in choices}) == 1:
                source, entry = choices[0]
                candidates[key] = (source, entry, key)
                relocated.append({'key':key, 'source_key':source})
        for key, (catalog_key, entry, source_key) in candidates.items():
            current = ko.get(key)
            english = en.get(source_key)
            allowed = current is None or current == '' or current in (entry.get('before'), entry['after']) or normal(current) == normal(english)
            if key in owned and current == owned[key]['after']:
                allowed = True
            if not allowed:
                preserved.append(key)
                continue
            matched.add(key)
            if current == entry['after']:
                continue
            before = owned[key].get('before') if key in owned else current
            ko[key] = entry['after']
            owned[key] = {'before':before, 'after':entry['after'], 'en':english,
                          'source_key':source_key, 'catalog_key':catalog_key}
    new_state = {'format':2, 'entries':owned, 'table_sha256':table_hash(ko)}
    payload = (json.dumps(new_state, ensure_ascii=False, sort_keys=True, indent=2)+'\n').encode()
    if not owned and not previous and ko == originals:
        payload = None
    return ko, payload, {'matched_translation_entries':len(matched), 'skipped_translation_entries':len(skipped),
        'translation_changes':sum(originals.get(k) != ko.get(k) for k in set(originals)|set(ko)),
        'relocated_translations':relocated, 'preserved_native_korean':preserved,
        'stale_translation_ownership_discarded':stale}
