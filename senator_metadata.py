import pandas as pd
import json
import os
import io
import requests


LEGISLATORS_URL = 'https://unitedstates.github.io/congress-legislators/legislators-current.csv'
HEADERS = {
    'User-Agent': 'PartisanPhrases/1.0 (https://github.com/jackbandy/partisan-phrases)',
}


def main():
    resp = requests.get(LEGISLATORS_URL, headers=HEADERS)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    df = df[df.type == 'sen']

    senators = []
    for _, row in df.iterrows():
        senators.append({
            'full_name': row.full_name,
            'bioguide_id': row.bioguide_id,
            'party': row.party,
            'state': row.state,
            'headshot_url': f'https://unitedstates.github.io/images/congress/225x275/{row.bioguide_id}.jpg',
        })

    os.makedirs('docs/data', exist_ok=True)
    with open('docs/data/senators.json', 'w') as f:
        json.dump(senators, f, indent=2)

    print(f"Wrote {len(senators)} senators to docs/data/senators.json")


if __name__ == '__main__':
    main()
