// SPIDY CRYPTO Reactive Client HUD Engine (Multi-Coin Reactive System)
let ws = null;
let currentSymbol = "ETHUSD";
let currentResolution = "5m";
let currentCandles = [];
let activeTrade = null;
let marketStates = {};
let coinAnalysisData = {};
let selectedModelId = "MODEL_7";

function getSymbolPrecision(sym) {
    if (sym === "XRPUSD") return 4;
    if (sym === "AVAXUSD") return 3;
    if (sym === "BTCUSD") return 1;
    return 2;
}

function formatPrice(sym, val) {
    if (val === null || val === undefined || isNaN(val)) return "--";
    return Number(val).toFixed(getSymbolPrecision(sym));
}

let userManuallySelectedSymbol = false;
let lastActiveTradeId = null;

document.addEventListener("DOMContentLoaded", () => {
    initWebSocket();
    fetchStatus();
    
    // Initial selection
    selectSymbol("ETHUSD");

    // Market card coin selector
    document.querySelectorAll(".market-card").forEach(card => {
        card.addEventListener("click", () => {
            const sym = card.dataset.symbol;
            if (sym) {
                userManuallySelectedSymbol = true;
                selectSymbol(sym);
            }
        });
    });

    // Timeframe selector buttons
    document.querySelectorAll(".tf-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".tf-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            currentResolution = btn.dataset.tf;
            document.getElementById("chart-symbol-label").textContent = `${currentSymbol} • ${currentResolution.toUpperCase()} CHART`;
            loadCandles(currentSymbol, currentResolution);
        });
    });

    // Operational action buttons
    const btnPower = document.getElementById("btn-power-toggle");
    if (btnPower) btnPower.addEventListener("click", toggleBotPower);

    const btnScan = document.getElementById("btn-scan");
    if (btnScan) btnScan.addEventListener("click", triggerScan);

    const btnBacktest = document.getElementById("btn-backtest");
    if (btnBacktest) btnBacktest.addEventListener("click", runBacktest);

    const btnValidate = document.getElementById("btn-validate");
    if (btnValidate) btnValidate.addEventListener("click", runValidation);

    const btnLong = document.getElementById("btn-sim-long");
    if (btnLong) btnLong.addEventListener("click", () => simulateSetup("LONG"));

    const btnShort = document.getElementById("btn-sim-short");
    if (btnShort) btnShort.addEventListener("click", () => simulateSetup("SHORT"));

    const btnRelease = document.getElementById("btn-release-lock");
    if (btnRelease) btnRelease.addEventListener("click", releaseActiveTradeLock);

    // Dedicated War Room Action Buttons
    const btnWtBe = document.getElementById("btn-wt-be");
    if (btnWtBe) btnWtBe.addEventListener("click", triggerBreakeven);

    const btnWtPartial = document.getElementById("btn-wt-partial");
    if (btnWtPartial) btnWtPartial.addEventListener("click", triggerPartial);

    const btnWtClose = document.getElementById("btn-wt-close");
    if (btnWtClose) btnWtClose.addEventListener("click", releaseActiveTradeLock);

    const btnWtView = document.getElementById("btn-wt-view");
    if (btnWtView) btnWtView.addEventListener("click", () => {
        if (activeTrade && activeTrade.coin) {
            userManuallySelectedSymbol = false;
            selectSymbol(activeTrade.coin);
        }
    });

    const btnSnapActive = document.getElementById("btn-snap-active");
    if (btnSnapActive) btnSnapActive.addEventListener("click", () => {
        if (activeTrade && activeTrade.coin) {
            userManuallySelectedSymbol = false;
            selectSymbol(activeTrade.coin);
        }
    });

    // PIN Security Pill click listener
    const secPill = document.getElementById("security-pill");
    if (secPill) {
        secPill.addEventListener("click", () => {
            const stored = getStoredPin();
            if (stored) {
                if (confirm("Admin controls are currently UNLOCKED. Do you want to lock them now?")) {
                    setStoredPin("");
                }
            } else {
                openPinModal(() => {
                    alert("Admin unlocked successfully.");
                });
            }
        });
    }

    // PIN modal buttons & Enter key
    const btnPinSubmit = document.getElementById("btn-pin-submit");
    if (btnPinSubmit) btnPinSubmit.addEventListener("click", submitPinAuth);

    const btnPinCancel = document.getElementById("btn-pin-cancel");
    if (btnPinCancel) btnPinCancel.addEventListener("click", closePinModal);

    const pinInput = document.getElementById("pin-input");
    if (pinInput) {
        pinInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter") submitPinAuth();
            if (e.key === "Escape") closePinModal();
        });
    }

    // Initialize security badge from session
    updateSecurityBadge(!!getStoredPin());

    // Unconditional high-frequency status polling to ensure web HUD is always 100% in sync with Telegram
    setInterval(() => {
        fetchStatus();
    }, 2500);
});

function selectSymbol(sym) {
    currentSymbol = sym;

    // 1. Instantly highlight active card
    document.querySelectorAll(".market-card").forEach(c => {
        c.classList.toggle("selected", c.dataset.symbol === sym);
    });

    // 2. Instantly update tactical panel header and labels
    const coinBadge = document.getElementById("trade-badge-coin");
    if (coinBadge) coinBadge.textContent = sym;

    const chartLabel = document.getElementById("chart-symbol-label");
    if (chartLabel) chartLabel.textContent = `${sym} • ${currentResolution.toUpperCase()} CHART`;

    // 3. Update price levels locally ONLY if there is an active trade on this coin
    if (activeTrade && activeTrade.coin === sym && (activeTrade.trade_status === "ACTIVE" || activeTrade.trade_status === "WAITING")) {
        document.getElementById("val-entry").textContent = formatPrice(sym, activeTrade.entry);
        document.getElementById("val-stop").textContent = formatPrice(sym, activeTrade.stop_loss);
        document.getElementById("val-t1").textContent = formatPrice(sym, activeTrade.target_1);
        document.getElementById("val-t2").textContent = formatPrice(sym, activeTrade.target_2);
        document.getElementById("val-margin").textContent = `₹${Number(activeTrade.margin_used || 3000).toLocaleString('en-IN')} (6x Leverage)`;

        const dirBadge = document.getElementById("trade-direction-badge");
        if (dirBadge) {
            dirBadge.textContent = activeTrade.direction;
            dirBadge.className = `direction-badge ${activeTrade.direction}`;
        }
    } else {
        document.getElementById("val-entry").textContent = "--";
        document.getElementById("val-stop").textContent = "--";
        document.getElementById("val-t1").textContent = "--";
        document.getElementById("val-t2").textContent = "--";
        document.getElementById("val-margin").textContent = "Idle (₹3,000 Margin @ 6x)";

        const m = marketStates[sym];
        const dirBadge = document.getElementById("trade-direction-badge");
        if (dirBadge) {
            const isBull = (m && m.mtf_context && m.mtf_context.exec_context_15m === "Bullish");
            dirBadge.textContent = isBull ? "BULLISH BIAS" : "BEARISH BIAS";
            dirBadge.className = `direction-badge ${isBull ? 'LONG' : 'SHORT'}`;
        }
    }

    // 4. Fetch candles and full deep SMC server analysis
    loadCandles(sym, currentResolution);
    fetchCoinAnalysis(sym);

    // 5. Contextual banner if previewing another coin while active trade is running
    const activeNotice = document.getElementById("tactical-active-notice");
    if (activeNotice) {
        if (activeTrade && (activeTrade.trade_status === "ACTIVE" || activeTrade.trade_status === "WAITING") && sym !== activeTrade.coin) {
            activeNotice.style.display = "flex";
            const cEl = document.getElementById("tactical-notice-coin");
            const dEl = document.getElementById("tactical-notice-dir");
            const vEl = document.getElementById("tactical-notice-viewing");
            if (cEl) cEl.textContent = activeTrade.coin;
            if (dEl) {
                dEl.textContent = `(${activeTrade.direction})`;
                dEl.style.color = activeTrade.direction === "LONG" ? "var(--emerald-neon)" : "var(--rose-neon)";
            }
            if (vEl) vEl.textContent = sym;
        } else {
            activeNotice.style.display = "none";
        }
    }

    // 5. If backtest was executed, refresh highlight for selected coin
    if (lastBacktestByMarket && lastBacktestByMarket[sym]) {
        const bm = lastBacktestByMarket[sym];
        const bmColor = bm.total_r >= 0 ? "var(--emerald-neon)" : "var(--rose-neon)";
        const box = document.getElementById("backtest-summary-box");
        const content = document.getElementById("backtest-summary-content");
        if (box && content && box.style.display !== "none") {
            let html = `
                <div style="font-size:12px; margin-bottom:4px;">
                    <strong style="color:var(--cyan-neon);">[ ${sym} BACKTEST ]:</strong>
                    Trades: <strong>${bm.trades}</strong> | 
                    Win Rate: <strong style="color:var(--emerald-neon)">${bm.win_rate}%</strong> | 
                    Total Gain: <strong style="color:${bmColor}">${bm.total_r > 0 ? '+' : ''}${bm.total_r}R</strong> | 
                    Profit Factor: <strong>${bm.profit_factor}</strong>
                </div>
            `;
            html += `<div style="margin-top:6px; display:flex; flex-wrap:wrap; gap:12px; font-size:10px; border-top:1px solid rgba(255,255,255,0.1); padding-top:6px;">`;
            for (const [s, b] of Object.entries(lastBacktestByMarket)) {
                const c = b.total_r >= 0 ? "var(--emerald-neon)" : "var(--rose-neon)";
                const isSel = s === sym;
                html += `
                    <div style="${isSel ? 'background:rgba(0,240,255,0.15); padding:2px 6px; border-radius:4px; border:1px solid var(--cyan-neon);' : ''}">
                        <strong style="color:${isSel ? 'var(--cyan-neon)' : '#fff'};">${s}:</strong> 
                        ${b.trades} trds | 
                        WR: <strong style="color:var(--emerald-neon);">${b.win_rate}%</strong> | 
                        Gain: <strong style="color:${c};">${b.total_r > 0 ? '+' : ''}${b.total_r}R</strong> | 
                        PF: ${b.profit_factor}
                    </div>
                `;
            }
            html += `</div>`;
            content.innerHTML = html;
        }
    }
}

function initWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    try {
        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
            document.getElementById("ws-status-dot").className = "status-dot green";
            document.getElementById("ws-status-text").textContent = "STREAM LIVE";
        };

        ws.onclose = () => {
            document.getElementById("ws-status-dot").className = "status-dot rose";
            document.getElementById("ws-status-text").textContent = "RECONNECTING";
            setTimeout(initWebSocket, 2000);
        };

        ws.onerror = () => {
            try { ws.close(); } catch(e) {}
        };

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                handleWsMessage(data);
            } catch (e) {
                console.error("WS parse error", e);
            }
        };
    } catch (e) {
        console.error("WebSocket init error", e);
        setTimeout(initWebSocket, 3000);
    }
}

function handleWsMessage(msg) {
    if (msg.type === "STATUS_UPDATE" || msg.type === "INITIAL_STATE") {
        updateHUD(msg.data);
    } else if (msg.type === "PRICE_TICK") {
        updatePrice(msg.symbol, msg.price);
    } else if (msg.type === "CANDLE_CLOSED" && msg.symbol === currentSymbol && msg.resolution === currentResolution) {
        loadCandles(currentSymbol, currentResolution);
    }
}

async function fetchStatus() {
    try {
        const res = await fetch("/api/status");
        if (res.ok) {
            const data = await res.json();
            updateHUD(data);
        }
    } catch (e) {
        // Fallback quiet
    }
}

async function fetchCoinAnalysis(sym) {
    try {
        const res = await fetch(`/api/analysis/${sym}`);
        if (res.ok) {
            const data = await res.json();
            coinAnalysisData[sym] = data;
            renderTacticalPanel(data);
        }
    } catch (e) {
        console.error("Error fetching coin analysis", e);
    }
}

async function loadCandles(sym, resParam) {
    try {
        const res = await fetch(`/api/candles/${sym}?resolution=${resParam || currentResolution}&limit=40`);
        if (res.ok) {
            const data = await res.json();
            currentCandles = data.candles || [];
            drawChart();
        }
    } catch (e) {
        console.error("Error fetching candles", e);
    }
}

function updateHUD(data) {
    if (data.markets) {
        marketStates = data.markets;
        for (const [sym, m] of Object.entries(data.markets)) {
            updatePrice(sym, m.current_price, m.is_stale, m.connection_status);
            if (m.mtf_context) {
                const el4h = document.getElementById(`mtf-4h-${sym}`);
                const el1h = document.getElementById(`mtf-1h-${sym}`);
                const el15 = document.getElementById(`mtf-15m-${sym}`);
                const el5 = document.getElementById(`mtf-5m-${sym}`);
                if (el4h) el4h.textContent = `4H: ${m.mtf_context.macro_bias_4h}`;
                if (el1h) el1h.textContent = `1H: ${m.mtf_context.trend_1h}`;
                if (el15) el15.textContent = `15M: ${m.mtf_context.exec_context_15m}`;
                if (el5) el5.textContent = `5M: ${m.mtf_context.struct_5m}`;
            }
        }
    }

    if (data.reentry_status) {
        for (const [sym, rStat] of Object.entries(data.reentry_status)) {
            const cardMeta = document.getElementById(`reentry-meta-${sym}`);
            if (cardMeta) {
                const rem = rStat.cooldown_remaining_bars || 0;
                if (rStat.state === "POST_TRADE_COOLDOWN" || rem > 0) {
                    cardMeta.innerHTML = `<span style="color:var(--amber-neon);">COOLDOWN (${rem} BARS)</span> | <span style="color:#ff3b5c;">BLOCKED</span>`;
                } else if (rStat.state === "WAITING_FOR_NEW_STRUCTURE") {
                    cardMeta.innerHTML = `<span style="color:var(--cyan-neon);">WAITING STRUCTURE</span> | <span style="color:#ff3b5c;">BLOCKED</span>`;
                } else {
                    cardMeta.innerHTML = `<span style="color:var(--emerald-neon);">READY</span> | <span style="color:var(--emerald-neon);">FRESH</span>`;
                }
            }

            if (sym === currentSymbol) {
                const stateEl = document.getElementById("reentry-state-badge");
                const cdEl = document.getElementById("reentry-cd-badge");
                const prevEl = document.getElementById("reentry-prev-setup");
                const structEl = document.getElementById("reentry-fresh-struct");
                const eligEl = document.getElementById("reentry-eligibility");

                if (stateEl) {
                    stateEl.textContent = rStat.state || "READY";
                    stateEl.style.color = (rStat.state === "POST_TRADE_COOLDOWN" || rStat.state === "WAITING_FOR_NEW_STRUCTURE") ? "var(--amber-neon)" : "var(--emerald-neon)";
                }
                if (cdEl) cdEl.textContent = `${rStat.cooldown_remaining_bars || 0} BARS`;
                if (prevEl) prevEl.textContent = rStat.previous_setup_status || "CONSUMED";
                if (structEl) {
                    structEl.textContent = rStat.fresh_structure || "CONFIRMED";
                    structEl.style.color = (rStat.fresh_structure === "NOT YET") ? "#ff3b5c" : "var(--emerald-neon)";
                }
                if (eligEl) {
                    eligEl.textContent = rStat.trade_eligibility || "READY";
                    eligEl.style.color = (rStat.trade_eligibility === "BLOCKED") ? "#ff3b5c" : "var(--emerald-neon)";
                }
            }
        }
    }

    activeTrade = data.active_trade;
    const lockDot = document.getElementById("lock-status-dot");
    const lockText = document.getElementById("lock-status-text");
    const standbyDot = document.getElementById("standby-dot");
    const standbyTitle = document.getElementById("standby-title");
    const standbyDesc = document.getElementById("standby-desc");
    const powerBtn = document.getElementById("btn-power-toggle");

    const isPaused = data.is_paused || data.global_status === "STOPPED";

    if (isPaused) {
        if (lockDot) lockDot.className = "status-dot red";
        if (lockText) lockText.textContent = "BOT STOPPED / PAUSED";

        if (standbyDot) standbyDot.className = "status-dot red";
        if (standbyTitle) {
            standbyTitle.textContent = "SPIDY BOT POWERED OFF / STOPPED";
            standbyTitle.style.color = "var(--rose-neon)";
        }
        if (standbyDesc) {
            standbyDesc.textContent = "Trading is paused. Bot will not enter any trades. Send /resume on Telegram or click Resume below.";
        }
        if (powerBtn) {
            powerBtn.textContent = "▶️ Power On / Resume Spidy Bot";
            powerBtn.style.borderColor = "var(--emerald-neon)";
            powerBtn.style.color = "var(--emerald-neon)";
        }
    } else if (activeTrade && (activeTrade.trade_status === "WAITING" || activeTrade.trade_status === "ACTIVE")) {
        if (lockDot) lockDot.className = "status-dot amber";
        if (lockText) lockText.textContent = `LOCKED (${activeTrade.coin})`;
        if (powerBtn) {
            powerBtn.textContent = "🛑 Power Off / Pause Spidy Bot";
            powerBtn.style.borderColor = "var(--rose-neon)";
            powerBtn.style.color = "var(--rose-neon)";
        }
    } else {
        if (lockDot) lockDot.className = "status-dot green";
        if (lockText) lockText.textContent = "SLOT OPEN (0/1)";
        if (standbyDot) standbyDot.className = "status-dot green";
        if (standbyTitle) {
            standbyTitle.textContent = "GLOBAL SLOT OPEN (0/1)";
            standbyTitle.style.color = "var(--emerald-neon)";
        }
        if (standbyDesc) {
            standbyDesc.textContent = "24/7 Institutional Scanner Active Across 6 Delta Exchange India Markets";
        }
        if (powerBtn) {
            powerBtn.textContent = "🛑 Power Off / Pause Spidy Bot";
            powerBtn.style.borderColor = "var(--rose-neon)";
            powerBtn.style.color = "var(--rose-neon)";
        }
    }

    // Render Dedicated Active Trade War Room Banner
    renderActiveTradeWarRoom(activeTrade);

    // Refresh tactical panel for currently selected coin
    fetchCoinAnalysis(currentSymbol);

    if (data.model_stats) {
        renderModelStats(data.model_stats);
    }

    if (data.history) {
        renderHistoryTable(data.history);
    }
}

function updatePrice(symbol, price, isStale, connStatus) {
    const priceEl = document.getElementById(`price-${symbol}`);
    if (priceEl && price > 0) {
        if (symbol === "XRPUSD") {
            priceEl.textContent = price.toFixed(4);
        } else if (price >= 1000) {
            priceEl.textContent = price.toLocaleString('en-US', {minimumFractionDigits: 1, maximumFractionDigits: 2});
        } else {
            priceEl.textContent = price.toFixed(2);
        }
    }
    const statusEl = document.getElementById(`status-${symbol}`);
    if (statusEl) {
        if (isStale) {
            statusEl.textContent = "STALE DATA";
            statusEl.style.color = "var(--rose-neon)";
        } else if (activeTrade && activeTrade.coin === symbol && (activeTrade.trade_status === "ACTIVE" || activeTrade.trade_status === "WAITING")) {
            statusEl.textContent = `🚨 IN TRADE (${activeTrade.direction})`;
            statusEl.style.color = activeTrade.direction === "LONG" ? "var(--emerald-neon)" : "var(--rose-neon)";
        } else {
            statusEl.textContent = "SCANNING";
            statusEl.style.color = "var(--emerald-neon)";
        }
    }
    if (activeTrade && activeTrade.coin === symbol) {
        renderActiveTradeWarRoom(activeTrade);
    }
    if (symbol === currentSymbol) {
        drawChart();
    }
}

function renderTacticalPanel(data) {
    if (!data || data.error) return;

    const sym = data.symbol;
    document.getElementById("trade-badge-coin").textContent = sym;

    const modeEl = document.getElementById("trade-coin-mode");
    if (data.is_active_trade) {
        modeEl.textContent = "LOCKED ACTIVE TRADE";
        modeEl.style.color = "var(--amber-neon)";
        modeEl.style.borderColor = "var(--amber-neon)";
        modeEl.style.background = "rgba(245, 158, 11, 0.15)";
    } else {
        modeEl.textContent = "LIVE COIN ANALYSIS";
        modeEl.style.color = "var(--cyan-neon)";
        modeEl.style.borderColor = "var(--cyan-neon)";
        modeEl.style.background = "rgba(0, 240, 255, 0.15)";
    }

    // Direction & Status
    const dirEl = document.getElementById("trade-direction-badge");
    dirEl.textContent = data.direction;
    dirEl.className = `direction-badge ${data.direction}`;

    const stEl = document.getElementById("trade-status-badge");
    stEl.textContent = data.status;

    document.getElementById("trade-model-badge").textContent = data.model_name;

    // Confirmations & Score
    document.getElementById("conf-badge-pill").textContent = `CONFIRMATIONS: ${data.confirmations_count}/7`;
    document.getElementById("score-number").textContent = data.score;

    // Grade & Policy Badges
    const gradeBadge = document.getElementById("trade-grade-badge");
    if (gradeBadge) {
        const gr = data.grade || "A+";
        gradeBadge.textContent = gr === "A+" ? "🌟 GRADE: A+" : "⚡ GRADE: B+";
        gradeBadge.style.color = gr === "A+" ? "var(--emerald-neon)" : "var(--amber-neon)";
        gradeBadge.style.borderColor = gr === "A+" ? "rgba(0,255,163,0.4)" : "rgba(245,158,11,0.4)";
        gradeBadge.style.background = gr === "A+" ? "rgba(0,255,163,0.15)" : "rgba(245,158,11,0.15)";
    }

    const policyBadge = document.getElementById("trade-policy-badge");
    if (policyBadge) {
        policyBadge.textContent = data.policy || (data.grade === "B+" ? "Strict Risk (Tight SL / Quick 1.4R TP)" : "Institutional Conviction");
    }

    // Dealing Range (Premium vs Discount) & Displacement
    if (data.dealing_range) {
        const dr = data.dealing_range;
        const rangeEl = document.getElementById("val-range-span");
        if (rangeEl) rangeEl.textContent = `[${dr.range_low.toFixed(1)} - ${dr.range_high.toFixed(1)}]`;

        const eqEl = document.getElementById("val-eq-price");
        if (eqEl) eqEl.textContent = dr.equilibrium.toFixed(1);

        const pdEl = document.getElementById("val-pd-zone");
        if (pdEl) {
            pdEl.textContent = `${dr.zone} (${(dr.current_position_pct * 100).toFixed(0)}%)`;
            pdEl.style.color = dr.zone.includes("DISCOUNT") ? "var(--emerald-neon)" : (dr.zone.includes("PREMIUM") ? "var(--rose-neon)" : "var(--cyan-neon)");
        }
    }

    if (data.displacement) {
        const dispEl = document.getElementById("val-displacement");
        if (dispEl) {
            dispEl.textContent = data.displacement.detected ? `DETECTED (${(data.displacement.body_ratio * 100).toFixed(0)}% body, ${data.displacement.expansion_ratio}x)` : "Normal";
            dispEl.style.color = data.displacement.detected ? "var(--emerald-neon)" : "var(--text-muted)";
        }
    }

    // Dynamic Levels tailored to this coin: ONLY when active trade is open!
    if (data.is_active_trade && data.levels) {
        document.getElementById("val-entry").textContent = formatPrice(sym, data.levels.entry);
        document.getElementById("val-stop").textContent = formatPrice(sym, data.levels.stop_loss);
        document.getElementById("val-t1").textContent = formatPrice(sym, data.levels.target_1);
        document.getElementById("val-t2").textContent = formatPrice(sym, data.levels.target_2);
        document.getElementById("val-margin").textContent = data.levels.margin || "₹3,000 Margin (6x Lev)";
    } else {
        document.getElementById("val-entry").textContent = "--";
        document.getElementById("val-stop").textContent = "--";
        document.getElementById("val-t1").textContent = "--";
        document.getElementById("val-t2").textContent = "--";
        document.getElementById("val-margin").textContent = "Idle (₹3,000 Margin @ 6x)";
    }

    // Delta Exchange India Point Value Telemetry
    const ptValEl = document.getElementById("val-point-value");
    if (ptValEl) {
        if (data.delta_telemetry) {
            const dt = data.delta_telemetry;
            const inrVal = Number(dt.point_value_inr || dt.inr_per_point || 0);
            ptValEl.textContent = `${dt.point_label} = ±₹${inrVal.toFixed(2)}`;
            ptValEl.title = `Delta Spec: ${dt.delta_contracts} ${dt.contract_unit} | Notional: ₹${Math.round(dt.notional_inr || 0).toLocaleString('en-IN')} ($${Math.round(dt.notional_usd || 0)})`;
        } else {
            ptValEl.textContent = "--";
        }
    }

    // Dynamic Progression Bar (reflects exact progression of this coin!)
    const progContainer = document.getElementById("progression-bar");
    if (progContainer && data.progression_steps) {
        progContainer.innerHTML = "";
        data.progression_steps.forEach((step, idx) => {
            const stepDiv = document.createElement("div");
            let cls = "prog-step";
            if (step.passed) {
                cls += " passed";
            } else if (idx === 0 || (data.progression_steps[idx - 1] && data.progression_steps[idx - 1].passed)) {
                cls += " active";
            }
            stepDiv.className = cls;
            stepDiv.textContent = step.label;
            stepDiv.title = step.desc || "";
            progContainer.appendChild(stepDiv);

            if (idx < data.progression_steps.length - 1) {
                const arrow = document.createElement("span");
                arrow.className = "prog-arrow";
                arrow.textContent = "▶";
                progContainer.appendChild(arrow);
            }
        });
    }

    // Setup Reasoning
    const reasonsContainer = document.getElementById("reasoning-container");
    reasonsContainer.innerHTML = "";
    if (data.reasons && Array.isArray(data.reasons)) {
        data.reasons.forEach(r => {
            const div = document.createElement("div");
            div.className = "reason-item";
            div.innerHTML = `<span class="highlight">▶</span> ${r}`;
            reasonsContainer.appendChild(div);
        });
    }

    drawChart();
}

function renderModelStats(stats) {
    const tbody = document.getElementById("model-stats-tbody");
    if (!tbody) return;
    tbody.innerHTML = "";

    stats.forEach(s => {
        const tr = document.createElement("tr");
        const rColor = s.total_r >= 0 ? "var(--emerald-neon)" : "var(--rose-neon)";
        tr.innerHTML = `
            <td style="font-weight:600; color:#fff;" title="${s.model_name}">${s.model_id}</td>
            <td>${s.trades_count}</td>
            <td style="color:${s.win_rate >= 50 ? 'var(--emerald-neon)' : 'var(--amber-neon)'}; font-weight:700;">${s.win_rate}%</td>
            <td style="color:${rColor}; font-weight:700;">${s.total_r > 0 ? '+' : ''}${s.total_r.toFixed(1)}R</td>
            <td>${s.profit_factor.toFixed(2)}</td>
        `;
        tbody.appendChild(tr);
    });
}

function renderHistoryTable(items) {
    const tbody = document.getElementById("history-tbody");
    if (!tbody) return;
    tbody.innerHTML = "";

    if (!items || items.length === 0) {
        tbody.innerHTML = `<tr><td colspan="11" style="text-align:center; color:var(--text-muted);">No setups recorded yet.</td></tr>`;
        return;
    }

    items.slice(0, 35).forEach(item => {
        const tr = document.createElement("tr");
        const dt = new Date(item.detection_timestamp * 1000).toLocaleTimeString();

        let statusBadge = `<span style="color:var(--cyan-neon);">${item.trade_status}</span>`;
        if (item.trade_status === "BLOCKED BY ACTIVE TRADE") {
            statusBadge = `<span style="color:var(--amber-neon);">BLOCKED</span>`;
        } else if (item.trade_status === "COMPLETED" || item.trade_status === "TARGET HIT") {
            statusBadge = `<span style="color:var(--emerald-neon);">${item.trade_status}</span>`;
        } else if (item.trade_status === "STOPPED" || item.trade_status === "CANCELLED") {
            statusBadge = `<span style="color:var(--rose-neon);">${item.trade_status}</span>`;
        }

        const dirColor = item.direction === "LONG" ? "var(--emerald-neon)" : "var(--rose-neon)";
        const confText = item.confirmations_count ? `${item.confirmations_count}/7` : "-";

        tr.innerHTML = `
            <td>${dt}</td>
            <td style="font-weight:700; color:#fff;">${item.coin}</td>
            <td style="font-size:11px; color:var(--cyan-neon);">${item.model_id || 'M1'}</td>
            <td style="color:${dirColor}; font-weight:700;">${item.direction}</td>
            <td><strong style="color:var(--cyan-neon);">${item.setup_score}</strong>/100</td>
            <td style="color:var(--purple-neon); font-weight:700;">${confText}</td>
            <td>${item.entry ? formatPrice(item.coin, item.entry) : '-'}</td>
            <td>${item.stop_loss ? formatPrice(item.coin, item.stop_loss) : '-'}</td>
            <td>1:${item.rr ? item.rr.toFixed(1) : '-'}</td>
            <td>${statusBadge}</td>
            <td style="font-size:11px; max-width:200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${item.rejection_reason || item.final_result || ''}">
                ${item.rejection_reason || item.final_result || 'Qualified setup'}
            </td>
        `;
        tbody.appendChild(tr);
    });
}

function drawChart() {
    const canvas = document.getElementById("chart-canvas");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");

    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * window.devicePixelRatio;
    canvas.height = rect.height * window.devicePixelRatio;
    ctx.scale(window.devicePixelRatio, window.devicePixelRatio);

    const w = rect.width;
    const h = rect.height;

    ctx.clearRect(0, 0, w, h);

    if (!currentCandles || currentCandles.length === 0) {
        ctx.fillStyle = "rgba(255,255,255,0.2)";
        ctx.font = "13px monospace";
        ctx.textAlign = "center";
        ctx.fillText(`Loading ${currentSymbol} ${currentResolution.toUpperCase()} candles...`, w / 2, h / 2);
        return;
    }

    const candles = currentCandles.slice(-40);
    const n = candles.length;
    let minPrice = Math.min(...candles.map(c => c.low));
    let maxPrice = Math.max(...candles.map(c => c.high));

    const coinData = coinAnalysisData[currentSymbol];
    if (coinData && coinData.levels && coinData.is_active_trade) {
        minPrice = Math.min(minPrice, coinData.levels.stop_loss, coinData.levels.entry);
        maxPrice = Math.max(maxPrice, coinData.levels.target_2, coinData.levels.entry);
    }

    const pad = (maxPrice - minPrice) * 0.1 || 1.0;
    minPrice -= pad;
    maxPrice += pad;
    const priceRange = maxPrice - minPrice;

    function getY(p) {
        return h - ((p - minPrice) / priceRange) * (h - 40) - 20;
    }

    // Grid lines
    ctx.strokeStyle = "rgba(255,255,255,0.05)";
    ctx.lineWidth = 1;
    for (let i = 1; i <= 4; i++) {
        const y = (h / 5) * i;
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
        ctx.stroke();
    }

    const candleWidth = Math.max(3, (w - 60) / n - 3);

    candles.forEach((c, idx) => {
        const x = 30 + idx * ((w - 60) / n);
        const yOpen = getY(c.open);
        const yClose = getY(c.close);
        const yHigh = getY(c.high);
        const yLow = getY(c.low);

        const isGreen = c.close >= c.open;
        ctx.strokeStyle = isGreen ? "#10b981" : "#f43f5e";
        ctx.fillStyle = isGreen ? "#10b981" : "#f43f5e";

        ctx.lineWidth = 1.2;
        ctx.beginPath();
        ctx.moveTo(x, yHigh);
        ctx.lineTo(x, yLow);
        ctx.stroke();

        const bodyTop = Math.min(yOpen, yClose);
        const bodyHeight = Math.max(2, Math.abs(yOpen - yClose));
        ctx.fillRect(x - candleWidth / 2, bodyTop, candleWidth, bodyHeight);
    });

    // Draw technical levels ONLY if an active/waiting trade is open on this coin!
    if (coinData && coinData.levels && coinData.is_active_trade) {
        const lvls = coinData.levels;
        const dec = currentSymbol === "XRPUSD" ? 4 : 2;
        drawHLine(ctx, w, getY(lvls.entry), "#00f0ff", `ENTRY: ${lvls.entry.toFixed(dec)}`);
        drawHLine(ctx, w, getY(lvls.stop_loss), "#f43f5e", `STOP: ${lvls.stop_loss.toFixed(dec)}`);
        drawHLine(ctx, w, getY(lvls.target_1), "#10b981", `T1: ${lvls.target_1.toFixed(dec)}`);
        drawHLine(ctx, w, getY(lvls.target_2), "#34d399", `T2: ${lvls.target_2.toFixed(dec)}`);
    }
}

function drawHLine(ctx, w, y, color, label) {
    ctx.strokeStyle = color;
    ctx.setLineDash([4, 4]);
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(30, y);
    ctx.lineTo(w - 30, y);
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.fillStyle = color;
    ctx.font = "10px monospace";
    ctx.textAlign = "right";
    ctx.fillText(label, w - 35, y - 4);
}

async function triggerScan() {
    const btn = document.getElementById("btn-scan");
    const box = document.getElementById("scan-result-box");
    const content = document.getElementById("scan-result-content");

    if (btn) {
        btn.disabled = true;
        btn.textContent = "⏳ Scanning 9 Models Across Markets...";
        btn.style.borderColor = "var(--amber-neon)";
        btn.style.color = "var(--amber-neon)";
    }
    if (box) {
        box.style.display = "block";
        content.innerHTML = "<em>Querying Delta Exchange live feeds & evaluating 27 model checks...</em>";
    }

    try {
        const res = await fetch("/api/trigger_scan", { method: "POST" });
        const data = await res.json();
        
        if (box && data.results) {
            let html = `<div style="margin-bottom:6px; color:#fff;">${data.message}</div>`;
            html += `<table style="width:100%; font-size:10px; border-collapse:collapse;">`;
            data.results.forEach(r => {
                html += `<tr style="border-bottom:1px solid rgba(255,255,255,0.05); padding:2px 0;">
                    <td style="font-weight:700; color:var(--cyan-neon); padding:2px 4px;">${r.symbol}:</td>
                    <td style="color:${r.status.includes('QUALIFIED') ? 'var(--emerald-neon)' : 'var(--text-secondary)'}; padding:2px 4px;">${r.status}</td>
                    <td style="color:var(--purple-neon); padding:2px 4px;">${r.confirmations}</td>
                    <td style="color:var(--text-muted); padding:2px 4px;">${r.best_model}</td>
                </tr>`;
            });
            html += `</table>`;
            content.innerHTML = html;
        }

        fetchStatus();
        fetchCoinAnalysis(currentSymbol);
    } catch (e) {
        if (content) content.textContent = "Scan error: " + e;
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = "⚡ Trigger Market Scan (9 Models) ✓";
            btn.style.borderColor = "var(--cyan-neon)";
            btn.style.color = "#fff";
            setTimeout(() => {
                btn.textContent = "⚡ Trigger Market Scan (9 Models)";
            }, 2500);
        }
    }
}

// ==========================================
// 4-DIGIT ADMIN PIN SECURITY SYSTEM (PIN: 1408)
// ==========================================
let pendingPinAction = null;

function getStoredPin() {
    return sessionStorage.getItem("spidy_admin_pin") || "";
}

function setStoredPin(pin) {
    if (pin) {
        sessionStorage.setItem("spidy_admin_pin", pin);
        updateSecurityBadge(true);
    } else {
        sessionStorage.removeItem("spidy_admin_pin");
        updateSecurityBadge(false);
    }
}

function updateSecurityBadge(unlocked) {
    const icon = document.getElementById("security-lock-icon");
    const txt = document.getElementById("security-status-text");
    if (icon && txt) {
        if (unlocked) {
            icon.textContent = "🔓";
            txt.textContent = "ADMIN UNLOCKED";
            txt.style.color = "var(--emerald-neon)";
        } else {
            icon.textContent = "🔒";
            txt.textContent = "PIN LOCKED";
            txt.style.color = "var(--amber-neon)";
        }
    }
}

async function verifyPinWithServer(pin) {
    try {
        const res = await fetch("/api/verify_pin", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ pin: pin })
        });
        return res.ok;
    } catch (e) {
        console.error("PIN verification error", e);
        return false;
    }
}

function openPinModal(onSuccess) {
    pendingPinAction = onSuccess;
    const modal = document.getElementById("pin-modal");
    const input = document.getElementById("pin-input");
    const errMsg = document.getElementById("pin-error-msg");
    if (modal && input) {
        modal.style.display = "flex";
        input.value = "";
        if (errMsg) errMsg.textContent = "";
        setTimeout(() => input.focus(), 50);
    }
}

function closePinModal() {
    const modal = document.getElementById("pin-modal");
    if (modal) modal.style.display = "none";
    pendingPinAction = null;
}

async function submitPinAuth() {
    const input = document.getElementById("pin-input");
    const errMsg = document.getElementById("pin-error-msg");
    const pin = (input ? input.value : "").trim();
    if (!pin) {
        if (errMsg) errMsg.textContent = "Please enter 4-digit PIN";
        return;
    }

    const isValid = await verifyPinWithServer(pin);
    if (isValid) {
        setStoredPin(pin);
        const action = pendingPinAction;
        closePinModal();
        if (action) action(pin);
    } else {
        if (errMsg) errMsg.textContent = "❌ Invalid PIN. Access Denied.";
        if (input) {
            input.value = "";
            input.focus();
        }
    }
}

function requireAdminPin(action) {
    const stored = getStoredPin();
    if (stored) {
        action(stored);
    } else {
        openPinModal(action);
    }
}

async function releaseActiveTradeLock() {
    if (!confirm("Are you sure you want to command SPIDY to stop and close the active trade?")) {
        return;
    }
    requireAdminPin(async (pin) => {
        try {
            const res = await fetch("/api/close_active_trade", {
                method: "POST",
                headers: { "X-Admin-PIN": pin }
            });
            if (res.status === 401) {
                setStoredPin("");
                alert("❌ Unauthorized: Invalid Admin PIN. Please authenticate.");
                openPinModal(() => releaseActiveTradeLock());
                return;
            }
            const data = await res.json();
            fetchStatus();
            fetchCoinAnalysis(currentSymbol);
            alert(data.message || "Active trade lock released.");
        } catch (e) {
            console.error("Release lock error", e);
        }
    });
}

let lastBacktestByMarket = null;

async function runBacktest() {
    const box = document.getElementById("backtest-summary-box");
    const content = document.getElementById("backtest-summary-content");
    box.style.display = "block";
    content.innerHTML = `<em>Running event-driven institutional backtest for <strong>${currentSymbol}</strong> & portfolio...</em>`;

    try {
        const res = await fetch(`/api/backtest/run?symbol=${currentSymbol}`, { method: "POST" });
        const data = await res.json();
        if (data.metrics) {
            const m = data.metrics;
            lastBacktestByMarket = data.by_market;
            const rColor = m.total_r_gain >= 0 ? "var(--emerald-neon)" : "var(--rose-neon)";

            let html = `
                <div style="font-size:12px; margin-bottom:4px;">
                    <strong style="color:var(--cyan-neon);">[ ${data.selected_symbol} BACKTEST ]:</strong>
                    Trades: <strong>${m.total_trades}</strong> | 
                    Win Rate: <strong style="color:var(--emerald-neon)">${m.win_rate}%</strong> | 
                    Expectancy: <strong>${m.expectancy}R</strong> | 
                    Profit Factor: <strong>${m.profit_factor}</strong> | 
                    Total Gain: <strong style="color:${rColor}">${m.total_r_gain > 0 ? '+' : ''}${m.total_r_gain}R</strong> | 
                    Max DD: <strong>${m.max_drawdown_r}R</strong>
                </div>
            `;

            if (data.by_market && Object.keys(data.by_market).length > 0) {
                html += `<div style="margin-top:6px; display:flex; flex-wrap:wrap; gap:12px; font-size:10px; border-top:1px solid rgba(255,255,255,0.1); padding-top:6px;">`;
                for (const [sym, bm] of Object.entries(data.by_market)) {
                    const bmColor = bm.total_r >= 0 ? "var(--emerald-neon)" : "var(--rose-neon)";
                    const isSelected = sym === currentSymbol;
                    html += `
                        <div style="${isSelected ? 'background:rgba(0,240,255,0.15); padding:2px 6px; border-radius:4px; border:1px solid var(--cyan-neon);' : ''}">
                            <strong style="color:${isSelected ? 'var(--cyan-neon)' : '#fff'};">${sym}:</strong> 
                            ${bm.trades} trds | 
                            WR: <strong style="color:var(--emerald-neon);">${bm.win_rate}%</strong> | 
                            Gain: <strong style="color:${bmColor};">${bm.total_r > 0 ? '+' : ''}${bm.total_r}R</strong> | 
                            PF: ${bm.profit_factor}
                        </div>
                    `;
                }
                html += `</div>`;
            }

            content.innerHTML = html;

            // Immediately hydrate Model Performance Tracking with REAL, non-zero stats
            if (data.model_stats) {
                renderModelStats(data.model_stats);
            }
        }
    } catch (e) {
        content.textContent = "Error executing backtest: " + e;
    }
}

async function runValidation() {
    const box = document.getElementById("backtest-summary-box");
    const content = document.getElementById("backtest-summary-content");
    box.style.display = "block";
    content.innerHTML = `<em>Running In-Sample (70%) vs Out-of-Sample (30%) validation for <strong>${currentSymbol}</strong>...</em>`;

    try {
        const res = await fetch(`/api/backtest/validate?symbol=${currentSymbol}`, { method: "POST" });
        const data = await res.json();
        if (data.retention) {
            content.innerHTML = `
                <div style="font-size:12px; margin-bottom:4px;">
                    <strong style="color:var(--cyan-neon);">[ ${data.selected_symbol} VALIDATION ]:</strong>
                    In-Sample Trades: <strong>${data.in_sample_trades}</strong> (WR: <strong style="color:var(--emerald-neon);">${data.in_sample_metrics.win_rate}%</strong>)<br>
                    Out-of-Sample Trades: <strong>${data.out_of_sample_trades}</strong> (WR: <strong style="color:var(--emerald-neon);">${data.out_of_sample_metrics.win_rate}%</strong>)<br>
                    Win Rate Retention: <strong>${data.retention.win_rate_retention_pct}%</strong> | 
                    Robust Institutional Edge: <strong style="color:${data.is_robust ? 'var(--emerald-neon)' : 'var(--amber-neon)'}">${data.is_robust ? 'CONFIRMED' : 'REFINING'}</strong>
                </div>
            `;
        }
    } catch (e) {
        content.textContent = "Error executing validation: " + e;
    }
}

async function simulateSetup(dir) {
    requireAdminPin(async (pin) => {
        try {
            const modelEl = document.getElementById("select-test-model");
            const modelId = modelEl ? modelEl.value : "MODEL_7";
            const res = await fetch(`/api/simulate_setup?symbol=${currentSymbol}&direction=${dir}&model_id=${modelId}&force=true`, {
                method: "POST",
                headers: { "X-Admin-PIN": pin }
            });
            if (res.status === 401) {
                setStoredPin("");
                alert("❌ Unauthorized: Invalid Admin PIN. Please authenticate.");
                openPinModal(() => simulateSetup(dir));
                return;
            }
            await res.json();
            fetchStatus();
            fetchCoinAnalysis(currentSymbol);
        } catch (e) {
            console.error("Simulation error", e);
        }
    });
}

function renderActiveTradeWarRoom(at) {
    const banner = document.getElementById("global-active-trade-banner");
    const standby = document.getElementById("global-standby-banner");
    if (!banner || !standby) return;

    if (!at || (at.trade_status !== "ACTIVE" && at.trade_status !== "WAITING")) {
        banner.style.display = "none";
        standby.style.display = "flex";
        const activeNotice = document.getElementById("tactical-active-notice");
        if (activeNotice) activeNotice.style.display = "none";
        document.querySelectorAll(".market-card").forEach(c => {
            c.classList.remove("in-trade");
            const sym = c.dataset.symbol;
            const stEl = document.getElementById(`status-${sym}`);
            if (stEl) {
                stEl.textContent = "SCANNING";
                stEl.style.color = "var(--emerald-neon)";
            }
        });
        return;
    }

    // Active trade is LIVE!
    banner.style.display = "flex";
    standby.style.display = "none";

    const sym = at.coin;
    const dir = (at.direction || "LONG").toUpperCase();
    const entry = Number(at.entry || 0);
    const sl = Number(at.stop_loss || 0);
    const t1 = Number(at.target_1 || 0);
    const t2 = Number(at.target_2 || 0);
    const margin = Number(at.margin_used || 3000);
    const lev = Number(at.leverage || 6);

    // Header badge group
    const dirBadge = document.getElementById("wt-coin-dir");
    if (dirBadge) {
        dirBadge.textContent = `${sym} ${dir}`;
        dirBadge.className = `war-room-dir-badge ${dir}`;
    }

    const gradeEl = document.getElementById("wt-grade");
    if (gradeEl) gradeEl.textContent = `GRADE: ${at.grade || 'A+'}`;

    const scoreEl = document.getElementById("wt-score");
    if (scoreEl) scoreEl.textContent = `SCORE: ${at.setup_score || 85}/100`;

    const modelEl = document.getElementById("wt-model");
    if (modelEl) modelEl.textContent = at.model_name || "Institutional Strategy";

    // Levels
    const entryEl = document.getElementById("wt-entry");
    if (entryEl) entryEl.textContent = `$${formatPrice(sym, entry)}`;

    const stopEl = document.getElementById("wt-stop");
    if (stopEl) stopEl.textContent = `$${formatPrice(sym, sl)}`;

    const t1El = document.getElementById("wt-t1");
    if (t1El) t1El.textContent = `$${formatPrice(sym, t1)}`;

    const t2El = document.getElementById("wt-t2");
    if (t2El) t2El.textContent = `$${formatPrice(sym, t2)}`;

    const marginEl = document.getElementById("wt-margin");
    if (marginEl) marginEl.textContent = `₹${margin.toLocaleString('en-IN')} (${lev}x)`;

    // Delta Contract Specs & Point Values
    const pointValEl = document.getElementById("wt-point-val");
    const deltaContractsEl = document.getElementById("wt-delta-contracts");
    const pointsMovedEl = document.getElementById("wt-points-moved");

    let ptInr = Number(at.point_val_inr || 0);
    let ptLabel = at.point_label || "1.0 pt";
    let contracts = (at.delta_contracts !== undefined && at.delta_contracts !== null) ? at.delta_contracts : (at.units || "--");
    let cUnit = at.contract_unit || "Lots";

    if (pointValEl) {
        pointValEl.textContent = ptInr > 0 ? `${ptLabel} = ±₹${ptInr.toFixed(2)}` : "--";
    }
    if (deltaContractsEl) {
        deltaContractsEl.textContent = `${contracts} ${cUnit}`;
    }

    // Live Mark & Real-time Dynamic PnL calculation
    let liveP = (marketStates[sym] && marketStates[sym].current_price) ? Number(marketStates[sym].current_price) : (Number(at.current_price) || entry);
    const markEl = document.getElementById("wt-mark");
    if (markEl) markEl.textContent = `$${formatPrice(sym, liveP)}`;

    let priceDiff = dir === "LONG" ? (liveP - entry) : (entry - liveP);
    let pointsMoved = priceDiff;
    let ptsSign = pointsMoved >= 0 ? "+" : "";
    let ptsFormatted = sym === "XRPUSD" ? pointsMoved.toFixed(4) : (Math.abs(pointsMoved) >= 100 ? pointsMoved.toFixed(1) : pointsMoved.toFixed(2));

    if (pointsMovedEl) {
        pointsMovedEl.textContent = `${ptsSign}${ptsFormatted} pts`;
        pointsMovedEl.style.color = pointsMoved >= 0 ? "var(--emerald-neon)" : "var(--rose-neon)";
    }

    // Exact PnL using Delta Exchange point value formula
    let pnlInr = ptInr > 0 ? (pointsMoved * ptInr) : (margin * ((entry > 0 ? priceDiff / entry : 0) * lev));
    let pnlPct = margin > 0 ? (pnlInr / margin) * 100 : 0;
    let riskDist = Math.abs(entry - sl);
    let achR = riskDist > 0 ? (priceDiff / riskDist) : 0;

    let pnlSign = pnlInr >= 0 ? "+" : "";
    let pnlColor = pnlInr >= 0 ? "var(--emerald-neon)" : "var(--rose-neon)";

    const pnlEl = document.getElementById("wt-pnl");
    if (pnlEl) {
        pnlEl.textContent = `${pnlSign}₹${pnlInr.toFixed(2)} (${pnlSign}${pnlPct.toFixed(2)}%)`;
        pnlEl.style.color = pnlColor;
    }

    const rEl = document.getElementById("wt-r");
    if (rEl) {
        rEl.textContent = `${pnlSign}${achR.toFixed(2)}R`;
        rEl.style.color = pnlColor;
    }

    // Highlight card in market strip: ONLY the active coin gets in-trade badge!
    document.querySelectorAll(".market-card").forEach(c => {
        const cardSym = c.dataset.symbol;
        const stEl = document.getElementById(`status-${cardSym}`);
        if (cardSym === sym) {
            c.classList.add("in-trade");
            if (stEl) {
                stEl.textContent = `🚨 IN TRADE (${dir})`;
                stEl.style.color = dir === "LONG" ? "var(--emerald-neon)" : "var(--rose-neon)";
            }
        } else {
            c.classList.remove("in-trade");
            if (stEl) {
                stEl.textContent = "SCANNING";
                stEl.style.color = "var(--emerald-neon)";
            }
        }
    });

    // Auto-focus on active trade coin if a new trade was opened
    if (at.setup_id && at.setup_id !== lastActiveTradeId) {
        lastActiveTradeId = at.setup_id;
        userManuallySelectedSymbol = false;
        selectSymbol(sym);
    } else if (!userManuallySelectedSymbol && currentSymbol !== sym) {
        selectSymbol(sym);
    }

    // Update contextual banner if previewing another coin
    const activeNotice = document.getElementById("tactical-active-notice");
    if (activeNotice) {
        if (currentSymbol !== sym) {
            activeNotice.style.display = "flex";
            const cEl = document.getElementById("tactical-notice-coin");
            const dEl = document.getElementById("tactical-notice-dir");
            const vEl = document.getElementById("tactical-notice-viewing");
            if (cEl) cEl.textContent = sym;
            if (dEl) {
                dEl.textContent = `(${dir})`;
                dEl.style.color = dir === "LONG" ? "var(--emerald-neon)" : "var(--rose-neon)";
            }
            if (vEl) vEl.textContent = currentSymbol;
        } else {
            activeNotice.style.display = "none";
        }
    }
}

async function triggerBreakeven() {
    requireAdminPin(async (pin) => {
        try {
            const res = await fetch("/api/breakeven", {
                method: "POST",
                headers: { "X-Admin-PIN": pin }
            });
            if (res.status === 401) {
                setStoredPin("");
                alert("❌ Unauthorized: Invalid Admin PIN. Please authenticate.");
                openPinModal(() => triggerBreakeven());
                return;
            }
            const data = await res.json();
            alert(data.message || "Breakeven applied.");
            fetchStatus();
        } catch (e) {
            console.error("Breakeven error", e);
        }
    });
}

async function triggerPartial() {
    requireAdminPin(async (pin) => {
        try {
            const res = await fetch("/api/partial", {
                method: "POST",
                headers: { "X-Admin-PIN": pin }
            });
            if (res.status === 401) {
                setStoredPin("");
                alert("❌ Unauthorized: Invalid Admin PIN. Please authenticate.");
                openPinModal(() => triggerPartial());
                return;
            }
            const data = await res.json();
            alert(data.message || "Partial profit secured.");
            fetchStatus();
        } catch (e) {
            console.error("Partial error", e);
        }
    });
}

async function toggleBotPower() {
    const powerBtn = document.getElementById("btn-power-toggle");
    const isPaused = powerBtn && powerBtn.textContent.includes("Resume");
    const endpoint = isPaused ? "/api/resume" : "/api/pause";
    requireAdminPin(async (pin) => {
        try {
            if (powerBtn) powerBtn.disabled = true;
            const res = await fetch(endpoint, {
                method: "POST",
                headers: { "X-Admin-PIN": pin }
            });
            if (res.status === 401) {
                setStoredPin("");
                alert("❌ Unauthorized: Invalid Admin PIN. Please authenticate.");
                openPinModal(() => toggleBotPower());
                return;
            }
            const data = await res.json();
            alert(data.message || "State updated.");
            await fetchStatus();
        } catch (e) {
            console.error("Power toggle error", e);
        } finally {
            if (powerBtn) powerBtn.disabled = false;
        }
    });
}

