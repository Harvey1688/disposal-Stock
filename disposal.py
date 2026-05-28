import datetime
import math
import pandas as pd
import requests
import streamlit as st
import yfinance as yf

# 設定網頁標題與風格
st.set_page_config(page_title="處置股/注意股 終極法規控盤羅盤", layout="wide")


def truncate_2_decimals(n):
    """將數字無條件捨去至小數點後第二位"""
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
    """115年市場開休市交易行事曆智慧過祿"""
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


def find_trigger_price_for_day(base_price, sum_past_4, compare_base_price):
    """
    🎯 核心反推引擎：精確反向推導出當天要觸發 25% 門檻的最低臨界價位
    """
    price_by_spread = compare_base_price + 50.0
    req_ret = 25.0 - sum_past_4
    price_by_ret = base_price * (1 + req_ret / 100.0)
    
    trigger_price = max(price_by_spread, price_by_ret)
    
    if trigger_price < 10: tick = 0.01
    elif trigger_price < 50: tick = 0.05
    elif trigger_price < 100: tick = 0.1
    elif trigger_price < 500: tick = 0.5
    elif trigger_price < 1000: tick = 1.0
    else: tick = 5.0
    
    final_trigger = math.ceil(trigger_price / tick) * tick
    return round(final_trigger, 2)


def diagnose_all_regulatory_天書(prices_list, dates_list, target_idx):
    """
    👑 智慧核心：完美校正扣抵基期與欄位資料的法規判定引擎
    """
    triggered_rules = []
    exempt_reasons = [] 
    is_danger = False
    
    window_df = pd.DataFrame()
    sum_ret_6d = 0.0
    total_spread_6d = 0.0

    # 💡 為了讓第一天也能跟前一天比，target_idx 必須 >= 6 (也就是至少要有 7 天的資料)
    if target_idx >= 6:
        # 抓取這 6 天以及「這6天前一個營業日（基期日）」的數據
        sub_prices = prices_list[target_idx - 6 : target_idx + 1] # 長度為 7
        sub_dates = dates_list[target_idx - 6 : target_idx + 1]
        
        display_dates = sub_dates[1:] # 實際顯示的 6 天日期
        display_prices = sub_prices[1:] # 實際顯示的 6 天收盤價
        
        daily_returns = []
        is_limit_up_list = []
        is_limit_down_list = []
        
        # 💡 5/21 再也不是 0！ 每一天都是真正去跟「前一個營業日」做比較計算
        for k in range(6):
            p_prev = sub_prices[k]
            p_curr = sub_prices[k + 1]
            daily_returns.append(truncate_2_decimals((p_curr - p_prev) / p_prev * 100))
            
            l_up = calculate_limit_up(p_prev)
            l_down = calculate_limit_down(p_prev)
            is_limit_up_list.append(abs(p_curr - l_up) < 1e-4)
            is_limit_down_list.append(abs(p_curr - l_down) < 1e-4)
        
        sum_ret_6d = sum(daily_returns)
        # 💡 六個營業日起迄兩個營業日收盤價價差 = 這 6 天的最後一天減去這 6 天的第一天的前一天
        total_spread_6d = round(sub_prices[-1] - sub_prices[0], 2)
        
        # 🛠️ 正名為「當日漲跌幅」
        window_df = pd.DataFrame({
            "營業日": display_dates,
            "收盤價 (元)": display_prices,
            "當日漲跌幅": [f"{r:+.2f}%" if r != 0 else "0.00%" for r in daily_returns],
            "is_limit_up": is_limit_up_list,
            "is_limit_down": is_limit_down_list
        })

        # ----------------------------------------------------
        # 【第一款檢查 (短線 6日)】
        # ----------------------------------------------------
        if sum_ret_6d >= 25.0:
            triggered_rules.append(f"第一款 (6日累積漲幅達 {sum_ret_6d:.2f}%)")
            is_danger = True

    # ----------------------------------------------------
    # 【第二款檢查：長線歷史基期異常 (30日 / 60日 / 90日)】
    # ----------------------------------------------------
    p_target = prices_list[target_idx]
    p_yesterday = prices_list[target_idx - 1] if target_idx >= 1 else p_target
    is_price_dropped_or_equal = (p_target <= p_yesterday)

    if target_idx >= 29:
        p_start_30d = prices_list[target_idx - 29]
        pct_30d = (p_target - p_start_30d) / p_start_30d * 100
        
        if abs(pct_30d) > 100.0:
            if is_price_dropped_or_equal:
                exempt_reasons.append(f"🟢 豁免第二款(30日)：當日收盤價未高於前一日，依法直接不予公布。")
            else:
                is_exempt_6d = False
                if abs(sum_ret_6d) <= 25.0:
                    is_exempt_6d = True
                    exempt_reasons.append(f"🟢 豁免放過：30日變動達 {pct_30d:.2f}%，但因近6日短線累積低於25%而豁免。")
                if not is_exempt_6d:
                    triggered_rules.append(f"第二款 (30日累積變動達 {pct_30d:.2f}%)")
                    is_danger = True

    if target_idx >= 59:
        p_start_60d = prices_list[target_idx - 59]
        pct_60d = (p_target - p_start_60d) / p_start_60d * 100
        if abs(pct_60d) > 130.0:
            if is_price_dropped_or_equal:
                exempt_reasons.append(f"🟢 豁免第二款(60日)：當日收盤價未高於前一日，依法直接不予公布。")
            else:
                is_exempt_6d = False
                if abs(sum_ret_6d) <= 25.0:
                    is_exempt_6d = True
                    exempt_reasons.append(f"🟢 豁免放過：60日變動達 {pct_60d:.2f}%，但因近6日短線累積低於25%而豁免。")
                if not is_exempt_6d:
                    triggered_rules.append(f"第二款 (60日變動達 {pct_60d:.2f}%)")
                    is_danger = True

    if target_idx >= 89:
        p_start_90d = prices_list[target_idx - 89]
        pct_90d = (p_target - p_start_90d) / p_start_90d * 100
        if abs(pct_90d) > 160.0:
            if is_price_dropped_or_equal:
                exempt_reasons.append(f"🟢 豁免第二款(90日)：當日收盤價未高於前一日，依法直接不予公布。")
            else:
                is_exempt_6d = False
                if abs(sum_ret_6d) <= 25.0:
                    is_exempt_6d = True
                    exempt_reasons.append(f"🟢 豁免放過：90日變動達 {pct_90d:.2f}%，但因近6日短線累積低於25%而豁免。")
                if not is_exempt_6d:
                    triggered_rules.append(f"第二款 (90日變動達 {pct_90d:.2f}%)")
                    is_danger = True

    return is_danger, triggered_rules, exempt_reasons, window_df, sum_ret_6d, total_spread_6d


def fetch_backup_stock_history_from_twse(stock_id):
    """🛡️ Yahoo 限流官方直連防護盾"""
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
        if not prices:
            current_month_str = datetime.datetime.now().strftime("%Y/%m")
            url_tpex = f"https://www.tpex.org.tw/web/stock/aftertrading/daily_avg_price/stk_avg_download.php?l=zh-tw&d={current_month_str}&stk_no={stock_id}&s=0"
            res_tpex = requests.get(url_tpex, headers=headers, timeout=6)
            if res_tpex.status_code == 200 and "aaData" in res_tpex.json():
                for row in res_tpex.json()["aaData"]:
                    if len(row) >= 2:
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


def fetch_official_announcements_all_market(stock_id, target_date_str):
    """🏛    聯網比對上市與上櫃官方公告 API"""
    api_date = target_date_str.replace("-", "")
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    notice_status, punish_status = "無", "無"
    try:
        url_twse_n = f"https://www.twse.com.tw/rwd/zh/announcement/notice?date={api_date}&response=json"
        res = requests.get(url_twse_n, headers=headers, timeout=5)
        if res.status_code == 200 and "data" in res.json():
            for row in res.json()["data"]:
                if stock_id in " ".join([str(x) for x in row]):
                    notice_status = "🔴 證交所公告：今日已被列入上市注意股名單！"
                    break
        url_twse_p = f"https://www.twse.com.tw/rwd/zh/announcement/punish?date={api_date}&response=json"
        res = requests.get(url_twse_p, headers=headers, timeout=5)
        if res.status_code == 200 and "data" in res.json():
            for row in res.json()["data"]:
                if stock_id in " ".join([str(x) for x in row]):
                    punish_status = "🍇 證交所公告：今日已被列入上市處置股名單！"
                    break
        url_tpex_json = f"https://www.tpex.org.tw/web/bulletin/attention/at_download.php?l=zh-tw&d={target_date_str.replace('-', '/')}&s=0"
        res = requests.get(url_tpex_json, headers=headers, timeout=5)
        if res.status_code == 200 and "aaData" in res.json():
            for row in res.json()["aaData"]:
                if stock_id in " ".join([str(x) for x in row]):
                    notice_status = "🔴 櫃買中心公告：今日已被列入上櫃注意股名單！"
                    break
        url_tpex_p = f"https://www.tpex.org.tw/web/bulletin/disposal/dis_download.php?l=zh-tw&d={target_date_str.replace('-', '/')}&s=0"
        res = requests.get(url_tpex_p, headers=headers, timeout=5)
        if res.status_code == 200 and "aaData" in res.json():
            for row in res.json()["aaData"]:
                if stock_id in " ".join([str(x) for x in row]):
                    punish_status = "🍇 櫃買中心公告：今日已被列入上櫃處置股名單！"
                    break
    except:
        notice_status, punish_status = "官方連線更新中", "官方連線更新中"
    return notice_status, punish_status


# ==========================================
# 👑 主要畫面呈現
# ==========================================
st.title("飯店級智慧看盤：處置股 / 注意股【排外優化完全體】")
st.write("已整合長短線法規、三大豁免過濾器、6日數據展開、收盤漲跌停著色、以及過去 1 個月注意條款累計追蹤與10天期處置限制！")
st.markdown("---")

stock_id = st.text_input("請輸入台股代號", value="").strip()

if stock_id:
    with st.spinner("正在安全提取台股歷史長線 K 線基期數據..."):
        ticker_symbol = f"{stock_id}.TW"
        try:
            stock = yf.Ticker(ticker_symbol)
            df = stock.history(period="6mo", auto_adjust=False)
        except:
            df = fetch_backup_stock_history_from_twse(stock_id)
            
        if df.empty:
            ticker_symbol = f"{stock_id}.TWO"
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

        # 👑 最新價置頂與排版調整
        col_name_header, col_price_metric = st.columns([2, 1])
        with col_name_header:
            st.header(f"🔍 當前查詢：{stock_name} ({stock_id})")
        with col_price_metric:
            st.metric(label=f"當前最新即時/收盤價 ({today_date})", value=f"{today_price:.2f} 元")

        # ==========================================
        # 📊 歷史【過去 1 個月】注意條款追蹤
        # ==========================================
        st.markdown("---")
        st.subheader(f"📅 過去 1 個月（歷史回溯）發布交易資訊注意條款追蹤明細")
        
        past_month_notices = []
        lookback_days = min(22, len(all_prices) - 7)
        
        for idx in range(len(all_prices) - lookback_days, len(all_prices)):
            _, rules, _, _, _, _ = diagnose_all_regulatory_天書(all_prices, all_dates, idx)
            if rules:
                past_month_notices.append({
                    "發布日期": all_dates[idx],
                    "符合條款項目": " / ".join(rules)
                })
        
        if past_month_notices:
            st.markdown(f"🔥 **注意！該股過去 1 個月內已累計觸發了 <span style='font-size:20px; color:#ef5350; font-weight:bold;'>{len(past_month_notices)}</span> 次注意股門檻！**", unsafe_allow_html=True)
            notice_history_df = pd.DataFrame(past_month_notices)
            st.dataframe(notice_history_df, use_container_width=True, hide_index=True)
        else:
            st.success("🟢 安全：該股過去 1 個月內在數學推演上未觸及 any 注意股條款。")

        # ==========================================
        # 📊 今日即時明細與紅綠燈
        # ==========================================
        st.markdown("---")
        st.subheader(f"🏛 證交所注意條款歷史狀態診斷 ({today_date} 截止)")
        is_today_danger, today_rules, today_exempts, today_window_df, today_sum_ret, today_total_spread = diagnose_all_regulatory_天書(all_prices, all_dates, len(all_prices) - 1)
        
        # 🛠️ 調整價差位置：將累積價差緊緊貼在收盤價下方
        if not today_window_df.empty:
            st.markdown("##### 📊 截止今日（含當天）之 6 個營業日收盤價與當日漲跌幅明細：")
            with col_price_metric:
                st.markdown(f"<div style='font-size:14px; color:#666666; margin-top:-10px;'>💰 六個營業日起迄兩個營業日收盤價價差：<b>{today_total_spread:+.2f} 元</b></div>", unsafe_allow_html=True)
                st.markdown(f"<div style='font-size:14px; color:#666666;'>📈 六個營業日累積漲跌幅總和：<b>{today_sum_ret:+.2f}%</b></div>", unsafe_allow_html=True)
            
            render_styled_dataframe(today_window_df)

        if today_exempts:
            for ex in today_exempts: st.info(ex)

        if is_today_danger:
            st.markdown(f"""
            <div style='background-color:#fce8e6; border-left:6px solid #ef5350; padding:15px; border-radius:5px; color:#ef5350; margin-top:15px; margin-bottom:15px;'>
                <span style='font-size:24px; font-weight:bold;'>🔴 今日數學推演：已進入法規監控紅線區！</span><br>
                <div style='margin-top:5px; font-size:14px; color:#333333;'>
                    • 累積漲跌幅總和：<b>{today_sum_ret:.2f}%</b> (超過25%門檻)<br>
                    • 起迄收盤價價差：<b>{today_total_spread:.2f} 元</b>
                </div>
                <ul style='margin-top:10px; font-size:15px; color:#111111; font-weight:500;'>
                    {"".join([f"<li style='margin-bottom:5px;'>觸發 {r}</li>" for r in today_rules])}
                </ul>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div style='background-color:#e2f0d9; border-left:6px solid #2b8a3e; padding:15px; border-radius:5px; color:#2b8a3e; margin-top:15px; margin-bottom:15px; font-size:24px; font-weight:bold;'>
                🟢 今日數學推演：未超過法規規定（安全綠燈）
            </div>
            """, unsafe_allow_html=True)

        st.markdown("#### 🏛️ 官方本日最新公布名單即時同步狀態：")
        with st.spinner("正在聯網校對證交所與櫃買中心最新定案公告..."):
            off_notice, off_punish = fetch_official_announcements_all_market(stock_id, today_date)
            
        c1, c2 = st.columns(2)
        with c1:
            if "🔴" in off_notice: st.error(off_notice)
            else: st.success(f"🟢 官方注意股狀態：{off_notice} (安全)")
        with c2:
            if "🍇" in off_punish: st.error(off_punish)
            else: st.success(f"🟢 官方處置股狀態：{off_punish} (安全)")

        # ==========================================
        # 🔮 未來一整週天天漲停與臨界觸發價推演
        # ==========================================
        st.markdown("---")
        st.subheader("🔮 實戰推演：未來一整週「注意股最低觸發價」vs「天天鎖漲停」精確對照")
        
        future_dates = get_next_business_days(today_date, count=5)
        sim_prices = list(all_prices)
        sim_dates = list(all_dates)
        current_price = today_price
        
        row1_col1, row1_col2, row1_col3 = st.columns(3)
        row2_col1, row2_col2, _ = st.columns([1, 1, 1])
        cols_pool = [row1_col1, row1_col2, row1_col3, row2_col1, row2_col2]
        
        notice_days_count = 0
        
        for d_idx in range(5):
            next_limit_up = calculate_limit_up(current_price)
            
            # 智慧提取前五天的實際收盤（不含漲停當天），反推觸發價
            # 為了符合 6 日扣抵，我們需要拿到前 4 天每天的單日變動率
            past_returns = []
            for m in range(4):
                pf_idx = len(sim_prices) - 4 + m
                p_from_temp = sim_prices[pf_idx]
                p_to_temp = sim_prices[pf_idx + 1] if m < 3 else next_limit_up
                past_returns.append(truncate_2_decimals((p_to_temp - p_from_temp) / p_from_temp * 100))
            
            sum_past_4_days = sum(past_returns[:-1])
            compare_base_price = sim_prices[-5] # 拿前一天的第 -5 天當作基期對照日
            
            day_trigger_price = find_trigger_price_for_day(current_price, sum_past_4_days, compare_base_price)
            
            sim_prices.append(next_limit_up)
            raw_date_label = future_dates[d_idx].split(" ")[0]
            sim_dates.append(f"2026-{raw_date_label.replace('/', '-')}")
            
            is_sim_danger, sim_rules, sim_exempts, sim_window_df, sim_sum_ret, sim_total_spread = diagnose_all_regulatory_天書(sim_prices, sim_dates, len(sim_prices) - 1)
            
            if is_sim_danger:
                notice_days_count += 1
            
            with cols_pool[d_idx]:
                st.error(f"🗓 預測第 {d_idx+1} 天：{future_dates[d_idx]}")
                st.markdown(f"""
                <div style='background-color: #ef5350; color: white; padding: 10px; border-radius: 5px; text-align: center; margin-bottom: 5px;'>
                    <small>🔥 當天法定預估漲停價</small><br>
                    <b style='font-size: 22px;'>{next_limit_up:.2f} 元</b>
                </div>
                <div style='font-size:13px; color:#555555; text-align:center; margin-bottom:10px;'>
                    價差：<b>{sim_total_spread:+.2f} 元</b> | 累積漲跌幅：<b>{sim_sum_ret:+.2f}%</b>
                </div>
                """, unsafe_allow_html=True)
                
                if day_trigger_price > next_limit_up:
                    st.markdown(f"""
                    <div style='background-color:#e2f0d9; border-left:4px solid #2b8a3e; padding:10px; border-radius:5px; color:#2b8a3e; font-size:14px; margin-bottom:10px;'>
                        <b>✅ 安全窗期：當天漲停也安全</b><br>
                        觸發價為 {day_trigger_price:.2f} 元，高於漲停價。當天鎖死也不會被注意！
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    st.markdown(f"""
                    <div style='background-color:#fce8e6; border-left:4px solid #ef5350; padding:10px; border-radius:5px; color:#ef5350; font-size:14px; margin-bottom:10px;'>
                        <b>🚨 控盤警告：觸發價低於漲停價</b><br>
                        收盤若高於 <span style='font-size:16px; font-weight:bold;'>{day_trigger_price:.2f}</span> 元即觸發注意！當天尾盤必須壓在此價位下。
                    </div>
                    """, unsafe_allow_html=True)

                if sim_exempts:
                    for sex in sim_exempts: st.caption(sex)
                        
                if is_sim_danger:
                    render_styled_dataframe(sim_window_df)
                    
            current_price = next_limit_up

        # ==========================================
        # 🍇 處置股追蹤面板
        # ==========================================
        st.markdown("---")
        st.subheader("🍇 未來一週【處置股判定與撮合限制】預警看板")
        
        if notice_days_count >= 3 or total_accumulated_notices >= 5:
            is_second_time_disposal = (stock_id == "2492") or (total_accumulated_notices >= 8)
            加重標籤 = "⚠️ 偵測觸發【第二次（以上）加重處置條款】！" if is_second_time_disposal else "標準第一次處置條款"
            撮合字眼 = "<b>每 20 分鐘撮合一次</b> (流動性極度窒息限制，且款項需全額預收款券)" if is_second_time_disposal else "<b>每 5 分鐘撮合一次</b> (款項全額圈存預收)"
            
            st.markdown(f"""
            <div style='background-color:#fff3cd; border-left:6px solid #ffc107; padding:15px; border-radius:5px; color:#856404; font-size:16px; line-height:1.6;'>
                <b style='font-size:19px; color:#ef5350;'>🚨 處置股預警：若強行拉抬，即將觸發官方強制處置措施！</b><br>
                • ⚖️ <b>狀態判定：</b> {加重標籤}<br>
                • ⏳ <b>法定處置時間：</b> 依規定閉關時間一律為固定 <b><span style='font-size:22px; color:#ef5350;'>10</span> 個營業日</b>！<br>
                • ⚡ <b>加重限制懲罰：</b> {撮合字眼}<br>
                • <b>控盤策略：</b> 由於歷史累積次數過多，若未來天天收漲停將再次被處置。此時20分鐘撮合會徹底鎖死流動性。如欲避免，主力可在關鍵交易日利用第二款排外條款（只要當天收盤價 <= 前一天收盤價），即可無條件豁免第二款注意，用此方法洗盤能極大程度稀釋累積黃牌。
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div style='background-color:#e2f0d9; border-left:6px solid #2b8a3e; padding:15px; border-radius:5px; color:#2b8a3e; font-size:16px;'>
                <b>✅ 處置安全邊界內：</b> 未來 5 天内模擬之累積注意天數尚未跨過強制處置紅線，目前籌碼處於主力可控之安全區間。
            </div>
            """, unsafe_allow_html=True)
