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

    state = st_calendar(
        events=[],
        options=options,
        callbacks=["dateClick"],
        key="month_calendar",
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
