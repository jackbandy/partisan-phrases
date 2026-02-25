# Partisan Phrases

Which words and phrases are used most by Democrats vs. Republicans in the U.S. Senate? Visualized as an interactive bubble chart.

## Setup

```bash
pip install requests beautifulsoup4 lxml tqdm pandas scikit-learn progressbar2 'urllib3<2'
```

## Pipeline

```bash
python generate_corpus.py   # scrape VoteSmart statements → corpus/
python senator_metadata.py  # build docs/data/senators.json
python analyze_corpus.py    # analyze corpus → docs/data/
```

`generate_corpus.py` is incremental — rerunning skips already-downloaded files.

To test on fewer files, temporarily set `STATES = ["WY"]` in `generate_corpus.py`.

## Local development

```bash
python3 -m http.server 8080 --directory docs
```

Then open [http://localhost:8080](http://localhost:8080).
