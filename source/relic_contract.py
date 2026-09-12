"""Fingerprint the equipment contract, not unrelated code or token indices.

Only hashes and member names are distributed. New implementations of a required
operation fail closed; unrelated functions, comments and line shifts do not.
"""
import hashlib
import json
from gdc import Script, NAMES


ROOTS = {
    'Scripts/Relics/InventoryService.gdc': [
        '_init', 'for_active_lineup', 'equip', 'unequip', 'find_item',
        'validate_lineup_relics', '_active_capacity', 'inventory_changed',
    ],
    'Scripts/Relics/ItemInstance.gdc': [
        'instance_id', 'definition_id', 'state', 'inventory_slot',
        'equipped_fighter_id', 'equipped_slot', 'local_listing_id',
        'quarantine_reason', 'capacity_locked', 'rolled_modifiers',
        'is_equipped', 'is_in_inventory', 'transition_to_inventory',
        'transition_to_equipped', 'get_relic_definition',
    ],
    'Scripts/Campaign/MercenaryInstance.gdc': [
        'instance_id', 'equipped_item_instance_ids', 'equipped_relics',
        'ensure_relic_slot_count', 'is_relic_slot_unlocked',
        'get_equipped_item_instance_id', 'set_equipped_item_instance_id',
        'clear_equipped_item_instance_id',
    ],
    'Scripts/Campaign/CampaignSave.gdc': [
        'owned_item_instances', 'owned_mercenaries', 'item_new_instance_ids',
        'item_inventory_capacity', 'active_lineup_slot', 'lineup_slots',
        'deployed_mercenary_ids', 'DEFAULT_ITEM_INVENTORY_CAPACITY',
        'MAX_ITEM_INVENTORY_CAPACITY', 'get_mercenary_by_id',
        'get_saved_active_lineup', 'set_saved_active_lineup',
    ],
}


def members(script):
    """Top-level declarations; continuation lines and inner classes stay inside."""
    starts = []
    firsts = {line: i for i, (_, line) in reversed(list(enumerate(script.tokens)))}
    declared = {'FUNC', 'VAR', 'TK_CONST', 'ENUM', 'CLASS', 'SIGNAL', 'EXTENDS', 'CLASS_NAME'}
    for line, start in sorted(firsts.items()):
        if script.columns.get(start, 1) != 1:
            continue
        i = start
        # Export annotations can be on the same line as the declaration.
        while i < len(script.tokens) and script.tokens[i][1] == line:
            code = script.tokens[i][0]
            kind = NAMES[code & 0x7f]
            if kind in declared:
                if kind in ('EXTENDS', 'CLASS_NAME'):
                    name = '@' + kind.lower()
                elif script.tokens[i+1][0] & 0x7f == 2:
                    name = script.spelling(script.tokens[i+1][0])
                else:
                    raise ValueError('Unnamed top-level declaration')
                starts.append((start, name))
                break
            if kind not in ('ANNOTATION', 'STATIC', 'IDENTIFIER', 'LITERAL', 'PARENTHESIS_OPEN', 'PARENTHESIS_CLOSE', 'COMMA'):
                break
            i += 1
    result = {}
    for n, (start, name) in enumerate(starts):
        stop = starts[n+1][0] if n+1 < len(starts) else len(script.tokens)
        while stop > start and (script.tokens[stop-1][0] & 0x7f) == NAMES.index('TK_EOF'):
            stop -= 1
        if name in result:
            raise ValueError('Duplicate top-level member: ' + name)
        result[name] = (start, stop)
    return result


def canonical(script, start, stop):
    result = []
    previous = None
    for i in range(start, stop):
        code, line = script.tokens[i]
        kind = code & 0x7f
        if line != previous:
            # Retain line boundaries and indentation (which affect GDScript).
            result.append(['line', script.columns.get(i, 1)])
            previous = line
        value = script.identifiers[code >> 8] if kind in (1, 2) else script.constant_bytes[code >> 8].hex() if kind == 3 else code
        result.append([kind, value])
    return result


def fingerprint(script, span):
    return hashlib.sha256(json.dumps(canonical(script, *span), ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def make_contract(data, roots):
    script = Script(data)
    spans = members(script)
    selected = set(roots) | {'@extends', '@class_name'}
    pending = list(selected)
    while pending:
        name = pending.pop()
        if name not in spans:
            raise ValueError('Missing contract member: ' + name)
        start, stop = spans[name]
        # Conservative local dependency closure, including fields and constants.
        # Extra selections are safe; they can only cause rejection, not bypass it.
        for code, _ in script.tokens[start:stop]:
            if code & 0x7f != 2:
                continue
            reference = script.identifiers[code >> 8]
            if reference in spans and reference not in selected:
                selected.add(reference)
                pending.append(reference)
    return {name: fingerprint(script, spans[name]) for name in sorted(selected)}


def mismatches(data, expected):
    script = Script(data)
    spans = members(script)
    return [name for name, digest in expected.items()
            if name not in spans or fingerprint(script, spans[name]) != digest]
