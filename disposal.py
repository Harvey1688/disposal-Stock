import datetime
import math
import pandas as pd
import requests
import streamlit as st
import yfinance as yf

# 設定網頁標題與風格 (滿版模式)
st.set_page_config(page_title="處置股/注意股 一週價位預測器", layout="wide")


def truncate_2_decimals(n):
    """將數字無條件捨去至小數點後第二位（往 0 的方向捨去）"""
    if n >= 0:
        return math.floor(n * 100) / 100
    else:
        return math.ceil(n * 100) / 100


def calculate_limit_up(price):
    """根據台灣證券交易所的升降單位(Tick Size)與單日10%限制，精確計算漲停價"""
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
    """根據台灣證券交易所的升降單位(Tick Size)與單日10%限制，精確計算跌停價（需無條件進位）"""
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
    """結合證交所官方行事曆，自動跳過例假日與國定休假日"""
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
        
        is_weekend = current_date.weekday() >= 5
        is_twse_holiday = date_iso in twse_holidays
        
        if not is_weekend and not is_twse_holiday:
            weekday_cc = ["一", "二", "三", "四", "五", "六", "日"]
            cc_str = weekday_cc[current_date.weekday()]
            business_days.append(f"{current_date.strftime('%m/%d')} (星期{cc_str})")

    return business_days


def check_disposal_condition(sum_ret, spread):
    """判定是否達到注意股門檻二"""
    return sum_ret >= 25.0 and spread >= 50.0


def fetch_twse_notices_and_punishes(stock_id, target_date_str):
    """對接證交所官方開放 JSON API 資料庫"""
    api_date = target_date_str.replace("-", "")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    notice_info, punish_info = "無", "無"
    
    try:
        api_notice_url = f"https://www.twse.com.tw/rwd/zh/announcement/notice?date={api_date}&response=json"
        res_n = requests.get(api_notice_url, headers=headers, timeout=5)
        if res_n.status_code == 200:
            data_n = res_n.json()
            if "data" in data_n:
                for row in data_n["data"]:
                    if stock_id in " ".join([str(x) for x in row]):
                        notice_info = "🔴 已列入官方注意股名單！"
                        break

        api_punish_url = f"https://www.twse.com.tw/rwd/zh/announcement/punish?date={api_date}&response=json"
        res_p = requests.get(api_punish_url, headers=headers, timeout=5)
        if res_p.status_code == 200:
            data_p = res_p.json()
            if "data" in data_p:
                for row in data_p["data"]:
                    if stock_id in " ".join([str(x) for x in row]):
                        punish_info = "🍇 警告：已正式列入官方處置股票名單！"
                        break
    except:
        notice_info, punish_info = "官方連線異常", "官方連線異常"

    return notice_info, punish_info


def find_trigger_price_for_day(base_price, sum_past_4, compare_base_price):
    """精確反推當天要達到門檻二所需要的最低注意觸發價"""
    price_by_spread = compare_base_price + 50
    req_ret = 25.0 - sum_past_4
    price_by_ret = base_price * (1 + req_ret / 100)
    
    trigger_price = max(price_by_spread, price_by_ret)
    
    if trigger_price < 10: tick = 0.01
    elif trigger_price < 50: tick = 0.05
    elif trigger_price < 100: tick = 0.1
    elif trigger_price < 500: tick = 0.5
    elif trigger_price < 1000: tick = 1.0
    else: tick = 5.0
    
    final_trigger = math.ceil(trigger_price / tick) * tick
    return round(final_trigger, 2)


# ==========================================
# 👑 核心主要畫面區塊
# ==========================================
st.title("📈 處置股 / 注意股【一整週】雙指標實戰預測器")
st.write("自動抓取收盤價，模擬**「天天鎖漲停」**與**「注意股觸發價」**之雙重對照。支援盤中與剛收盤最新即時價捕獲！")
st.markdown("---")

stock_id = st.text_input("請輸入台股代號", value="").strip()

if stock_id:
    with st.spinner("正在安全連線 Yahoo Finance 補抓當下最新即時數據..."):
        ticker_symbol = f"{stock_id}.TW"
        try:
            stock = yf.Ticker(ticker_symbol)
            df = stock.history(period="2mo", auto_adjust=False)  
            stock_info = stock.info
            stock_name = stock_info.get("shortName", stock_info.get("longName", ""))
            
            if df.empty:
                ticker_symbol = f"{stock_id}.TWO"
                stock = yf.Ticker(ticker_symbol)
                df = stock.history(period="2mo", auto_adjust=False)
                stock_info = stock.info
                stock_name = stock_info.get("shortName", stock_info.get("longName", ""))

            # 🛠️ 【修正關鍵核心】：強制捕獲最新未定案盤中價/剛收盤價
            try:
                fast_info = stock.fast_info
                latest_realtime_price = fast_info.get("lastPrice", None)
                
                # 取得本地今日日期 (格式: YYYY-MM-DD)
                today_str = datetime.datetime.now().strftime("%Y-%m-%d")
                
                if latest_realtime_price is not None and not df.empty:
                    last_df_date = df.index[-1].strftime("%Y-%m-%d")
                    # 如果歷史 K 線資料落後了（沒抓到今天），或者今天的收盤價與即時最新價不同步，強制覆蓋/插入最新一筆
                    if last_df_date != today_str:
                        new_row = pd.DataFrame(
                            [[latest_realtime_price]*5 + [0]], 
                            columns=["Open", "High", "Low", "Close", "Volume", "Dividends"],
                            index=[pd.to_datetime(today_str)]
                        )
                        df = pd.concat([df, new_row])
                    else:
                        df.iloc[-1, df.columns.get_loc("Close")] = latest_realtime_price
            except Exception as realtime_err:
                pass # 若 fast_info 失敗則沿用原 history

        except Exception as e:
            st.error(f"網路連線錯誤: {e}")
            df = pd.DataFrame()

    common_stocks = {"3030": "德律", "3231": "緯創", "2330": "台積電", "2317": "鴻海", "2454": "聯發科"}
    if stock_id in common_stocks: stock_name = common_stocks[stock_id]
    elif not stock_name or stock_name.isascii(): stock_name = f"台股 {stock_id}"

    st.header(f"🔍 當前查詢：{stock_name} ({stock_id})")

    if not df.empty and len(df) >= 15:
        all_prices = df["Close"].tolist()
        all_dates = df.index.strftime("%Y-%m-%d").tolist()
        
        latest_price = all_prices[-1]

        # ==========================================
        # 【歷史回溯診斷】
        # ==========================================
        notice_dates_list = []  
        consecutive_notice_count = 0  
        
        for j in range(6):
            idx_target = -6 + j
            check_date = all_dates[idx_target]
            check_price = all_prices[idx_target]
            check_base_price = all_prices[idx_target - 6]
            check_spread = check_price - check_base_price
            
            check_returns = []
            for k in range(6):
                p_f = all_prices[idx_target - 6 + k]
                p_t = all_prices[idx_target - 5 + k]
                check_returns.append(truncate_2_decimals((p_t - p_f) / p_f * 100))
            
            check_sum_return = sum(check_returns)
            if check_disposal_condition(check_sum_return, check_spread):
                notice_dates_list.append(check_date)
                consecutive_notice_count += 1
            else:
                if j < 5: consecutive_notice_count = 0

        # ==========================================
        # 【部分一：已定案近 6 日累積明細】
        # ==========================================
        history_truncated_returns = []
        history_rows = []
        for i in range(6):
            p_from = all_prices[-7 + i]
            p_to = all_prices[-6 + i]
            history_truncated_returns.append(truncate_2_decimals((p_to - p_from) / p_from * 100))
            
            day_limit_up = calculate_limit_up(p_from)
            day_limit_down = calculate_limit_down(p_from)
            history_rows.append({
                "營業日": all_dates[-6 + i], "當日收盤價 (元)": round(p_to, 2),
                "當日漲跌幅 (%)": history_truncated_returns[-1],
                "is_limit_up": abs(p_to - day_limit_up) < 1e-4, "is_limit_down": abs(p_to - day_limit_down) < 1e-4
            })

        sum_history_6days = sum(history_truncated_returns)
        today_price = all_prices[-1]
        today_date = all_dates[-1]
        today_start_price = all_prices[-6]
        today_history_spread = today_price - today_start_price

        future_dates = get_next_business_days(today_date, count=5)
        history_df = pd.DataFrame(list(reversed(history_rows)))

        st.subheader(f"📊 歷史今日截止（含最新即時價日期：{today_date}）近 6 日累積數據明細")
        col_t1, col_t2 = st.columns([2, 1])
        with col_t1:
            def style_limit_prices(row):
                styles = [""] * len(row)
                c_idx = row.index.get_loc("當日收盤價 (元)")
                if row["is_limit_up"]: 
                    styles[c_idx] = "background-color: #ef5350; color: white; font-weight: bold;"
                elif row["is_limit_down"]: 
                    styles[c_idx] = "background-color: #2b8a3e; color: white; font-weight: bold;"
                return styles
            
            st.dataframe(
                history_df.style.apply(style_limit_prices, axis=1)
                                .format({"當日收盤價 (元)": "{:.2f}", "當日漲跌幅 (%)": "{:.2f}%"}),
                column_config={
                    "營業日": st.column_config.TextColumn("營業日"), 
                    "當日收盤價 (元)": st.column_config.NumberColumn("當日收盤價 (元)"), 
                    "當日漲跌幅 (%)": st.column_config.NumberColumn("當日漲跌幅 (%) (已捨去)"), 
                    "is_limit_up": None, 
                    "is_limit_down": None
                },
                use_container_width=True,
                hide_index=True
            )
        with col_t2:
            st.metric(label=f"當前最新即時/收盤價 ({today_date})", value=f"{today_price:.2f} 元")
            st.metric(label="歷史近 6 日累積漲跌幅總和", value=f"{sum_history_6days:.2f} %")
            st.metric(label="今日近 6 日真實價差", value=f"{today_history_spread:.2f} 元", delta=f"區間第一天收盤價: {today_start_price:.2f} 元", delta_color="off")
            st.markdown("---")
            st.markdown("#### 📢 證交所注意條款歷史狀態診斷")
            if len(notice_dates_list) >= 1:
                st.error(f"⚠️ 該股在近 6 日內，已累積 **{len(notice_dates_list)} 次** 注意股！")
                for d in notice_dates_list: st.write(f"• 🔴 `{d}` 達標")
                st.info(f"🔥 連續觸發階段累計：**{consecutive_notice_count}** 天。")
            else: st.success("✅ 安全：該股近 6 日內尚未觸發過注意股門檻二。")

        st.markdown("---")

        # ==========================================
        # 【部分二：雙指標一週天天漲停推演】
        # ==========================================
        st.subheader("🔮 實戰推演：未來一整週「天天鎖漲停」vs「注意股觸發價」對照預測")
        st.write("💡 *智慧過濾器已啟動：自動以最新捕獲的日期為起點，往後推演實際有交易的 5 個營業日！*")

        sim_prices = []
        current_base_price = today_price
        current_window_returns = list(history_truncated_returns)
        current_consecutive = consecutive_notice_count

        weekly_results = []
        compare_indices = [-5, -4, -3, -2, -1]

        for d_idx in range(5):
            day_limit_up = calculate_limit_up(current_base_price)
            base_compare_price = all_prices[compare_indices[d_idx]] if d_idx < len(all_prices) - 10 else sim_prices[d_idx - 6]
            
            past_4_sum = sum(current_window_returns[1:]) 
            day_trigger_price = find_trigger_price_for_day(current_base_price, past_4_sum, base_compare_price)
            
            day_ret = truncate_2_decimals((day_limit_up - current_base_price) / current_base_price * 100)
            temp_window = current_window_returns[1:] + [day_ret]
            
            trigger_day_ret = truncate_2_decimals((day_trigger_price - current_base_price) / current_base_price * 100)
            trigger_window = current_window_returns[1:] + [trigger_day_ret]
            trigger_sum_ret = sum(trigger_window)
            trigger_spread = day_trigger_price - base_compare_price
            
            is_notice_if_limit_up = check_disposal_condition(sum(temp_window), day_limit_up - base_compare_price)
            is_already_disposal_day = (current_consecutive >= 3)
            
            if is_notice_if_limit_up: current_consecutive += 1
            else: current_consecutive = 0
                
            weekly_results.append({
                "label_date": future_dates[d_idx], "limit_up": day_limit_up,
                "trigger_price": day_trigger_price, "is_notice_if_limit_up": is_notice_if_limit_up,
                "consecutive": current_consecutive, "is_disposal_day": is_already_disposal_day,
                "trigger_sum_ret": trigger_sum_ret, "trigger_spread": trigger_spread
            })
            
            current_window_returns = current_window_returns[1:] + [day_ret]
            current_base_price = day_limit_up
            sim_prices.append(day_limit_up)

        row1_col1, row1_col2, row1_col3 = st.columns(3)
        row2_col1, row2_col2, _ = st.columns([1, 1, 1])
        cols_pool = [row1_col1, row1_col2, row1_col3, row2_col1, row2_col2]

        for idx, res in enumerate(weekly_results):
            with cols_pool[idx]:
                if res['is_disposal_day']:
                    st.markdown(f"<h4 style='color:#9c27b0; margin-bottom:10px;'>🚫 處置股狀態：{res['label_date']}</h4>", unsafe_allow_html=True)
                    header_bg = "#9c27b0"
                    match_box = f"<div style='background-color:#9c27b0; color:white; padding:10px; border-radius:5px; text-align:center;'><b>🚫 正式進入處置股期間（人工撮合）</b></div>"
                else:
                    if idx == 0: st.error(f"🗓️ 預測第 1 天：{res['label_date']}")
                    elif idx == 1: st.warning(f"🗓️ 預測第 2 天：{res['label_date']}")
                    elif idx == 2: st.info(f"🗓️ 預測第 3 天：{res['label_date']}")
                    elif idx == 3: st.success(f"🗓️ 預測第 4 天：{res['label_date']}")
                    header_bg = "#ef5350"
                    
                    if res['trigger_price'] > res['limit_up']:
                        match_box = f"""
                        <div style='background-color:#e2f0d9; border-left:5px solid #2b8a3e; padding:10px; border-radius:5px; color:#2b8a3e; font-size:14px;'>
                            <b>✅ 安全窗期：漲停也安全</b><br>
                            注意觸發價為 <span style='font-size:16px; font-weight:bold;'>{res['trigger_price']:.2f}</span> 元，高於漲停價。當天鎖死也不會被注意！
                        </div>
                        """
                    else:
                        match_box = f"""
                        <div style='background-color:#fce8e6; border-left:5px solid #ef5350; padding:12px; border-radius:5px; color:#ef5350; font-size:14px; line-height:1.6;'>
                            <b>🚨 控盤警告：觸發價低於漲停</b><br>
                            收盤若高於 <span style='font-size:18px; font-weight:bold;'>{res['trigger_price']:.2f}</span> 元即觸發注意！<br>
                            <span style='color:#555555; font-size:13px;'>
                                📈 最近六個營業日累積收盤價漲幅達 <b>{res['trigger_sum_ret']:.2f}%</b><br>
                                💰 六個營業日起迄兩個營業日收盤價價差達 <b>{res['trigger_spread']:.2f} 元</b>
                            </span><br>
                            <span style='font-weight:bold;'>（若衝過此價位，連帶累計達 {res['consecutive']} 天）</span>
                        </div>
                        """
                        if res['consecutive'] == 3:
                            match_box += "<div style='color:purple; font-weight:bold; margin-top:5px; font-size:13px;'>⚠️ 今日若超標將滿3天注意，隔日正式進入處置！</div>"

                st.markdown(f"""
                <div style='background-color: {header_bg}; color: white; padding: 12px; border-radius: 5px; text-align: center; margin-bottom: 12px;'>
                    <small>{ "🔥 當天法定預估漲停價" if not res['is_disposal_day'] else "🍇 處置狀態下之漲停價" }</small><br>
                    <b style='font-size: 24px;'>{res['limit_up']:.2f} 元</b>
                </div>
                """, unsafe_allow_html=True)
                
                st.markdown(match_box, unsafe_allow_html=True)

        # ==========================================
        # 【證交所官方公告對齊】
        # ==========================================
        st.markdown("---")
        st.subheader(f"🏛️ 證交所（TWSE）官方即時公告對齊 ({today_date})")
        with st.spinner("正在安全連線證交所官方資料庫..."):
            twse_notice, twse_punish = fetch_twse_notices_and_punishes(stock_id, today_date)
            
        c1, c2 = st.columns(2)
        with c1:
            st.info("📋 證交所公布注意股票公告 (Notice)")
            st.markdown(f"**🔗 官方網站對照點：** [點此查看官方注意網頁](https://www.twse.com.tw/zh/announcement/notice.html)")
            if "🔴" in twse_notice: st.error(twse_notice)
            else: st.success(f"🟢 今日狀態：{twse_notice}")
        with c2:
            st.warning("🔒 證交所處置有價證券公告 (Punish)")
            st.markdown(f"**🔗 官方網站對照點：** [點此查看官方處置網頁](https://www.twse.com.tw/zh/announcement/punish.html)")
            if "🍇" in twse_punish: st.error(twse_punish)
            else: st.success(f"🟢 今日狀態：{twse_punish}")

else:
    st.info("💡 請在上方輸入框鍵入台股代號（例如：3030 或 3231），系統將立即為您自動計算。")
