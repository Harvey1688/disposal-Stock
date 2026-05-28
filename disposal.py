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


def find_trigger_details_for_day(base_price, sum_past_4, compare_base_price):
    """🎯 核心反推引擎：精確反向推導出當天臨界價"""
    # 臨界價差：基期日價格 + 50元
    price_by_spread = compare_base_price + 50.0
    req_ret = 25.0 - sum_past_4
    price_by_ret = base_price * (1 + req_ret / 100.0)
    
    trigger_price = max(price_by_spread, price_by_ret)
    
    def apply_tick_size(p):
        if p < 10: tick = 0.01
        elif p < 50: tick = 0.05
        elif p < 100: tick = 0.1
        elif p < 500: tick = 0.5
        elif p < 1000: tick = 1.0
        else: tick = 5.0
        return round(math.ceil(p / tick) * tick, 2)
    
    final_trigger = apply_tick_size(trigger_price)
    
    corr_spread = round(final_trigger - compare_base_price, 2)
    corr_ret_day = truncate_2_decimals((final_trigger - base_price) / base_price * 100)
    corr_sum_ret = round(sum_past_4 + corr_ret_day, 2)
    
    return final_trigger, corr_spread, corr_sum_ret


def diagnose_all_regulatory_天書(prices_list, dates_list, target_idx):
    """👑 智慧核心：滾動窗格扣抵與法規數據計算"""
    is_danger = False
    window_df = pd.DataFrame()
    sum_ret_6d = 0.0
    total_spread_6d = 0.0

    if target_idx >= 6:
        # 👑 嚴格鎖定：取目前目標日算起共 7 筆資料（包含基期日本身）
        sub_prices = prices_list[target_idx - 6 : target_idx + 1] 
        sub_dates = dates_list[target_idx - 6 : target_idx + 1]
        
        display_dates = sub_dates[1:] 
        display_prices = sub_prices[1:] 
        
        daily_returns = []
        is_limit_up_list = []
        is_limit_down_list = []
        
        for k in range(6):
            p_prev = sub_prices[k]
            p_curr = sub_prices[k + 1]
            daily_returns.append(truncate_2_decimals((p_curr - p_prev) / p_prev * 100))
            
            l_up = calculate_limit_up(p_prev)
            l_down = calculate_limit_down(p_prev)
            is_limit_up_list.append(abs(p_curr - l_up) < 1e-4)
            is_limit_down_list.append(abs(p_curr - l_down) < 1e-4)
        
        sum_ret_6d = truncate_2_decimals(sum(daily_returns))
        
        # 👑 硬核精確扣抵：最後一天（當日）收盤價，直接減去 sub_prices[0]（基期日5/21的266元）
        # 390 - 266 = 124.00 元！絕無誤差！
        total_spread_6d = round(sub_prices[-1] - sub_prices[0], 2)
        
        window_df = pd.DataFrame({
            "營業日": display_dates,
            "收盤價 (元)": display_prices,
            "當日漲跌幅": [f"{r:+.2f}%" if r != 0 else "0.00%" for r in daily_returns],
            "is_limit_up": is_limit_up_list,
            "is_limit_down": is_limit_down_list
        })

        # 法規核心門檻：累積漲幅達25% 且 累積價差達50元
        if sum_ret_6d >= 25.0 and total_spread_6d >= 50.0:
            is_danger = True

    return is_danger, window_df, sum_ret_6d, total_spread_6d


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
            df = stock.history(period="6mo", auto_adjust=False)
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

    if not df.empty and len(df) >= 35:
        all_prices = df["Close"].tolist()
        all_dates = df.index.strftime("%Y-%m-%d").tolist()
        
        today_price = all_prices[-1]
        today_date = all_dates[-1]

        # 計算今日數據
        is_today_danger, today_window_df, today_sum_ret, today_total_spread = diagnose_all_regulatory_天書(all_prices, all_dates, len(all_prices) - 1)

        # 大標題直接放大呈現
        col_name_header, col_price_metric = st.columns([1.6, 1.4])
        with col_name_header:
            st.header(f"🔍 當前查詢：{stock_name} ({stock_id})")
            
            if is_today_danger:
                st.title(f"🔴 :red[紅燈：今日收盤價已觸動法規注意股門檻！]")
            else:
                st.title(f"🟢 :green[綠燈：今日收盤數據未達注意股標準（安全）]")
                
            # 👑 【極重要修正】：今日 6 日收盤起迄價差絕對精確顯示為 124.00 元！
            st.subheader(f"💰 今日6日收盤價起迄價差: {today_total_spread:+.2f} 元  |  📈 今日6日累積變動: {today_sum_ret:+.2f}%")
        
        with col_price_metric:
            st.metric(label=f"當前收盤/即時價 ({today_date})", value=f"{today_price:.2f} 元")

        # ==========================================
        # 🥇 【區塊一】：當天收盤數據明細
        # ==========================================
        st.markdown("---")
        st.subheader(f"📊 截止今日（含當天）之 6 個營業日收盤價與當日漲跌幅明細：")
        if not today_window_df.empty:
            render_styled_dataframe(today_window_df)

        if is_today_danger:
            st.error(f"🚨 今日數據已同時達標：累積漲幅 {today_sum_ret:.2f}% (門檻≧25%) 且 6日收盤價起迄價差 {today_total_spread:.2f}元 (門檻≧50元)。")
        else:
            st.success(f"🟢 今日數據安全：未同時達到 6日累積25% 與 50元 的雙重列管紅線。")

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
            
            past_returns = []
            for m in range(4):
                pf_idx = len(sim_prices) - 4 + m
                p_from_temp = sim_prices[pf_idx]
                p_to_temp = sim_prices[pf_idx + 1] if m < 3 else next_limit_up
                past_returns.append(truncate_2_decimals((p_to_temp - p_from_temp) / p_from_temp * 100))
            
            sum_past_4_days = sum(past_returns[:-1])
            
            # 🔮 未來模擬的扣抵基準日：與當前目標完全相同，往前精確錨定第 -6 個索引（即 6 日前的基期日）
            compare_base_price = sim_prices[-6] 
            
            day_trigger_price, corr_spread, corr_sum_ret = find_trigger_details_for_day(current_price, sum_past_4_days, compare_base_price)
            
            sim_prices.append(next_limit_up)
            raw_date_label = future_dates[d_idx].split(" ")[0]
            sim_dates.append(f"2026-{raw_date_label.replace('/', '-')}")
            
            is_sim_danger, sim_window_df, sim_sum_ret, sim_total_spread = diagnose_all_regulatory_天書(sim_prices, sim_dates, len(sim_prices) - 1)
            
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
    st.info("💡 請在上方輸入框鍵入台股代號（例如：2492 華新科），系統將立即為您進行法規觸動推演。")

# 官方傳送門保持底部
st.markdown("---")
st.markdown("### 🏛 證交所 / 櫃買中心 官方公告核對傳送門")
col_twse_1, col_twse_2, col_tpex_1, col_tpex_2 = st.columns(4)
with col_twse_1:
    st.markdown('<a href="https://www.twse.com.tw/zh/announcement/notice.html" target="_blank" style="text-decoration:none;"><div style="background-color:#f1f3f5; padding:15px; border-radius:8px; border-left:5px solid #0288d1; text-align:center;"><b style="color:#1a1a1a; font-size:15px;">臺灣證交所 (上市)</b><br><span style="color:#0288d1; font-size:13px; font-weight:bold;">每日注意股票公告 ↗</span></div></a>', unsafe_allow_html=True)
with col_twse_2:
    st.markdown('<a href="https://www.twse.com.tw/zh/announcement/punish.html" target="_blank" style="text-decoration:none;"><div style="background-color:#f1f3f5; padding:15px; border-radius:8px; border-left:5px solid #d32f2f; text-align:center;"><b style="color:#1a1a1a; font-size:15px;">臺灣證交所 (上市)</b><br><span style="color:#d32f2f; font-size:13px; font-weight:bold;">每日處置股票公告 ↗</span></div></a>', unsafe_allow_html=True)
with col_tpex_1:
    st.markdown('<a href="https://www.tpex.org.tw/zh-tw/announce/market/attention.html" target="_blank" style="text-decoration:none;"><div style="background-color:#f1f3f5; padding:15px; border-radius:8px; border-left:5px solid #0288d1; text-align:center;"><b style="color:#1a1a1a; font-size:15px;">櫃買中心 (上櫃)</b><br><span style="color:#0288d1; font-size:13px; font-weight:bold;">每日注意有價證券 ↗</span></div></a>', unsafe_allow_html=True)
with col_tpex_2:
    st.markdown('<a href="https://www.tpex.org.tw/zh-tw/announce/market/disposal.html" target="_blank" style="text-decoration:none;"><div style="background-color:#f1f3f5; padding:15px; border-radius:8px; border-left:5px solid #d32f2f; text-align:center;"><b style="color:#1a1a1a; font-size:15px;">櫃買中心 (上櫃)</b><br><span style="color:#d32f2f; font-size:13px; font-weight:bold;">每日處置有價證券 ↗</span></div></a>', unsafe_allow_html=True)
