(function () {
  "use strict";

  let allPhrases = [];
  let senators = {};
  let displayedPhrases = [];
  let shownSlugs = new Set();
  let simulation = null;
  let currentChart = null;
  let currentQuotes = [];
  let currentPhrase = null;
  let ngramFilter = 0; // 0=all, 1=1-word, 2=2-word, 3=3-word

  // ── Color ────────────────────────────────────────────────────────────────────
  function phraseColor(bias) {
    const absBias = Math.min(Math.abs(bias), 1);
    const saturation = absBias * 70;
    const lightness = 60 - absBias * 20;
    if (bias < 0) return `hsl(220, ${saturation.toFixed(1)}%, ${lightness.toFixed(1)}%)`;
    if (bias > 0) return `hsl(0, ${saturation.toFixed(1)}%, ${lightness.toFixed(1)}%)`;
    return `hsl(0, 0%, 60%)`;
  }

  // ── Oval sizing ───────────────────────────────────────────────────────────────
  // Reduced rx multiplier + increased ry gives a rounder, more bubble-like shape.
  function phraseRx(phrase) {
    return Math.max(32, phrase.length * 4 + 6);
  }
  const PHRASE_RY = 20;

  // ── Week → month label ────────────────────────────────────────────────────────
  function weekToMonthLabel(weekStr) {
    const dashW = weekStr.indexOf("-W");
    if (dashW < 0) return weekStr;
    const year = parseInt(weekStr.slice(0, dashW), 10);
    const weekNum = parseInt(weekStr.slice(dashW + 2), 10);
    const jan4 = new Date(year, 0, 4);
    const dayOfWeek = (jan4.getDay() + 6) % 7;
    const week1Start = new Date(jan4);
    week1Start.setDate(jan4.getDate() - dayOfWeek);
    const weekMid = new Date(week1Start);
    weekMid.setDate(week1Start.getDate() + (weekNum - 1) * 7 + 3);
    return weekMid.toLocaleString("en-US", { month: "short", year: "numeric" });
  }

  // Aggregate weekly data into monthly totals, filling in missing months with 0.
  // Returns { months, hasGaps } where hasGaps is true if any months were filled.
  function aggregateByMonth(filtered) {
    const MONTH_NAMES = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    function parseLabel(label) {
      const [mon, yr] = label.split(" ");
      return new Date(parseInt(yr, 10), MONTH_NAMES.indexOf(mon), 1);
    }

    const map = new Map();
    for (const h of filtered) {
      const label = weekToMonthLabel(h.week);
      if (!map.has(label)) map.set(label, { dem: 0, rep: 0, total: 0 });
      const m = map.get(label);
      m.dem += h.dem;
      m.rep += h.rep;
      m.total += h.total;
    }

    const dates = Array.from(map.keys()).map(parseLabel);
    const minDate = new Date(Math.min(...dates));
    const maxDate = new Date(Math.max(...dates));

    const months = [];
    let hasGaps = false;
    const d = new Date(minDate.getFullYear(), minDate.getMonth(), 1);
    while (d <= maxDate) {
      const label = d.toLocaleString("en-US", { month: "short", year: "numeric" });
      if (!map.has(label)) hasGaps = true;
      months.push({ label, ...(map.get(label) || { dem: 0, rep: 0, total: 0 }) });
      d.setMonth(d.getMonth() + 1);
    }
    return { months, hasGaps };
  }

  // ── Phrase highlighting in quotes ─────────────────────────────────────────────
  function escapeHtml(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function escapeRegex(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function highlightPhrase(sentence, phrase) {
    const safe = escapeHtml(sentence);
    const words = phrase.trim().split(/\s+/).map(escapeRegex);
    // Match with any non-word chars between tokens (handles punctuation gaps
    // like "skills, work ethic" for phrase "skills work ethic")
    const exact = new RegExp(`(${words.join("[^\\w]+")})`, "gi");
    if (exact.test(safe)) return safe.replace(exact, "<mark>$1</mark>");
    // Flexible match: allow 1–3 intervening words (for stop-word gaps like
    // "secretary state" inside "Secretary of State")
    const flex = new RegExp(
      `(${words.join("(?:[^\\w]+\\w+){0,3}[^\\w]+")})`,
      "gi"
    );
    return safe.replace(flex, "<mark>$1</mark>");
  }

  // ── Init ──────────────────────────────────────────────────────────────────────
  async function init() {
    const [phrasesRes, senatorsRes] = await Promise.all([
      fetch("data/phrases.json"),
      fetch("data/senators.json"),
    ]);
    allPhrases = await phrasesRes.json();
    const senatorsList = await senatorsRes.json();
    senatorsList.forEach((s) => {
      senators[s.full_name] = s;
      (s.alt_names || []).forEach((n) => { if (!senators[n]) senators[n] = s; });
    });

    // ngram_size computed client-side — no JSON rebuild needed
    allPhrases.forEach((p) => {
      p.ngram_size = p.phrase.split(" ").length;
    });

    showMore();

    document.getElementById("btn-show-more").addEventListener("click", showMore);
    document.getElementById("panel-close").addEventListener("click", closePanel);
    document.getElementById("panel-overlay").addEventListener("click", closePanel);
    document.getElementById("btn-more-quotes").addEventListener("click", sampleMoreQuotes);

    document.getElementById("search-input").addEventListener("input", () => {
      const filtered = getFilteredPhrases();
      renderBubbles(filtered);
      renderSearchResults(filtered);
    });

    document.querySelectorAll(".ngram-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".ngram-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        ngramFilter = parseInt(btn.dataset.ngram, 10);
        // Reset bucket display for the new filter
        displayedPhrases = [];
        shownSlugs = new Set();
        document.getElementById("btn-show-more").style.display = "";
        showMore();
        renderSearchResults(getFilteredPhrases());
      });
    });
  }

  // Pick n random phrases from each of the three bias buckets, excluding already-shown ones.
  // Respects the current ngramFilter so "1-word" only samples from 1-word phrases.
  function sampleBuckets(n) {
    const pool = ngramFilter > 0
      ? allPhrases.filter((p) => p.ngram_size === ngramFilter)
      : allPhrases;
    const left = pool.filter((p) => p.bias_score <= -0.1 && !shownSlugs.has(p.slug));
    const right = pool.filter((p) => p.bias_score >= 0.1 && !shownSlugs.has(p.slug));
    const neutral = pool.filter((p) => p.bias_score > -0.1 && p.bias_score < 0.1 && !shownSlugs.has(p.slug));
    function pick(arr, k) { return [...arr].sort(() => Math.random() - 0.5).slice(0, k); }
    return [...pick(left, n), ...pick(right, n), ...pick(neutral, n)];
  }

  // When search is active, filter across ALL phrases so nothing is hidden.
  // Otherwise show only the current bucket-sampled set (displayedPhrases).
  function getFilteredPhrases() {
    const term = document.getElementById("search-input").value.toLowerCase().trim();
    let result = term ? allPhrases : displayedPhrases;
    if (ngramFilter > 0) result = result.filter((p) => p.ngram_size === ngramFilter);
    if (term) result = result.filter((p) => p.phrase.toLowerCase().includes(term));
    return result;
  }

  function showMore() {
    const newPhrases = sampleBuckets(50);
    if (newPhrases.length === 0) {
      document.getElementById("btn-show-more").style.display = "none";
      return;
    }
    newPhrases.forEach((p) => shownSlugs.add(p.slug));
    displayedPhrases = [...displayedPhrases, ...newPhrases];

    const poolTotal = ngramFilter > 0
      ? allPhrases.filter((p) => p.ngram_size === ngramFilter).length
      : allPhrases.length;
    document.getElementById("phrase-count").textContent =
      `Showing ${displayedPhrases.length} of ${poolTotal} phrases`;

    if (shownSlugs.size >= poolTotal) {
      document.getElementById("btn-show-more").style.display = "none";
    }

    renderBubbles(getFilteredPhrases());
  }

  // ── Search results list ───────────────────────────────────────────────────────
  function renderSearchResults(phrases) {
    const el = document.getElementById("search-results");
    const term = document.getElementById("search-input").value.trim();
    if (!term) { el.classList.add("hidden"); return; }

    el.classList.remove("hidden");
    el.innerHTML = "";

    if (phrases.length === 0) {
      el.innerHTML = '<div class="search-result-more">No matching phrases.</div>';
      return;
    }

    const LIMIT = 30;
    phrases.slice(0, LIMIT).forEach((p) => {
      const row = document.createElement("div");
      row.className = "search-result-item";
      row.innerHTML = `
        <span class="search-result-dot" style="background:${phraseColor(p.bias_score)}"></span>
        <span class="search-result-phrase">${escapeHtml(p.phrase)}</span>
        <span class="search-result-count">${p.total_occurrences.toLocaleString()}</span>
      `;
      row.addEventListener("click", () => openPanel(p));
      el.appendChild(row);
    });

    if (phrases.length > LIMIT) {
      const more = document.createElement("div");
      more.className = "search-result-more";
      more.textContent = `+${phrases.length - LIMIT} more — refine your search`;
      el.appendChild(more);
    }
  }

  // ── Bubble rendering ──────────────────────────────────────────────────────────
  function renderBubbles(phrases) {
    const container = document.getElementById("bubble-container");
    const width = container.clientWidth;

    const svg = d3.select("#bubble-svg").attr("width", width).attr("height", PHRASE_RY * 2 + 10);
    svg.selectAll("*").remove();

    const nodes = phrases.map((p) => {
      const rx = phraseRx(p.phrase);
      return {
        ...p,
        rx,
        ry: PHRASE_RY,
        r: Math.sqrt(rx * PHRASE_RY) + 2,
        x: width / 2 + p.bias_score * (width * 0.4),
        y: PHRASE_RY + 10,
      };
    });

    if (simulation) simulation.stop();

    simulation = d3.forceSimulation(nodes)
      .force("x", d3.forceX((d) => width / 2 + d.bias_score * (width * 0.4)).strength(0.3))
      .force("y", d3.forceY(PHRASE_RY + 10).strength(0.07))
      .force("collide", d3.forceCollide((d) => d.r).iterations(3))
      .on("tick", ticked);

    const groups = svg.selectAll("g")
      .data(nodes)
      .enter()
      .append("g")
      .style("cursor", "pointer")
      .on("click", (event, d) => openPanel(d));

    groups.append("ellipse")
      .attr("rx", (d) => d.rx)
      .attr("ry", (d) => d.ry)
      .attr("fill", (d) => phraseColor(d.bias_score));

    groups.append("text").text((d) => d.phrase);

    function ticked() {
      nodes.forEach((d) => {
        d.x = Math.max(d.rx, Math.min(width - d.rx, d.x));
        d.y = Math.max(d.ry, d.y);
      });
      groups.attr("transform", (d) => `translate(${d.x},${d.y})`);
      const maxY = d3.max(nodes, (d) => d.y + d.ry);
      if (maxY) svg.attr("height", maxY + 10);
    }
  }

  // ── Panel ─────────────────────────────────────────────────────────────────────
  async function openPanel(phrase) {
    currentPhrase = phrase;
    const panel = document.getElementById("panel");
    const overlay = document.getElementById("panel-overlay");

    panel.classList.remove("hidden");
    overlay.classList.remove("hidden");
    void panel.offsetHeight;
    panel.classList.add("open");

    document.getElementById("panel-phrase").textContent = `"${phrase.phrase}"`;

    const biasColor = phraseColor(phrase.bias_score);
    const biasLabel = phrase.bias_score < -0.05
      ? "leans Democratic"
      : phrase.bias_score > 0.05 ? "leans Republican" : "neutral";

    // Bias share calculation: for score S, Rep share = (1+S)/2, Dem share = (1-S)/2
    const repShare = Math.round(((1 + phrase.bias_score) / 2) * 100);
    const demShare = 100 - repShare;
    const pRep = phrase.p_rep.toFixed(4);
    const pDem = phrase.p_dem.toFixed(4);
    const pSum = (phrase.p_rep + phrase.p_dem).toFixed(4);
    const formula = `(Rep rate − Dem rate) / (Rep rate + Dem rate) = (${pRep} − ${pDem}) / (${pSum}) = ${phrase.bias_score.toFixed(3)}, where rate = avg. occurrences per speech.`;
    let tooltipText;
    if (phrase.bias_score >= 0.05) {
      tooltipText = `${formula} ${repShare}% of per-speech usage is from Republicans, ${demShare}% from Democrats.`;
    } else if (phrase.bias_score <= -0.05) {
      tooltipText = `${formula} ${demShare}% of per-speech usage is from Democrats, ${repShare}% from Republicans.`;
    } else {
      tooltipText = `${formula} This phrase is used roughly equally by both parties.`;
    }

    document.getElementById("panel-stats").innerHTML = `
      <strong>Total occurrences:</strong> ${phrase.total_occurrences.toLocaleString()}<br>
      <strong>Bias score:</strong> <span class="bias-badge" style="background:${biasColor};">${phrase.bias_score.toFixed(3)}</span>
        (${biasLabel})<br>
      <strong>Rank:</strong> #${phrase.rank_left} left, #${phrase.rank_right} right, #${phrase.rank_overall} overall
    `;
    // Set tooltip text via JS to avoid HTML-encoding issues in the attribute
    document.querySelector(".bias-badge").dataset.tip = tooltipText;

    loadChart(phrase.slug);
    loadQuotes(phrase.slug);
  }

  function closePanel() {
    const panel = document.getElementById("panel");
    const overlay = document.getElementById("panel-overlay");
    panel.classList.remove("open");
    overlay.classList.add("hidden");
    setTimeout(() => panel.classList.add("hidden"), 300);
    if (currentChart) { currentChart.destroy(); currentChart = null; }
    currentPhrase = null;
  }

  // ── Chart ─────────────────────────────────────────────────────────────────────
  async function loadChart(slug) {
    const canvas = document.getElementById("panel-chart");
    if (currentChart) currentChart.destroy();

    try {
      const res = await fetch(`data/history/${slug}.json`);
      const history = await res.json();

      const filtered = history.filter(
        (h) => h.week.startsWith("2025") || h.week.startsWith("2026")
      );
      if (filtered.length === 0) { canvas.style.display = "none"; return; }
      canvas.style.display = "block";

      const { months: monthly, hasGaps } = aggregateByMonth(filtered);
      const note = document.getElementById("panel-chart-note");
      if (note) note.textContent = hasGaps ? "Some months had no recorded mentions and are shown as 0." : "";

      currentChart = new Chart(canvas, {
        type: "line",
        data: {
          labels: monthly.map((m) => m.label),
          datasets: [
            {
              label: "Democrat",
              data: monthly.map((m) => m.dem),
              borderColor: "hsl(220, 70%, 50%)",
              backgroundColor: "hsla(220, 70%, 50%, 0.1)",
              tension: 0.3,
              fill: false,
            },
            {
              label: "Republican",
              data: monthly.map((m) => m.rep),
              borderColor: "hsl(0, 70%, 50%)",
              backgroundColor: "hsla(0, 70%, 50%, 0.1)",
              tension: 0.3,
              fill: false,
            },
            {
              label: "Total",
              data: monthly.map((m) => m.total),
              borderColor: "#999",
              borderDash: [5, 5],
              tension: 0.3,
              fill: false,
            },
          ],
        },
        options: {
          responsive: true,
          plugins: { legend: { position: "bottom" } },
          scales: {
            x: { ticks: { maxRotation: 45, autoSkip: true, maxTicksLimit: 12 } },
            y: { beginAtZero: true, title: { display: true, text: "Mentions" } },
          },
        },
      });
    } catch {
      canvas.style.display = "none";
    }
  }

  // ── Quotes ────────────────────────────────────────────────────────────────────
  async function loadQuotes(slug) {
    const container = document.getElementById("panel-quotes");
    const btn = document.getElementById("btn-more-quotes");
    container.innerHTML = "";
    currentQuotes = [];

    try {
      const res = await fetch(`data/quotes/${slug}.json`);
      currentQuotes = await res.json();
      renderRandomQuotes();
      btn.classList.toggle("hidden", currentQuotes.length <= 10);
    } catch {
      container.innerHTML = "<p>No quotes available.</p>";
      btn.classList.add("hidden");
    }
  }

  function renderRandomQuotes() {
    const container = document.getElementById("panel-quotes");
    container.innerHTML = "";
    const shuffled = [...currentQuotes].sort(() => Math.random() - 0.5);
    shuffled.slice(0, 10).forEach((q) => renderQuoteCard(q, container));
  }

  function renderQuoteCard(q, container) {
    const card = document.createElement("div");
    card.className = `quote-card ${q.party === "Democrat" ? "dem" : "rep"}`;

    const senator = senators[q.senator];
    const headshotHtml = senator
      ? `<div class="headshot-container"><img src="${senator.headshot_url}" alt="${q.senator}" class="headshot" onerror="this.src='${senator.fallback_headshot_url}';this.onerror=function(){this.parentElement.style.display='none'}"></div>`
      : "";

    const highlighted = currentPhrase
      ? highlightPhrase(q.sentence, currentPhrase.phrase)
      : escapeHtml(q.sentence);

    const dateHtml = q.date
      ? `<span class="quote-date">${new Date(q.date + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}</span>`
      : "";
    const sourceLinkHtml = q.source_url
      ? `<a href="${q.source_url}" target="_blank" rel="noopener" class="source-link">↗ source</a>`
      : "";

    card.innerHTML = `
      <div class="quote-senator">${headshotHtml}<span class="senator-name">${escapeHtml(q.senator)} (${q.party === "Democrat" ? "D" : "R"})</span>${sourceLinkHtml}</div>
      <div class="quote-text">&ldquo;${highlighted}&rdquo;</div>
      ${dateHtml ? `<div class="quote-meta">${dateHtml}</div>` : ""}
    `;
    container.appendChild(card);
  }

  function sampleMoreQuotes() {
    renderRandomQuotes();
  }

  // ── Resize ────────────────────────────────────────────────────────────────────
  let resizeTimeout;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimeout);
    resizeTimeout = setTimeout(() => {
      if (displayedPhrases.length > 0) renderBubbles(getFilteredPhrases());
    }, 250);
  });

  init();
})();
