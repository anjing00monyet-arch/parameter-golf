"""Counterfactual backtest of designs B/C over the Crustle Wall replays.

Honest scope: this does NOT re-simulate the game (we don't have the pilot), so
it cannot output "N more wins". What it CAN measure is how often the shipped
guards touch a real decision point:

  C (Tusk exposure): every time a Great Tusk was KO'd *in the active spot*, was
     it a threat the tracker would have flagged (max_incoming >= tusk_hp), and
     was a Crustle sitting on our bench (i.e. a retreat/wall was available)?
     Those are the KOs decide_tusk_action would have prevented.

  A (mill race): for each self-deck-out loss, the margin we lost by.
"""
import json, glob, sys, os

try:
    from crustle_wall import control as m
except ImportError:  # run directly from inside the package dir
    sys.path.insert(0, os.path.dirname(__file__))
    import control as m

TUSK, CRUSTLE = 58, 345
AREA_ACTIVE, AREA_DISCARD = 4, 3


def deck_label(deck_names):
    return 'Crustle' in deck_names and 'Great Tusk' in deck_names


def analyze(path):
    try:
        d = json.load(open(path))
    except (json.JSONDecodeError, ValueError):
        return None
    names = [a['Name'] for a in d['info']['Agents']]
    if 'Kazuta MIZUTA' not in names:
        return None
    my = names.index('Kazuta MIZUTA'); opp = 1 - my
    cur0 = d['steps'][0][0]['visualize'][0]['current']
    my_deck_names = {c['name'] for c in cur0['players'][my]['deck']}
    if not deck_label(my_deck_names):
        return None

    reward = d['rewards'][my]
    tracker = m.ThreatTracker(opp_player_index=opp)
    last_state = None
    tusk_ko_events = []      # (incoming_at_ko, crustle_on_bench)

    for step in d['steps']:
        obs = step[my]['observation']
        logs = obs.get('logs') or []
        cur = obs.get('current')

        # ingest opponent attacks before reading KO consequences this batch
        tracker.observe_logs(logs)

        # detect our Great Tusk KO'd in the active spot this batch
        for log in logs:
            if (log.get('type') == 6 and log.get('cardId') == TUSK
                    and log.get('playerIndex') == my
                    and log.get('fromArea') == AREA_ACTIVE
                    and log.get('toArea') == AREA_DISCARD):
                incoming = tracker.max_incoming(last_state) if last_state else None
                crustle_benched = False
                if last_state:
                    bench = last_state['players'][my].get('bench') or []
                    crustle_benched = any(mn and mn.get('id') == CRUSTLE for mn in bench)
                tusk_ko_events.append((incoming, crustle_benched))

        if any(l.get('type') == 15 and l.get('playerIndex') == opp for l in logs):
            tracker.on_opponent_turn_end()
        if cur:
            last_state = cur

    # final margins for self-deck-out detection
    final = d['steps'][-1][my]['observation']['current']
    my_deck_end = final['players'][my]['deckCount']
    opp_deck_end = final['players'][opp]['deckCount']
    my_prize_left = sum(1 for x in (final['players'][my].get('prize') or []) if x is None)
    self_deckout = (reward == -1 and my_deck_end == 0 and my_prize_left == 6)

    return dict(path=path, opp=names[opp], reward=reward,
                tusk_ko=tusk_ko_events,
                self_deckout=self_deckout, opp_deck_end=opp_deck_end)


def main():
    replay_glob = sys.argv[1] if len(sys.argv) > 1 else 'replays_15/*.json'
    rows = [r for f in sorted(glob.glob(replay_glob))
            for r in [analyze(f)] if r]
    if not rows:
        print(f"no Crustle Wall replays matched: {replay_glob}")
        print("usage: python3 -m crustle_wall.backtest '<glob to replay json>'")
        return
    wins = sum(1 for r in rows if r['reward'] == 1)
    print(f"Crustle Wall games: {len(rows)}  ({wins}W / {len(rows)-wins}L)\n")

    # --- C: Tusk exposure ---
    total_ko = preventable = 0
    print("=== C: Great Tusk active-spot KOs ===")
    for r in rows:
        if not r['tusk_ko']:
            continue
        flagged = sum(1 for inc, cb in r['tusk_ko'] if inc is not None and inc >= 140)
        savable = sum(1 for inc, cb in r['tusk_ko'] if inc is not None and inc >= 140 and cb)
        total_ko += len(r['tusk_ko']); preventable += savable
        res = 'W' if r['reward'] == 1 else 'L'
        print(f"  [{res}] {r['opp']:24s} tusk_KO={len(r['tusk_ko'])} "
              f"threat-flagged={flagged} retreat-was-possible={savable}")
    print(f"  TOTAL: {total_ko} active-Tusk KOs, "
          f"{preventable} with a Crustle benched (C would have retreated/walled)\n")

    # --- A: self-deck-out ---
    print("=== A: self-deck-out losses (mill race target) ===")
    sd = [r for r in rows if r['self_deckout']]
    for r in sd:
        print(f"  {r['opp']:24s} we hit 0 deck; opp still had {r['opp_deck_end']} "
              f"(lost race by ~{r['opp_deck_end']} cards)")
    print(f"  TOTAL: {len(sd)} of {len(rows)-wins} losses were self-deck-out; "
          f"margins {[r['opp_deck_end'] for r in sd]}")

    # --- coverage: which LOSSES does either design touch? ---
    print("\n=== Loss coverage (union of A and B/C) ===")
    losses = [r for r in rows if r['reward'] == -1]
    untouched = []
    for r in losses:
        c_hit = any(inc is not None and inc >= 140 and cb for inc, cb in r['tusk_ko'])
        a_hit = r['self_deckout']
        if not (c_hit or a_hit):
            untouched.append(r['opp'])
    print(f"  {len(losses)-len(untouched)}/{len(losses)} losses touched by A and/or B+C")
    print(f"  {len(untouched)}/{len(losses)} NOT addressed (need separate work): {untouched}")


if __name__ == "__main__":
    main()
