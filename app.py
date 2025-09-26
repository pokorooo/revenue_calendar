from datetime import date, datetime
import re
import os
import csv
import json

import streamlit as st
from streamlit_calendar import calendar as st_calendar
try:
    import yfinance as yf
    _HAS_YF = True
except Exception:
    _HAS_YF = False
try:
    from streamlit_searchbox import st_searchbox
    _HAS_SB = True
except Exception:
    _HAS_SB = False


def _extract_symbol_token(text: str) -> str:
    s = (text or "").strip().replace('／', '/').replace('　', ' ')
    # explicit ticker like 7203.T anywhere (e.g., "トヨタ (7203.T)")
    m = re.search(r"([A-Za-z0-9]+\.[A-Za-z]+)", s)
    if m:
        return m.group(1)
    # 4-digit JP code
    m = re.search(r"\b(\d{4})\b", s)
    if m:
        return m.group(1)
    # fallback to first token or left of '/'
    if '/' in s:
        s = s.split('/', 1)[0].strip()
    else:
        s = s.split()[0] if s else s
    return s


def _normalize_symbol_for_yf(token: str) -> str:
    t = (token or "").strip()
    if t.isdigit() and len(t) == 4:
        return f"{t}.T"
    return t


if _HAS_YF:
    @st.cache_data(ttl=120)
    def fetch_price(sym_text: str):
        try:
            token = _extract_symbol_token(sym_text)
            if not token:
                return (None, "", "")
            norm = _normalize_symbol_for_yf(token)
            tk = yf.Ticker(norm)
            price = None
            fi = getattr(tk, 'fast_info', None)
            if fi:
                for k in ("last_price", "lastPrice", "regular_market_price", "regularMarketPrice"):
                    try:
                        val = fi[k]
                        if val is not None:
                            price = float(val); break
                    except Exception:
                        pass
            if price is not None:
                return (price, norm, "更新値")
            hist = tk.history(period="2d", interval="1d")
            if hist is not None and not hist.empty and "Close" in hist:
                last_close = float(hist["Close"].dropna().iloc[-1])
                idx = hist.index[-1]
                try:
                    ts = idx.to_pydatetime()
                    label = "当日終値" if ts.astimezone().date() == date.today() else "前日終値"
                except Exception:
                    label = "前日終値"
                return (last_close, norm, label)
            return (None, norm, "")
        except Exception:
            return (None, "", "")


# ---------- Symbol Master (JPX) ----------
@st.cache_data(ttl=60*60)
def load_symbol_master():
    paths = [
        os.path.join('data', 'jpx_symbols.csv'),
        os.path.join('data', 'symbols.csv'),
        'symbols.csv',
    ]
    rows = []
    for p in paths:
        if os.path.exists(p):
            try:
                with open(p, newline='', encoding='utf-8') as f:
                    r = csv.reader(f)
                    for row in r:
                        if not row:
                            continue
                        sym = (row[0] or '').strip()
                        name = (row[1] if len(row) > 1 else '').strip()
                        if not sym or sym.lower() in ('symbol','code','コード'):
                            continue
                        if sym.isdigit() and len(sym)==4:
                            sym = f"{sym}.T"
                        rows.append((sym, name))
                break
            except Exception:
                pass
    return rows


def _write_symbol_master(content: str) -> tuple[bool, str, int]:
    try:
        os.makedirs('data', exist_ok=True)
        out_path = os.path.join('data','jpx_symbols.csv')
        with open(out_path, 'w', encoding='utf-8', newline='') as f:
            f.write(content)
        # meta
        meta = { 'lastUpdated': datetime.utcnow().isoformat() }
        with open(os.path.join('data','symbols_meta.json'),'w',encoding='utf-8') as f:
            json.dump(meta, f)
        # count
        count = sum(1 for _ in csv.reader(content.splitlines()))
        try:
            load_symbol_master.clear()
        except Exception:
            pass
        return True, '保存しました', count
    except Exception as e:
        return False, f'保存に失敗しました: {e}', 0


def update_symbol_master() -> tuple[bool, str, int]:
    """Try to fetch JPX symbol list from known mirrors and save locally."""
    urls = [
        'https://raw.githubusercontent.com/woxtu/stock-list-jpx/master/data/jpx_stock_list.csv',
        'https://raw.githubusercontent.com/hiroakit/stock-list/master/data/jpx_tickers.csv',
    ]
    try:
        from urllib.request import urlopen, Request
    except Exception:
        return False, 'ネットワークモジュールが利用できません', 0
    for url in urls:
        try:
            req = Request(url, headers={'User-Agent':'Mozilla/5.0'})
            with urlopen(req, timeout=10) as resp:
                content = resp.read().decode('utf-8', errors='ignore')
            return _write_symbol_master(content)
        except Exception:
            continue
    return False, '取得に失敗しました（ネットワーク/URLをご確認ください）', 0


def symbol_master_age_days() -> int | None:
    try:
        mpath = os.path.join('data','symbols_meta.json')
        if os.path.exists(mpath):
            with open(mpath,encoding='utf-8') as f:
                meta = json.load(f)
            ts = meta.get('lastUpdated')
            if ts:
                dt = datetime.fromisoformat(ts)
                return (datetime.utcnow()-dt).days
        # fallback to file mtime
        p = os.path.join('data','jpx_symbols.csv')
        if os.path.exists(p):
            mtime = datetime.utcfromtimestamp(os.path.getmtime(p))
            return (datetime.utcnow()-mtime).days
    except Exception:
        return None
    return None


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
            # 常に日付部分だけを使用（タイムゾーン変換はしない）
            if 'T' in s:
                return s.split('T', 1)[0]
            if len(s) >= 10 and s[4] == '-' and s[7] == '-':
                return s[:10]
            return s[:10] if len(s) >= 10 else None

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

        # オフライン用 代表的上場銘柄（名称+ティッカー）
        OFFLINE_SYMBOLS = [
            ("7203.T", "トヨタ自動車"), ("6758.T", "ソニーグループ"), ("6861.T", "キーエンス"),
            ("7974.T", "任天堂"), ("8035.T", "東京エレクトロン"), ("9983.T", "ファーストリテイリング"),
            ("9984.T", "ソフトバンクグループ"), ("6501.T", "日立製作所"), ("6503.T", "三菱電機"),
            ("6981.T", "村田製作所"), ("6954.T", "ファナック"), ("7751.T", "キヤノン"),
            ("9432.T", "ＮＴＴ"), ("9433.T", "ＫＤＤＩ"), ("9434.T", "ソフトバンク"),
            ("8316.T", "三井住友フィナンシャルグループ"), ("8306.T", "三菱ＵＦＪフィナンシャル・グループ"),
            ("8411.T", "みずほフィナンシャルグループ"), ("8058.T", "三菱商事"), ("8031.T", "三井物産"),
            ("2768.T", "双日"), ("4901.T", "富士フイルムＨＤ"), ("4063.T", "信越化学工業"),
            ("4502.T", "武田薬品工業"), ("4503.T", "アステラス製薬"), ("4523.T", "エーザイ"),
            ("5108.T", "ブリヂストン"), ("6752.T", "パナソニックＨＤ"), ("2914.T", "日本たばこ産業"),
            ("1605.T", "ＩＮＰＥＸ"), ("5020.T", "ＥＮＥＯＳホールディングス"), ("7201.T", "日産自動車"),
            ("7267.T", "ホンダ"), ("4062.T", "イビデン"), ("6594.T", "ニデック"), ("6324.T", "ハーモニックドライブ"),
            ("8725.T", "MS&AD保険グループHD"), ("8630.T", "ＳＯＭＰＯホールディングス"), ("8766.T", "東京海上HD"),
            ("7272.T", "ヤマハ発動機"),
        ]

        def _norm_ja(s: str) -> str:
            if not isinstance(s, str):
                return ""
            out = []
            for ch in s:
                code = ord(ch)
                # カタカナ→ひらがなに正規化 + 英数は小文字化
                if 0x30A1 <= code <= 0x30F6:
                    out.append(chr(code - 0x60))
                else:
                    out.append(ch.lower())
            return "".join(out)

        # サジェストからの反映要求があれば、テキスト入力生成前に適用する
        if st.session_state.get('apply_sym_key') == sym_key and st.session_state.get('apply_sym'):
            st.session_state[sym_key] = st.session_state['apply_sym']
            st.session_state.pop('apply_sym', None)
            st.session_state.pop('apply_sym_key', None)

        # 銘柄入力（タイプ中にプルダウンで候補表示：streamlit-searchbox を優先利用）
        if _HAS_SB:
            def _search_candidates(term: str):
                term = (term or '').strip()
                if not term:
                    return []
                qn = _norm_ja(term)
                def _clean_ascii(x: str) -> str:
                    import re as _re
                    return _re.sub(r"[^a-z0-9]+", "", (x or "").lower())
                # マスター候補
                master = load_symbol_master()
                mst = [(sym, name) for sym, name in master if (qn in _norm_ja(name)) or (qn in sym.lower())]
                # オフライン候補
                off = [(sym, name) for sym, name in OFFLINE_SYMBOLS if (qn in _norm_ja(name)) or (qn in sym.lower())]
                # ローマ字エイリアス（簡易）
                romaji_alias = [
                    ("toyota", "7203.T", "トヨタ自動車"),
                    ("sony", "6758.T", "ソニーグループ"),
                    ("nintendo", "7974.T", "任天堂"),
                    ("hitachi", "6501.T", "日立製作所"),
                    ("mitsubishi", "6503.T", "三菱電機"),
                    ("mitsubishi", "8058.T", "三菱商事"),
                    ("mitsui", "8031.T", "三井物産"),
                    ("sumitomo", "8316.T", "三井住友フィナンシャルグループ"),
                    ("mizuho", "8411.T", "みずほフィナンシャルグループ"),
                    ("keyence", "6861.T", "キーエンス"),
                    ("murata", "6981.T", "村田製作所"),
                    ("canon", "7751.T", "キヤノン"),
                    ("panasonic", "6752.T", "パナソニックＨＤ"),
                    ("softbank", "9434.T", "ソフトバンク"),
                    ("sbg", "9984.T", "ソフトバンクグループ"),
                    ("kddi", "9433.T", "ＫＤＤＩ"),
                    ("nissan", "7201.T", "日産自動車"),
                    ("honda", "7267.T", "ホンダ"),
                    ("inpex", "1605.T", "ＩＮＰＥＸ"),
                    ("eneos", "5020.T", "ＥＮＥＯＳホールディングス"),
                    ("ana", "9202.T", "ANA HD"),
                    ("jr east", "9020.T", "東日本旅客鉄道"),
                    ("tokyo electron", "8035.T", "東京エレクトロン"),
                    ("uniqlo", "9983.T", "ファーストリテイリング"),
                    ("msad", "8725.T", "MS&AD保険グループHD"), ("ms&ad", "8725.T", "MS&AD保険グループHD"), ("ms-ad", "8725.T", "MS&AD保険グループHD"), ("ms ad", "8725.T", "MS&AD保険グループHD"),
                    ("sompo", "8630.T", "ＳＯＭＰＯホールディングス"), ("tokio marine", "8766.T", "東京海上HD"), ("tmhd", "8766.T", "東京海上HD"),
                    ("yamaha motor", "7272.T", "ヤマハ発動機"), ("yamaha-motor", "7272.T", "ヤマハ発動機"), ("yamahamotor", "7272.T", "ヤマハ発動機"), ("yamaha", "7272.T", "ヤマハ発動機"),
                ]
                rterm = _clean_ascii(term)
                rom = []
                for k, sym, name in romaji_alias:
                    if rterm and rterm in _clean_ascii(k):
                        rom.append((sym, name))
                # 履歴候補
                used_syms = [x.get("symbol", "") for x in st.session_state.get("simple_trades", [])]
                hist = []
                if used_syms:
                    used = sorted({s for s in used_syms if isinstance(s, str) and s.strip()})
                    name_map = {s:n for s,n in OFFLINE_SYMBOLS}
                    for s in used:
                        nm = name_map.get(s, '')
                        if qn in _norm_ja(nm) or qn in s.lower():
                            hist.append((s, nm))
                # オンライン候補（ベストエフォート）
                net = []
                try:
                    from urllib.request import urlopen, Request
                    from urllib.parse import urlencode
                    import json as _json
                    params = { 'q': term, 'lang': 'ja-JP', 'region': 'JP' }
                    url = 'https://query1.finance.yahoo.com/v1/finance/search?' + urlencode(params)
                    req = Request(url, headers={'User-Agent':'Mozilla/5.0'})
                    with urlopen(req, timeout=3) as resp:
                        data = _json.loads(resp.read().decode('utf-8'))
                    quotes = data.get('quotes') or []
                    for it in quotes:
                        sym = it.get('symbol'); nm = it.get('shortname') or it.get('longname') or ''
                        if not sym or it.get('quoteType') != 'EQUITY':
                            continue
                        net.append((sym, nm))
                except Exception:
                    pass
                combined = []
                seen = set()
                for src in (mst, off, rom, net, hist):
                    for sym, nm in src:
                        if sym and sym not in seen:
                            label = f"{nm} ({sym})" if nm else sym
                            combined.append(label)
                            seen.add(sym)
                        if len(combined) >= 20:
                            break
                    if len(combined) >= 20:
                        break
                return combined

            sel_label = st_searchbox(
                search_function=_search_candidates,
                placeholder="銘柄を検索（例: トヨタ, 7203）",
                key=f"sym_search_{sel}"
            )
            if sel_label:
                st.session_state[sym_key] = sel_label
        else:
            st.text_input("銘柄（直接入力）", key=sym_key, placeholder="例: 7203 / トヨタ / toyota")
            query = (st.session_state.get(sym_key) or "").strip()
        # ensure query is always defined regardless of input widget type
        query = (st.session_state.get(sym_key) or "").strip()
        if len(query) >= 1:
            # 履歴候補
            used_syms = [x.get("symbol", "") for x in st.session_state.get("simple_trades", [])]
            candidates = sorted({s for s in used_syms if isinstance(s, str) and s.strip()})
            suggestions = [s for s in candidates if query.lower() in s.lower()]
            # オフライン候補（名称＋ティッカー、正規化一致）
            qn = _norm_ja(query)
            off_hits = [(sym, name) for sym, name in OFFLINE_SYMBOLS if (qn in _norm_ja(name)) or (qn in sym.lower())]
            # ネット候補（可能なら）
            net_hits = []
            # ネット候補（可能なら）
            try:
                from urllib.request import urlopen, Request
                from urllib.parse import urlencode
                import json as _json
                params = { 'q': query, 'lang': 'ja-JP', 'region': 'JP' }
                url = 'https://query1.finance.yahoo.com/v1/finance/search?' + urlencode(params)
                req = Request(url, headers={'User-Agent':'Mozilla/5.0'})
                with urlopen(req, timeout=5) as resp:
                    data = _json.loads(resp.read().decode('utf-8'))
                quotes = data.get('quotes') or []
                for it in quotes:
                    sym = it.get('symbol'); nm = it.get('shortname') or it.get('longname') or ''
                    if not sym or it.get('quoteType') != 'EQUITY':
                        continue
                    net_hits.append((sym, nm))
            except Exception:
                pass

            # 銘柄プルダウン（統合候補を1つに表示）
            name_map = {sym: name for sym, name in OFFLINE_SYMBOLS}
            items_combined = []  # list of symbols
            labels_combined = []
            # 優先順: オフライン → ネット → 履歴
            for sym, name in off_hits[:20]:
                label = f"{name} ({sym})"
                if sym not in items_combined:
                    items_combined.append(sym); labels_combined.append(label)
            for sym, nm in net_hits[:20]:
                label = f"{nm} ({sym})" if nm else sym
                if sym not in items_combined:
                    items_combined.append(sym); labels_combined.append(label)
            for s in suggestions[:20]:
                nm = name_map.get(s)
                label = f"{nm} ({s})" if nm else s
                if s not in items_combined:
                    items_combined.append(s); labels_combined.append(label)

            if labels_combined:
                sel_label = st.selectbox("銘柄", options=[f"直接入力: {query}"] + labels_combined, key=f"unified_symbol_{sel}")
                if sel_label and not sel_label.startswith("直接入力:"):
                    idx = labels_combined.index(sel_label)
                    chosen_sym = items_combined[idx]
                    st.session_state['apply_sym'] = chosen_sym
                    st.session_state['apply_sym_key'] = sym_key
                    try: st.rerun()
                    except Exception: pass

        # 価格の自動プリフィル（フォーム生成前に行うことで確実に反映）
        if _HAS_YF:
            cur_sym = (st.session_state.get(sym_key) or "").strip()
            buy_v = float(st.session_state.get(buy_key, 0.0) or 0.0)
            sell_v = float(st.session_state.get(sell_key, 0.0) or 0.0)
            prefill_key = f"_prefilled_symbol_{sel}"
            should_prefill = (len(cur_sym) >= 2) and (buy_v == 0.0 and sell_v == 0.0) and (st.session_state.get(prefill_key) != cur_sym)
            if should_prefill:
                price, norm, asof = fetch_price(cur_sym)
                if price is not None:
                    st.session_state[buy_key] = float(price)
                    st.session_state[sell_key] = float(price)
                    st.session_state[prefill_key] = cur_sym
                    st.info(f"価格設定: {norm} = {price:,.2f}（{asof}）")

        # 価格取得（フォーム外ボタン）
        if _HAS_YF:
            if st.button("価格取得", key=f"btn_fetch_{sel}"):
                cur_sym = (st.session_state.get(sym_key) or "").strip()
                price, norm, asof = fetch_price(cur_sym)
                if price is not None:
                    st.session_state[buy_key] = float(price)
                    st.session_state[sell_key] = float(price)
                    st.success(f"価格設定: {norm} = {price:,.2f}（{asof}）")
                else:
                    st.warning("価格を取得できませんでした。コード（例: 7203 / 7203.T）をご確認ください。")

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
