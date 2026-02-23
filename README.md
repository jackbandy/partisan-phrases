# Partisan Phrases

![](cover.png)

Materials I used in a blog post. The idea for using VoteSmart data to calculate bias came from the paper, "Auditing the partisanship of Google search snippets" by Robertson et al.

## Usage

### Requirements

```bash
pip install requests beautifulsoup4 lxml tqdm 'urllib3<2'
```

### Generating the corpus

```bash
python generate_corpus.py
```

This scrapes congressional public statements from VoteSmart for the last 12 months across all 50 states + DC. Speeches are saved to `corpus/{Person Name}/{Title, Date, Location}.txt`.

The script is **incremental** — rerunning it skips already-downloaded speeches, so you can safely Ctrl+C and resume later.

### Analyzing the corpus

```bash
python analyze_corpus.py
```

### Testing with a subset

To test on a single state, temporarily edit the `STATES` list in `generate_corpus.py`:

```python
STATES = ["WY"]  # small state, fewer results
```

### Inspecting downloaded files

```bash
ls corpus/                        # see person directories
ls corpus/*/ | head -20           # see some filenames
head -5 corpus/*/*.txt | head -30 # peek at file contents
```
