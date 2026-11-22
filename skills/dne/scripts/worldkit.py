#!/usr/bin/env python3
"""Campaign-local world content, using SRD records and 5e class chassis."""
import argparse
import json
import re
from fractions import Fraction
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import campaign_ruleset, find_campaign, norm_key, srd_path

CATEGORIES = ('races', 'classes', 'backgrounds', 'monsters', 'spells',
              'equipment', 'features', 'conditions', 'class_options')
CR_XP = dict(enumerate((10, 200, 450, 700, 1100, 1800, 2300, 2900, 3900,
                       5000, 5900, 7200, 8400, 10000, 11500, 13000, 15000,
                       18000, 20000, 22000, 25000, 33000, 41000, 50000,
                       62000, 75000, 90000, 105000, 120000, 135000, 155000)))
CR_XP.update({0.125: 25, 0.25: 50, 0.5: 100})


def path(campaign):
    return find_campaign(campaign) / 'worldkit.json'


def load(campaign):
    source = path(campaign)
    if not source.exists():
        return None
    try:
        kit = json.loads(source.read_text(encoding='utf-8'))
    except ValueError as exc:
        raise ValueError(f'{source}: invalid JSON: {exc}') from exc
    errors = validate(kit, campaign)
    if errors:
        raise ValueError('\n'.join(errors))
    return kit


def find(kit, category, name):
    key = norm_key(name)
    if not key:
        return None
    return next((r for r in kit.get(category, [])
                 if key in (norm_key(r.get('name')), norm_key(r.get('index')))), None)


def skill_names(kit):
    return kit.get('skills', {}) if kit else {}


def class_powers(kit, cls):
    keys = {norm_key(cls[k]) for k in ('name', 'index') if cls and cls.get(k)}
    return [s for s in (kit or {}).get('spells', [])
            if keys.intersection(norm_key(c) for c in s.get('classes', []))]


def class_chassis(name, campaign=None):
    from character import _race_key
    kit = load(campaign) if campaign else None
    record = find(kit, 'classes', name) if kit else None
    return _race_key(record['chassis'] if record else name)


def validate(kit, campaign=None):
    from character import HIT_DICE, STATS, SKILLS, _AC_PAT, _race_key
    from combat import parse_damage
    if not isinstance(kit, dict):
        return ['worldkit: top-level must be a dict']
    errors = []
    meta = kit.get('_meta', {})
    if isinstance(meta, dict) and 'power' in meta and meta['power'] not in ('none', 'low', 'medium', 'high'):
        errors.append('_meta.power must be none, low, medium or high')
    rules_2024 = (isinstance(meta, dict) and meta.get('base_ruleset') == '2024'
                  or campaign is not None and campaign_ruleset(campaign) == '2024')
    srd_2024 = {}
    if rules_2024 and srd_path('2024').exists():
        try:
            srd_2024 = json.loads(srd_path('2024').read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            errors.append(f'cannot load 2024 SRD for validation: {exc}')
    masteries = {norm_key(r['name']) for r in srd_2024.get('weapon_mastery_properties', [])}
    feats = {norm_key(r['name']) for r in srd_2024.get('feats', [])}
    classes = [r for r in kit.get('classes', []) if isinstance(r, dict)] if isinstance(kit.get('classes', []), list) else []
    class_keys = {norm_key(r.get(k)) for r in classes for k in ('name', 'index') if r.get(k)}
    skills = set(SKILLS) | set(kit.get('skills', {}).values())
    spells = [r for r in kit.get('spells', []) if isinstance(r, dict)] if isinstance(kit.get('spells', []), list) else []
    srd_spells = None
    srd_options = None
    categories = set(CATEGORIES) | {k for k, v in kit.items() if isinstance(v, list)}
    for category in sorted(categories):
        if category not in kit:
            continue
        records = kit[category]
        if not isinstance(records, list):
            errors.append(f'{category}: must be a list of dicts')
            continue
        seen = set()
        indices = set()
        for i, record in enumerate(records):
            label = f'{category}[{i}]'
            if not isinstance(record, dict):
                errors.append(f'{label}: must be a dict')
                continue
            name = record.get('name')
            label = f'{label} {name or "<unnamed>"}'
            if not isinstance(name, str) or not name.strip():
                errors.append(f'{label}: name is required')
            else:
                key = _race_key(name)
                if key in seen:
                    errors.append(f'{label}: duplicate name {name}')
                seen.add(key)
            if 'index' in record:
                index = record['index']
                if not isinstance(index, str) or not re.fullmatch(r'[a-z0-9]+(-[a-z0-9]+)*', index):
                    errors.append(f'{label}: invalid index {index!r}')
                elif index in indices:
                    errors.append(f'{label}: duplicate index {index}')
                if isinstance(index, str):
                    indices.add(index)
            if category == 'classes':
                chassis = record.get('chassis')
                if not isinstance(chassis, str) or chassis.lower() not in HIT_DICE:
                    errors.append(f'{label}: invalid chassis {chassis!r}')
                subs = record.get('subclasses', [])
                if not isinstance(subs, list) or any(
                        not isinstance(s, dict) or not s.get('name') for s in subs):
                    errors.append(f'{label}: subclasses must be a list of {{name, description}}')
            elif category == 'races':
                if type(record.get('speed')) is not int:
                    errors.append(f'{label}: speed must be an integer')
                bonuses = record.get('ability_bonuses')
                if not isinstance(bonuses, dict):
                    errors.append(f'{label}: ability_bonuses must be a dict')
                else:
                    if all(type(v) is int for v in bonuses.values()) and sum(bonuses.values()) != 3:
                        errors.append(f'{label}: ability_bonuses must total +3')
                    for ability, value in bonuses.items():
                        if ability not in STATS or type(value) is not int:
                            errors.append(f'{label}: invalid ability_bonuses {ability}={value!r}')
            elif category == 'backgrounds':
                if rules_2024 and 'feat' in record and norm_key(record['feat']) not in feats:
                    errors.append(f'{label}: unknown 2024 feat {record["feat"]!r}')
                options = record.get('ability_options')
                if (not isinstance(options, list) or len(options) != 3
                        or any(a not in STATS for a in options)
                        or len(set(options)) != 3):
                    errors.append(f'{label}: ability_options must contain 3 distinct abilities')
                bg_skills = record.get('skills')
                if not isinstance(bg_skills, list) or len(bg_skills) != 2:
                    errors.append(f'{label}: skills must contain exactly 2 entries')
                if isinstance(bg_skills, list):
                    for skill in bg_skills:
                        if not isinstance(skill, str) or skill not in skills:
                            errors.append(f'{label}: unknown skill {skill!r}')
            elif category == 'monsters':
                if record.get('role') not in ('brute', 'skirmisher', 'ranged', 'caster', 'support'):
                    errors.append(f'{label}: invalid role {record.get("role")!r}')
                biomes = record.get('biomes')
                if (not isinstance(biomes, list) or not biomes
                        or any(not isinstance(b, str) or not b or b != b.strip() for b in biomes)):
                    errors.append(f'{label}: biomes must be non-empty strings without surrounding whitespace')
                dice = re.fullmatch(r'(\d+)d(\d+)([+-]\d+)?', str(record.get('hp_dice', '')))
                if dice:
                    n, die, offset = int(dice[1]), int(dice[2]), int(dice[3] or 0)
                    hp = record.get('hp')
                    if not isinstance(hp, (int, float)) or not n + offset <= hp <= n * die + offset:
                        errors.append(f'{label}: hp {hp!r} outside hp_dice range')
                for field in ('cr', 'xp', 'hp', 'ac', 'str', 'dex', 'con', 'int', 'wis', 'cha'):
                    if field not in record:
                        errors.append(f'{label}: missing {field}')
                cr = record.get('cr')
                try:
                    cr = {'1/8': 0.125, '1/4': 0.25, '1/2': 0.5}.get(str(cr), cr)
                    expected = CR_XP.get(float(cr))
                except (TypeError, ValueError):
                    expected = None
                if expected is None or record.get('xp') != expected:
                    errors.append(f'{label}: xp must match standard CR {cr!r} ({expected})')
            elif category == 'spells':
                level = record.get('level')
                if type(level) is not int or not 0 <= level <= 9:
                    errors.append(f'{label}: level must be an integer 0..9')
                spell_classes = record.get('classes', [])
                if not isinstance(spell_classes, list):
                    errors.append(f'{label}: classes must be a list')
                    spell_classes = []
                for cls in spell_classes:
                    if norm_key(cls) not in class_keys:
                        errors.append(f'{label}: unknown class {cls!r}')
                for chassis in re.findall(r'\(chassis:\s*([^),]+)', str(record.get('description', '')), re.I):
                    if srd_spells is None:
                        srd_spells = {}
                        try:
                            base_spells = json.loads(srd_path('2014').read_text(encoding='utf-8')).get('spells', [])
                        except (OSError, ValueError) as exc:
                            errors.append(f'{label}: cannot validate spell chassis: {exc}')
                            base_spells = []
                        for spell in base_spells + srd_2024.get('spells', []):
                            for key in ('name', 'index'):
                                if spell.get(key):
                                    srd_spells.setdefault(norm_key(spell[key]), set()).add(spell['level'])
                    chassis_levels = srd_spells.get(norm_key(chassis))
                    if not chassis_levels:
                        errors.append(f'{label}: unknown SRD spell chassis {chassis.strip()}')
                    elif type(level) is int and level not in chassis_levels:
                        levels = ' or '.join(str(n) for n in sorted(chassis_levels))
                        errors.append(f'{label}: level must match {chassis.strip()} (level {levels})')
            elif category == 'class_options':
                if record.get('kind') not in ('invocation', 'fighting_style', 'pact_boon', 'metamagic', 'other'):
                    errors.append(f'{label}: invalid kind {record.get("kind")!r}')
                if 'level' in record and type(record['level']) is not int:
                    errors.append(f'{label}: level must be an integer')
                for chassis in re.findall(r'\(chassis:\s*([^),]+)', str(record.get('description', '')), re.I):
                    if srd_options is None:
                        try:
                            records = json.loads(srd_path('2014').read_text(encoding='utf-8')).get('class_options', [])
                            srd_options = {norm_key(r[k]) for r in records for k in ('name', 'index') if r.get(k)}
                        except (OSError, ValueError) as exc:
                            errors.append(f'{label}: cannot validate class_options chassis: {exc}')
                            srd_options = set()
                    if norm_key(chassis) not in srd_options:
                        errors.append(f'{label}: unknown SRD class_options chassis {chassis.strip()}')
            elif category == 'equipment' and 'damage' in record:
                try:
                    parse_damage(record['damage'] if isinstance(record['damage'], str) else '')
                except ValueError:
                    errors.append(f'{label}: invalid damage {record["damage"]!r}')
            if category == 'equipment' and record.get('ac'):
                if not isinstance(record['ac'], str) or not _AC_PAT.fullmatch(record['ac']):
                    errors.append(f'{label}: invalid ac {record["ac"]!r}')
            if category == 'equipment' and rules_2024 and 'mastery' in record:
                if norm_key(record['mastery']) not in masteries:
                    errors.append(f'{label}: unknown 2024 mastery {record["mastery"]!r}')
    for cls in classes:
        # An omitted spells category explicitly represents a no-powers world.
        if 'spells' in kit and cls.get('chassis', '').lower() in ('bard', 'cleric', 'druid', 'sorcerer', 'warlock', 'wizard', 'paladin', 'ranger'):
            keys = {norm_key(cls.get(k)) for k in ('name', 'index') if cls.get(k)}
            if not any(spell.get('level') == 1 and isinstance(spell.get('classes'), list)
                       and keys.intersection(norm_key(c) for c in spell['classes']) for spell in spells):
                errors.append(f'{cls.get("name")}: casting class needs a level-1 spell')
    return errors


def warnings(kit):
    out = []
    for field, low, high in (('lexicon', 5, 15), ('races', 3, 6), ('classes', 5, 8),
                             ('backgrounds', 4, 6), ('monsters', 8, 15)):
        count = len(kit.get(field, {}))
        if not low <= count <= high:
            out.append(f'{field}: expected {low}–{high}, got {count}')
    for cls in kit.get('classes', []):
        if not cls.get('subclasses'):
            out.append(f'{cls["name"]}: missing subclasses')
    from character import CANTRIPS_START
    for cls in kit.get('classes', []):
        chassis = cls.get('chassis', '').lower()
        if chassis not in (*CANTRIPS_START, 'paladin', 'ranger'):
            continue
        powers = class_powers(kit, cls)
        for level, minimum in ((0, CANTRIPS_START.get(chassis, 0)), (1, 6 if chassis == 'wizard' else 4), (2, 3), (3, 3)):
            count = sum(s.get('level') == level for s in powers)
            if count < minimum:
                label = 'cantrips' if level == 0 else f'level-{level} powers'
                out.append(f'{cls["name"]}: {label} shortfall {minimum - count} (has {count}, needs {minimum})')
        if chassis == 'warlock' and not any(r.get('kind') == 'invocation' for r in kit.get('class_options', [])):
            out.append(f'{cls["name"]}: missing invocation class_options')
    biomes = {b for r in kit.get('monsters', []) for b in r.get('biomes', [])}
    for biome in sorted(biomes):
        if not any(biome in r.get('biomes', []) and Fraction(str(r.get('cr', 0))) <= 1 for r in kit.get('monsters', [])):
            out.append(f'{biome}: no monster of CR ≤ 1')
    casters = [c['name'] for c in kit.get('classes', [])
               if c.get('chassis', '').lower() in (*CANTRIPS_START, 'paladin', 'ranger')]
    power = str(kit.get('_meta', {}).get('power', '')).lower()
    if power == 'none' and casters:
        out.append(f"_meta.power is none but these classes cast: {', '.join(casters)}")
    if power == 'low' and len(casters) > 2:
        out.append(f"_meta.power is low (at most 2 casting classes) but {len(casters)} cast: {', '.join(casters)}")
    if not kit.get('currency'):
        out.append('missing currency')
    for field in ('name', 'genre', 'premise'):
        if not kit.get('_meta', {}).get(field):
            out.append(f'missing _meta.{field}')
    return out


def format_cr(cr):
    return str(Fraction(str(cr)))


def show(kit):
    meta = kit.get('_meta', {})
    print(meta.get('name', 'World Kit'))
    genre = meta.get('genre', '')
    print('Genre:', ', '.join(genre) if isinstance(genre, list) else genre)
    print('Premise:', meta.get('premise', ''))
    currency = kit.get('currency', {})
    print('Currency:', ', '.join(f'{k}: {v}' for k, v in currency.items()) if isinstance(currency, dict) else currency)
    print('Origins:')
    for r in kit.get('races', []):
        print(f"  {r['name']}: " + ', '.join(f'{a} {v:+}' for a, v in r['ability_bonuses'].items()))
    print('Classes:')
    for r in kit.get('classes', []):
        print(f"  {r['name']} → {r['chassis']}")
        if r.get('subclasses'):
            print(f"    {r.get('subclass_label', 'Subclasses')}: " + ', '.join(x['name'] for x in r['subclasses']))
    print('Backgrounds:')
    for r in kit.get('backgrounds', []):
        print(f"  {r['name']}: abilities {', '.join(r['ability_options'])}; skills {', '.join(r['skills'])}")
    print('Powers:')
    for cls in kit.get('classes', []):
        if cls.get('chassis', '').lower() not in ('bard', 'cleric', 'druid', 'sorcerer', 'warlock', 'wizard', 'paladin', 'ranger'):
            continue
        counts = {}
        for spell in class_powers(kit, cls):
            level = spell['level']
            counts[level] = counts.get(level, 0) + 1
        print(f"  {cls['name']}: " + (', '.join(f'level {lv}: {n}' for lv, n in sorted(counts.items())) or '0'))
    print('Gear:')
    for r in kit.get('equipment', []):
        stats = [r[k] for k in ('damage', 'ac') if r.get(k)]
        properties = r.get('properties')
        if properties:
            stats.append(', '.join(map(str, properties)) if isinstance(properties, list) else str(properties))
        print(f"  {r['name']}" + (": " + '; '.join(stats) if stats else ''))
    print('Threats:')
    for r in sorted(kit.get('monsters', []), key=lambda r: Fraction(str(r['cr']))):
        print(f"  {r['name']}: CR {format_cr(r['cr'])}; {r['role']}; {', '.join(r['biomes'])}")
    print('Lexicon:')
    for key, value in kit.get('lexicon', {}).items():
        print(f'  {key} → {value}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('validate', 'show'))
    parser.add_argument('source')
    args = parser.parse_args()
    source = Path(args.source)
    campaign = None
    if args.command == 'show' or not source.is_file():
        campaign = args.source
        source = path(args.source)
    elif source.name == 'worldkit.json':
        campaign = str(source.resolve().parent)
    try:
        kit = json.loads(source.read_text(encoding='utf-8'))
        errors = validate(kit, campaign)
        if errors:
            raise ValueError('\n'.join(errors))
    except (OSError, ValueError) as exc:
        print(exc)
        return 1
    counts = ', '.join(f'{k}: {len(v)}' for k, v in kit.items() if isinstance(v, list))
    if args.command == 'validate':
        print(f'OK: {counts}')
        for warning in warnings(kit):
            print(f'warning: {warning}')
    else:
        show(kit)
    return 0


if __name__ == '__main__':
    sys.exit(main())
