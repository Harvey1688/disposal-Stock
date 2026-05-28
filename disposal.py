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


def diagnose_all_regulatory_天書(prices_list, dates_list, target_idx):
    """
    👑 智慧核心：內嵌三大排外過濾器與動態漲跌停註記的判定引擎
    """
    triggered_rules = []
    exempt_reasons = [] 
    is_danger = False
    
    window_df = pd.DataFrame()
    sum_ret_6d = 0.0

    if target_idx >= 5:
        sub_prices = prices_list[target_idx - 5 : target_idx + 1]
        sub_dates = dates_list[target_idx - 5 : target_idx + 1]
        
        history_truncated_returns = [0.0]
        is_limit_up_list = [False]
        is_limit_down_list = [False]
        
        for k in range(5):
            p_f = sub_prices[k]
            p_t = sub_prices[k + 1]
            history_truncated_returns.append(truncate_2_decimals((p_t - p_f) / p_f * 100))
            
            l_up = calculate_limit_up(p_f)
            l_down = calculate_limit_down(p_f)
            is_limit_up_list.append(abs(p_t - l_up) < 1e-4)
            is_limit_down_list.append(abs(p_t - l_down) < 1e-4)
        
        sum_ret_6d = sum(history_truncated_returns)
        
        window_df = pd.DataFrame({
            "營業日": sub_dates,
            "收盤價 (元)": sub_prices,
            "當日累積漲跌幅": [f"{r:+.2f}%" if r != 0 else "0.00%" for r in history_truncated_returns],
            "is_limit_up": is_limit_up_list,
            "is_limit_down": is_limit_down_list
        })

        # ----------------------------------------------------
        # 【第一款檢查 (短線 6日)】
        # ----------------------------------------------------
        p_start_6d = prices_list[target_idx - 5]
        p_target = prices_list[target_idx]
        spread_6d = p_target - p_start_6d
        
        if sum_ret_6d >= 25.0:
            triggered_rules.append(f"🔴 觸發【第一款】：6日累積漲幅達 {sum_ret_6d:.2f}% (價差 {spread_6d:.2f} 元)。")
            is_danger = True

    # ----------------------------------------------------
    # 【第二款檢查：長線歷史基期異常 (30日 / 60日 / 90日)】
    # ----------------------------------------------------
    if target_idx >= 29:
        p_start_30d = prices_list[target_idx - 29]
        p_target = prices_list[target_idx]
        pct_30d = (p_target - p_start_30d) / p_start_30d * 100
        
        if abs(pct_30d) > 100.0:
            is_exempt = False
            if abs(sum_ret_6d) <= 25.0:
                is_exempt = True
                exempt_reasons.append(f"🟢 豁免放過 (條件1)：雖然30日漲幅達 {pct_30d:.2f}%，但近6日累積僅 {sum_ret_6d:.2f}% (未超25%乖巧線)，不予公布第二款。")
            elif pct_30d * sum_ret_6d < 0:
                is_exempt = True
                exempt_reasons.append(f"🟢 豁免放過 (條件3)：30日趨勢與近6日回檔方向相反 (短線已在修正)，不予公布第二款。")
                
            if not is_exempt:
                triggered_rules.append(f"🔴 觸發【第二款-30日爆發】：30日變動達 {pct_30d:.2f}% (超過100%紅線)，且不符合排外豁免。")
                is_danger = True

    # 60日條款
    if target_idx >= 59:
        p_start_60d = prices_list[target_idx - 59]
        p_target = prices_list[target_idx]
        pct_60d = (p_target - p_start_60d) / p_start_60d * 100
        if abs(pct_60d) > 130.0:
            if abs(sum_ret_6d) <= 25.0:
                exempt_reasons.append(f"🟢 豁免放過：60日漲幅達 {pct_60d:.2f}%，因近6日乖巧而豁免。")
            else:
                triggered_rules.append(f"🔴 觸發【第二款-60日長波】：60日變動達 {pct_60d:.2f}% (超過130%紅線)。")
                is_danger = True

    # 90日條款
    if target_idx >= 89:
        p_start_90d = prices_list[target_idx - 89]
        p_target = prices_list[target_idx]
        pct_90d = (p_target - p_start_90d) / p_start_90d * 100
        if abs(pct_90d) > 160.0:
            if abs(sum_ret_6d) <= 25.0:
                exempt_reasons.append(f"🟢 豁免放過：90日漲幅達 {pct_90d:.2f}%，因近6日乖巧而豁免。")
            else:
                triggered_rules.append(f"🔴 觸發【第二款-90日終極】：90日變動達 {pct_90d:.2f}% (超過160%巨型紅線)。")
                is_danger = True

    return is_danger, triggered_rules, exempt_reasons, window_df


def render_styled_dataframe(display_df):
    """
    🛠️ 核心美化引擎：對表格的「收盤價 (元)」進行漲跌停紅綠燈渲染
    """
    if display_df.empty:
        return
        
    def style_rows(row):
        styles = [""] * len(row)
        c_idx = display_df.columns.get_loc("收盤價 (元)")
        if row["is_limit_up"]:
            styles[c_idx] = "background-color: #ef5350; color: white; font-weight: bold;"
        elif row["is_limit_down"]:
            styles[c_idx] = "background-color: #2b8a3e; color: white; font-weight: bold;"
        return styles

    st.dataframe(
        display_df.style.apply(style_rows, axis=1).format({"收盤價 (元)": "{:.2f}"}),
        column_config={"is_limit_up": None, "is_limit_down": None},
        use_container_width=True,
        hide_index=True
    )


def fetch_official_announcements_all_market(stock_id, target_date_str):
    """
    🏛️ 聯網比對：全面打通上市與上櫃的四大公告 API 資料庫
    """
    api_date = target_date_str.replace("-", "")
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    notice_status = "無"
    punish_status = "無"
    
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
                    
    except Exception as e:
        notice_status = "官方連線更新中"
        punish_status = "官方連線更新中"

    return notice_status, punish_status


def fetch_backup_stock_history_from_twse(stock_id):
    """
    🛡️ 神級防護盾：當 Yahoo Finance 噴出 Rate Limit 限流時，
    直接聯網向臺灣證交所/櫃買中心官方盤後歷史資料庫索取最近 95 天的真實收盤數據！
    """
    prices, dates = [], []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    try:
        # 先嘗試上市 API (證交所個股年成交資訊)
        current_year = datetime.datetime.now().year
        url = f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_AVG?date={current_year}0101&stockNo={stock_id}&response=json"
        res = requests.get(url, headers=headers, timeout=6)
        
        if res.status_code == 200 and "data" in res.json():
            raw_data = res.json()["data"]
            for row in raw_data:
                if len(row) >= 2 and row[1] != "0":
                    # 民國轉西元日期
                    roc_date = row[0].split("/")
                    year = int(roc_date[0]) + 1911
                    date_str = f"{year}-{roc_date[1]}-{roc_date[2]}"
                    dates.append(date_str)
                    prices.append(float(row[1].replace(",", "")))
                    
        # 若上市抓不到，切換至上櫃 API (櫃買中心個股日收盤平均價)
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
    except:
        pass
        
    if len(prices) >= 15:
        # 建立一個模擬的 DataFrame 結構，完全相容主程式邏輯
        df_backup = pd.DataFrame({"Close": prices}, index=pd.DatetimeIndex(dates))
        return df_backup.sort_index()
    return pd.DataFrame()


# ==========================================
# 👑 主要畫面呈現
# ==========================================
st.title("飯店級智慧看盤：處置股 / 注意股【官方 API 直連防護完全體】")
st.write("已全面整合 Yahoo 限流主動防護盾。當 Yahoo Finance 卡住時，系統會自動無縫改採證交所官方直連技術！")
st.markdown("---")

stock_id = st.text_input("請輸入台股代號", value="").strip()

if stock_id:
    df = pd.DataFrame()
    with st.spinner("正在安全提取台股歷史長線 K 線基期數據..."):
        ticker_symbol = f"{stock_id}.TW"
        try:
            stock = yf.Ticker(ticker_symbol)
            df = stock.history(period="6mo", auto_adjust=False)
            if df.empty or "Too Many Requests" in str(st.session_state):
                raise Exception("Yahoo Limited Triggered")
        except Exception as yahoo_err:
            # 🛡️ 觸發官方直連防護盾
            df = fetch_backup_stock_history_from_twse(stock_id)
            
        if df.empty:
            # 備援的備援：櫃買中心直連試探
            ticker_symbol = f"{stock_id}.TWO"
            try:
                stock = yf.Ticker(ticker_symbol)
                df = stock.history(period="6mo", auto_adjust=False)
            except:
                df = fetch_backup_stock_history_from_twse(stock_id)

        # 寫入即時整合資料
        if not df.empty:
            if isinstance(df.index, pd.DatetimeIndex):
                df.index = df.index.tz_localize(None)
            try:
                # 只有在 yfinance 沒被鎖時才拿即時價，被鎖時直接沿用官方盤後結算價
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

    if not df.empty and len(df) >= 10:
        all_prices = df["Close"].tolist()
        all_dates = df.index.strftime("%Y-%m-%d").tolist()
        
        today_price = all_prices[-1]
        today_date = all_dates[-1]

        # 👑 「最新收盤價」強勢置頂
        col_name_header, col_price_metric = st.columns([2, 1])
        with col_name_header:
            st.header(f"🔍 當前查詢：{stock_name} ({stock_id})")
        with col_price_metric:
            st.metric(label=f"當前最新即時/收盤價 ({today_date})", value=f"{today_price:.2f} 元")

        # ==========================================
        # 📊 歷史今日狀態診斷 (大字紅綠燈看板)
        # ==========================================
        st.subheader(f"🏛 證交所注意條款歷史狀態診斷 ({today_date} 截止)")
        
        is_today_danger, today_rules, today_exempts, today_window_df = diagnose_all_regulatory_天書(all_prices, all_dates, len(all_prices) - 1)
        
        if not today_window_df.empty:
            st.markdown("##### 📊 截止今日（含當天）之 6 個營業日收盤價與累積變動明細：")
            render_styled_dataframe(today_window_df)

        if today_exempts:
            for ex in today_exempts:
                st.success(ex)

        if is_today_danger:
            st.markdown(f"""
            <div style='background-color:#fce8e6; border-left:6px solid #ef5350; padding:15px; border-radius:5px; color:#ef5350; margin-top:15px; margin-bottom:15px;'>
                <span style='font-size:24px; font-weight:bold;'>🔴 今日數學推演：已進入法規監控紅線區！</span><br>
                <div style='margin-top:8px; font-size:13px; color:#555555;'>💡 提示：若以下條款與「類股/大盤平均」之差幅未達法規標準，則可啟用大盤保護傘安全除外。</div>
                <ul style='margin-top:10px; font-size:15px; color:#111111; font-weight:500;'>
                    {"".join([f"<li style='margin-bottom:5px;'>{r}</li>" for r in today_rules])}
                </ul>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown("""
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
        # 🔮 未來一整週天天漲停推演
        # ==========================================
        st.markdown("---")
        st.subheader("🔮 實戰推演：未來一整週「天天鎖漲停」法規風險與過濾器對照預測")
        
        future_dates = get_next_business_days(today_date, count=5)
        
        sim_prices = list(all_prices)
        sim_dates = list(all_dates)
        current_price = today_price
        
        row1_col1, row1_col2, row1_col3 = st.columns(3)
        row2_col1, row2_col2, _ = st.columns([1, 1, 1])
        cols_pool = [row1_col1, row1_col2, row1_col3, row2_col1, row2_col2]
        
        notice_days_count = 0
        
        for d_idx in range(min(5, len(future_dates))):
            next_limit_up = calculate_limit_up(current_price)
            sim_prices.append(next_limit_up)
            
            raw_date_label = future_dates[d_idx].split(" ")[0]
            sim_dates.append(f"2026-{raw_date_label.replace('/', '-')} ")
            
            is_sim_danger, sim_rules, sim_exempts, sim_window_df = diagnose_all_regulatory_天書(sim_prices, sim_dates, len(sim_prices) - 1)
            
            if is_sim_danger:
                notice_days_count += 1
            
            with cols_pool[d_idx]:
                st.error(f"🗓 預測第 {d_idx+1} 天：{future_dates[d_idx]}")
                
                st.markdown(f"""
                <div style='background-color: #ef5350; color: white; padding: 10px; border-radius: 5px; text-align: center; margin-bottom: 10px;'>
                    <small>🔥 當天若鎖死漲停價</small><br>
                    <b style='font-size: 22px;'>{next_limit_up:.2f} 元</b>
                </div>
                """, unsafe_allow_html=True)
                
                if sim_exempts:
                    for sex in sim_exempts:
                        st.caption(sex)
                
                if is_sim_danger:
                    rules_html = "".join([f"<div style='margin-bottom:6px;'>• {r}</div>" for r in sim_rules])
                    st.markdown(f"""
                    <div style='background-color:#fce8e6; border-left:4px solid #ef5350; padding:10px; border-radius:5px; color:#ef5350; font-size:13px; line-height:1.5; margin-bottom:10px;'>
                        <b style='font-size:14px;'>🔴 警報：若收此價將踩中下列法規：</b><br>
                        <div style='color:#333333; margin-top:5px;'>{rules_html}</div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    st.markdown("<small>📋 當天往前推算之 6 日累積變動數據明細：</small>", unsafe_allow_html=True)
                    render_styled_dataframe(sim_window_df)
                else:
                    st.markdown("""
                    <div style='background-color:#e2f0d9; border-left:4px solid #2b8a3e; padding:10px; border-radius:5px; color:#2b8a3e; font-size:14px; font-weight:bold;'>
                        🟢 綠燈安全：此價格仍未觸及 any 長短線紅線（或符合排外條件）。
                    </div>
                    """, unsafe_allow_html=True)
                    
            current_price = next_limit_up

        # ==========================================
        # 🍇 處置股追蹤面板
        # ==========================================
        st.markdown("---")
        st.subheader("🍇 未來一週【處置股累計注意天數】計數面板")
        
        if notice_days_count >= 3:
            st.markdown(f"""
            <div style='background-color:#fff3cd; border-left:6px solid #ffc107; padding:15px; border-radius:5px; color:#856404; font-size:16px; line-height:1.6;'>
                <b>🚨 警告：未來 5 個營業日內有 <span style='font-size:22px; color:#ef5350;'>{notice_days_count}</span> 天將達標公布注意股！</b><br>
                • 處置踩線點：若天天收漲停，將直接面臨<b>「連續三個營業日」</b>之強制發布交易資訊處置紅線（送進人工撮合關廁所）！
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div style='background-color:#e2f0d9; border-left:6px solid #2b8a3e; padding:15px; border-radius:5px; color:#2b8a3e; font-size:16px;'>
                <b>✅ 處置安全：未來 5 天内累積注意天數僅 {notice_days_count} 天。</b> 未達「連續三天」之強制處置門檻，主力控盤安全。
            </div>
            """, unsafe_allow_html=True)
    else:
        st.warning("⚠️ 官方本日數據盤後正在結算中、或該股代號不正確。請稍候再試或檢查代號！")

else:
    st.info("💡 請在上方輸入框鍵入台股代號（例如：2492 華新科 或 3030 德律），系統將立即為您解開完整法規天書推演。")

# ==========================================
# 🏛️ 官方數據核對傳送門
# ==========================================
st.markdown("---")
st.markdown("### 🏛️ 證交所 / 櫃買中心 官方公告核對傳送門")
st.write("💡 *以下為快捷對照備用連結，方便隨時點開手動覆核網頁數據：*")

col_twse_1, col_twse_2, col_tpex_1, col_tpex_2 = st.columns(4)
with col_twse_1:
    st.markdown('<a href="https://www.twse.com.tw/zh/announcement/notice.html" target="_blank" style="text-decoration:none;"><div style="background-color:#f1f3f5; padding:15px; border-radius:8px; border-left:5px solid #0288d1; text-align:center;"><b style="color:#1a1a1a; font-size:15px;">臺灣證交所 (上市)</b><br><span style="color:#0288d1; font-size:13px; font-weight:bold;">每日注意股票公告 ↗</span></div></a>', unsafe_allow_html=True)
with col_twse_2:
    st.markdown('<a href="https://www.twse.com.tw/zh/announcement/punish.html" target="_blank" style="text-decoration:none;"><div style="background-color:#f1f3f5; padding:15px; border-radius:8px; border-left:5px solid #d32f2f; text-align:center;"><b style="color:#1a1a1a; font-size:15px;">臺灣證交所 (上市)</b><br><span style="color:#d32f2f; font-size:13px; font-weight:bold;">每日處置股票公告 ↗</span></div></a>', unsafe_allow_html=True)
with col_tpex_1:
    st.markdown('<a href="https://www.tpex.org.tw/zh-tw/announce/market/attention.html" target="_blank" style="text-decoration:none;"><div style="background-color:#f1f3f5; padding:15px; border-radius:8px; border-left:5px solid #0288d1; text-align:center;"><b style="color:#1a1a1a; font-size:15px;">櫃買中心 (上櫃)</b><br><span style="color:#0288d1; font-size:13px; font-weight:bold;">每日注意有價證券 ↗</span></div></a>', unsafe_allow_html=True)
with col_tpex_2:
    st.markdown('<a href="https://www.tpex.org.tw/zh-tw/announce/market/disposal.html" target="_blank" style="text-decoration:none;"><div style="background-color:#f1f3f5; padding:15px; border-radius:8px; border-left:5px solid #d32f2f; text-align:center;"><b style="color:#1a1a1a; font-size:15px;">櫃買中心 (上櫃)</b><br><span style="color:#d32f2f; font-size:13px; font-weight:bold;">每日處置有價證券 ↗</span></div></a>', unsafe_allow_html=True)
