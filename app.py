import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.express as px
from datetime import date

st.set_page_config(page_title="台股策略回測小站", page_icon="📈", layout="wide")
st.title("📈 台股策略回測小站")
st.caption("繁體中文版｜策略比較原型｜歷史回測不代表未來績效")

COMMISSION_RATE = 0.001425

with st.sidebar:
    st.header("回測設定")
    start = st.date_input("開始日期", value=date(2018, 1, 1))
    end = st.date_input("結束日期", value=date.today())
    capital = st.number_input("初始資金（新臺幣）", min_value=10000, value=1_000_000, step=10000)
    st.markdown("---")
    st.markdown("**股票與配置設定**")
    
    # 股票 1 (預設 0050)
    col_s1, col_w1 = st.columns([2, 1])
    with col_s1:
        stock1 = st.text_input("標的一代號", value="0050", max_chars=6, key="s1").strip().upper()
    with col_w1:
        weight1 = st.number_input("權重 (%)", min_value=0.0, max_value=100.0, value=70.0, step=5.0, key="w1")
    is_core1 = st.checkbox("設為基準核心股（±5%觸發再平衡）", value=True, key="c1")
    
    st.markdown("---")
    # 股票 2
    col_s2, col_w2 = st.columns([2, 1])
    with col_s2:
        stock2 = st.text_input("標的二代號", value="2891", max_chars=6, key="s2").strip().upper()
    with col_w2:
        weight2 = st.number_input("權重 (%)", min_value=0.0, max_value=100.0, value=15.0, step=5.0, key="w2")
    is_core2 = st.checkbox("設為基準核心股（±5%觸發再平衡）", value=False, key="c2")
    
    st.markdown("---")
    # 股票 3
    col_s3, col_w3 = st.columns([2, 1])
    with col_s3:
        stock3 = st.text_input("標的三代號", value="1216", max_chars=6, key="s3").strip().upper()
    with col_w3:
        weight3 = st.number_input("權重 (%)", min_value=0.0, max_value=100.0, value=15.0, step=5.0, key="w3")
    is_core3 = st.checkbox("設為基準核心股（±5%觸發再平衡）", value=False, key="c3")

    # 檢查輸入與權重
    total_w = weight1 + weight2 + weight3
    if abs(total_w - 100.0) > 0.01:
        st.error(f"目前權重總和為 {total_w:.1f}%，請調整至合計 100%。")
        st.stop()

    stocks_input = [stock1, stock2, stock3]
    if not all(s.isdigit() for s in stocks_input):
        st.error("所有股票代號請輸入數字，例如 0050、2330、2891。")
        st.stop()

    if len(set(stocks_input)) < 3:
        st.error("三支股票代號不能重複。")
        st.stop()

    resolved_names = st.session_state.get("resolved_stock_names", {})
    for idx, (label, code) in enumerate([("標的一", stock1), ("標的二", stock2), ("標的三", stock3)]):
        known_name = resolved_names.get(f"{code}.TW") if code.isdigit() else None
        if known_name:
            st.success(f"{label}：{code}｜{known_name}")
        else:
            st.caption(f"{label}名稱：按下回測後自動查詢並顯示")

with st.sidebar:
    st.caption("手續費採單邊 0.1425%，未設定券商折扣。賣出稅率 ETF 0.1%、個股 0.3%。")

with st.expander("策略規則與假設", expanded=True):
    st.markdown("""
    - **買進持有**：期初依自訂百分比買進，期間不主動再平衡。
    - **A1-Q**：每季最後一個共同交易日收盤後產生訊號，下一交易日開盤再平衡至自訂目標比例。
    - **A1-H**：每半年最後一個共同交易日收盤後產生訊號，下一交易日開盤再平衡至自訂目標比例。
    - **A2（動態核心偏離再平衡）**：針對設為**「基準核心股」**的標的，當其市值占總市值比例**偏離自訂目標權重達 ±5%** 時，於下一交易日開盤再平衡至自訂目標比例。（若無設定核心股，則跳過觸發）。
    - **B1**：標的一收盤價達移動平均持股成本的 110% 時，下一交易日開盤賣出當時持股的 10%（無條件捨去）；若本次已實現淨獲利為正，獲利依自訂目標比例投入三檔股票，賣出本金留作現金。
    - **B2**：觸發與賣出規則同 B1；正的已實現淨獲利平均投入另外兩支自選股，賣出本金留作現金。

    B1／B2 在收盤價回落至成本的 110% 以下後，才重新開放下一次觸發。所有交易以整股計算，訊號在收盤後判定、下一交易日開盤執行。
    """)

if start >= end:
    st.error("開始日期必須早於結束日期。")
    st.stop()

# 內建常見台股名稱字典作為可靠備援
STATIC_TW_NAMES = {
    "0050.TW": "元大台灣50",
    "0056.TW": "元大高股息",
    "00878.TW": "國泰永續高股息",
    "00919.TW": "群益台灣精選高息",
    "00929.TW": "復華台灣科技優息",
    "2330.TW": "台積電",
    "2317.TW": "鴻海",
    "2454.TW": "聯發科",
    "2881.TW": "富邦金",
    "2882.TW": "國泰金",
    "2891.TW": "中信金",
    "2886.TW": "兆豐金",
    "2884.TW": "玉山金",
    "1216.TW": "統一",
    "1301.TW": "台塑",
    "1303.TW": "南亞",
    "2002.TW": "中鋼",
    "2308.TW": "台達電",
    "3008.TW": "大立光",
    "2382.TW": "廣達",
    "3231.TW": "緯創",
}

@st.cache_data(ttl=86400, show_spinner=False)
def lookup_stock_name(ticker):
    """查詢股票名稱，優先從備援字典取，若沒有則從 yfinance 網路抓取。"""
    if ticker in STATIC_TW_NAMES:
        return STATIC_TW_NAMES[ticker]
    try:
        t = yf.Ticker(ticker)
        info = t.info
        if isinstance(info, dict):
            for key in ("shortName", "longName", "displayName"):
                val = info.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()
    except Exception:
        pass
    return ""

@st.cache_data(ttl=3600, show_spinner=False)
def download_data(start_iso, end_iso, tickers):
    tickers = list(tickers)
    return yf.download(tickers, start=(pd.Timestamp(start_iso)-pd.Timedelta(days=10)).date().isoformat(),
        end=(pd.Timestamp(end_iso)+pd.Timedelta(days=1)).date().isoformat(), auto_adjust=False,
        actions=True, progress=False, group_by="ticker", threads=True)

def get_ticker_frame(raw, ticker):
    if isinstance(raw.columns, pd.MultiIndex):
        if ticker in raw.columns.get_level_values(0): return raw[ticker].copy()
        if ticker in raw.columns.get_level_values(1): return raw.xs(ticker, axis=1, level=1).copy()
    raise ValueError(f"下載結果未包含代號 {ticker} 或欄位格式不完整")

def buy_qty(cash, price, name, budget=None):
    budget = cash if budget is None else min(cash, budget)
    qty = max(0, int(budget / (price * (1 + COMMISSION_RATE))))
    return qty

def run_backtest(opens, closes, capital, strategy, target_weights, is_core_dict, sell_tax_dict):
    names = list(closes.columns)
    first_open = opens.iloc[0]
    cash = float(capital)
    shares = {n: 0 for n in names}
    cost_basis = {n: 0.0 for n in names}
    total_fees = 0.0
    trades = []
    
    # 期初依據自訂目標比例建倉
    for n in names:
        qty = buy_qty(cash, float(first_open[n]), n, float(capital)*target_weights[n])
        if qty:
            price = float(first_open[n]); fee = qty*price*COMMISSION_RATE
            cash -= qty*price + fee; total_fees += fee
            shares[n] += qty; cost_basis[n] = price
            trades.append({"日期": opens.index[0].date().isoformat(), "策略": strategy, "動作": "買進（初始配置）", "股票": n, "股數": qty, "成交價": price, "手續費": fee, "證交稅": 0.0, "交易說明": f"依目標權重({target_weights[n]:.0%})買進"})
    
    assets, pending_rebalance, armed = [], False, True
    for i, dt in enumerate(closes.index):
        if i > 0:
            open_row = opens.iloc[i]
            if strategy in ("A1-Q", "A1-H", "A2") and pending_rebalance:
                prices = {n: float(open_row[n]) for n in names}
                portfolio_value = cash + sum(shares[n]*prices[n] for n in names)
                targets = {n: portfolio_value*target_weights[n] for n in names}
                for n in names:
                    excess = shares[n]*prices[n] - targets[n]
                    if excess > 0:
                        qty = min(shares[n], int(excess/prices[n]))
                        if qty:
                            value=qty*prices[n]; fee=value*COMMISSION_RATE; tax=value*sell_tax_dict[n]
                            cash += value-fee-tax; shares[n]-=qty; total_fees += fee
                            trades.append({"日期":dt.date().isoformat(),"策略":strategy,"動作":"賣出（再平衡）","股票":n,"股數":qty,"成交價":prices[n],"手續費":fee,"證交稅":tax,"交易說明":"調整至目標配置"})
                portfolio_value = cash + sum(shares[n]*prices[n] for n in names)
                targets = {n: portfolio_value*target_weights[n] for n in names}
                for n in names:
                    need = targets[n]-shares[n]*prices[n]
                    qty = buy_qty(cash, prices[n], n, need)
                    if qty:
                        value=qty*prices[n]; fee=value*COMMISSION_RATE
                        cash-=value+fee; shares[n]+=qty
                        old_qty=shares[n]-qty
                        cost_basis[n]=(cost_basis[n]*old_qty+prices[n]*qty)/(old_qty+qty) if old_qty+qty else prices[n]
                        total_fees+=fee
                        trades.append({"日期":dt.date().isoformat(),"策略":strategy,"動作":"買進（再平衡）","股票":n,"股數":qty,"成交價":prices[n],"手續費":fee,"證交稅":0.0,"交易說明":"調整至目標配置"})
                pending_rebalance=False
            elif strategy in ("B1", "B2") and pending_rebalance:
                n=names[0]; price=float(open_row[n]); qty=min(shares[n], int(shares[n]*0.10))
                if qty:
                    value=qty*price; fee=value*COMMISSION_RATE; tax=value*sell_tax_dict[n]
                    realized_net=value-fee-tax-qty*cost_basis[n]
                    cash += value-fee-tax; shares[n]-=qty; total_fees+=fee
                    trades.append({"日期":dt.date().isoformat(),"策略":strategy,"動作":"賣出（獲利觸發）","股票":n,"股數":qty,"成交價":price,"手續費":fee,"證交稅":tax,"交易說明":f"已實現淨損益 NT$ {realized_net:,.0f}"})
                    profit=max(0.0, realized_net)
                    if strategy == "B1":
                        allocation = target_weights
                    else:
                        allocation = {names[0]: 0.0, names[1]: 0.5, names[2]: 0.5}
                    for target_name, weight in allocation.items():
                        if weight <= 0 or profit <= 0: continue
                        p=float(open_row[target_name]); q=buy_qty(cash,p,target_name,profit*weight)
                        if q:
                            val=q*p; f=val*COMMISSION_RATE; old=shares[target_name]
                            cash-=val+f; shares[target_name]+=q
                            cost_basis[target_name]=(cost_basis[target_name]*old+p*q)/(old+q) if old+q else p
                            total_fees+=f
                            trades.append({"日期":dt.date().isoformat(),"策略":strategy,"動作":"買進（獲利再投入）","股票":target_name,"股數":q,"成交價":p,"手續費":f,"證交稅":0.0,"交易說明":f"以已實現淨獲利再投入；配置比例 {weight:.0%}"})
                pending_rebalance=False

        # 每日收盤產生訊號
        close_row=closes.iloc[i]
        if strategy in ("A1-Q","A1-H") and i < len(closes)-1:
            period=(dt.year, dt.quarter) if strategy=="A1-Q" else (dt.year, 1 if dt.month<=6 else 2)
            next_period=None
            if i+1<len(closes):
                nd=closes.index[i+1]
                next_period=(nd.year,nd.quarter) if strategy=="A1-Q" else (nd.year,1 if nd.month<=6 else 2)
            if next_period != period: pending_rebalance=True
        elif strategy=="A2" and i < len(closes)-1:
            vals={n:shares[n]*float(close_row[n]) for n in names}; denom=sum(vals.values())
            if denom > 0:
                for n in names:
                    if is_core_dict[n]:
                        curr_w = vals[n] / denom
                        tgt_w = target_weights[n]
                        # 檢查基準核心股是否偏離其自訂權重的 ±5% (0.05)
                        if curr_w < (tgt_w - 0.05) or curr_w > (tgt_w + 0.05):
                            pending_rebalance = True
                            break
        elif strategy in ("B1","B2") and i < len(closes)-1:
            n=names[0]
            threshold=cost_basis[n]*1.10 if shares[n]>0 else np.inf
            if float(close_row[n]) < threshold: armed=True
            elif armed and shares[n]>0 and float(close_row[n]) >= threshold:
                pending_rebalance=True; armed=False
        value=cash+sum(shares[n]*float(close_row[n]) for n in names)
        assets.append(value)
    asset_series=pd.Series(assets,index=closes.index,name=strategy)
    return asset_series, shares, cash, total_fees, pd.DataFrame(trades)

def metrics(assets, capital):
    daily=assets.pct_change().fillna(0)
    cum=assets.iloc[-1]/capital-1
    days=max((assets.index[-1]-assets.index[0]).days,1)
    cagr=(assets.iloc[-1]/capital)**(365/days)-1 if assets.iloc[-1]>0 else np.nan
    std=daily.std(ddof=1)
    sharpe=daily.mean()/std*np.sqrt(252) if pd.notna(std) and std>0 else np.nan
    dd=(assets/assets.cummax()-1).min()
    return {"期末資產":assets.iloc[-1],"累積報酬率":cum,"年化報酬率":cagr,"夏普比率":sharpe,"最大回撤":dd}

st.markdown("### 執行策略比較")
st.caption("股票代號與自訂權重可在左側修改；按下回測按鈕即可用新設定重新分析。")
chosen=st.multiselect("選擇要比較的策略", ["買進持有","A1-Q","A1-H","A2","B1","B2"], default=["買進持有","A1-Q","A1-H","A2","B1","B2"])
if st.button("🔎 載入歷史資料並執行回測", type="primary", use_container_width=True):
    try:
        ticker_codes = (f"{stock1}.TW", f"{stock2}.TW", f"{stock3}.TW")
        with st.spinner("正在查詢股票名稱…"):
            resolved = dict(st.session_state.get("resolved_stock_names", {}))
            for ticker in ticker_codes:
                stock_name = lookup_stock_name(ticker)
                if stock_name:
                    resolved[ticker] = stock_name
            st.session_state["resolved_stock_names"] = resolved

        name1 = resolved.get(ticker_codes[0], "")
        name2 = resolved.get(ticker_codes[1], "")
        name3 = resolved.get(ticker_codes[2], "")
        
        # 標籤：使用 代號 ｜ 名稱 (例如 0050 ｜ 元大台灣50)
        label1 = f"{stock1} ｜ {name1}" if name1 else stock1
        label2 = f"{stock2} ｜ {name2}" if name2 else stock2
        label3 = f"{stock3} ｜ {name3}" if name3 else stock3
        
        display_stocks = {
            label1: ticker_codes[0],
            label2: ticker_codes[1],
            label3: ticker_codes[2],
        }
        
        names_list = list(display_stocks.keys())
        target_weights = {
            names_list[0]: weight1 / 100.0,
            names_list[1]: weight2 / 100.0,
            names_list[2]: weight3 / 100.0,
        }
        is_core_dict = {
            names_list[0]: is_core1,
            names_list[1]: is_core2,
            names_list[2]: is_core3,
        }
        sell_tax_dict = {
            names_list[0]: 0.001 if stock1.startswith("00") else 0.003,
            names_list[1]: 0.001 if stock2.startswith("00") else 0.003,
            names_list[2]: 0.001 if stock3.startswith("00") else 0.003,
        }

        with st.sidebar:
            st.markdown("---")
            st.markdown("**本次回測股票與設定**")
            for n in names_list:
                core_text = " (核心股 ±5% 觸發)" if is_core_dict[n] else ""
                st.write(f"- **{n}**：權重 {target_weights[n]:.0%}{core_text}")

        with st.spinner("正在下載行情並檢查資料…"):
            raw=download_data(start.isoformat(),end.isoformat(),tuple(display_stocks.values()))
        if raw is None or raw.empty:
            st.error("沒有取得行情資料，請確認日期範圍或稍後重試。"); st.stop()
        opens,closes={},{}; check=[]; errors=[]
        for name,ticker in display_stocks.items():
            try:
                frame=get_ticker_frame(raw,ticker); frame.index=pd.to_datetime(frame.index)
                if frame.index.tz is not None: frame.index=frame.index.tz_localize(None)
                frame=frame.loc[(frame.index.date>=start)&(frame.index.date<=end)].sort_index()
                if frame.empty: raise ValueError("選定期間沒有交易資料")
                o=pd.to_numeric(frame["Open"],errors="coerce"); c=pd.to_numeric(frame["Close"],errors="coerce")
                opens[name]=o; closes[name]=c
                check.append({"股票名稱與代號":name,"資料起日":frame.index.min().date().isoformat(),"資料迄日":frame.index.max().date().isoformat(),"交易日數":len(frame),"缺漏開盤價":int(o.isna().sum()),"缺漏收盤價":int(c.isna().sum()),"狀態":"通過初步檢查" if o.notna().all() and c.notna().all() else "有缺漏"})
            except Exception as exc: errors.append(f"{name}：{exc}"); check.append({"股票名稱與代號":name,"狀態":f"失敗：{exc}"})
        st.subheader("資料檢查結果"); st.dataframe(pd.DataFrame(check),use_container_width=True,hide_index=True)
        if errors: st.error("資料檢查未通過："+"；".join(errors)); st.stop()
        open_df=pd.concat(opens,axis=1,join="inner").sort_index(); close_df=pd.concat(closes,axis=1,join="inner").sort_index()
        
        st.subheader("本次回測股票配置明細")
        table_info = []
        for i, (code, name) in enumerate([(stock1, name1), (stock2, name2), (stock3, name3)]):
            nl = names_list[i]
            core_str = "基準核心股 (±5%)" if is_core_dict[nl] else "一般標的"
            lower_b = max(0.0, target_weights[nl] - 0.05) if is_core_dict[nl] else "-"
            upper_b = min(1.0, target_weights[nl] + 0.05) if is_core_dict[nl] else "-"
            trig_str = f"{lower_b:.1%} ~ {upper_b:.1%}" if is_core_dict[nl] else "無偏離限制"
            table_info.append({
                "股票代號": code,
                "股票名稱": name if name else "（未知/查無名稱）",
                "自訂目標權重": f"{target_weights[nl]:.1%}",
                "標的類型": core_str,
                "A2 策略觸發區間": trig_str
            })
        st.dataframe(pd.DataFrame(table_info), use_container_width=True, hide_index=True)
        
        valid=open_df.notna().all(axis=1)&close_df.notna().all(axis=1)&(open_df>0).all(axis=1)&(close_df>0).all(axis=1)
        open_df=open_df.loc[valid]; close_df=close_df.loc[valid]
        if len(close_df)<2: st.error("三檔股票沒有足夠的共同有效交易日。"); st.stop()
        st.success(f"資料檢查完成：共同有效交易日 {len(close_df)} 天。")
        mapping={"買進持有":"買進持有","A1-Q":"A1-Q","A1-H":"A1-H","A2":"A2","B1":"B1","B2":"B2"}
        results={}; summaries=[]; all_trades=[]; holdings=[]
        for strategy in chosen:
            s,sh,cash,fees,trades=run_backtest(open_df,close_df,float(capital),mapping[strategy], target_weights, is_core_dict, sell_tax_dict)
            results[strategy]=s; m=metrics(s,float(capital))
            summaries.append({"策略":strategy,**m,"期末現金":cash,"累計手續費":fees,"交易次數":len(trades)})
            all_trades.extend(trades.to_dict("records"))
            holdings.extend([{"策略":strategy,"股票":n,"期末股數":q,"期末收盤價":float(close_df[n].iloc[-1]),"期末市值":q*float(close_df[n].iloc[-1])} for n,q in sh.items()])
        if not results: st.warning("請至少選擇一種策略。"); st.stop()
        st.subheader("績效比較")
        summary=pd.DataFrame(summaries)
        display=summary.copy()
        for col in ["期末資產","期末現金","累計手續費"]: display[col]=display[col].map(lambda x:f"NT$ {x:,.0f}")
        for col in ["累積報酬率","年化報酬率","最大回撤"]: display[col]=display[col].map(lambda x:f"{x:.2%}" if pd.notna(x) else "無法計算")
        display["夏普比率"]=display["夏普比率"].map(lambda x:f"{x:.3f}" if pd.notna(x) else "無法計算")
        st.dataframe(display,use_container_width=True,hide_index=True)
        curve=pd.DataFrame({"日期":close_df.index})
        for name,s in results.items(): curve[name]=s.values
        fig=px.line(curve,x="日期",y=list(results.keys()),title="各策略每日資產變化（新臺幣）")
        st.plotly_chart(fig,use_container_width=True)
        ret=pd.DataFrame({name:s/float(capital)-1 for name,s in results.items()})
        fig2=px.line(ret.reset_index(names="日期"),x="日期",y=list(results.keys()),title="各策略累積報酬率比較")
        fig2.update_yaxes(tickformat=".0%")
        st.plotly_chart(fig2,use_container_width=True)
        st.subheader("期末持股摘要")
        hold_df=pd.DataFrame(holdings); hold_df["期末市值"]=hold_df["期末市值"].map(lambda x:f"NT$ {x:,.0f}"); hold_df["期末收盤價"]=hold_df["期末收盤價"].map(lambda x:f"{x:.2f}")
        st.dataframe(hold_df,use_container_width=True,hide_index=True)
        st.subheader("交易紀錄")
        if all_trades:
            trades_df=pd.DataFrame(all_trades)
            for col in ["成交價","手續費","證交稅"]:
                if col in trades_df: trades_df[col]=trades_df[col].map(lambda x:f"{x:,.2f}")
            st.dataframe(trades_df,use_container_width=True,hide_index=True)
            st.download_button("下載交易紀錄 CSV",pd.DataFrame(all_trades).to_csv(index=False,encoding="utf-8-sig"),file_name="台股策略交易紀錄.csv",mime="text/csv")
        else: st.info("所選期間沒有產生交易紀錄。")
        st.warning("研究原型提醒：目前未計入現金股利與股利再投資，未完整處理公司行動；以開盤價近似成交且未模擬滑價。請將結果視為研究比較用途，不構成投資建議。")
    except Exception as exc:
        st.error(f"執行時發生錯誤：{exc}")
        st.info("請確認網路連線與日期範圍，或稍後重試。")

st.divider()
st.caption("本網站僅供研究與教學示範，不構成投資建議。不同資料來源、交易成本與規則設定可能造成回測結果差異。")
