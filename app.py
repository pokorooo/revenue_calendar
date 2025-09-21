from datetime import date, datetime

import streamlit as st
from streamlit_calendar import calendar as st_calendar


def main():
    st.set_page_config(page_title="株の収益カレンダー", layout="wide")
    # 初期状態
    st.session_state.setdefault("selected", date.today().isoformat())
    st.session_state.setdefault("simple_trades", [])  # [{date, buy, sell, profit}]
    st.session_state.setdefault("input_visible", False)

    selected = st.session_state["selected"]

    # 登録済みの収益を日別に集計してイベント化（プラス=赤、マイナス=緑、ゼロ=グレー）
    def _fmt_amount(n: float) -> str:
        sign = '+' if n > 0 else '-' if n < 0 else '±'
        return f"{sign}{abs(n):,.0f}"

    totals = {}
    for e in st.session_state.get("simple_trades", []):
        d = e.get("date")
        p = float(e.get("profit") or 0.0)
        if not d:
            continue
        totals[d] = totals.get(d, 0.0) + p

    events = []
    for d, amt in totals.items():
        cls = "rc-pos" if amt > 0 else "rc-neg" if amt < 0 else "rc-zero"
        events.append({
            "title": _fmt_amount(amt),
            "start": d,
            "allDay": True,
            # 色はCSSクラスで制御
            "className": cls,
            "classNames": [cls],
        })

    options = {
        "initialView": "dayGridMonth",
        "initialDate": selected,
        "locale": "ja",
        "timeZone": "local",
        "firstDay": 0,  # Sunday
        "headerToolbar": {"left": "prev,next today", "center": "title", "right": ""},
        "weekNumbers": False,
        "navLinks": False,
        "editable": False,
        "selectable": False,
        "height": "auto",
        # Show weeks up to the one that contains the last day of month
        "fixedWeekCount": False,
    }

    custom_css = """
    /* remove background/border and bolden text */
    .fc .rc-pos, .fc .rc-neg, .fc .rc-zero { background: transparent !important; border: 0 !important; box-shadow: none !important; }
    .fc .rc-pos .fc-event-main, .fc .rc-pos .fc-event-title { color:#ef4444 !important; font-weight:700 !important; text-align:right; white-space:nowrap; padding-right:4px; }
    .fc .rc-neg .fc-event-main, .fc .rc-neg .fc-event-title { color:#10b981 !important; font-weight:700 !important; text-align:right; white-space:nowrap; padding-right:4px; }
    .fc .rc-zero .fc-event-main, .fc .rc-zero .fc-event-title { color:#6b7280 !important; font-weight:700 !important; text-align:right; white-space:nowrap; padding-right:4px; }
    /* container & sums placement */
    .rc-calwrap { position: relative; }
    .rc-sum { position:absolute; right:6px; bottom:6px; text-align:right; font-weight:700; background: transparent; }
    .rc-sum .rc-pos { color:#ef4444 !important; }
    .rc-sum .rc-neg { color:#10b981 !important; }
    .rc-sum .rc-zero { color:#6b7280 !important; }
    """
    st.markdown('<div class="rc-calwrap">', unsafe_allow_html=True)
    state = st_calendar(
        events=events,
        options=options,
        callbacks=["dateClick", "datesSet"],
        custom_css=custom_css,
        key="month_calendar",
    )

    # 表示中の月・年の合計を右下に表示
    view_year = None
    view_month = None
    if isinstance(state, dict) and isinstance(state.get("datesSet"), dict):
        info = state["datesSet"]
        try:
            start_str = info.get("startStr") or info.get("start")
            end_str = info.get("endStr") or info.get("end")
            if isinstance(start_str, str) and isinstance(end_str, str):
                s = datetime.fromisoformat(start_str.replace('Z','+00:00')).astimezone()
                e = datetime.fromisoformat(end_str.replace('Z','+00:00')).astimezone()
                mid = s + (e - s) / 2
                view_year, view_month = mid.year, mid.month
        except Exception:
            pass
    if view_year is None or view_month is None:
        try:
            d0 = datetime.fromisoformat(selected)
            view_year, view_month = d0.year, d0.month
        except Exception:
            today = date.today()
            view_year, view_month = today.year, today.month

    month_total = 0.0
    year_total = 0.0
    for ent in st.session_state.get("simple_trades", []):
        ds = str(ent.get("date") or "")
        try:
            dt = datetime.fromisoformat(ds)
        except Exception:
            continue
        if dt.year == view_year:
            year_total += float(ent.get("profit") or 0.0)
            if dt.month == view_month:
                month_total += float(ent.get("profit") or 0.0)

    def _cls_for(n: float) -> str:
        return "rc-pos" if n > 0 else "rc-neg" if n < 0 else "rc-zero"

    month_str = _fmt_amount(month_total)
    year_str = _fmt_amount(year_total)
    st.markdown(
        f'<div class="rc-sum">'
        f'<div>月合計: <span class="{_cls_for(month_total)}">{month_str}</span></div>'
        f'<div>年合計: <span class="{_cls_for(year_total)}">{year_str}</span></div>'
        f'</div></div>',
        unsafe_allow_html=True
    )

    # クリックした日付を保持し、入力画面を開く（dateClick.dateStr を優先し、ISO日時はローカル日に補正）
    if isinstance(state, dict):
        dc = state.get("dateClick")
        def _normalize_date_str(val: str):
            if not isinstance(val, str) or not val:
                return None
            s = val.strip()
            # すでに日付のみ
            if len(s) >= 10 and s[4] == '-' and s[7] == '-' and 'T' not in s:
                return s[:10]
            # ISO日時 -> ローカル日付へ変換
            try:
                z = s.replace('Z', '+00:00')
                dt = datetime.fromisoformat(z)
                local_date = dt.astimezone().date().isoformat()
                return local_date
            except Exception:
                # それでもダメなら先頭10文字を日付として扱う
                return s[:10]

        date_str = None
        if isinstance(dc, dict):
            ds = dc.get("dateStr") or dc.get("date")
            date_str = _normalize_date_str(ds)
        if date_str:
            st.session_state["selected"] = date_str
            st.session_state["input_visible"] = True

    # 入力パネル（買値・売値から収益を計算）: 日付クリック後に表示
    sel = st.session_state["selected"]
    if st.session_state.get("input_visible"):
        st.subheader(f"入力（{sel}）")
        buy_key = f"buy_{sel}"
        sell_key = f"sell_{sel}"
        sym_key = f"sym_{sel}"
        st.session_state.setdefault(buy_key, 0.0)
        st.session_state.setdefault(sell_key, 0.0)
        st.session_state.setdefault(sym_key, "")

        with st.form(f"trade_form_{sel}"):
            # 銘柄入力（1文字以上で候補表示）
            st.text_input("銘柄", key=sym_key, placeholder="例: 7203 / トヨタ")
            query = (st.session_state.get(sym_key) or "").strip()
            if len(query) >= 1:
                # 履歴から候補を作成
                used_syms = [x.get("symbol", "") for x in st.session_state.get("simple_trades", [])]
                candidates = sorted({s for s in used_syms if isinstance(s, str) and s.strip()})
                suggestions = [s for s in candidates if query.lower() in s.lower()]
                if suggestions:
                    sel_sug = st.selectbox("候補", options=["選択しない"] + suggestions, key=f"sug_{sel}")
                    if sel_sug and sel_sug != "選択しない":
                        st.session_state[sym_key] = sel_sug
            c1, c2, c3 = st.columns([1,1,1])
            with c1:
                buy = st.number_input("買値", min_value=0.0, step=100.0, key=buy_key)
            with c2:
                sell = st.number_input("売値", min_value=0.0, step=100.0, key=sell_key)
            profit = float(st.session_state[sell_key]) - float(st.session_state[buy_key])
            with c3:
                st.metric("収益", f"{profit:,.2f}")
            submitted = st.form_submit_button("保存")

        if submitted:
            st.session_state["simple_trades"].append({
                "date": sel,
                "symbol": str(st.session_state[sym_key]).strip(),
                "buy": float(st.session_state[buy_key] or 0.0),
                "sell": float(st.session_state[sell_key] or 0.0),
                "profit": float(profit),
            })
            st.success("保存しました")

        # 登録済み一覧（当日分）と閉じる
        entries = [x for x in st.session_state["simple_trades"] if x["date"] == sel]
        if entries:
            st.markdown("#### 登録済み")
            for idx, e in enumerate(entries):
                cols = st.columns([3,2,2,2,1])
                cols[0].write(f"銘柄: {e.get('symbol','') or '-'}")
                cols[1].write(f"買値: {e['buy']:,.2f}")
                cols[2].write(f"売値: {e['sell']:,.2f}")
                cols[3].write(f"収益: {e['profit']:,.2f}")
                if cols[4].button("削除", key=f"del-{sel}-{idx}"):
                    all_list = st.session_state["simple_trades"]
                    for j, a in enumerate(all_list):
                        if (
                            a.get("date")==sel and
                            a.get("symbol","")==e.get("symbol","") and
                            a.get("buy")==e.get("buy") and
                            a.get("sell")==e.get("sell") and
                            a.get("profit")==e.get("profit")
                        ):
                            del all_list[j]
                            break
                    # 変更は次の描画で反映されます

        if st.button("閉じる"):
            st.session_state["input_visible"] = False
    else:
        st.info("日付セルをクリックして入力を開きます。")


if __name__ == "__main__":
    main()
