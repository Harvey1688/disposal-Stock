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


def find_trigger_details_for_day(current_price, sum_past_5_truncated, compare_base_price):
    """🎯 核心反推引擎：根據天天「先捨去再加總」定義，反推明天的最低臨界觸發收盤價"""
    price_by_spread = compare_base_price + 50.0
    req_this_day_ret = 25.0 - sum_past_5_truncated
    price_by_ret = current_price * (1 + req_this_day_ret / 100.0)
    
    trigger_price = max(price_by_spread, price_by_ret)
    
    if trigger_price < 10: tick = 0.01
    elif trigger_price < 50: tick = 0.05
    elif trigger_price < 100: tick = 0.1
    elif trigger_price < 500: tick = 0.5
    elif trigger_price < 1000: tick = 1.0
    else: tick = 5.0
    
    final_trigger = math.ceil(trigger_price / tick) * tick
    final_trigger = round(final_trigger, 2)
    
    corr_spread = round(final_trigger - compare_base_price, 2)
    this_day_ret_truncated = truncate_2_decimals(((final_trigger - current_price) / current_price) * 100)
    corr_sum_ret = round(sum_past_5_truncated + this_day_ret_truncated, 2)
    
    return final_trigger, corr_spread, corr_sum_ret


def diagnose_all_regulatory_天書(prices_list, dates_list, target_idx):
    """👑 智慧核心：完美收錄【第一款 6日滾動先捨後加法】與您糾正之【第二款 30/60/90日收盤下跌即豁免法】"""
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
            triggered_rules.append(f"第一款 (6日加總捨去漲幅達 {sum_ret_6d:.2f}% 且 起迄價差達 {total_spread_6d:.2f}元)")
            is_danger = True

    # --- 【第二款：長線 30 / 60 / 90 營業日收盤價判定（核心邏輯精準修正）】 ---
    p_target = prices_list[target_idx]
    p_yesterday = prices_list[target_idx - 1] if target_idx >= 1 else p_target
    
    # 🎯 遵照您的糾正：當日收盤價「低於」前一營業日收盤價（即收盤下跌），第二款不分天數全部無條件直接豁免！
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
                exempt_reasons.append(f"🟢 豁免第二款(30日)：收盤漲幅達 {pct_30d:.2f}% 已超標，但因今日收盤價低於前一日收盤價，依法直接不予注意。")
        else:
            if abs(pct_30d) >= 100.0:
                if abs(sum_ret_6d) <= 25.0:
                    exempt_reasons.append(f"🟢 豁免放過(30日)：長線達 {pct_30d:.2f}%，但因近6日短線累積低於25%乖巧線而安全。")
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
                exempt_reasons.append(f"🟢 豁免第二款(60日)：收盤漲幅達 {pct_60d:.2f}% 已超標，但因今日收盤價低於前一日收盤價，依法直接不予注意。")
        else:
            if abs(pct_60d) >= 130.0:
                if abs(sum_ret_6d) <= 25.0:
                    exempt_reasons.append(f"🟢 豁免放過(60日)：長線達 {pct_60d:.2f}%，但因近6日短線累積低於25%而安全。")
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
                exempt_reasons.append(f"🟢 豁免第二款(90日)：收盤漲幅達 {pct_90d:.2f}% 已超標，但因今日收盤價低於前一日收盤價，依法直接不予注意。")
        else:
            if abs(pct_90d) >= 160.0:
                if abs(sum_ret_6d) <= 25.0:
                    exempt_reasons.append(f"🟢 豁免放過(90日)：長線達 {pct_90d:.2f}%，但因近6日短線累積低於25%而安全。")
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
# 👑 主要畫面呈現
# ==========================================
st.title("飯店級智慧看盤：純粹法規注意股計算面板")
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

        # 大標題大字呈現
        col_name_header, col_price_metric = st.columns([1.6, 1.4])
        with col_name_header:
            st.header(f"🔍 當前查詢：{stock_name} ({stock_id})")
            if is_today_danger:
                st.title(f"🔴 :red[紅燈：今日收盤價已觸動法規注意股門檻！]")
            else:
                st.title(f"🟢 :green[綠燈：今日收盤數據未達注意股標準（安全）]")
            st.subheader(f"💰 今日6日收盤起迄價差: {today_total_spread:+.2f} 元  |  📈 今日6日加總捨去漲幅: {today_sum_ret:+.2f}%")
        
        with col_price_metric:
            st.metric(label=f"當前收盤/即時價 ({today_date})", value=f"{today_price:.2f} 元")

        # ==========================================
        # 🥇 【看板】：30 / 60 / 90 營業日收盤價漲幅動態看板
        # ==========================================
        st.markdown("---")
        st.subheader(f"🏛 證交所注意條款長線基準日對位看板 ({today_date} 截止)")
        
        c_30, c_60, c_90 = st.columns(3)
        with c_30:
            if long_term["is_exempt_30d"]:
                st.markdown("### 📅 最近 30 個營業日")
                st.markdown("## :green[🟢 今日下跌豁免]")
                st.caption(f"實際起迄幅：{long_term['pct_30d']:+.2f}% (對照基期：{long_term['p_start_30d']:.2f} 元)")
            else:
                color_30 = "red" if long_term["hit_30d"] else "green"
                st.markdown("### 📅 最近 30 個營業日收盤漲幅")
                st.markdown(f"## :{color_30}[{long_term['pct_30d']:+.2f}%]")
                st.caption(f"起迄對照基準日收盤價：{long_term['p_start_30d']:.2f} 元 (門檻：±100%)")
                
        with c_60:
            if long_term["is_exempt_60d"]:
                st.markdown("### 📅 最近 60 個營業日")
                st.markdown("## :green[🟢 今日下跌豁免]")
                st.caption(f"實際起迄幅：{long_term['pct_60d']:+.2f}% (對照基期：{long_term['p_start_60d']:.2f} 元)")
            else:
                color_60 = "red" if long_term["hit_60d"] else "green"
                st.markdown("### 📅 最近 60 個營業日收盤漲幅")
                st.markdown(f"## :{color_60}[{long_term['pct_60d']:+.2f}%]")
                st.caption(f"起迄對照基準日收盤價：{long_term['p_start_60d']:.2f} 元 (門檻：±130%)")
                
        with c_90:
            if long_term["is_exempt_90d"]:
                st.markdown("### 📅 最近 90 個營業日")
                st.markdown("## :green[🟢 今日下跌豁免]")
                st.caption(f"實際起迄幅：{long_term['pct_90d']:+.2f}% (對照基期：{long_term['p_start_90d']:.2f} 元)")
            else:
                color_90 = "red" if long_term["hit_90d"] else "green"
                st.markdown("### 📅 最近 90 個營業日收盤漲幅")
                st.markdown(f"## :{color_90}[{long_term['pct_90d']:+.2f}%]")
                st.caption(f"起迄對照基準日收盤價：{long_term['p_start_90d']:.2f} 元 (門檻：±160%)")

        st.markdown("---")
        if not today_window_df.empty:
            st.markdown("##### 📊 截止今日（含當天）之 6 個營業日收盤價與當日漲跌幅明細：")
            render_styled_dataframe(today_window_df)

        if today_exempts:
            st.markdown("##### 💡 當日觸發排外免死金牌原因：")
            for ex in today_exempts: st.info(ex)

        if is_today_danger:
            st.markdown(f"""
            <div style='background-color:#fce8e6; border-left:6px solid #ef5350; padding:15px; border-radius:5px; color:#ef5350; margin-top:15px; margin-bottom:15px;'>
                <span style='font-size:20px; font-weight:bold;'>🔴 今日數學推演：已名列法規注意下列條款：</span><br>
                <ul style='margin-top:10px; font-size:15px; color:#111111; font-weight:bold;'>
                    {"".join([f"<li style='margin-bottom:5px;'>{r}</li>" for r in today_rules])}
                </ul>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.success(f"🟢 今日數據安全：未同時觸動短線 6日(25% 且 50元) 或 長線 30/60/90日 的發布注意股紅線。")

        # ==========================================
        # 🔮 【區塊二】：未來一整週天天漲停與臨界觸發價推演
        # ==========================================
        st.markdown("---")
        st.subheader("🔮 預測推演：未來一整週「注意股最低觸發價」vs「天天鎖漲停」精確對照")
        
        future_dates = get_next_business_days(today_date, count=5)
        sim_prices = list(all_prices)
        sim_dates = list(all_dates)
        current_price = today_price
        
        row1_col1, row1_col2, row1_col3 = st.columns(3)
        row2_col1, row2_col2, _ = st.columns([1, 1, 1])
        cols_pool = [row1_col1, row1_col2, row1_col3, row2_col1, row2_col2]
        
        for d_idx in range(5):
            next_limit_up = calculate_limit_up(current_price)
            
            past_returns_truncated = []
            for m in range(5):
                ref_idx = len(sim_prices) - 5 + m
                p_prev_temp = sim_prices[ref_idx - 1]
                p_curr_temp = sim_prices[ref_idx]
                past_returns_truncated.append(truncate_2_decimals(((p_curr_temp - p_prev_temp) / p_prev_temp) * 100))
            sum_past_5_truncated = sum(past_returns_truncated)
            
            compare_base_price = sim_prices[-5] 
            
            day_trigger_price, corr_spread, corr_sum_ret = find_trigger_details_for_day(current_price, sum_past_5_truncated, compare_base_price)
            
            sim_prices.append(next_limit_up)
            raw_date_label = future_dates[d_idx].split(" ")[0]
            sim_dates.append(f"2026-{raw_date_label.replace('/', '-')}")
            
            is_sim_danger, sim_window_df, sim_sum_ret, sim_total_spread, sim_long, sim_rules, sim_ex = diagnose_all_regulatory_天書(sim_prices, sim_dates, len(sim_prices) - 1)
            
            with cols_pool[d_idx]:
                st.error(f"🗓 預測第 {d_idx+1} 天：{future_dates[d_idx]}")
                st.header(f"🔥 鎖漲停價: {next_limit_up:.2f} 元")
                
                is_sim_both_triggered = (sim_sum_ret >= 25.0) and (sim_total_spread >= 50.0)
                
                if is_sim_both_triggered:
                    st.subheader(f"🔴 :red[預估起迄價差: {sim_total_spread:+.2f} 元]")
                    st.subheader(f"🔴 :red[預估累積漲幅: {sim_sum_ret:+.2f}%]")
                else:
                    st.subheader(f"🟢 :green[預估起迄價差: {sim_total_spread:+.2f} 元]")
                    st.subheader(f"🟢 :green[預估累積漲幅: {sim_sum_ret:+.2f}%]")
                
                if day_trigger_price > next_limit_up:
                    st.info(f"✅ 當天最高漲停也安全！臨界觸發價為 {day_trigger_price:.2f} 元。")
                else:
                    st.warning(f"🚨 當天收盤價高於 {day_trigger_price:.2f} 元即觸發注意股！")
                    st.markdown(f"**💡 臨界價之聯動數值明細：**")
                    if is_sim_both_triggered:
                        st.markdown(f"🔴 累積漲幅：:red[{corr_sum_ret:+.2f}%] (已達標)")
                        st.markdown(f"🔴 起迄價差：:red[{corr_spread:+.2f} 元] (已達標)")
                    else:
                        st.markdown(f"🟢 累積漲幅：:green[{corr_sum_ret:+.2f}%] (未雙達標)")
                        st.markdown(f"🟢 起迄價差：:green[{corr_spread:+.2f} 元] (未雙達標)")
                    
            current_price = next_limit_up
    else:
        st.warning("⚠️ 長線 K 線資料庫深度不足 95 天，無法精確對位 90 個營業日的第二款起迄變動率。")
else:
    st.info("💡 請在上方輸入框鍵入台股代號（例如：2492 華新科），系統將立即為您解開 6日 / 30日 / 60日 / 90日 的完整法規判定。")
