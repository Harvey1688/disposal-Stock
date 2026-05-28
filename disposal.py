import datetime
import math
import pandas as pd
import requests
import streamlit as st
import yfinance as yf

# 設定網頁標題與風格
st.set_page_config(page_title="精品法規注意股監控盤", layout="wide")

# 注入高級感監控盤專用 CSS 樣式表 (控制字體與間距，防止巨大重疊或過於樸素)
st.markdown("""
<style>
    .reportview-container .main .block-container{ max-width: 95%; padding-top: 1.5rem; }
    .stMetric { background-color: #f8f9fa; padding: 10px 15px; border-radius: 6px; border: 1px solid #eaeaea; }
    .status-card { padding: 12px 18px; border-radius: 6px; margin-bottom: 15px; font-size: 14px; }
    .danger-card { background-color: #fff5f5; border-left: 5px solid #ff4d4f; color: #ff4d4f; }
    .success-card { background-color: #f6ffed; border-left: 5px solid #52c41a; color: #52c41a; }
    .future-box { background-color: #fafafa; border: 1px solid #f0f0f0; border-radius: 6px; padding: 15px; margin-bottom: 10px; }
    .bullet-title { font-weight: bold; color: #262626; margin-top: 5px; font-size: 14px; }
    .bullet-item { font-size: 13px; color: #595959; margin-left: 10px; margin-bottom: 3px; }
    .highlight-red { color: #ff4d4f; font-weight: bold; }
    .highlight-green { color: #52c41a; font-weight: bold; }
</style>
""", unsafe_allow_html=True)


def truncate_2_decimals(n):
    """將數字無條件捨去至小數點後第二位 (台股法規計算核心)"""
    if n >= 0:
        return math.floor(n * 100) / 100
    else:
        return math.ceil(n * 100) / 100


def calculate_limit_up(price):
    """精確計算台股漲停價 (考慮 Tick Size)"""
    raw_limit_up = price * 1.1
    if raw_limit_up < 10: tick = 0.01
    elif raw_limit_up < 50: tick = 0.05
    elif raw_limit_up < 100: tick = 0.1
    elif raw_limit_up < 500: tick = 0.5
    elif raw_limit_up < 1000: tick = 1.0
    else: tick = 5.0
    eps = 1e-9
    limit_up_price = math.floor((raw_limit_up + eps) / tick) * tick
    return round(limit_up_price, 2)


def calculate_limit_down(price):
    """精確計算台股跌停價"""
    raw_limit_down = price * 0.9
    if raw_limit_down <= 10: tick = 0.01
    elif raw_limit_down <= 50: tick = 0.05
    elif raw_limit_down <= 100: tick = 0.1
    elif raw_limit_down <= 500: tick = 0.5
    elif raw_limit_down <= 1000: tick = 1.0
    else: tick = 5.0
    eps = 1e-9
    limit_down_price = math.ceil((raw_limit_down - eps) / tick) * tick
    return round(limit_down_price, 2)


def get_next_business_days(start_date_str, count=5):
    """115年市場開休市交易行事曆智慧過濾"""
    twse_holidays = {
        "2026-01-01", "2026-02-12", "2026-02-13", "2026-02-16", "2026-02-17", 
        "2026-02-18", "2026-02-19", "2026-02-20", "2026-02-27", "2026-04-03", 
        "2026-04-06", "2026-05-01", "2026-06-19", "2026-09-25", "2026-09-28", 
        "2026-10-09", "2026-10-26", "2026-12-25"
    }
    start_date = datetime.datetime.strptime(start_date_str, "%Y-%m-%d").date()
    business_days = []
    current_date = start_date
    while len(business_days) < count:
        current_date += datetime.timedelta(days=1)
        date_iso = current_date.strftime("%Y-%m-%d")
        if current_date.weekday() < 5 and date_iso not in twse_holidays:
            weekday_cc = ["一", "二", "三", "四", "五", "六", "日"]
            business_days.append(f"{current_date.strftime('%m/%d')} (星期{weekday_cc[current_date.weekday()]})")
    return business_days


def get_tick_size(price):
    """取得台股該價格區間的 Tick Size"""
    if price < 10: return 0.01
    elif price < 50: return 0.05
    elif price < 100: return 0.1
    elif price < 500: return 0.5
    elif price < 1000: return 1.0
    else: return 5.0


def find_comprehensive_trigger_price(prices_history, dates_history, current_idx):
    """🎯 核心推演引擎：完美對位四大條款，反推明天各款分別需要『精確收盤幾元』才會觸發注意股"""
    p_yesterday = prices_history[current_idx]  # 對明天而言，今天就是前一日價
    
    # --- 1. 第一款 (6日滾動) 反推 ---
    sub_prices_5 = prices_history[current_idx - 4 : current_idx + 1]
    past_returns_truncated = []
    for m in range(4):
        p_prev_temp = sub_prices_5[m]
        p_curr_temp = sub_prices_5[m + 1]
        past_returns_truncated.append(truncate_2_decimals(((p_curr_temp - p_prev_temp) / p_prev_temp) * 100))
    sum_past_5_truncated = sum(past_returns_truncated)
    compare_base_price_6d = prices_history[current_idx - 4]
    
    price_by_spread = compare_base_price_6d + 50.0
    req_this_day_ret = 25.0 - sum_past_5_truncated
    price_by_ret = p_yesterday * (1 + req_this_day_ret / 100.0)
    trigger_6d_raw = max(price_by_spread, price_by_ret)
    tick_6d = get_tick_size(trigger_6d_raw)
    trigger_6d = math.ceil(trigger_6d_raw / tick_6d) * tick_6d
    
    # --- 2. 第二款 (30/60/90日) 起迄反推與下跌豁免咬合 ---
    # 30日 (起迄累積達 100%)
    p_start_30d = prices_history[current_idx - 28] 
    trigger_30d_raw = p_start_30d * 2.0  
    tick_30d = get_tick_size(trigger_30d_raw)
    trigger_30d = math.ceil(trigger_30d_raw / tick_30d) * tick_30d
    if trigger_30d < p_yesterday: trigger_30d = float('inf') # 觸發點比昨天低，代表下跌即可達成，依法豁免不適用
    
    # 60日 (起迄累積達 130%)
    p_start_60d = prices_history[current_idx - 58]
    trigger_60d_raw = p_start_60d * 2.3  
    tick_60d = get_tick_size(trigger_60d_raw)
    trigger_60d = math.ceil(trigger_60d_raw / tick_60d) * tick_60d
    if trigger_60d < p_yesterday: trigger_60d = float('inf')
        
    # 90日 (起迄累積達 160%)
    p_start_90d = prices_history[current_idx - 88]
    trigger_90d_raw = p_start_90d * 2.6  
    tick_90d = get_tick_size(trigger_90d_raw)
    trigger_90d = math.ceil(trigger_90d_raw / tick_90d) * tick_90d
    if trigger_90d < p_yesterday: trigger_90d = float('inf')

    # 四款取最小值，即為明天出事的最低臨界防線
    valid_prices = [trigger_6d, trigger_30d, trigger_60d, trigger_90d]
    final_lowest_trigger = min(valid_prices)
    
    return final_lowest_trigger, trigger_6d, trigger_30d, trigger_60d, trigger_90d


def diagnose_all_regulatory_天書(prices_list, dates_list, target_idx):
    """👑 智慧核心：純粹法規診斷器"""
    is_danger = False
    window_df = pd.DataFrame()
    sum_ret_6d = 0.0
    total_spread_6d = 0.0
    
    long_term_results = {
        "pct_30d": 0.0, "p_start_30d": 0.0, "hit_30d": False, "is_exempt_30d": False,
        "pct_60d": 0.0, "p_start_60d": 0.0, "hit_60d": False, "is_exempt_60d": False,
        "pct_90d": 0.0, "p_start_90d": 0.0, "hit_90d": False, "is_exempt_90d": False
    }
    triggered_rules = []
    exempt_reasons = []

    # 第一款 6 日判定
    if target_idx >= 5:
        sub_prices = prices_list[target_idx - 5 : target_idx + 1] 
        sub_dates = dates_list[target_idx - 5 : target_idx + 1]
        display_returns = []
        is_limit_up_list = []
        is_limit_down_list = []
        
        for k in range(6):
            global_idx = target_idx - 5 + k
            p_prev = prices_list[global_idx - 1]
            p_curr = prices_list[global_idx]
            ret_truncated = truncate_2_decimals(((p_curr - p_prev) / p_prev) * 100)
            display_returns.append(ret_truncated)
            is_limit_up_list.append(abs(p_curr - calculate_limit_up(p_prev)) < 1e-4)
            is_limit_down_list.append(abs(p_curr - calculate_limit_down(p_prev)) < 1e-4)
        
        sum_ret_6d = round(sum(display_returns), 2)
        total_spread_6d = round(sub_prices[-1] - sub_prices[0], 2)
        
        window_df = pd.DataFrame({
            "營業日": sub_dates, "收盤價 (元)": sub_prices,
            "當日漲跌幅": [f"{r:+.2f}%" if r != 0 else "0.00%" for r in display_returns],
            "is_limit_up": is_limit_up_list, "is_limit_down": is_limit_down_list
        })
        if sum_ret_6d >= 25.0 and total_spread_6d >= 50.0:
            triggered_rules.append(f"第一款 (6日滾動增幅 {sum_ret_6d:.2f}% 且起迄價差 {total_spread_6d:.2f}元)")
            is_danger = True

    # 第二款 30/60/90日判定 (融入下跌霸王條款)
    p_target = prices_list[target_idx]
    p_yesterday = prices_list[target_idx - 1] if target_idx >= 1 else p_target
    is_price_dropped = (p_target < p_yesterday)

    # 30日
    if target_idx >= 29:
        p_start_30d = prices_list[target_idx - 29]
        pct_30d = truncate_2_decimals(((p_target - p_start_30d) / p_start_30d) * 100)
        long_term_results["pct_30d"] = pct_30d
        long_term_results["p_start_30d"] = p_start_30d
        if is_price_dropped:
            long_term_results["is_exempt_30d"] = True
            if abs(pct_30d) >= 100.0: exempt_reasons.append("🟢 30日條款：雖然起迄增幅超標，但因今日收盤下跌，依法獲豁免。")
        else:
            if abs(pct_30d) >= 100.0:
                if abs(sum_ret_6d) <= 25.0: exempt_reasons.append("🟢 30日條款：起迄超標，但因近6日累積未破25%安全線而豁免。")
                else:
                    long_term_results["hit_30d"] = True
                    triggered_rules.append(f"第二款 (30個營業日起迄收盤漲幅達 {pct_30d:.2f}%)")
                    is_danger = True

    # 60日
    if target_idx >= 59:
        p_start_60d = prices_list[target_idx - 59]
        pct_60d = truncate_2_decimals(((p_target - p_start_60d) / p_start_60d) * 100)
        long_term_results["pct_60d"] = pct_60d
        long_term_results["p_start_60d"] = p_start_60d
        if is_price_dropped:
            long_term_results["is_exempt_60d"] = True
            if abs(pct_60d) >= 130.0: exempt_reasons.append("🟢 60日條款：雖然起迄增幅超標，但因今日收盤下跌，依法獲豁免。")
        else:
            if abs(pct_60d) >= 130.0:
                if abs(sum_ret_6d) <= 25.0: exempt_reasons.append("🟢 60日條款：起迄超標，但因近6日累積未破25%安全線而豁免。")
                else:
                    long_term_results["hit_60d"] = True
                    triggered_rules.append(f"第二款 (60個營業日起迄收盤漲幅達 {pct_60d:.2f}%)")
                    is_danger = True

    # 90日
    if target_idx >= 89:
        p_start_90d = prices_list[target_idx - 89]
        pct_90d = truncate_2_decimals(((p_target - p_start_90d) / p_start_90d) * 100)
        long_term_results["pct_90d"] = pct_90d
        long_term_results["p_start_90d"] = p_start_90d
        if is_price_dropped:
            long_term_results["is_exempt_90d"] = True
            if abs(pct_90d) >= 160.0: exempt_reasons.append("🟢 90日條款：雖然起迄增幅超標，但因今日收盤下跌，依法獲豁免。")
        else:
            if abs(pct_90d) >= 160.0:
                if abs(sum_ret_6d) <= 25.0: exempt_reasons.append("🟢 90日條款：起迄超標，但因近6日累積未破25%安全線而豁免。")
                else:
                    long_term_results["hit_90d"] = True
                    triggered_rules.append(f"第二款 (90個營業日起迄收盤漲幅達 {pct_90d:.2f}%)")
                    is_danger = True

    return is_danger, window_df, sum_ret_6d, total_spread_6d, long_term_results, triggered_rules, exempt_reasons


def fetch_backup_stock_history_from_twse(stock_id):
    prices, dates = [], []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        current_year = datetime.datetime.now().year
        url = f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_AVG?date={current_year}0101&stockNo={stock_id}&response=json"
        res = requests.get(url, headers=headers, timeout=6)
        if res.status_code == 200 and "data" in res.json():
            for row in res.json()["data"]:
                if len(row) >= 2 and row[1] != "0":
                    roc_date = row[0].split("/")
                    dates.append(f"{int(roc_date[0]) + 1911}-{roc_date[1]}-{roc_date[2]}")
                    prices.append(float(row[1].replace(",", "")))
    except: pass
    if len(prices) >= 15:
        return pd.DataFrame({"Close": prices}, index=pd.DatetimeIndex(dates)).sort_index()
    return pd.DataFrame()


# ==========================================
# 👑 主畫面呈現 (飯店級高級感盯盤儀表板)
# ==========================================
st.markdown("#### 🏛 臺灣證券交易所・純粹法規控盤精細儀表板")

stock_id = st.text_input("請輸入台股代號 (如 2492)", value="").strip()

if stock_id:
    with st.spinner("智慧提取盤面即時數據中..."):
        ticker_symbol = f"{stock_id}.TW"
        try:
            stock = yf.Ticker(ticker_symbol)
            df = stock.history(period="1y", auto_adjust=False) 
        except:
            df = fetch_backup_stock_history_from_twse(stock_id)

        if not df.empty:
            if isinstance(df.index, pd.DatetimeIndex): df.index = df.index.tz_localize(None)
            try:
                stock = yf.Ticker(f"{stock_id}.TW")
                latest_realtime_price = stock.fast_info.get("lastPrice", None)
                today_ts = pd.Timestamp(datetime.date.today())
                if latest_realtime_price is not None:
                    if df.index[-1].date() != today_ts.date():
                        df.loc[today_ts] = [latest_realtime_price]*max(1, len(df.columns))
                    else:
                        df.iloc[-1, df.columns.get_loc("Close")] = latest_realtime_price
            except: pass

    common_stocks = {"3030": "德律", "3231": "緯創", "2330": "台積電", "2317": "鴻海", "2454": "聯發科", "2492": "華新科"}
    stock_name = common_stocks.get(stock_id, f"台股 {stock_id}")

    if not df.empty and len(df) >= 95:
        all_prices = df["Close"].tolist()
        all_dates = df.index.strftime("%Y-%m-%d").tolist()
        today_price = all_prices[-1]
        today_date = all_dates[-1]

        # 診斷當日全法規
        is_today_danger, today_window_df, today_sum_ret, today_total_spread, long_term, today_rules, today_exempts = diagnose_all_regulatory_天書(all_prices, all_dates, len(all_prices) - 1)

        # 🛰️ 頂部狀態列：高級感精確對位
        col_lbl, col_met = st.columns([2, 1])
        with col_lbl:
            st.markdown(f"**📈 監控對象**：<span style='font-size:16px; font-weight:bold; color:#1f1f1f;'>{stock_name} ({stock_id})</span>", unsafe_allow_html=True)
            if is_today_danger:
                st.markdown('<div class="status-card danger-card"><b>🚨 今日注意股雷達：已名列公布注意股條款！</b></div>', unsafe_allow_html=True)
            else:
                st.markdown('<div class="status-card success-card"><b>🟢 今日注意股雷達：數據安全，未同時達各款注意標準。</b></div>', unsafe_allow_html=True)
        with col_met:
            st.metric(label=f"今日收盤價 ({today_date})", value=f"{today_price:.2f} 元")

        # 📊 當日短線與長線的核心數據面板
        st.markdown("##### 🔍 截止今日（含當天）各條款核對現況")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(f"**⚡ 短線 6日滾動 (第一款)**<br>● 起迄價差：`{today_total_spread:+.2f} 元`<br>● 累積漲幅：`{today_sum_ret:+.2f}%`<br>*(門檻：50元 且 25%)*", unsafe_allow_html=True)
        with c2:
            lbl_30 = "<span class='highlight-green'>🟢 下跌豁免</span>" if long_term["is_exempt_30d"] else ("<span class='highlight-red'>🔴 超標</span>" if long_term["hit_30d"] else "🟢 安全")
            st.markdown(f"**📅 30個營業日 (第二款)**<br>● 當前狀態：{lbl_30}<br>● 起迄增幅：**{long_term['pct_30d']:+.2f}%**<br>● 基期價格：`{long_term['p_start_30d']:.2f} 元`", unsafe_allow_html=True)
        with c3:
            lbl_60 = "<span class='highlight-green'>🟢 下跌豁免</span>" if long_term["is_exempt_60d"] else ("<span class='highlight-red'>🔴 超標</span>" if long_term["hit_60d"] else "🟢 安全")
            st.markdown(f"**📅 60個營業日 (第二款)**<br>● 當前狀態：{lbl_60}<br>● 起迄增幅：**{long_term['pct_60d']:+.2f}%**<br>● 基期價格：`{long_term['p_start_60d']:.2f} 元`", unsafe_allow_html=True)
        with c4:
            lbl_90 = "<span class='highlight-green'>🟢 下跌豁免</span>" if long_term["is_exempt_90d"] else ("<span class='highlight-red'>🔴 超標</span>" if long_term["hit_90d"] else "🟢 安全")
            st.markdown(f"**📅 90個營業日 (第二款)**<br>● 當前狀態：{lbl_90}<br>● 起迄增幅：**{long_term['pct_90d']:+.2f}%**<br>● 基期價格：`{long_term['p_start_90d']:.2f} 元`", unsafe_allow_html=True)

        if today_exempts:
            st.markdown("<span style='font-size:12px; color:#8c8c8c;'>💡 備註：</span>" + " ｜ ".join([f"<span style='font-size:12px; color:#52c41a;'>{ex}</span>" for ex in today_exempts]), unsafe_allow_html=True)

        # ==========================================
        # 🔮 【全條款推演中心】：一眼看清明天「各款分別要幾元」才會出事！
        # ==========================================
        st.markdown("---")
        st.markdown("##### 🔮 控盤核心：未來一整週「各款獨立最低臨界觸發價」vs「鎖漲停目標價」精細對照")
        
        future_dates = get_next_business_days(today_date, count=5)
        sim_prices = list(all_prices)
        sim_dates = list(all_dates)
        current_price = today_price
        
        # 建立五天橫向卡片
        f_cols = st.columns(5)
        
        for d_idx in range(5):
            next_limit_up = calculate_limit_up(current_price)
            
            # 呼叫全條款綜合反推引擎，把 6日/30日/60日/90日 獨立要觸發的驚悚數字一口氣抓出來！
            lowest_trigger, trig_6d, trig_30d, trig_60d, trig_90d = find_comprehensive_trigger_price(sim_prices, sim_dates, len(sim_prices) - 1)
            
            # 推入模擬環境
            sim_prices.append(next_limit_up)
            raw_date_label = future_dates[d_idx].split(" ")[0]
            sim_dates.append(f"2026-{raw_date_label.replace('/', '-')}")
            
            with f_cols[d_idx]:
                # 卡片式包裹，視覺層次感拉滿
                st.markdown(f"""
                <div class="future-box">
                    <span style="font-size: 13px; font-weight: bold; color: #1890ff;">🗓 第 {d_idx+1} 天：{future_dates[d_idx]}</span><br>
                    <span style="font-size: 15px; font-weight: bold; color: #d4380d;">🔥 鎖漲停價: {next_limit_up:.2f} 元</span>
                    <hr style="margin: 8px 0; border: 0; border-top: 1px solid #e8e8e8;">
                    
                    <div class="bullet-title">🎯 各條款獨立觸發臨界收盤價：</div>
                    <div class="bullet-item">📈 6日(第一款)門檻：<b>{trig_6d:.2f} 元</b></div>
                    <div class="bullet-item">📅 30日(第二款)門檻：{"<b>" + f"{trig_30d:.2f} 元</b>" if trig_30d != float('inf') else "<span style='color:#8c8c8c; font-style:italic;'>下跌豁免不適用</span>"}</div>
                    <div class="bullet-item">📅 60日(第二款)門檻：{"<b>" + f"{trig_60d:.2f} 元</b>" if trig_60d != float('inf') else "<span style='color:#8c8c8c; font-style:italic;'>下跌豁免不適用</span>"}</div>
                    <div class="bullet-item">📅 90日(第二款)門檻：{"<b>" + f"{trig_90d:.2f} 元</b>" if trig_90d != float('inf') else "<span style='color:#8c8c8c; font-style:italic;'>下跌豁免不適用</span>"}</div>
                    
                    <hr style="margin: 8px 0; border: 0; border-top: 1px solid #e8e8e8;">
                    <div class="bullet-title">📊 綜合雷達診斷結果：</div>
                    {"<span class='highlight-green' style='font-size:13px;'>● 當天鎖漲停也絕對安全！</span>" if lowest_trigger > next_limit_up else f"<span class='highlight-red' style='font-size:13px;'>● 收盤高於 <b>{lowest_trigger:.2f} 元</b> 即亮注意股！</span>"}
                </div>
                """, unsafe_allow_html=True)
                
            current_price = next_limit_up

        # K線滾動細節表格放底部折疊
        st.markdown("---")
        with st.expander("📊 點此展開查看今日截止之歷史 6 個營業日滾動數據明細表"):
            if not today_window_df.empty: render_styled_dataframe(today_window_df)
    else:
        st.warning("⚠️ 數據厚度不足 95 天，無法精確回推長線條款。")
