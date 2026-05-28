import datetime
import math
import pandas as pd
import requests
import streamlit as st
import yfinance as yf

# 設定網頁標題與風格
st.set_page_config(page_title="純粹法規注意股監控盤", layout="wide")


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
    """🎯 終極反推引擎：同時對位 6日/30日/60日/90日 條款，計算出明天『各款分別需要多少元』才會被注意"""
    p_yesterday = prices_history[current_idx]  # 對明天而言，歷史最後一天就是「前一日收盤價」
    
    # 建立一個測試用的虛擬明天環境
    # 1. 估算第一款 (6日滾動)
    sub_prices_5 = prices_history[current_idx - 4 : current_idx + 1]
    past_returns_truncated = []
    for m in range(4):
        p_prev_temp = sub_prices_5[m]
        p_curr_temp = sub_prices_5[m + 1]
        past_returns_truncated.append(truncate_2_decimals(((p_curr_temp - p_prev_temp) / p_prev_temp) * 100))
    sum_past_5_truncated = sum(past_returns_truncated)
    compare_base_price_6d = prices_history[current_idx - 4]
    
    # 第一款反推公式
    price_by_spread = compare_base_price_6d + 50.0
    req_this_day_ret = 25.0 - sum_past_5_truncated
    price_by_ret = p_yesterday * (1 + req_this_day_ret / 100.0)
    trigger_6d_raw = max(price_by_spread, price_by_ret)
    tick_6d = get_tick_size(trigger_6d_raw)
    trigger_6d = math.ceil(trigger_6d_raw / tick_6d) * tick_6d
    
    # 2. 估算第二款 (30日/60日/90日) 臨界價
    # 30日
    p_start_30d = prices_history[current_idx - 28] # 明天對比的是 29 天前(含明天共30天)
    trigger_30d_raw = p_start_30d * 2.0  # 漲幅達 100% 代表價格變成 2 倍
    tick_30d = get_tick_size(trigger_30d_raw)
    trigger_30d = math.ceil(trigger_30d_raw / tick_30d) * tick_30d
    if trigger_30d < p_yesterday: trigger_30d = float('inf') # 下跌豁免，設定為無限大
    
    # 60日
    p_start_60d = prices_history[current_idx - 58]
    trigger_60d_raw = p_start_60d * 2.3  # 漲幅達 130%
    tick_60d = get_tick_size(trigger_60d_raw)
    trigger_60d = math.ceil(trigger_60d_raw / tick_60d) * tick_60d
    if trigger_60d < p_yesterday: trigger_60d = float('inf')
        
    # 90日
    p_start_90d = prices_history[current_idx - 88]
    trigger_90d_raw = p_start_90d * 2.6  # 漲幅達 160%
    tick_90d = get_tick_size(trigger_90d_raw)
    trigger_90d = math.ceil(trigger_90d_raw / tick_90d) * tick_90d
    if trigger_90d < p_yesterday: trigger_90d = float('inf')

    # 綜合評估最低觸發價
    valid_prices = [trigger_6d, trigger_30d, trigger_60d, trigger_90d]
    final_lowest_trigger = min(valid_prices)
    
    return final_lowest_trigger, trigger_6d, trigger_30d, trigger_60d, trigger_90d


def diagnose_all_regulatory_天書(prices_list, dates_list, target_idx):
    """👑 智慧核心：第一款短線與第二款長線起迄判定引擎"""
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

    # --- 【第一款：短線 6日滾動核對】 ---
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
            
            ret_raw = ((p_curr - p_prev) / p_prev) * 100
            ret_truncated = truncate_2_decimals(ret_raw)
            display_returns.append(ret_truncated)
            
            l_up = calculate_limit_up(p_prev)
            l_down = calculate_limit_down(p_prev)
            is_limit_up_list.append(abs(p_curr - l_up) < 1e-4)
            is_limit_down_list.append(abs(p_curr - l_down) < 1e-4)
        
        sum_ret_6d = round(sum(display_returns), 2)
        total_spread_6d = round(sub_prices[-1] - sub_prices[0], 2)
        
        window_df = pd.DataFrame({
            "營業日": sub_dates,
            "收盤價 (元)": sub_prices,
            "當日漲跌幅": [f"{r:+.2f}%" if r != 0 else "0.00%" for r in display_returns],
            "is_limit_up": is_limit_up_list,
            "is_limit_down": is_limit_down_list
        })

        if sum_ret_6d >= 25.0 and total_spread_6d >= 50.0:
            triggered_rules.append(f"第一款 (6日加總漲幅達 {sum_ret_6d:.2f}% 且 價差達 {total_spread_6d:.2f}元)")
            is_danger = True

    # --- 【第二款：長線 30 / 60 / 90 營業日收盤價判定】 ---
    p_target = prices_list[target_idx]
    p_yesterday = prices_list[target_idx - 1] if target_idx >= 1 else p_target
    is_price_dropped = (p_target < p_yesterday)

    # 30日條款
    if target_idx >= 29:
        p_start_30d = prices_list[target_idx - 29]
        pct_30d = truncate_2_decimals(((p_target - p_start_30d) / p_start_30d) * 100)
        long_term_results["pct_30d"] = pct_30d
        long_term_results["p_start_30d"] = p_start_30d
        
        if is_price_dropped:
            long_term_results["is_exempt_30d"] = True
            if abs(pct_30d) >= 100.0:
                exempt_reasons.append(f"🟢 豁免第二款(30日)：收盤漲幅達 {pct_30d:.2f}% 已達標，但因今日收盤下跌而豁免注意。")
        else:
            if abs(pct_30d) >= 100.0:
                if abs(sum_ret_6d) <= 25.0:
                    exempt_reasons.append(f"🟢 豁免放過(30日)：長線達 {pct_30d:.2f}%，但近6日短線累積未達25%而安全。")
                else:
                    long_term_results["hit_30d"] = True
                    triggered_rules.append(f"第二款 (最近30個營業日起迄收盤價漲幅達 {pct_30d:.2f}%)")
                    is_danger = True

    # 60日條款
    if target_idx >= 59:
        p_start_60d = prices_list[target_idx - 59]
        pct_60d = truncate_2_decimals(((p_target - p_start_60d) / p_start_60d) * 100)
        long_term_results["pct_60d"] = pct_60d
        long_term_results["p_start_60d"] = p_start_60d
        
        if is_price_dropped:
            long_term_results["is_exempt_60d"] = True
            if abs(pct_60d) >= 130.0:
                exempt_reasons.append(f"🟢 豁免第二款(60日)：收盤漲幅達 {pct_60d:.2f}% 已達標，但因今日收盤下跌而豁免注意。")
        else:
            if abs(pct_60d) >= 130.0:
                if abs(sum_ret_6d) <= 25.0:
                    exempt_reasons.append(f"🟢 豁免放過(60日)：長線達 {pct_60d:.2f}%，但近6日短線累積未達25%而安全。")
                else:
                    long_term_results["hit_60d"] = True
                    triggered_rules.append(f"第二款 (最近60個營業日起迄收盤價漲幅達 {pct_60d:.2f}%)")
                    is_danger = True

    # 90日條款
    if target_idx >= 89:
        p_start_90d = prices_list[target_idx - 89]
        pct_90d = truncate_2_decimals(((p_target - p_start_90d) / p_start_90d) * 100)
        long_term_results["pct_90d"] = pct_90d
        long_term_results["p_start_90d"] = p_start_90d
        
        if is_price_dropped:
            long_term_results["is_exempt_90d"] = True
            if abs(pct_90d) >= 160.0:
                exempt_reasons.append(f"🟢 豁免第二款(90日)：收盤漲幅達 {pct_90d:.2f}% 已達標，但因今日收盤下跌而豁免注意。")
        else:
            if abs(pct_90d) >= 160.0:
                if abs(sum_ret_6d) <= 25.0:
                    exempt_reasons.append(f"🟢 豁免放過(90日)：長線達 {pct_90d:.2f}%，但近6日短線累積未達25%而安全。")
                else:
                    long_term_results["hit_90d"] = True
                    triggered_rules.append(f"第二款 (最近90個營業日起迄收盤價漲幅達 {pct_90d:.2f}%)")
                    is_danger = True

    return is_danger, window_df, sum_ret_6d, total_spread_6d, long_term_results, triggered_rules, exempt_reasons


def fetch_backup_stock_history_from_twse(stock_id):
    """🛡️ 備用官方連線機制"""
    prices, dates = [], []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        current_year = datetime.datetime.now().year
        url = f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_AVG?date={current_year}0101&stockNo={stock_id}&response=json"
        res = requests.get(url, headers=headers, timeout=6)
        if res.status_code == 200 and "data" in res.json():
            raw_data = res.json()["data"]
            for row in raw_data:
                if len(row) >= 2 and row[1] != "0":
                    roc_date = row[0].split("/")
                    year = int(roc_date[0]) + 1911
                    date_str = f"{year}-{roc_date[1]}-{roc_date[2]}"
                    dates.append(date_str)
                    prices.append(float(row[1].replace(",", "")))
    except: pass
    if len(prices) >= 15:
        df_backup = pd.DataFrame({"Close": prices}, index=pd.DatetimeIndex(dates))
        return df_backup.sort_index()
    return pd.DataFrame()


def render_styled_dataframe(display_df):
    """表格收盤價紅綠燈變色"""
    if display_df.empty: return
    def style_rows(row):
        styles = [""] * len(row)
        c_idx = display_df.columns.get_loc("收盤價 (元)")
        if row["is_limit_up"]: styles[c_idx] = "background-color: #ef5350; color: white; font-weight: bold;"
        elif row["is_limit_down"]: styles[c_idx] = "background-color: #2b8a3e; color: white; font-weight: bold;"
        return styles
    st.dataframe(
        display_df.style.apply(style_rows, axis=1).format({"收盤價 (元)": "{:.2f}"}),
        column_config={"is_limit_up": None, "is_limit_down": None, "營業日": st.column_config.TextColumn("營業日")},
        use_container_width=True, hide_index=True
    )


# ==========================================
# 👑 主要畫面呈現 (精緻小字體化)
# ==========================================
st.markdown("### 🏛 純粹法規注意股監控面板 (飯店級精緻版)")
st.markdown("---")

stock_id = st.text_input("請輸入台股代號", value="").strip()

if stock_id:
    with st.spinner("正在提取台股歷史數據..."):
        ticker_symbol = f"{stock_id}.TW"
        try:
            stock = yf.Ticker(ticker_symbol)
            df = stock.history(period="1y", auto_adjust=False) 
        except:
            df = fetch_backup_stock_history_from_twse(stock_id)

        if not df.empty:
            if isinstance(df.index, pd.DatetimeIndex):
                df.index = df.index.tz_localize(None)
            try:
                stock = yf.Ticker(f"{stock_id}.TW")
                fast_info = stock.fast_info
                latest_realtime_price = fast_info.get("lastPrice", None)
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

        # 核心診斷
        is_today_danger, today_window_df, today_sum_ret, today_total_spread, long_term, today_rules, today_exempts = diagnose_all_regulatory_天書(all_prices, all_dates, len(all_prices) - 1)

        # 頂部狀態列 (全面縮小字體)
        st.markdown(f"**🔍 查詢對象**：{stock_name} ({stock_id}) | **當前價格**：`{today_price:.2f} 元` ({today_date})")
        if is_today_danger:
            st.markdown("⚠️ **當前狀態**：🔴 <span style='color:#ef5350; font-weight:bold;'>今日數據已達注意股發布門檻！</span>", unsafe_allow_html=True)
        else:
            st.markdown("✨ **當前狀態**：🟢 <span style='color:#2b8a3e; font-weight:bold;'>今日數據安全，未達法規注意標準。</span>", unsafe_allow_html=True)
            
        st.markdown(f"* **今日 6 日短線滾動數據**：起迄價差 `{today_total_spread:+.2f} 元` / 累積加總捨去漲幅 `{today_sum_ret:+.2f}%` (門檻: 50元 且 25%)")

        # ==========================================
        # 🥇 【長線條列化看板】：30 / 60 / 90 營業日起迄扣抵增幅
        # ==========================================
        st.markdown("##### 🏛 長線條款基準日扣抵對位 (第二款)")
        
        c_30, c_60, c_90 = st.columns(3)
        with c_30:
            st.markdown("**📅 最近 30 個營業日起迄：**")
            if long_term["is_exempt_30d"]:
                st.markdown("● 狀態：`🟢 下跌豁免`")
            else:
                status_lbl = "🔴 超標" if long_term["hit_30d"] else "🟢 安全"
                st.markdown(f"● 狀態：`{status_lbl}`")
            st.markdown(f"● 累積增幅：**{long_term['pct_30d']:+.2f}%** (門檻: ±100%)")
            st.markdown(f"● 基期收盤價：`{long_term['p_start_30d']:.2f} 元`")
                
        with c_60:
            st.markdown("**📅 最近 60 個營業日起迄：**")
            if long_term["is_exempt_60d"]:
                st.markdown("● 狀態：`🟢 下跌豁免`")
            else:
                status_lbl = "🔴 超標" if long_term["hit_60d"] else "🟢 安全"
                st.markdown(f"● 狀態：`{status_lbl}`")
            st.markdown(f"● 累積增幅：**{long_term['pct_60d']:+.2f}%** (門檻: ±130%)")
            st.markdown(f"● 基期收盤價：`{long_term['p_start_60d']:.2f} 元`")
                
        with c_90:
            st.markdown("**📅 最近 90 個營業日起迄：**")
            if long_term["is_exempt_90d"]:
                st.markdown("● 狀態：`🟢 下跌豁免`")
            else:
                status_lbl = "🔴 超標" if long_term["hit_90d"] else "🟢 安全"
                st.markdown(f"● 狀態：`{status_lbl}`")
            st.markdown(f"● 累積增幅：**{long_term['pct_90d']:+.2f}%** (門檻: ±160%)")
            st.markdown(f"● 基期收盤價：`{long_term['p_start_90d']:.2f} 元`")

        if today_exempts:
            st.markdown("**💡 今日法規豁免備註：**")
            for ex in today_exempts: st.markdown(f"- {ex}")

        # ==========================================
        # 🔮 【全方位預測推演】：未來一週「各條款最低被注意數字」條列化
        # ==========================================
        st.markdown("---")
        st.markdown("##### 🔮 預測推演：未來一整週各款「注意股最低臨界被注意數字」條列對照")
        
        future_dates = get_next_business_days(today_date, count=5)
        
        # 複製歷史紀錄進行多日滾動預測模擬
        sim_prices = list(all_prices)
        sim_dates = list(all_dates)
        current_price = today_price
        
        row1_col1, row1_col2, row1_col3 = st.columns(3)
        row2_col1, row2_col2, _ = st.columns([1, 1, 1])
        cols_pool = [row1_col1, row1_col2, row1_col3, row2_col1, row2_col2]
        
        for d_idx in range(5):
            next_limit_up = calculate_limit_up(current_price)
            
            # 使用我們新開發的 comprehensive 反推引擎，把 6/30/60/90 日個別要被注意的數字全部精確算出來！
            lowest_trigger, trig_6d, trig_30d, trig_60d, trig_90d = find_comprehensive_trigger_price(sim_prices, sim_dates, len(sim_prices) - 1)
            
            # 將明天的模擬數據推入歷史，為下後天做準備 (假設天天鎖漲停)
            sim_prices.append(next_limit_up)
            raw_date_label = future_dates[d_idx].split(" ")[0]
            sim_dates.append(f"2026-{raw_date_label.replace('/', '-')}")
            
            with cols_pool[d_idx]:
                st.markdown(f"**🗓 預測第 {d_idx+1} 天：{future_dates[d_idx]}**")
                st.markdown(f"● **天天鎖漲停目標價**：`{next_limit_up:.2f} 元`")
                
                # 條列化列出各款要被注意的具體數字
                st.markdown("● **各條款獨立觸發臨界收盤價**：")
                st.markdown(f"  - 6日(第一款)門檻：`{trig_6d:.2f} 元`")
                
                lbl_30 = f"`{trig_30d:.2f} 元`" if trig_30d != float('inf') else "`下跌豁免不適用`"
                st.markdown(f"  - 30日(第二款)門檻：{lbl_30}")
                
                lbl_60 = f"`{trig_60d:.2f} 元`" if trig_60d != float('inf') else "`下跌豁免不適用`"
                st.markdown(f"  - 60日(第二款)門檻：{lbl_60}")
                
                lbl_90 = f"`{trig_90d:.2f} 元`" if trig_90d != float('inf') else "`下跌豁免不適用`"
                st.markdown(f"  - 90日(第二款)門檻：{lbl_90}")
                
                # 結論亮燈
                if lowest_trigger > next_limit_up:
                    st.markdown("● **綜合診斷**：🟢 <span style='color:#2b8a3e; font-weight:bold;'>當天即使拉到漲停也絕對安全！</span>", unsafe_allow_html=True)
                else:
                    st.markdown(f"● **綜合診斷**：🚨 <span style='color:#ef5350; font-weight:bold;'>收盤價高於 {lowest_trigger:.2f} 元即引爆注意股！</span>", unsafe_allow_html=True)
                st.markdown("---")
                    
            current_price = next_limit_up

        # ==========================================
        # 📊 【表格明細放底部】
        # ==========================================
        if not today_window_df.empty:
            with st.expander("📊 點此展開查看今日截止之 6 個營業日滾動精細數據明細"):
                render_styled_dataframe(today_window_df)
    else:
        st.warning("⚠️ 長線 K 線資料庫深度不足 95 天，無法精確對位 90 個營業日的起迄變動率。")
else:
    st.info("💡 請在上方輸入框鍵入台股代號，系統將立即為您條列解開 6日 / 30日 / 60日 / 90日 的完整臨界數據。")
