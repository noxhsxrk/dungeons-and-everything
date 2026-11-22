#!/usr/bin/env python3
"""Campaign-local world content, using SRD records and 5e class chassis."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import find_campaign

CATEGORIES = ('races', 'classes', 'backgrounds', 'monsters', 'spells',
              'equipment', 'features', 'conditions')
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
    errors = validate(kit)
    if errors:
        raise ValueError('\n'.join(errors))
    return kit


def find(kit, category, name):
    from character import _race_key
    key = _race_key(name)
    return next((r for r in kit.get(category, [])
                 if key in (_race_key(r.get('name')), _race_key(r.get('index')))), None)


def skill_names(kit):
    return kit.get('skills', {}) if kit else {}


def class_chassis(name, campaign=None):
    from character import _race_key
    kit = load(campaign) if campaign else None
    record = find(kit, 'classes', name) if kit else None
    return _race_key(record['chassis'] if record else name)


def validate(kit):
    from character import HIT_DICE, STATS, _AC_PAT, _race_key
    if not isinstance(kit, dict):
        return ['worldkit: top-level must be a dict']
    errors = []
    categories = set(CATEGORIES) | {k for k, v in kit.items() if isinstance(v, list)}
    for category in sorted(categories):
        if category not in kit:
            continue
        records = kit[category]
        if not isinstance(records, list):
            errors.append(f'{category}: must be a list of dicts')
            continue
        seen = set()
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
            if category == 'classes':
                chassis = record.get('chassis')
                if not isinstance(chassis, str) or chassis.lower() not in HIT_DICE:
                    errors.append(f'{label}: invalid chassis {chassis!r}')
                subs = record.get('subclasses', [])
                if not isinstance(subs, list) or any(
                        not isinstance(s, dict) or not s.get('name') for s in subs):
                    errors.append(f'{label}: subclasses must be a list of {{name, description}}')
            elif category == 'races':
                bonuses = record.get('ability_bonuses')
                if not isinstance(bonuses, dict):
                    errors.append(f'{label}: ability_bonuses must be a dict')
                else:
                    for ability, value in bonuses.items():
                        if ability not in STATS or type(value) is not int:
                            errors.append(f'{label}: invalid ability_bonuses {ability}={value!r}')
            elif category == 'backgrounds':
                options = record.get('ability_options')
                if (not isinstance(options, list) or len(options) != 3
                        or any(a not in STATS for a in options)
                        or len(set(options)) != 3):
                    errors.append(f'{label}: ability_options must contain 3 distinct abilities')
            elif category == 'monsters':
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
            elif category == 'equipment' and record.get('ac'):
                if not isinstance(record['ac'], str) or not _AC_PAT.fullmatch(record['ac']):
                    errors.append(f'{label}: invalid ac {record["ac"]!r}')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('validate', 'show'))
    parser.add_argument('source')
    args = parser.parse_args()
    source = Path(args.source)
    if args.command == 'show' or not source.is_file():
        source = path(args.source)
    try:
        kit = json.loads(source.read_text(encoding='utf-8'))
        errors = validate(kit)
        if errors:
            raise ValueError('\n'.join(errors))
    except (OSError, ValueError) as exc:
        print(exc)
        return 1
    counts = ', '.join(f'{k}: {len(v)}' for k, v in kit.items() if isinstance(v, list))
    if args.command == 'validate':
        print(f'OK: {counts}')
    else:
        print(json.dumps(kit.get('_meta', {}), ensure_ascii=False))
        print(counts)
        for record in kit.get('classes', []):
            print(f'{record["name"]} → {record["chassis"]}')
        print('Lexicon:', json.dumps(kit.get('lexicon', {}), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
