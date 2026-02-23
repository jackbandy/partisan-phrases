from sklearn.feature_extraction.text import CountVectorizer
from progressbar import progressbar
from dateutil import parser as dateparser
import pandas as pd
import requests
import json
import re
import os
import io

LEGISLATORS_URL = 'https://unitedstates.github.io/congress-legislators/legislators-current.csv'
HEADERS = {
    'User-Agent': 'PartisanPhrases/1.0 (https://github.com/jackbandy/partisan-phrases)',
}


def main():
    resp = requests.get(LEGISLATORS_URL, headers=HEADERS)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    df.at[df.twitter == 'SenSanders', 'party'] = 'Democrat'  # for ideological purposes
    df = df[df.type == 'sen']
    df = df[~df.votesmart_id.isna()]

    texts_df = get_all_texts(df)

    tf_vectorizer = CountVectorizer(max_df=0.8, min_df=50,
                                    ngram_range=(1, 2),
                                    binary=False,
                                    stop_words='english')

    print("Fitting...")
    tf_vectorizer.fit(texts_df.text.tolist())
    term_frequencies = tf_vectorizer.fit_transform(texts_df.text.tolist())
    feature_names = tf_vectorizer.get_feature_names_out()
    phrases_df = pd.DataFrame(data=feature_names, columns=['phrase'])
    phrases_df['total_occurrences'] = term_frequencies.sum(axis=0).A1

    phrases_df.sort_values(by='total_occurrences', ascending=False).head(20).to_csv(
        'output/top_20_overall.csv', index=False)

    print("Analyzing partisan patterns...")
    dem_mask = texts_df.party == 'Democrat'
    rep_mask = texts_df.party == 'Republican'
    dem_tfs = tf_vectorizer.transform(texts_df[dem_mask].text.tolist())
    rep_tfs = tf_vectorizer.transform(texts_df[rep_mask].text.tolist())
    n_dem_docs = dem_tfs.shape[0]
    n_rep_docs = rep_tfs.shape[0]
    print(f"{n_dem_docs} Dem docs, {n_rep_docs} Rep docs")

    total_dem_tfs = dem_tfs.sum(axis=0).A1
    total_rep_tfs = rep_tfs.sum(axis=0).A1
    p_dem = total_dem_tfs / n_dem_docs
    p_rep = total_rep_tfs / n_rep_docs

    bias = (p_rep - p_dem) / (p_rep + p_dem + 1e-10)

    phrases_df['bias_score'] = bias
    phrases_df['p_dem'] = p_dem
    phrases_df['p_rep'] = p_rep
    phrases_df['n_dem'] = total_dem_tfs
    phrases_df['n_rep'] = total_rep_tfs

    # Existing CSV output
    phrases_df.sort_values(by='total_occurrences', ascending=False).to_csv(
        'output/all_phrases.csv', index=False)

    print("Most Democratic...")
    top_dem = phrases_df.sort_values(by='bias_score', ascending=True).head(200).copy()
    top_dem['n_senators'] = top_dem.apply(
        lambda x: len(texts_df[texts_df.text.str.contains(x.phrase, regex=False)].person.unique()), axis=1)
    top_dem = top_dem[top_dem.n_senators > 2]
    top_dem.head(20).to_csv('output/top_20_democrat.csv', index=False)

    print("Most Republican:")
    top_rep = phrases_df.sort_values(by='bias_score', ascending=False).head(200).copy()
    top_rep['n_senators'] = top_rep.apply(
        lambda x: len(texts_df[texts_df.text.str.contains(x.phrase, regex=False)].person.unique()), axis=1)
    top_rep = top_rep[top_rep.n_senators > 2]
    top_rep.head(20).to_csv('output/top_20_republican.csv', index=False)

    # === JSON output for website ===
    print("Generating JSON for website...")
    generate_website_json(phrases_df, texts_df, tf_vectorizer, feature_names)


def generate_website_json(phrases_df, texts_df, tf_vectorizer, feature_names):
    os.makedirs('docs/data/history', exist_ok=True)
    os.makedirs('docs/data/quotes', exist_ok=True)

    # Select top phrases: 300 left + 300 right + 300 overall, deduplicated
    top_left = phrases_df.sort_values('bias_score', ascending=True).head(300)
    top_right = phrases_df.sort_values('bias_score', ascending=False).head(300)
    top_overall = phrases_df.sort_values('total_occurrences', ascending=False).head(300)

    combined = pd.concat([top_left, top_right, top_overall]).drop_duplicates(subset=['phrase'])

    # Add rank columns
    left_ranked = phrases_df.sort_values('bias_score', ascending=True).reset_index(drop=True)
    right_ranked = phrases_df.sort_values('bias_score', ascending=False).reset_index(drop=True)
    overall_ranked = phrases_df.sort_values('total_occurrences', ascending=False).reset_index(drop=True)

    left_rank_map = {p: i + 1 for i, p in enumerate(left_ranked.phrase)}
    right_rank_map = {p: i + 1 for i, p in enumerate(right_ranked.phrase)}
    overall_rank_map = {p: i + 1 for i, p in enumerate(overall_ranked.phrase)}

    combined['rank_left'] = combined.phrase.map(left_rank_map)
    combined['rank_right'] = combined.phrase.map(right_rank_map)
    combined['rank_overall'] = combined.phrase.map(overall_rank_map)
    combined['slug'] = combined.phrase.apply(slugify)

    # Write phrases.json
    phrases_out = combined[['phrase', 'slug', 'total_occurrences', 'bias_score',
                            'p_dem', 'p_rep', 'rank_left', 'rank_right', 'rank_overall']].copy()
    phrases_out['total_occurrences'] = phrases_out['total_occurrences'].astype(int)
    phrases_out['rank_left'] = phrases_out['rank_left'].astype(int)
    phrases_out['rank_right'] = phrases_out['rank_right'].astype(int)
    phrases_out['rank_overall'] = phrases_out['rank_overall'].astype(int)

    with open('docs/data/phrases.json', 'w') as f:
        json.dump(phrases_out.to_dict(orient='records'), f)
    print(f"  Wrote {len(phrases_out)} phrases to docs/data/phrases.json")

    # Compute weekly history and extract quotes for target phrases
    print("  Computing weekly history and extracting quotes...")
    compute_weekly_history(combined, texts_df, tf_vectorizer, feature_names)
    extract_quotes(combined, texts_df)


def slugify(phrase):
    slug = re.sub(r'[^a-z0-9]+', '-', phrase.lower()).strip('-')
    return slug


def compute_weekly_history(target_df, texts_df, tf_vectorizer, feature_names):
    if 'week' not in texts_df.columns:
        print("  No week data available, skipping history generation")
        return

    feature_to_idx = {name: i for i, name in enumerate(feature_names)}
    weeks = sorted(texts_df.week.dropna().unique())

    for _, row in progressbar(list(target_df.iterrows())):
        slug = row['slug']
        phrase = row['phrase']
        idx = feature_to_idx.get(phrase)
        if idx is None:
            continue

        history = []
        for week in weeks:
            week_texts = texts_df[texts_df.week == week]
            dem_texts = week_texts[week_texts.party == 'Democrat'].text.tolist()
            rep_texts = week_texts[week_texts.party == 'Republican'].text.tolist()

            dem_count = 0
            rep_count = 0
            if dem_texts:
                dem_tf = tf_vectorizer.transform(dem_texts)
                dem_count = int(dem_tf[:, idx].sum())
            if rep_texts:
                rep_tf = tf_vectorizer.transform(rep_texts)
                rep_count = int(rep_tf[:, idx].sum())

            if dem_count > 0 or rep_count > 0:
                history.append({
                    'week': week,
                    'dem': dem_count,
                    'rep': rep_count,
                    'total': dem_count + rep_count,
                })

        with open(f'docs/data/history/{slug}.json', 'w') as f:
            json.dump(history, f)


def extract_quotes(target_df, texts_df):
    for _, row in progressbar(list(target_df.iterrows())):
        slug = row['slug']
        phrase = row['phrase']

        matches = texts_df[texts_df.text.str.contains(phrase, case=False, regex=False)]
        if len(matches) == 0:
            continue

        # Balance across parties
        dem_matches = matches[matches.party == 'Democrat'].sample(
            n=min(15, len(matches[matches.party == 'Democrat'])), random_state=42)
        rep_matches = matches[matches.party == 'Republican'].sample(
            n=min(15, len(matches[matches.party == 'Republican'])), random_state=42)
        selected = pd.concat([dem_matches, rep_matches]).head(30)

        quotes = []
        for _, m in selected.iterrows():
            # Find the sentence containing the phrase
            sentences = re.split(r'(?<=[.!?])\s+', m.text)
            matching_sentence = next(
                (s for s in sentences if phrase.lower() in s.lower()), None)
            if matching_sentence and len(matching_sentence) < 500:
                quotes.append({
                    'senator': m.person,
                    'party': m.party,
                    'sentence': matching_sentence.strip(),
                })
            if len(quotes) >= 30:
                break

        with open(f'docs/data/quotes/{slug}.json', 'w') as f:
            json.dump(quotes, f)


def get_all_texts(df):
    texts_list = []
    date_pattern = re.compile(
        r',\s*(\w+ \d{1,2},\s*\d{4})'
    )

    for row in df.itertuples():
        n_tweets = 0
        print("Reading in {}...".format(row.full_name))
        corpus_dir = f'corpus/{row.full_name}'
        if not os.path.isdir(corpus_dir):
            print(f"  No corpus directory found, skipping")
            continue
        all_files = os.listdir(corpus_dir)
        for fname in progressbar(all_files):
            with open(f'{corpus_dir}/{fname}', 'r') as f:
                title_and_speech = f.read().split('\n\n\n')
                if len(title_and_speech) < 2:
                    continue
                title = title_and_speech[0]
                speech = title_and_speech[1]
            if title.split()[0] == 'Tweet':
                n_tweets += 1
                continue

            # Parse date from filename
            date_str = None
            week = None
            match = date_pattern.search(fname)
            if match:
                try:
                    parsed_date = dateparser.parse(match.group(1))
                    date_str = parsed_date.strftime('%Y-%m-%d')
                    iso = parsed_date.isocalendar()
                    week = f'{iso[0]}-W{iso[1]:02d}'
                except (ValueError, TypeError):
                    pass

            text = {
                'party': row.party,
                'person': row.full_name,
                'bioguide_id': row.bioguide_id,
                'state': row.state,
                'title': title,
                'text': speech,
                'date': date_str,
                'week': week,
            }
            texts_list.append(text)
        print("{} tweets excluded".format(n_tweets))

    texts_df = pd.DataFrame(texts_list)
    texts_df = texts_df.drop_duplicates(subset=['text'])
    texts_df.sample(min(100, len(texts_df))).to_csv('output/all_texts_sample.csv', index=False)

    return texts_df


if __name__ == '__main__':
    main()
