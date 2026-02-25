from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from time import sleep
from random import uniform, shuffle
import requests
from tqdm import tqdm
import os
import re

BASE_URL = "https://justfacts.votesmart.org"
HEADERS = {
    'User-Agent': 'PartisanPhrases/1.0 (https://github.com/jackbandy/partisan-phrases)',
}

STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC",
]


def main():
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365)
    start_str = start_date.strftime("%m/%d/%Y")
    end_str = end_date.strftime("%m/%d/%Y")

    os.makedirs("corpus", exist_ok=True)

    states = list(STATES)
    shuffle(states)
    for state in tqdm(states, desc="States", unit="state"):
        try:
            scrape_state(state, start_str, end_str)
        except Exception as e:
            tqdm.write(f"Error scraping state {state}: {e}")
            continue


def scrape_state(state, start_str, end_str):
    tqdm.write(f"Scraping {state}...")
    page_num = 1

    while True:
        url = (
            f"{BASE_URL}/public-statements/{state}/C/"
            f"?search=&section=&bull=&search=&start={start_str}&end={end_str}&p={page_num}"
        )
        resp = requests.get(url, headers=HEADERS)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, features="lxml")

        tbody = soup.find("tbody")
        if tbody is None or not tbody.find("tr"):
            if page_num == 1:
                tqdm.write(f"\tNo results for {state}")
            break

        rows = tbody.find_all("tr")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 3:
                continue
            link_tag = cells[1].find("a", href=True)
            if not link_tag:
                continue
            href = link_tag["href"]
            if not href.startswith("http"):
                href = BASE_URL + href

            # Person name from the 3rd column of search results
            table_person = cells[2].get_text(strip=True)
            table_person = re.sub(r"^(Rep\.|Sen\.|Representative|Senator)\s+", "", table_person).strip()

            # Title from the link text in the search results
            table_title = link_tag.get_text(strip=True).split(",")[0]
            if len(table_title) > 150:
                table_title = table_title[:150]

            # Skip if a file already exists for this person + title
            person_dir = os.path.join("corpus", table_person)
            if os.path.isdir(person_dir):
                existing = os.listdir(person_dir)
                if any(f.startswith(table_title) for f in existing):
                    continue

            try:
                scrape_speech(href, state, table_person)
            except Exception as e:
                tqdm.write(f"\tError scraping {href}: {e}")
                continue

        tqdm.write(f"\t{state} page {page_num}: {len(rows)} rows")
        page_num += 1
        sleep(uniform(2, 4))


def scrape_speech(speech_url, state, table_person):
    resp = requests.get(speech_url, headers=HEADERS, allow_redirects=True)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.content, features="lxml")

    # Extract title from VoteSmart page (h3 with class="title")
    title_tag = soup.find("h3", {"class": "title"})
    if not title_tag:
        return
    title = title_tag.text.strip()

    # Extract date: <b>Date:</b> <span>...</span>
    date = "Unknown Date"
    date_b = soup.find("b", string=re.compile(r"^\s*Date\s*:\s*$"))
    if date_b:
        date_span = date_b.find_next("span")
        if date_span:
            date = date_span.get_text(strip=True)

    # Extract location: <b>Location:</b> <span>...</span>
    location = "Unknown Location"
    loc_b = soup.find("b", string=re.compile(r"^\s*Location\s*:\s*$"))
    if loc_b:
        loc_span = loc_b.find_next("span")
        if loc_span:
            location = loc_span.get_text(strip=True)

    # Extract person name: <b>By:</b> followed by <a> tag
    person = None
    by_b = soup.find("b", string=re.compile(r"^\s*By\s*:\s*$"))
    if by_b:
        link = by_b.find_next("a")
        if link:
            person = link.get_text(strip=True)

    # Final fallback: use name from search results table
    if not person:
        person = table_person

    if not person:
        tqdm.write(f"\tCould not find person name for {speech_url}")
        return

    # Strip title prefixes like "Rep. " or "Sen. "
    person = re.sub(r"^(Rep\.|Sen\.|Representative|Senator)\s+", "", person).strip()

    # Build file path early so we can skip before fetching the source page
    person_dir = os.path.join("corpus", person)
    os.makedirs(person_dir, exist_ok=True)

    safe_title = title.split(",")[0]
    if len(safe_title) > 150:
        safe_title = safe_title[:150]
    file_name = f"{safe_title}, {date}, {location}.txt".replace("/", " ")
    file_path = os.path.join(person_dir, file_name)

    # Skip if already exists
    if os.path.exists(file_path):
        return

    speech_text = None

    # Prefer inline speech content from VoteSmart if available
    content_div = soup.find("div", {"id": "publicStatementDetailSpeechContent"})
    if content_div:
        p_list = content_div.find_all("p")
        text_list = [p.get_text().strip() for p in p_list if p.get_text().strip()]
        speech_text = "\n\n".join(text_list)
    else:
        # Fall back to the "Source" link (govinfo.gov / gpo.gov)
        source_url = None
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if "govinfo.gov" in href or "gpo.gov" in href:
                source_url = href
                break
        if not source_url:
            source_link = soup.find("a", string=re.compile(r"source", re.IGNORECASE))
            if source_link and source_link.get("href"):
                source_url = source_link["href"]

        if not source_url:
            tqdm.write(f"\tNo source link found for {speech_url}")
            return

        sleep(uniform(2, 4))
        source_resp = requests.get(source_url, headers=HEADERS, allow_redirects=True)
        source_resp.raise_for_status()
        source_soup = BeautifulSoup(source_resp.content, features="lxml")

        body = source_soup.find("body")
        if not body:
            return

        pre = body.find("pre")
        if pre:
            speech_text = pre.get_text().strip()
        else:
            p_list = body.find_all("p")
            if p_list:
                text_list = [p.get_text().strip() for p in p_list if p.get_text().strip()]
                speech_text = "\n\n".join(text_list)
            else:
                speech_text = body.get_text(separator="\n\n").strip()

    if not speech_text:
        return

    # Remove "BREAK IN TRANSCRIPT" lines
    speech_text = re.sub(r"\n*\s*BREAK IN TRANSCRIPT\s*\n*", "\n\n", speech_text).strip()

    if not speech_text:
        return

    full_text = f"{title}\n\n\n{speech_url}\n\n\n{speech_text}"
    with open(file_path, "w") as f:
        f.write(full_text)

    tqdm.write(f"\tSaved: {person} — {safe_title}")
    sleep(uniform(2, 4))


if __name__ == "__main__":
    main()
