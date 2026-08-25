document.addEventListener("DOMContentLoaded", () => {
  const dateSelect = document.getElementById("date-select");
  const dateSelectorContainer = document.getElementById("date-selector-container");
  const mainContent = document.getElementById("main-content");
  const trackerContent = document.getElementById("tracker-content");
  const emptyState = document.getElementById("empty-state");

  // Tab 按钮
  const tabBtnDaily = document.getElementById("tab-btn-daily");
  const tabBtnTracker = document.getElementById("tab-btn-tracker");

  // 每日决策 DOM 元素
  const marketSummaryText = document.getElementById("market-summary-text");
  const badNewsTableBody = document.getElementById("bad-news-table-body");
  const catalystAccordion = document.getElementById("catalyst-accordion");
  const stockTabs = document.getElementById("stock-tabs");
  const stockDetailContent = document.getElementById("stock-detail-content");
  const excludedStockList = document.getElementById("excluded-stock-list");
  const watchStockList = document.getElementById("watch-stock-list");
  const operationSummaryText = document.getElementById("operation-summary-text");

  // 跟踪看板 DOM 元素
  const statWinRate = document.getElementById("stat-win-rate");
  const statWinRatio = document.getElementById("stat-win-ratio");
  const statAvgGain = document.getElementById("stat-avg-gain");
  const statAvgLoss = document.getElementById("stat-avg-loss");
  const statTop1Win = document.getElementById("stat-top1-win");
  const statRankBreakdown = document.getElementById("stat-rank-breakdown");
  const trackerTableBody = document.getElementById("tracker-table-body");
  const trackerSearch = document.getElementById("tracker-search");
  const trackerStatusFilter = document.getElementById("tracker-status-filter");

  let currentDecisionData = null;
  let allTrackingsData = [];
  let currentActiveTab = "daily"; // "daily" | "tracker"

  // --- 1. 视图切换逻辑 ---
  tabBtnDaily.addEventListener("click", () => {
    if (currentActiveTab === "daily") return;
    currentActiveTab = "daily";
    tabBtnDaily.classList.add("active");
    tabBtnTracker.classList.remove("active");
    trackerContent.style.display = "none";
    dateSelectorContainer.style.display = "flex";
    if (currentDecisionData) {
      mainContent.style.display = "grid";
    }
  });

  tabBtnTracker.addEventListener("click", () => {
    if (currentActiveTab === "tracker") return;
    currentActiveTab = "tracker";
    tabBtnTracker.classList.add("active");
    tabBtnDaily.classList.remove("active");
    mainContent.style.display = "none";
    dateSelectorContainer.style.display = "none";
    trackerContent.style.display = "block";
    loadTrackerData();
  });

  // --- 2. 初始化拉取决策日期列表 (优先 /api/decisions，兜底 data/list.json) ---
  fetchDates();

  function fetchDates() {
    fetch('/api/decisions')
      .then(res => {
        if (!res.ok) throw new Error("API not available");
        return res.json();
      })
      .then(resData => {
        if (resData.success && resData.data && resData.data.length > 0) {
          populateDateSelector(resData.data);
        } else {
          fallbackStaticDates();
        }
      })
      .catch(() => {
        fallbackStaticDates();
      });
  }

  function fallbackStaticDates() {
    fetch(`data/list.json?t=${new Date().getTime()}`)
      .then(res => res.json())
      .then(datesArray => {
        if (datesArray && datesArray.length > 0) {
          populateDateSelector(datesArray);
        } else {
          showEmptyState();
        }
      })
      .catch(err => {
        console.error("加载日期列表失败:", err);
        showEmptyState();
      });
  }

  function populateDateSelector(dates) {
    dateSelect.innerHTML = "";
    dates.forEach(date => {
      const opt = document.createElement("option");
      opt.value = date;
      const dateParts = date.split("-");
      opt.textContent = `📅 ${dateParts[0]}年${dateParts[1]}月${dateParts[2]}日`;
      dateSelect.appendChild(opt);
    });
    // 默认加载最新的一天决策
    loadDecisionDetail(dates[0]);
  }

  dateSelect.addEventListener("change", (e) => {
    if (e.target.value) {
      loadDecisionDetail(e.target.value);
    }
  });

  // --- 3. 加载某一天具体的决策详情 (优先 /api/decisions/:date，兜底 data/YYYY-MM-DD.json) ---
  function loadDecisionDetail(dateStr) {
    mainContent.style.display = "none";
    emptyState.style.display = "none";

    fetch(`/api/decisions/${dateStr}`)
      .then(res => {
        if (!res.ok) throw new Error("API not available");
        return res.json();
      })
      .then(resData => {
        if (resData.success && resData.data) {
          currentDecisionData = resData.data;
          renderDailyUI(resData.data);
          if (currentActiveTab === "daily") {
            mainContent.style.display = "grid";
          }
        } else {
          fallbackStaticDecisionDetail(dateStr);
        }
      })
      .catch(() => {
        fallbackStaticDecisionDetail(dateStr);
      });
  }

  function fallbackStaticDecisionDetail(dateStr) {
    fetch(`data/${dateStr}.json?t=${new Date().getTime()}`)
      .then(res => res.json())
      .then(detailObj => {
        currentDecisionData = detailObj;
        renderDailyUI(detailObj);
        if (currentActiveTab === "daily") {
          mainContent.style.display = "grid";
        }
      })
      .catch(err => {
        console.error(`加载日期 ${dateStr} 决策详情失败:`, err);
        showEmptyState();
      });
  }

  // --- 4. 每日决策渲染逻辑 ---
  function renderDailyUI(data) {
    marketSummaryText.textContent = data.market_summary || "暂无大盘评述";

    // 渲染利空排除表格
    badNewsTableBody.innerHTML = "";
    if (data.bad_news_table && data.bad_news_table.length > 0) {
      data.bad_news_table.forEach(item => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td class="bold text-color-red">${item.source}</td>
          <td>${item.content}</td>
          <td class="bold">${item.exclude}</td>
        `;
        badNewsTableBody.appendChild(tr);
      });
    } else {
      badNewsTableBody.innerHTML = `<tr><td colspan="3" class="text-center text-muted">今日无重大消息利空排除项</td></tr>`;
    }

    // 渲染催化折叠面板
    catalystAccordion.innerHTML = "";
    if (data.catalyst_list && data.catalyst_list.length > 0) {
      data.catalyst_list.forEach((item, index) => {
        const accItem = document.createElement("div");
        accItem.className = `accordion-item ${index === 0 ? 'active' : ''}`;
        accItem.innerHTML = `
          <div class="accordion-header">
            <span><i class="fa-solid fa-bolt text-color-yellow" style="margin-right: 8px;"></i>${item.title}</span>
            <i class="fa-solid fa-chevron-down accordion-icon"></i>
          </div>
          <div class="accordion-content">
            <p>${item.content}</p>
          </div>
        `;
        accItem.querySelector(".accordion-header").addEventListener("click", () => {
          accItem.classList.toggle("active");
        });
        catalystAccordion.appendChild(accItem);
      });
    }

    // 渲染首选三标 Tabs 与详情
    stockTabs.innerHTML = "";
    stockDetailContent.innerHTML = "";
    if (data.top_three_stocks && data.top_three_stocks.length > 0) {
      data.top_three_stocks.forEach((stock, index) => {
        const tabBtn = document.createElement("button");
        tabBtn.className = `tab-btn ${index === 0 ? 'active' : ''}`;
        tabBtn.innerHTML = `
          <span class="badge badge-rank">Top ${stock.rank || (index + 1)}</span>
          <span>${stock.name}</span>
          <span class="tab-score">${stock.score ? stock.score + '分' : ''}</span>
        `;

        const detailCard = document.createElement("div");
        detailCard.className = `stock-panel ${index === 0 ? 'active' : ''}`;
        detailCard.id = `stock-panel-${index}`;
        detailCard.innerHTML = `
          <div class="stock-panel-header">
            <div class="stock-title-wrap">
              <h3>${stock.name} <span class="stock-code">${stock.code}</span></h3>
              <span class="stock-direction-tag">${stock.direction || '主线重点'}</span>
            </div>
            <div class="stock-score-badge">
              <span class="score-num">${stock.score || '--'}</span>
              <span class="score-label">综合评分</span>
            </div>
          </div>
          
          <div class="stock-meta-grid">
            <div class="meta-item">
              <span class="meta-label"><i class="fa-solid fa-coins"></i> 市值参考</span>
              <span class="meta-val">${stock.market_cap || '正在校对...'}</span>
            </div>
            <div class="meta-item">
              <span class="meta-label"><i class="fa-solid fa-chart-simple"></i> 近5日表现</span>
              <span class="meta-val">${stock.pct_change_5d || '正在校对...'}</span>
            </div>
          </div>

          <div class="detail-section">
            <h4><i class="fa-solid fa-lightbulb"></i> 核心入选逻辑</h4>
            <p class="logic-text">${stock.logic}</p>
          </div>

          <div class="detail-section">
            <h4><i class="fa-solid fa-crosshairs"></i> 详细介入条件与风控要求</h4>
            <div class="condition-box">${stock.price_condition || stock.entry_condition || '按战法开盘竞价量比标准执行'}</div>
          </div>

          <div class="detail-section">
            <h4><i class="fa-solid fa-wave-square"></i> K线及筹码特征</h4>
            <p class="feature-text">${stock.k_features || stock.features || '均线多头排列，回踩均线支撑有力'}</p>
          </div>
        `;

        tabBtn.addEventListener("click", () => {
          document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
          document.querySelectorAll(".stock-panel").forEach(p => p.classList.remove("active"));
          tabBtn.classList.add("active");
          detailCard.classList.add("active");
        });

        stockTabs.appendChild(tabBtn);
        stockDetailContent.appendChild(detailCard);
      });
    }

    // 渲染今日排除与关注池
    excludedStockList.innerHTML = "";
    if (data.excluded_stocks && data.excluded_stocks.length > 0) {
      data.excluded_stocks.forEach(item => {
        const li = document.createElement("li");
        li.innerHTML = `<strong>${item.name}</strong>: <span>${item.reason}</span>`;
        excludedStockList.appendChild(li);
      });
    }

    watchStockList.innerHTML = "";
    if (data.watch_list && data.watch_list.length > 0) {
      data.watch_list.forEach(item => {
        const li = document.createElement("li");
        li.innerHTML = `<strong>${item.name}</strong> (${item.direction || '观察'}): <span>${item.logic || item.trigger || ''}</span>`;
        watchStockList.appendChild(li);
      });
    }

    // 渲染操作总结
    if (window.marked && data.operation_summary) {
      operationSummaryText.innerHTML = marked.parse(data.operation_summary);
    } else {
      operationSummaryText.textContent = data.operation_summary || "按既定战法严格执行纪律。";
    }
  }

  // --- 5. 实盘跟踪与胜率复盘看板逻辑 ---
  function loadTrackerData() {
    // 5.1 拉取统计数据 (优先 /api/trackings/stats，兜底 data/tracking_stats.json)
    fetch('/api/trackings/stats')
      .then(res => {
        if (!res.ok) throw new Error("API not available");
        return res.json();
      })
      .then(resData => {
        if (resData.success && resData.data) {
          renderKPI(resData.data);
        } else {
          fallbackStaticStats();
        }
      })
      .catch(() => fallbackStaticStats());

    // 5.2 拉取跟踪明细 (优先 /api/trackings，兜底 data/trackings.json)
    fetch('/api/trackings?limit=300')
      .then(res => {
        if (!res.ok) throw new Error("API not available");
        return res.json();
      })
      .then(resData => {
        if (resData.success && resData.data) {
          allTrackingsData = resData.data;
          renderTrackerTable(allTrackingsData);
        } else {
          fallbackStaticTrackings();
        }
      })
      .catch(() => fallbackStaticTrackings());
  }

  function fallbackStaticStats() {
    fetch(`data/tracking_stats.json?t=${new Date().getTime()}`)
      .then(res => res.json())
      .then(stats => renderKPI(stats))
      .catch(err => console.error("加载静态胜率统计失败:", err));
  }

  function fallbackStaticTrackings() {
    fetch(`data/trackings.json?t=${new Date().getTime()}`)
      .then(res => res.json())
      .then(rows => {
        allTrackingsData = rows || [];
        renderTrackerTable(allTrackingsData);
      })
      .catch(err => console.error("加载静态跟踪数据失败:", err));
  }

  function renderKPI(stats) {
    if (!stats) return;
    statWinRate.textContent = `${stats.win_rate || 0}%`;
    statWinRatio.textContent = `盈利 ${stats.win_count || 0} / 总计 ${stats.valid_total || 0} 标的`;
    statAvgGain.textContent = stats.avg_max_gain ? `+${stats.avg_max_gain}%` : "+0.0%";
    statAvgLoss.textContent = stats.avg_max_loss ? `${stats.avg_max_loss}%` : "0.0%";

    if (stats.rank_stats && stats.rank_stats.Top_1) {
      statTop1Win.textContent = `${stats.rank_stats.Top_1.win_rate}%`;
      const t2 = stats.rank_stats.Top_2 ? `${stats.rank_stats.Top_2.win_rate}%` : '--%';
      const t3 = stats.rank_stats.Top_3 ? `${stats.rank_stats.Top_3.win_rate}%` : '--%';
      statRankBreakdown.textContent = `Top 2: ${t2} | Top 3: ${t3}`;
    }
  }

  function renderTrackerTable(rows) {
    trackerTableBody.innerHTML = "";
    if (!rows || rows.length === 0) {
      trackerTableBody.innerHTML = `<tr><td colspan="13" class="text-center text-muted">暂无历史跟踪数据</td></tr>`;
      return;
    }

    const keyword = trackerSearch.value.trim().toLowerCase();
    const statusFilter = trackerStatusFilter.value;

    const filtered = rows.filter(r => {
      const matchStatus = statusFilter === "ALL" || r.win_loss_status === statusFilter;
      const matchKeyword = !keyword ||
        (r.code && r.code.includes(keyword)) ||
        (r.name && r.name.toLowerCase().includes(keyword)) ||
        (r.direction && r.direction.toLowerCase().includes(keyword)) ||
        (r.decision_date && r.decision_date.includes(keyword));
      return matchStatus && matchKeyword;
    });

    if (filtered.length === 0) {
      trackerTableBody.innerHTML = `<tr><td colspan="13" class="text-center text-muted">没有符合筛选条件的记录</td></tr>`;
      return;
    }

    filtered.forEach(r => {
      const tr = document.createElement("tr");

      // 格式化收益显示与红绿色
      const formatPct = (val) => {
        if (val === null || val === undefined) return '<span class="text-muted">--</span>';
        const num = parseFloat(val);
        const cls = num > 0 ? 'text-color-red font-bold' : (num < 0 ? 'text-color-green font-bold' : 'text-muted');
        const sign = num > 0 ? '+' : '';
        return `<span class="${cls}">${sign}${num.toFixed(2)}%</span>`;
      };

      let pillHtml = '<span class="status-pill pill-pending">⏳ 跟踪中</span>';
      if (r.win_loss_status === 'WIN') {
        pillHtml = '<span class="status-pill pill-win">🟢 超预期冲高</span>';
      } else if (r.win_loss_status === 'LOSS') {
        pillHtml = '<span class="status-pill pill-loss">🔴 回撤走弱</span>';
      } else if (r.win_loss_status === 'DRAW') {
        pillHtml = '<span class="status-pill pill-draw">🟡 震荡蓄势</span>';
      }

      tr.innerHTML = `
        <td class="bold font-mono">${r.decision_date}</td>
        <td><span class="badge badge-rank">Top ${r.rank}</span></td>
        <td class="font-mono">${r.code}</td>
        <td class="bold">${r.name}</td>
        <td style="max-width: 160px;" class="ellipsis" title="${r.direction || ''}">${r.direction || '--'}</td>
        <td class="bold">${r.score ? r.score + '分' : '--'}</td>
        <td class="font-mono">${r.buy_price ? r.buy_price.toFixed(2) + '元' : '--'}</td>
        <td>${formatPct(r.t0_return)}</td>
        <td>${formatPct(r.t1_return)}</td>
        <td>${formatPct(r.t3_return)}</td>
        <td><span class="text-color-red bold">+${r.max_gain_5d ? r.max_gain_5d.toFixed(2) : '0.00'}%</span></td>
        <td><span class="text-color-green bold">${r.max_loss_5d ? r.max_loss_5d.toFixed(2) : '0.00'}%</span></td>
        <td>${pillHtml}</td>
      `;
      trackerTableBody.appendChild(tr);
    });
  }

  // 搜索和状态过滤事件监听
  trackerSearch.addEventListener("input", () => renderTrackerTable(allTrackingsData));
  trackerStatusFilter.addEventListener("change", () => renderTrackerTable(allTrackingsData));

  function showEmptyState() {
    mainContent.style.display = "none";
    trackerContent.style.display = "none";
    emptyState.style.display = "block";
  }
});
