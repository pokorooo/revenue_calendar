from datetime import date

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
        options={**options, "selectable": True, "unselectAuto": True},
        callbacks=["dateClick", "select"],
        key="month_calendar",
    )

    # クリックした日付を保持し、入力画面を開く
    def _extract_date(obj):
        import re
        if isinstance(obj, str):
            m = re.search(r"\d{4}-\d{2}-\d{2}", obj)
            return m.group(0) if m else None
        if isinstance(obj, dict):
            # prefer common keys
            for k in ("dateStr","startStr","endStr","clickedDate"):
                if k in obj and isinstance(obj[k], str):
                    d = _extract_date(obj[k])
                    if d: return d
            for v in obj.values():
                d = _extract_date(v)
                if d: return d
        if isinstance(obj, (list, tuple)):
            for v in obj:
                d = _extract_date(v)
                if d: return d
        return None

    if isinstance(state, dict):
        picked = None
        dc = state.get("dateClick")
        if isinstance(dc, dict):
            picked = _extract_date(dc)
        if picked is None:
            sel = state.get("select")
            if isinstance(sel, dict):
                picked = _extract_date(sel)
        if picked is None:
            picked = _extract_date(state)
        if picked:
            picked = picked[:10]
            st.session_state["selected"] = picked
            st.session_state["input_visible"] = True
            try:
                st.toast(f"{picked} を選択しました")
            except Exception:
                pass

    # 入力パネル（買値・売値から収益を計算）: 日付クリック後に表示
    sel = st.session_state["selected"]
    if st.session_state.get("input_visible"):
        st.subheader(f"入力（{sel}）")
        buy_key = f"buy_{sel}"
        sell_key = f"sell_{sel}"
        st.session_state.setdefault(buy_key, 0.0)
        st.session_state.setdefault(sell_key, 0.0)

        with st.form(f"trade_form_{sel}"):
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
                cols = st.columns([3,3,3,1])
                cols[0].write(f"買値: {e['buy']:,.2f}")
                cols[1].write(f"売値: {e['sell']:,.2f}")
                cols[2].write(f"収益: {e['profit']:,.2f}")
                if cols[3].button("削除", key=f"del-{sel}-{idx}"):
                    all_list = st.session_state["simple_trades"]
                    for j, a in enumerate(all_list):
                        if a["date"]==sel and a["buy"]==e["buy"] and a["sell"]==e["sell"] and a["profit"]==e["profit"]:
                            del all_list[j]
                            break
                    st.experimental_rerun()

        if st.button("閉じる"):
            st.session_state["input_visible"] = False
    else:
        st.info("日付セルをクリックして入力を開きます。")


if __name__ == "__main__":
    main()
