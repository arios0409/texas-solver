#!/usr/bin/env python3
"""
Parse TexasSolver range files from 6max_range/ and generate JSON data
for the front-end trainer app.

Directory path format (alternating positions and actions/sizes):
  {Position}/{Size}/{NextPlayer}/{Size_or_Action}/{OrigRaiser}/{Action_or_Size}/.../*_range.txt

Special considerations:
  - "Call" nodes record both players' ranges (the player acting and the player who just acted)
  - "AllIn" nodes similarly
  - "Fold" nodes only have the other player's range (folder folds, no range for them)
  - Sizes contain "bb" (e.g., "11.0bb", "24.0bb")
  - Range file format: "AA:1.0,AKs:0.578,AQs:1.0,..." (hand:frequency)
"""

import os
import json
from datetime import datetime

RANGE_DIR = r"E:\solver\TexasSolver-v0.2.0-Windows\TexasSolver-v0.2.0-Windows\ranges\6max_range"
OUTPUT_FILE = r"E:\openclaw\workspace\texas-solver\ranges_data.js"

POSITIONS = ['UTG', 'MP', 'CO', 'BTN', 'SB', 'BB']

def parse_range_text(text):
    """Parse 'AA:1.0,AKs:0.578,...' into {hand: freq} dict."""
    result = {}
    if not text or not text.strip():
        return result
    parts = text.strip().split(',')
    for p in parts:
        p = p.strip()
        if ':' in p:
            hand, freq = p.split(':', 1)
            try:
                f = float(freq)
                if f > 0:
                    result[hand.upper()] = f
            except ValueError:
                pass
    return result

def is_bet_size(s):
    """Check if a string represents a bet size (contains 'bb')."""
    return 'bb' in s.lower()

def get_players_and_actions(path_components):
    """
    Parse path into a list of (player, action, size) tuples.
    Path format: alternating position, then size or action.
    """
    actions = []
    i = 0
    while i < len(path_components):
        entry = path_components[i]
        if entry in POSITIONS:
            player = entry
            if i + 1 < len(path_components):
                next_val = path_components[i + 1]
                if is_bet_size(next_val):
                    actions.append({'player': player, 'action': 'raise', 'size': next_val})
                    i += 2
                elif next_val in ('Call', 'Fold', 'AllIn'):
                    actions.append({'player': player, 'action': next_val.lower()})
                    i += 2
                else:
                    # Unknown - position but next isn't a recognized action/size
                    i += 1
            else:
                # Position at the end (shouldn't happen)
                i += 1
        else:
            i += 1
    return actions

def find_ranges():
    """
    Scan all range files and build structured data.
    Returns dict with:
      rfi: {pos: {hand: freq}}  - RFI ranges
      vs_raise: {pos: {raiser_pos: {call: {hand:freq}, raise: {hand:freq}}}}
      vs_3bet: {pos: {3better_pos: {call: {hand:freq}, raise: {hand:freq}}}}
    """
    result = {
        'rfi': {},
        'vs_raise': {},
        'vs_3bet': {}
    }
    
    # Collect all range files with their scenarios
    # Walk through the directory tree
    for root, dirs, files in os.walk(RANGE_DIR):
        range_files = [f for f in files if f.endswith('_range.txt') and '_range.txt' in f]
        if not range_files:
            continue
        
        # Get the relative path from RANGE_DIR
        rel_path = os.path.relpath(root, RANGE_DIR)
        parts = rel_path.split(os.sep)
        
        # Parse the action sequence
        actions = get_players_and_actions(parts)
        
        if not actions:
            continue
        
        # Determine the scenario
        # The last action is the current state
        for rf_name in range_files:
            # rf_name is like "BTN_range.txt" or "BB_range.txt"
            player_name = rf_name.replace('_range.txt', '')
            
            with open(os.path.join(root, rf_name), 'r', encoding='utf-8') as f:
                text = f.read()
            ranges = parse_range_text(text)
            if not ranges:
                continue
            
            # RFI scenario: one player raised to 2.5bb (or 3bb for SB), 
            # and someone else called (first call node from the opener's perspective)
            # This is the opener's range when facing a call
            first_action = actions[0]
            if len(actions) >= 3:
                # first: raiser opens, second: responder calls
                # third should be that responder's action... hmm
                # Actually let me think about this differently
                pass
            
            # Let's just classify based on the action sequence:
            
            # --- RFI: first player raises, second player calls ---
            # Path: {Pos}/{Size}/{Responder}/Call/{Pos}_range.txt
            if (len(actions) >= 2 and
                actions[0]['action'] == 'raise' and
                actions[1]['action'] == 'call' and
                player_name == actions[0]['player']):
                # This is the opener's RFI range
                pos = player_name
                if pos not in result['rfi']:
                    result['rfi'][pos] = ranges
                result['rfi'][pos].update(ranges)
            
            # --- Facing Raise: Call range ---
            # Path: {Raiser}/{Size}/{Defender}/Call/{Defender}_range.txt
            if (len(actions) >= 2 and
                actions[0]['action'] == 'raise' and
                actions[1]['action'] == 'call' and
                player_name == actions[1]['player']):
                # Defender called - this is their calling range
                defender = player_name
                raiser = actions[0]['player']
                if defender not in result['vs_raise']:
                    result['vs_raise'][defender] = {}
                if raiser not in result['vs_raise'][defender]:
                    result['vs_raise'][defender][raiser] = {'call': {}, 'raise': {}}
                result['vs_raise'][defender][raiser]['call'] = ranges
            
            # --- Facing Raise: 3bet range ---
            # Path: {Raiser}/{Size}/{Defender}/{3betSize}/{Raiser}/{Action}/*/{Defender}_range.txt
            if (len(actions) >= 4 and
                actions[0]['action'] == 'raise' and
                actions[1]['action'] == 'raise' and  # defender 3bet
                player_name == actions[1]['player']):  # file is defender's range
                defender = player_name
                raiser = actions[0]['player']
                if defender not in result['vs_raise']:
                    result['vs_raise'][defender] = {}
                if raiser not in result['vs_raise'][defender]:
                    result['vs_raise'][defender][raiser] = {'call': {}, 'raise': {}}
                # Merge 3bet ranges from all sub-paths
                for hand, freq in ranges.items():
                    if hand not in result['vs_raise'][defender][raiser]['raise'] or freq > result['vs_raise'][defender][raiser]['raise'][hand]:
                        result['vs_raise'][defender][raiser]['raise'][hand] = freq
            
            # --- Facing 3bet: Call range ---
            # Path: {Raiser}/{Size}/{3better}/{3betSize}/{Raiser}/Call/{Raiser}_range.txt
            # Actions: [Raiser raise, 3better raise, Raiser call, ...]
            if (len(actions) >= 3 and
                actions[0]['action'] == 'raise' and
                actions[1]['action'] == 'raise' and  # 3better 3bet
                actions[2]['player'] == actions[0]['player'] and  # back to original raiser
                actions[2]['action'] in ('call', 'fold') and  # call or fold (fold means they fold to the 3bet; file won't exist for fold)
                player_name == actions[0]['player']):  # file is raiser's range
                raiser = player_name
                threeBetter = actions[1]['player']
                if raiser not in result['vs_3bet']:
                    result['vs_3bet'][raiser] = {}
                if threeBetter not in result['vs_3bet'][raiser]:
                    result['vs_3bet'][raiser][threeBetter] = {'call': {}, 'raise': {}}
                result['vs_3bet'][raiser][threeBetter]['call'] = ranges
            
            # --- Facing 3bet: 4bet range ---
            # Path: {Raiser}/{Size}/{3better}/{3betSize}/{Raiser}/{4betSize}/...
            # Actions: [Raiser raise, 3better raise, Raiser raise(4bet), ...]
            if (len(actions) >= 4 and
                actions[0]['action'] == 'raise' and
                actions[1]['action'] == 'raise' and
                actions[2]['player'] == actions[0]['player'] and  # back to raiser
                actions[2]['action'] == 'raise' and  # they 4bet
                player_name == actions[0]['player']):  # file is raiser's range
                raiser = player_name
                threeBetter = actions[1]['player']
                if raiser not in result['vs_3bet']:
                    result['vs_3bet'][raiser] = {}
                if threeBetter not in result['vs_3bet'][raiser]:
                    result['vs_3bet'][raiser][threeBetter] = {'call': {}, 'raise': {}}
                # Merge 4bet ranges
                for hand, freq in ranges.items():
                    if hand not in result['vs_3bet'][raiser][threeBetter]['raise'] or freq > result['vs_3bet'][raiser][threeBetter]['raise'][hand]:
                        result['vs_3bet'][raiser][threeBetter]['raise'][hand] = freq
    
    return result

def freq_to_binary(ranges, threshold=0.0):
    """Convert frequency-based ranges to sorted binary hand list."""
    if not ranges:
        return []
    hands = sorted(ranges.keys(), key=lambda h: _hand_sort_key(h))
    return [h for h in hands if ranges[h] > threshold]

def _hand_sort_key(h):
    """Sort hands by rank: pairs first, then suited, then offsuit, by high card."""
    rank_order = 'AKQJT98765432'
    if len(h) == 2:
        # Pair: e.g., AA
        return (0, rank_order.index(h[0]), 0)
    elif len(h) == 3:
        if h[2] == 's':
            # Suited: AKs
            return (1, rank_order.index(h[0]), rank_order.index(h[1]))
        else:
            # Offsuit: AKo
            return (2, rank_order.index(h[0]), rank_order.index(h[1]))
    return (9, 0, 0)

def calc_effective_combos(ranges):
    """Calculate effective number of combos (accounting for frequencies)."""
    total = 0.0
    for hand, freq in ranges.items():
        if len(hand) == 2:
            # Pair: 6 combos
            total += 6 * freq
        elif hand[2] == 's':
            # Suited: 4 combos
            total += 4 * freq
        else:
            # Offsuit: 12 combos
            total += 12 * freq
    return total

POS_MAP = {'MP': 'HJ'}  # Solver uses MP, app uses HJ

def remap_positions(data):
    """Map solver position names to app position names."""
    result = {}
    for key, value in data.items():
        new_key = POS_MAP.get(key, key)
        result[new_key] = value
    return result

def remap_nested_dict(d):
    """Recursively remap position names in nested dicts."""
    if isinstance(d, dict):
        result = {}
        for k, v in d.items():
            nk = POS_MAP.get(k, k)
            result[nk] = remap_nested_dict(v)
        return result
    return d

def main():
    print("Parsing range files...")
    data = find_ranges()
    
    # Remap position names (MP → HJ)
    data['rfi'] = remap_positions(data['rfi'])
    data['vs_raise'] = remap_nested_dict(data['vs_raise'])
    data['vs_3bet'] = remap_nested_dict(data['vs_3bet'])
    
    APPOSITIONS = ['UTG', 'HJ', 'CO', 'BTN', 'SB', 'BB']
    
    # Convert to binary (freq > 0 = in range)
    output = {
        'rfi': {},
        'vs_raise': {},
        'vs_3bet': {},
        'rfi_pct': {}
    }
    
    print("\n=== RFI Ranges ===")
    TOTAL_COMBOS = 1326.0
    for pos in ['UTG', 'HJ', 'CO', 'BTN', 'SB']:
        if pos in data.get('rfi', {}):
            hands = freq_to_binary(data['rfi'][pos])
            output['rfi'][pos] = hands
            # Calculate effective %
            eff = calc_effective_combos(data['rfi'][pos])
            pct = round(eff / TOTAL_COMBOS * 100)
            output['rfi_pct'][pos] = pct
            print(f"  {pos}: {len(hands)} types, {eff:.1f} effective combos ({pct}%)")
        else:
            output['rfi'][pos] = []
            output['rfi_pct'][pos] = 0
            print(f"  {pos}: NOT FOUND")
    
    print("\n=== Facing Raise (Call & 3bet) ===")
    for defender in sorted(data.get('vs_raise', {}).keys()):
        output['vs_raise'][defender] = {}
        for raiser in sorted(data['vs_raise'][defender].keys()):
            call_hands = freq_to_binary(data['vs_raise'][defender][raiser].get('call', {}))
            raise_hands = freq_to_binary(data['vs_raise'][defender][raiser].get('raise', {}))
            output['vs_raise'][defender][raiser] = {
                'call': call_hands,
                'raise': raise_hands
            }
            print(f"  {defender} vs {raiser}: call={len(call_hands)}, raise={len(raise_hands)}")
    # Fill in missing defenders
    for pos in APPOSITIONS:
        if pos not in output['vs_raise']:
            output['vs_raise'][pos] = {}
    
    print("\n=== Facing 3bet (Call & 4bet) ===")
    for raiser in sorted(data.get('vs_3bet', {}).keys()):
        output['vs_3bet'][raiser] = {}
        for threeBetter in sorted(data['vs_3bet'][raiser].keys()):
            call_hands = freq_to_binary(data['vs_3bet'][raiser][threeBetter].get('call', {}))
            raise_hands = freq_to_binary(data['vs_3bet'][raiser][threeBetter].get('raise', {}))
            output['vs_3bet'][raiser][threeBetter] = {
                'call': call_hands,
                'raise': raise_hands
            }
            print(f"  {raiser} vs {threeBetter}: call={len(call_hands)}, raise={len(raise_hands)}")
    # Fill in missing
    for pos in APPOSITIONS:
        if pos not in output['vs_3bet']:
            output['vs_3bet'][pos] = {}
    
    # Write JS
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    js_content = f"""// Auto-generated GTO range data from TexasSolver
// Generated: {timestamp}

const GTO_RANGES = {json.dumps(output, ensure_ascii=False, indent=2)};
"""
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(js_content)
    
    print(f"\nData written to {OUTPUT_FILE}")
    print(f"File size: {os.path.getsize(OUTPUT_FILE)} bytes")

if __name__ == '__main__':
    main()
