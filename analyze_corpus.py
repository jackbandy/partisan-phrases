from sklearn.feature_extraction.text import CountVectorizer
from difflib import get_close_matches
from progressbar import progressbar
from datetime import datetime
import pandas as pd
import requests
import json
import re
import os
import io

LEGISLATORS_CURRENT_URL = 'https://unitedstates.github.io/congress-legislators/legislators-current.csv'
LEGISLATORS_HISTORICAL_URL = 'https://unitedstates.github.io/congress-legislators/legislators-historical.csv'
HEADERS = {
    'User-Agent': 'PartisanPhrases/1.0 (https://github.com/jackbandy/partisan-phrases)',
}


def build_party_lookup():
    """Build a name -> party dict from current + historical legislators."""
    party_lookup = {}

    for url in [LEGISLATORS_CURRENT_URL, LEGISLATORS_HISTORICAL_URL]:
        try:
            resp = requests.get(url, headers=HEADERS)
            resp.raise_for_status()
            df = pd.read_csv(io.StringIO(resp.text))
            # Treat Independents who caucus with Democrats as Democrat
            for _, row in df.iterrows():
                name = str(row.get('full_name', ''))
                party = row.get('party', 'Unknown')
                if not name:
                    continue
                party_lookup[name] = party
                # Also store by "First Last" (drop middle initials/suffixes)
                parts = name.split()
                if len(parts) >= 2:
                    simple_name = f"{parts[0]} {parts[-1]}"
                    if simple_name not in party_lookup:
                        party_lookup[simple_name] = party
        except Exception as e:
            print(f"Warning: could not fetch {url}: {e}")

    print(f"Party lookup has {len(party_lookup)} entries")
    return party_lookup


# Manual overrides for names that don't match the legislators dataset.
# Maps VoteSmart display name -> party string, or None to skip (non-federal officials).
NAME_OVERRIDES = {
    # Nickname mismatches
    'Bobby Scott': 'Democrat',        # Robert C. Scott (VA)
    'Buddy Carter': 'Republican',     # Earl L. Carter (GA)
    'Chuck Schumer': 'Democrat',      # Charles E. Schumer (NY)
    'Chuy Garcia': 'Democrat',        # Jesús G. García (IL)
    'Dick Durbin': 'Democrat',        # Richard J. Durbin (IL)
    'GT Thompson, Jr.': 'Republican', # Glenn Thompson (PA)
    # New members not yet in legislators dataset
    'Jim Justice, Jr.': 'Republican', # WV Senator, sworn in Jan 2025
    'Nick Begich': 'Republican',      # AK Rep, sworn in Jan 2025
    'Nick Begich III': 'Republican',
    # Gil Cisneros is in historical data but fuzzy match misses it
    'Gil Cisneros': 'Democrat',       # former CA Rep
    # Non-federal officials — skip so they don't skew the analysis
    'Bob Onder': None,                # MO state senator
    'Christian Menefee': None,        # TX county attorney
    'Felix Moore': None,              # not a federal legislator
}


def lookup_party(person_name, party_lookup):
    """Look up party for a person name, with fuzzy matching fallback."""
    # Manual overrides take priority
    if person_name in NAME_OVERRIDES:
        return NAME_OVERRIDES[person_name]

    # Exact match
    if person_name in party_lookup:
        return party_lookup[person_name]

    # Try "First Last" (drop middle parts)
    parts = person_name.split()
    if len(parts) >= 2:
        simple = f"{parts[0]} {parts[-1]}"
        if simple in party_lookup:
            return party_lookup[simple]

    # Fuzzy match against all known names
    match = get_close_matches(person_name, party_lookup.keys(), n=1, cutoff=0.75)
    if match:
        return party_lookup[match[0]]

    return None


def main():
    party_lookup = build_party_lookup()
    texts_df = get_all_texts(party_lookup)

    tf_vectorizer = CountVectorizer(max_df=0.8, min_df=20,
                                    ngram_range=(1, 3),
                                    binary=False,
                                    stop_words='english')

    print("Fitting...")
    term_frequencies = tf_vectorizer.fit_transform(texts_df.text.tolist())
    feature_names = tf_vectorizer.get_feature_names_out()
    phrases_df = pd.DataFrame(data=feature_names, columns=['phrase'])
    phrases_df['total_occurrences'] = term_frequencies.sum(axis=0).A1

    phrases_df.sort_values(by='total_occurrences', ascending=False).head(20).to_csv(
        'output/top_20_overall.csv', index=False)

    print("Analyzing partisan patterns...")
    dem_mask = texts_df.party == 'Democrat'
    rep_mask = texts_df.party == 'Republican'
    dem_tfs = term_frequencies[dem_mask.values]
    rep_tfs = term_frequencies[rep_mask.values]
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
    phrases_df['ngram_size'] = phrases_df['phrase'].apply(lambda x: len(x.split()))

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
    generate_website_json(phrases_df, texts_df, tf_vectorizer, feature_names, term_frequencies)


def generate_website_json(phrases_df, texts_df, tf_vectorizer, feature_names, term_frequencies):
    os.makedirs('docs/data/history', exist_ok=True)
    os.makedirs('docs/data/quotes', exist_ok=True)

    # Select top phrases: 600 left + 600 right + 600 overall, deduplicated
    top_left = phrases_df.sort_values('bias_score', ascending=True).head(600)
    top_right = phrases_df.sort_values('bias_score', ascending=False).head(600)
    top_overall = phrases_df.sort_values('total_occurrences', ascending=False).head(600)

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
                            'p_dem', 'p_rep', 'rank_left', 'rank_right', 'rank_overall',
                            'ngram_size']].copy()
    phrases_out['total_occurrences'] = phrases_out['total_occurrences'].astype(int)
    phrases_out['rank_left'] = phrases_out['rank_left'].astype(int)
    phrases_out['rank_right'] = phrases_out['rank_right'].astype(int)
    phrases_out['rank_overall'] = phrases_out['rank_overall'].astype(int)

    with open('docs/data/phrases.json', 'w') as f:
        json.dump(phrases_out.to_dict(orient='records'), f)
    print(f"  Wrote {len(phrases_out)} phrases to docs/data/phrases.json")

    # Compute weekly history and extract quotes for target phrases
    print("  Computing weekly history and extracting quotes...")
    compute_weekly_history(combined, texts_df, feature_names, term_frequencies)
    extract_quotes(combined, texts_df, feature_names, term_frequencies, tf_vectorizer)


def slugify(phrase):
    slug = re.sub(r'[^a-z0-9]+', '-', phrase.lower()).strip('-')
    return slug


def compute_weekly_history(target_df, texts_df, feature_names, term_frequencies):
    if 'week' not in texts_df.columns:
        print("  No week data available, skipping history generation")
        return

    feature_to_idx = {name: i for i, name in enumerate(feature_names)}
    weeks = sorted(texts_df.week.dropna().unique())

    # Pre-compute per-week, per-party column sums across all phrases at once.
    # This replaces O(phrases × weeks × 2) transform calls with O(weeks × 2) sums.
    print("  Pre-computing weekly term counts...")
    week_dem_sums = {}  # week -> np array of length n_features
    week_rep_sums = {}
    for week in weeks:
        dem_mask = (texts_df.week == week) & (texts_df.party == 'Democrat')
        rep_mask = (texts_df.week == week) & (texts_df.party == 'Republican')
        if dem_mask.any():
            week_dem_sums[week] = term_frequencies[dem_mask.values].sum(axis=0).A1
        if rep_mask.any():
            week_rep_sums[week] = term_frequencies[rep_mask.values].sum(axis=0).A1

    for _, row in progressbar(list(target_df.iterrows())):
        slug = row['slug']
        phrase = row['phrase']
        idx = feature_to_idx.get(phrase)
        if idx is None:
            continue

        history = []
        for week in weeks:
            dem_count = int(week_dem_sums[week][idx]) if week in week_dem_sums else 0
            rep_count = int(week_rep_sums[week][idx]) if week in week_rep_sums else 0
            if dem_count > 0 or rep_count > 0:
                history.append({
                    'week': week,
                    'dem': dem_count,
                    'rep': rep_count,
                    'total': dem_count + rep_count,
                })

        with open(f'docs/data/history/{slug}.json', 'w') as f:
            json.dump(history, f)


def extract_quotes(target_df, texts_df, feature_names, term_frequencies, tf_vectorizer):
    feature_to_idx = {name: i for i, name in enumerate(feature_names)}
    # Build a word-level tokenizer that mirrors the vectorizer's preprocessing
    # pipeline WITHOUT producing n-grams (unlike build_analyzer()).
    # This lets us match stop-word-skipped n-grams like "secretary state"
    # (from "Secretary of State") via a token subsequence check.
    preprocessor = tf_vectorizer.build_preprocessor()
    tokenizer = tf_vectorizer.build_tokenizer()
    stop_words = tf_vectorizer.get_stop_words() or set()

    def word_tokens(text):
        """Tokenize text to individual words, stop words removed."""
        return [t for t in tokenizer(preprocessor(text)) if t not in stop_words]

    for _, row in progressbar(list(target_df.iterrows())):
        slug = row['slug']
        phrase = row['phrase']
        idx = feature_to_idx.get(phrase)
        phrase_words = phrase.split()   # e.g. ["skills", "work", "ethic"]
        n = len(phrase_words)

        # Regex that handles punctuation between phrase words.
        # e.g. "skills, work ethic" matches phrase "skills work ethic".
        # \W+ matches one or more non-word chars (spaces, commas, etc.)
        punct_pattern = re.compile(
            r'\b' + r'\W+'.join(re.escape(w) for w in phrase_words) + r'\b',
            re.IGNORECASE
        )

        # Sparse-matrix column lookup: O(1) to find all docs containing this phrase
        if idx is not None:
            doc_indices = term_frequencies[:, idx].nonzero()[0]
            matches = texts_df.iloc[doc_indices]
        else:
            matches = texts_df[texts_df.text.str.contains(phrase, case=False, regex=False)]

        if len(matches) == 0:
            continue

        dem_matches = matches[matches.party == 'Democrat'].sample(
            n=min(15, len(matches[matches.party == 'Democrat'])), random_state=42)
        rep_matches = matches[matches.party == 'Republican'].sample(
            n=min(15, len(matches[matches.party == 'Republican'])), random_state=42)
        selected = pd.concat([dem_matches, rep_matches]).head(30)

        quotes = []
        for _, m in selected.iterrows():
            sentences = re.split(r'(?<=[.!?])\s+', m.text)
            matching_sentence = None
            for sentence in sentences:
                # Fast path 1: exact substring match
                if phrase.lower() in sentence.lower():
                    matching_sentence = sentence
                    break
                # Fast path 2: punctuation-gap regex
                # Catches "skills, work ethic" for phrase "skills work ethic"
                if punct_pattern.search(sentence):
                    matching_sentence = sentence
                    break
                # Slow path: word-token subsequence for stop-word gaps.
                # Catches "secretary state" inside "Secretary of State".
                if n > 1:
                    sent_tokens = word_tokens(sentence)
                    for i in range(len(sent_tokens) - n + 1):
                        if sent_tokens[i:i + n] == phrase_words:
                            matching_sentence = sentence
                            break
                if matching_sentence:
                    break

            if matching_sentence and len(matching_sentence) < 500:
                quotes.append({
                    'senator': m.person,
                    'party': m.party,
                    'sentence': matching_sentence.strip(),
                    'title': m.title,
                    'date': m.date,
                })
            if len(quotes) >= 30:
                break

        with open(f'docs/data/quotes/{slug}.json', 'w') as f:
            json.dump(quotes, f)


_DATE_FORMATS = ('%b %d %Y', '%B %d %Y')

def _parse_date_fast(raw):
    """Parse a date string extracted from a corpus filename.

    Handles both abbreviated ('Feb. 26, 2025') and full ('February 26, 2025')
    month names.  Much faster than dateparser.parse() for known formats.
    """
    # Strip trailing periods from abbreviated months and commas throughout
    cleaned = re.sub(r'\.(?=\s)', '', raw).replace(',', '').strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


def get_all_texts(party_lookup):
    texts_list = []
    date_pattern = re.compile(
        r',\s*(\w+\.? \d{1,2},?\s*\d{4})'
    )
    skipped_unknown = []

    corpus_root = 'corpus'
    if not os.path.isdir(corpus_root):
        print("No corpus/ directory found")
        return pd.DataFrame()

    person_dirs = sorted(d for d in os.listdir(corpus_root)
                         if os.path.isdir(os.path.join(corpus_root, d)))

    for person_name in person_dirs:
        party = lookup_party(person_name, party_lookup)
        if not party:
            skipped_unknown.append(person_name)
            continue

        n_tweets = 0
        print(f"Reading in {person_name} ({party})...")
        corpus_dir = os.path.join(corpus_root, person_name)
        all_files = os.listdir(corpus_dir)
        for fname in progressbar(all_files):
            fpath = os.path.join(corpus_dir, fname)
            if not fname.endswith('.txt'):
                continue
            with open(fpath, 'r') as f:
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
                parsed_date = _parse_date_fast(match.group(1))
                if parsed_date is not None:
                    # Skip speeches from before 2025
                    if parsed_date.year < 2025:
                        continue
                    date_str = parsed_date.strftime('%Y-%m-%d')
                    iso = parsed_date.isocalendar()
                    week = f'{iso[0]}-W{iso[1]:02d}'

            text = {
                'party': party,
                'person': person_name,
                'title': title,
                'text': speech,
                'date': date_str,
                'week': week,
            }
            texts_list.append(text)
        if n_tweets:
            print(f"  {n_tweets} tweets excluded")

    if skipped_unknown:
        print(f"\nSkipped {len(skipped_unknown)} people with unknown party: {', '.join(skipped_unknown)}")

    texts_df = pd.DataFrame(texts_list)
    if len(texts_df) == 0:
        print("No texts found in corpus")
        return texts_df
    texts_df = texts_df.drop_duplicates(subset=['text'])
    os.makedirs('output', exist_ok=True)
    texts_df.sample(min(100, len(texts_df))).to_csv('output/all_texts_sample.csv', index=False)

    return texts_df


if __name__ == '__main__':
    main()
