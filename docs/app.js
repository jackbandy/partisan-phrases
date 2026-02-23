(function () {
  "use strict";

  const PAGE_SIZE = 300; // 100 left + 100 right + 100 overall per page
  let allPhrases = [];
  let senators = {};
  let displayedCount = 0;
  let simulation = null;
  let currentChart = null;
  let currentQuotes = [];
  let quotePage = 0;

  // Color helpers
  function phraseColor(bias) {
    const absBias = Math.min(Math.abs(bias), 1);
    if (bias < 0) {
      // Democrat — blue
      const lightness = 65 - absBias * 25;
      return `hsl(220, 70%, ${lightness}%)`;
    } else {
      // Republican — red
      const lightness = 65 - absBias * 25;
      return `hsl(0, 70%, ${lightness}%)`;
    }
  }

  function phraseRadius(totalOccurrences) {
    return Math.max(18, Math.sqrt(Math.log(totalOccurrences + 1)) * 14);
  }

  // Init
  async function init() {
    const [phrasesRes, senatorsRes] = await Promise.all([
      fetch("data/phrases.json"),
      fetch("data/senators.json"),
    ]);
    allPhrases = await phrasesRes.json();
    const senatorsList = await senatorsRes.json();
    senatorsList.forEach((s) => (senators[s.full_name] = s));

    // Sort for pagination: interleave left/right/overall
    allPhrases.sort((a, b) => {
      const aRank = Math.min(a.rank_left, a.rank_right, a.rank_overall);
      const bRank = Math.min(b.rank_left, b.rank_right, b.rank_overall);
      return aRank - bRank;
    });

    showMore();

    document.getElementById("btn-show-more").addEventListener("click", showMore);
    document.getElementById("panel-close").addEventListener("click", closePanel);
    document.getElementById("panel-overlay").addEventListener("click", closePanel);
    document.getElementById("btn-more-quotes").addEventListener("click", showMoreQuotes);
  }

  function showMore() {
    const next = allPhrases.slice(displayedCount, displayedCount + PAGE_SIZE);
    if (next.length === 0) return;
    displayedCount += next.length;

    document.getElementById("phrase-count").textContent =
      `Showing ${displayedCount} of ${allPhrases.length} phrases`;

    if (displayedCount >= allPhrases.length) {
      document.getElementById("btn-show-more").style.display = "none";
    }

    renderBubbles(allPhrases.slice(0, displayedCount));
  }

  function renderBubbles(phrases) {
    const container = document.getElementById("bubble-container");
    const width = container.clientWidth;
    const height = Math.max(600, width * 0.6);

    const svg = d3.select("#bubble-svg")
      .attr("width", width)
      .attr("height", height);

    svg.selectAll("*").remove();

    const nodes = phrases.map((p) => ({
      ...p,
      r: phraseRadius(p.total_occurrences),
      x: width / 2 + p.bias_score * (width * 0.4),
      y: height / 2,
    }));

    if (simulation) simulation.stop();

    simulation = d3.forceSimulation(nodes)
      .force("x", d3.forceX((d) => width / 2 + d.bias_score * (width * 0.4)).strength(0.3))
      .force("y", d3.forceY(height / 2).strength(0.05))
      .force("collide", d3.forceCollide((d) => d.r + 1.5).iterations(3))
      .on("tick", ticked);

    const groups = svg.selectAll("g")
      .data(nodes)
      .enter()
      .append("g")
      .style("cursor", "pointer")
      .on("click", (event, d) => openPanel(d));

    groups.append("circle")
      .attr("r", (d) => d.r)
      .attr("fill", (d) => phraseColor(d.bias_score));

    groups.append("text")
      .text((d) => d.r > 24 ? d.phrase : "")
      .style("font-size", (d) => Math.max(9, Math.min(d.r * 0.4, 14)) + "px");

    function ticked() {
      groups.attr("transform", (d) => `translate(${d.x},${d.y})`);
    }
  }

  // Panel
  async function openPanel(phrase) {
    const panel = document.getElementById("panel");
    const overlay = document.getElementById("panel-overlay");

    panel.classList.remove("hidden");
    overlay.classList.remove("hidden");
    // Trigger reflow for animation
    void panel.offsetHeight;
    panel.classList.add("open");

    document.getElementById("panel-phrase").textContent = `"${phrase.phrase}"`;
    document.getElementById("panel-stats").innerHTML = `
      <strong>Total occurrences:</strong> ${phrase.total_occurrences.toLocaleString()}<br>
      <strong>Bias score:</strong> ${phrase.bias_score.toFixed(3)}
        (${phrase.bias_score < 0 ? "leans Democratic" : "leans Republican"})<br>
      <strong>Rank:</strong> #${phrase.rank_left} left, #${phrase.rank_right} right, #${phrase.rank_overall} overall
    `;

    // Load history chart
    loadChart(phrase.slug);
    // Load quotes
    loadQuotes(phrase.slug);
  }

  function closePanel() {
    const panel = document.getElementById("panel");
    const overlay = document.getElementById("panel-overlay");
    panel.classList.remove("open");
    overlay.classList.add("hidden");
    setTimeout(() => panel.classList.add("hidden"), 300);
    if (currentChart) {
      currentChart.destroy();
      currentChart = null;
    }
  }

  async function loadChart(slug) {
    const canvas = document.getElementById("panel-chart");
    if (currentChart) currentChart.destroy();

    try {
      const res = await fetch(`data/history/${slug}.json`);
      const history = await res.json();

      if (history.length === 0) {
        canvas.style.display = "none";
        return;
      }
      canvas.style.display = "block";

      currentChart = new Chart(canvas, {
        type: "line",
        data: {
          labels: history.map((h) => h.week),
          datasets: [
            {
              label: "Democrat",
              data: history.map((h) => h.dem),
              borderColor: "hsl(220, 70%, 50%)",
              backgroundColor: "hsla(220, 70%, 50%, 0.1)",
              tension: 0.3,
              fill: false,
            },
            {
              label: "Republican",
              data: history.map((h) => h.rep),
              borderColor: "hsl(0, 70%, 50%)",
              backgroundColor: "hsla(0, 70%, 50%, 0.1)",
              tension: 0.3,
              fill: false,
            },
            {
              label: "Total",
              data: history.map((h) => h.total),
              borderColor: "#999",
              borderDash: [5, 5],
              tension: 0.3,
              fill: false,
            },
          ],
        },
        options: {
          responsive: true,
          plugins: {
            legend: { position: "bottom" },
          },
          scales: {
            x: {
              ticks: { maxTicksLimit: 8 },
            },
            y: {
              beginAtZero: true,
              title: { display: true, text: "Mentions" },
            },
          },
        },
      });
    } catch {
      canvas.style.display = "none";
    }
  }

  async function loadQuotes(slug) {
    const container = document.getElementById("panel-quotes");
    const btn = document.getElementById("btn-more-quotes");
    container.innerHTML = "";
    currentQuotes = [];
    quotePage = 0;

    try {
      const res = await fetch(`data/quotes/${slug}.json`);
      currentQuotes = await res.json();
      renderQuotePage();
      btn.classList.toggle("hidden", currentQuotes.length <= 10);
    } catch {
      container.innerHTML = "<p>No quotes available.</p>";
      btn.classList.add("hidden");
    }
  }

  function renderQuotePage() {
    const container = document.getElementById("panel-quotes");
    const start = quotePage * 10;
    const slice = currentQuotes.slice(start, start + 10);

    slice.forEach((q) => {
      const card = document.createElement("div");
      const partyClass = q.party === "Democrat" ? "dem" : "rep";
      card.className = `quote-card ${partyClass}`;

      const senator = senators[q.senator];
      const headshot = senator
        ? `<img src="${senator.headshot_url}" alt="${q.senator}" style="width:28px;height:28px;border-radius:50%;vertical-align:middle;margin-right:6px;">`
        : "";

      card.innerHTML = `
        <div class="quote-senator">${headshot}${q.senator} (${q.party === "Democrat" ? "D" : "R"})</div>
        <div class="quote-text">"${q.sentence}"</div>
      `;
      container.appendChild(card);
    });
  }

  function showMoreQuotes() {
    quotePage++;
    if (quotePage * 10 >= currentQuotes.length) {
      quotePage = 0;
      document.getElementById("panel-quotes").innerHTML = "";
    }
    renderQuotePage();
  }

  // Window resize handler
  let resizeTimeout;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimeout);
    resizeTimeout = setTimeout(() => {
      if (displayedCount > 0) {
        renderBubbles(allPhrases.slice(0, displayedCount));
      }
    }, 250);
  });

  init();
})();
