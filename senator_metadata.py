import pandas as pd
import json
import re
import os
import io
import requests
from difflib import get_close_matches


LEGISLATORS_URL = 'https://unitedstates.github.io/congress-legislators/legislators-current.csv'
HEADERS = {
    'User-Agent': 'PartisanPhrases/1.0 (https://github.com/jackbandy/partisan-phrases)',
}


def main():
    resp = requests.get(LEGISLATORS_URL, headers=HEADERS)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    df = df[df.type.isin(['sen', 'rep'])]

    # Build one entry per legislator
    legislators = []
    full_name_to_entry = {}
    for _, row in df.iterrows():
        if pd.isna(row.full_name):
            continue
        bid = row.bioguide_id
        fallback = (
            f'https://clerk.house.gov/images/members/{bid}.jpg'
            if row.type == 'rep'
            else f'https://www.senate.gov/senators/photos/{bid}.jpg'
        )
        entry = {
            'full_name': row.full_name,
            'bioguide_id': bid,
            'party': row.party,
            'state': row.state,
            'headshot_url': f'https://unitedstates.github.io/images/congress/225x275/{bid}.jpg',
            'fallback_headshot_url': fallback,
            'alt_names': [],
        }
        legislators.append(entry)
        full_name_to_entry[row.full_name] = entry

    # Scan corpus directories and fuzzy-match each name to a legislator.
    # This handles nicknames ("Jim" → "James"), middle initials, suffixes, etc.
    # without any hardcoded tables.
    corpus_root = 'corpus'
    if os.path.isdir(corpus_root):
        corpus_names = sorted(
            d for d in os.listdir(corpus_root)
            if os.path.isdir(os.path.join(corpus_root, d))
        )
        all_full_names = list(full_name_to_entry.keys())

        unmatched = []
        for corpus_name in corpus_names:
            if corpus_name in full_name_to_entry:
                continue  # exact match already covered
            matches = get_close_matches(corpus_name, all_full_names, n=1, cutoff=0.6)
            if matches:
                full_name_to_entry[matches[0]]['alt_names'].append(corpus_name)
            else:
                unmatched.append(corpus_name)

        n_aliased = sum(len(e['alt_names']) for e in legislators)
        print(f"  Aliased {n_aliased} corpus names to legislators")
        if unmatched:
            print(f"  No match found for: {', '.join(unmatched)}")

    os.makedirs('docs/data', exist_ok=True)
    with open('docs/data/senators.json', 'w') as f:
        json.dump(legislators, f, indent=2)

    print(f"Wrote {len(legislators)} legislators to docs/data/senators.json")


if __name__ == '__main__':
    main()
