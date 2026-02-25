# Plan: VoteSmart Corpus Scraper

## Overview

Scrape congressional public statements from VoteSmart's state-based search, replacing the old per-senator approach that relied on `votesmart_id` lookups (which frequently broke).

## Scraping Strategy

### Search URL pattern
```
https://justfacts.votesmart.org/public-statements/{STATE}/C/?search=&section=&bull=&search=&start={START}&end={END}&p={PAGE}
```

### Flow
1. Iterate all 50 states + DC (shuffled for even load distribution)
2. Date range: dynamically computed last 12 months
3. For each state, paginate through search results (increment `p=` until `<tbody>` is empty)
4. Each result row provides: date, statement title/link, and politician name (e.g., "Rep. Delia Ramirez")
5. For each statement, visit the VoteSmart detail page and extract:
   - Title (`<h3 class="title">`)
   - Date (`<b>Date:</b> <span>`)
   - Location (`<b>Location:</b> <span>`)
   - Person name (`<b>By:</b> <a>`, with table name as fallback)
6. Extract speech text from one of two sources (in priority order):
   - Inline content: `<div id="publicStatementDetailSpeechContent">`
   - Source link: follow govinfo.gov/gpo.gov link and extract text from that page
7. Save as `corpus/{Person Name}/{Title, Date, Location}.txt`
8. "BREAK IN TRANSCRIPT" markers are stripped from all text

### Incremental Updates
- Before fetching a detail page, check if a file with that title already exists in the person's corpus directory (using table metadata)
- After building the full filename, check `os.path.exists()` again before fetching the source page
- This means repeat runs skip already-downloaded speeches with zero HTTP requests

### Rate Limiting
- Random 0.5-1.5s pause between pagination requests
- Random 0.5-1.5s pause between speech detail page fetches
- Random 0.5-1.5s pause between source page fetches (when needed)

## File Structure

```
corpus/
  Mike Rogers/
    Recognizing the Service of Annie Wilcox Boyajian, Feb. 12 2026, Washington DC.txt
    ...
  Terri Sewell/
    We Will Beat Cancer, Jan. 22 2026, Washington DC.txt
    ...
```

Each `.txt` file contains:
```
Title

<speech text>
```

## Dependencies
- `requests`, `beautifulsoup4`, `lxml`, `tqdm`
- `urllib3<2` (for LibreSSL compatibility on macOS system Python)

## Error Handling
- Per-state try/except: a single state failure doesn't crash the run
- Per-speech try/except: a single speech failure doesn't skip the rest of the state
- Long titles truncated to 150 characters to avoid filesystem errors
- Missing person names fall back to the search results table
