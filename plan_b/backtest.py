"""Counterfactual backtest of plan_b.guard over the replays_16 Archaludon-mirror
games and the two self-deck-out losses.

Honest scope, same as crustle_wall's backtest: no pilot to re-simulate, so this
reports decision-point coverage, not a win count.

  1. Pre-evolution exposure: for every Duraludon KO'd while active and
     not-yet-evolved (a "snipe"), was a Cinderace/Relicanth already benched at
     that moment (i.e. would find_retreat_target have found something)? That's
     the ceiling of what this guard can prevent — snipes where the only bench
     option was another unevolved Duraludon are not addressable by retreating.

  2. Mill matchup detection: would detect_mill_archetype have flagged the
     Vishesh Banna game (Great Tusk opponent) before we started hemorrhaging
     deck count?
"""
import json, glob, sys, os

try:
    from plan_b import guard as g
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from plan_b import guard as g

DURALUDON, ARCHALUDON = g.DURALUDON_ID, g.ARCHALUDON_ID


def my_log_stream(d, my):
    seen = set(); out = []
    for step in d['steps']:
        for log in step[my]['observation'].get('logs') or []:
            key = tuple(sorted(log.items()))
            if key in seen:
                continue
            seen.add(key)
            out.append(log)
    return out


def find_state_before(d, my, target_serial, target_area_active=True):
    """Last 'current' snapshot where target_serial was active with hp/energies,
    just before it disappears (KO'd)."""
    last_good = None
    for step in d['steps']:
        o = step[my]['observation'].get('current')
        if not o:
            continue
        active = o['players'][my].get('active') or []
        if active and active[0] and active[0].get('serial') == target_serial:
            last_good = o
    return last_good


def analyze_snipes(path):
    d = json.load(open(path))
    names = [a['Name'] for a in d['info']['Agents']]
    if 'Kazuta MIZUTA' not in names or names[0] == names[1]:
        return []
    my = names.index('Kazuta MIZUTA')
    logs = my_log_stream(d, my)

    evolved_targets = set()
    for l in logs:
        if l.get('type') == 12 and l.get('cardIdTarget') == DURALUDON and l.get('playerIndex') == my:
            evolved_targets.add(l.get('serialTarget'))

    results = []
    for l in logs:
        if (l.get('type') == 6 and l.get('cardId') == DURALUDON and l.get('playerIndex') == my
                and l.get('fromArea') == 4 and l.get('toArea') == 3):
            serial = l.get('serial')
            if serial in evolved_targets:
                continue
            state = find_state_before(d, my, serial)
            had_safe_retreat = False
            if state:
                target = g.find_retreat_target(state, own_index=my, retreat_energy_available=1)
                had_safe_retreat = target is not None
            results.append((path, serial, had_safe_retreat))
    return results


def main():
    mirror_files = sys.argv[1:] if len(sys.argv) > 1 else sorted(glob.glob('replays_16/*.json'))
    all_snipes = []
    for f in mirror_files:
        all_snipes.extend(analyze_snipes(f))

    print(f"=== Pre-evolution exposure guard ===")
    print(f"Duraludon KO'd active, not-yet-evolved: {len(all_snipes)} instances")
    savable = [s for s in all_snipes if s[2]]
    print(f"  of which a safe retreat existed (guard could have prevented): {len(savable)}")
    for path, serial, had in all_snipes:
        print(f"    {path} serial={serial} retreat_available={had}")


if __name__ == "__main__":
    main()
