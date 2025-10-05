from datetime import date, datetime
from zoneinfo import ZoneInfo
import re
import os
import csv
import json
import io
import copy

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


def _infer_step_from_price(price: float) -> float:
    try:
        p = float(price)
    except Exception:
        return 1.0
    # 簡易ルール（目安）: 価格帯でステップを調整
    if p < 1000: return 0.1
    if p < 50000: return 1.0
    return 100.0


def _get_tax_rate() -> float:
    # 少数（例: 0.20315）で保持。既定は20.315%
    return float(st.session_state.get('tax_rate', 0.20315))


def _net_after_tax(amount: float, rate: float) -> float:
    # 利益にのみ課税。損失はそのまま（簡易モデル）
    try:
        a = float(amount)
    except Exception:
        return 0.0
    return a - (rate * a) if a > 0 else a


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
    # 現在のテーマ（light/dark）を把握して色を最適化
    try:
        _theme_base = st.get_option('theme.base') or 'light'
    except Exception:
        _theme_base = 'light'
    # アプリ内トグル優先、なければStreamlitテーマに追従
    _dark_pref = st.session_state.get('rc_dark_mode', None)
    is_dark = bool(_dark_pref) if _dark_pref is not None else (str(_theme_base).lower() == 'dark')

    # 背景・文字色（簡易）をテーマに合わせて適用
    if is_dark:
        bg = "#0b1220"   # 深めのダーク
        fg = "#ffffff"   # 文字は白で統一
        st.markdown(
            f"""
            <style>
            .stApp {{ background-color: {bg}; color: {fg}; }}
            /* Top-right option (popover/expander) button to gray */
            div[data-testid="stPopover"] > button,
            div[data-testid="stPopover"] button,
            div[data-testid="stExpander"] > details > summary,
            div[data-testid="stExpander"] summary {{
                background-color: #3a3a3a !important;
                color: #ffffff !important;
                border: 1px solid #545454 !important;
                border-radius: 6px !important;
                box-shadow: none !important;
            }}
            div[data-testid="stPopover"] > button:hover,
            div[data-testid="stPopover"] button:hover,
            div[data-testid="stExpander"] > details > summary:hover,
            div[data-testid="stExpander"] summary:hover {{
                background-color: #4a4a4a !important;
                border-color: #6b7280 !important;
            }}
            /* All buttons in dark mode (e.g., 価格取得/閉じる) */
            .stButton > button {{
                background-color: #3a3a3a !important;
                color: #ffffff !important;
                border: 1px solid #545454 !important;
                box-shadow: none !important;
            }}
            .stButton > button:hover {{
                background-color: #4a4a4a !important;
                border-color: #6b7280 !important;
            }}
            .stButton > button:active {{
                background-color: #2f2f2f !important;
                border-color: #4b5563 !important;
            }}
            /* Broaden selector for safety (inside our panel and general) */
            .rc-input .stButton button,
            .rc-input button,
            button[data-testid^="baseButton-"] {{
                background-color: #3a3a3a !important;
                color: #ffffff !important;
                border: 1px solid #545454 !important;
                box-shadow: none !important;
            }}
            .rc-input .stButton button:hover,
            .rc-input button:hover,
            button[data-testid^="baseButton-"]:hover {{
                background-color: #4a4a4a !important;
                border-color: #6b7280 !important;
            }}
            .rc-input .stButton button:active,
            .rc-input button:active,
            button[data-testid^="baseButton-"]:active {{
                background-color: #2f2f2f !important;
                border-color: #4b5563 !important;
            }}
            </style>
            """,
            unsafe_allow_html=True,
        )

    # 入力パネルの見た目（テーマに合わせてグレー系に）
    # ダーク: グレー基調でカード風に、ライト: 薄いグレー
    input_bg = "#2a2a2a" if is_dark else "#f3f4f6"
    input_fg = "#ffffff" if is_dark else "#111827"
    input_border = "#4b5563" if is_dark else "#e5e7eb"
    st.markdown(
        f"""
        <style>
        .rc-input {{
            background-color: {input_bg};
            color: {input_fg};
            padding: 12px 16px;
            border-radius: 8px;
            border: 0 !important;
            box-shadow: none !important;
        }}
        .rc-input .stMarkdown, .rc-input .stMetric, .rc-input label {{ color: {input_fg}; }}
        .rc-input .rc-label {{ color: {input_fg} !important; font-weight: 600; margin-bottom: 4px; }}
        /* テキスト入力のラベル（銘柄（直接入力））も白に */
        .rc-input [data-testid="stWidgetLabel"],
        .rc-input [data-testid="stWidgetLabel"] * ,
        .rc-input .stTextInput label {{
            color: {input_fg} !important;
        }}
        /* 税引後収益の数値とラベルも白に強制（ダーク時） */
        .rc-input .stMetric, .rc-input .stMetric * {{ color: {input_fg} !important; }}
        .rc-input [data-testid="stMetricValue"],
        .rc-input [data-testid="stMetricDelta"] {{ color: {input_fg} !important; }}
        /* 入力欄もカード内で馴染むように */
        .rc-input input, .rc-input textarea, .rc-input select {{
            background-color: {('#3a3a3a' if is_dark else '#ffffff')} !important;
            color: {input_fg} !important;
            border-color: {('#3f3f46' if is_dark else input_border)} !important;
            box-shadow: none !important;
        }}
        .rc-input .stNumberInput input {{
            background-color: {('#3a3a3a' if is_dark else '#ffffff')} !important;
            color: {input_fg} !important;
            border-color: {('#3f3f46' if is_dark else input_border)} !important;
            box-shadow: none !important;
        }}
        /* Streamlit TextInput (BaseWeb) の親コンテナも上書き */
        .rc-input [data-testid="stTextInput"] div[data-baseweb="input"] {{
            background-color: {('#3a3a3a' if is_dark else '#ffffff')} !important;
            border-color: {('#3f3f46' if is_dark else input_border)} !important;
            color: {input_fg} !important;
            box-shadow: none !important;
        }}
        .rc-input [data-testid="stTextInput"] div[data-baseweb="input"] input {{
            background-color: transparent !important;
            color: {input_fg} !important;
        }}
        /* さらに直接のテキスト型も強制 */
        .rc-input input[type="text"] {{
            background-color: {('#3a3a3a' if is_dark else '#ffffff')} !important;
            color: {input_fg} !important;
            border-color: {('#3f3f46' if is_dark else input_border)} !important;
        }}
        .rc-input input:focus, .rc-input textarea:focus, .rc-input select:focus,
        .rc-input .stNumberInput input:focus {{
            border-color: {('#525252' if is_dark else input_border)} !important;
            box-shadow: {('0 0 0 1px #525252 inset' if is_dark else 'none')} !important;
            outline: none !important;
        }}
        .rc-input ::placeholder {{ color: {('#d1d5db' if is_dark else '#6b7280')} !important; }}
        </style>
        """,
        unsafe_allow_html=True,
    )

    # ダークモード時のボタン/ラベル/入力欄のスタイル統一（Formスコープで強制適用）
    if is_dark:
        st.markdown(
            """
            <style>
            /* 入力フォーム全体をグレーのカードに */
            div[data-testid="stForm"] {
                background-color: #2a2a2a !important;
                color: #ffffff !important;
                padding: 12px 16px;
                border-radius: 8px;
                border: 0 !important;
                box-shadow: none !important;
            }
            /* ラベル/テキスト/メトリックを白 */
            div[data-testid="stForm"] label,
            div[data-testid="stForm"] .stMarkdown,
            div[data-testid="stForm"] [data-testid="stMetricValue"],
            div[data-testid="stForm"] [data-testid="stMetricDelta"],
            div[data-testid="stForm"] .stMetric,
            div[data-testid="stForm"] .stMetric * {
                color: #ffffff !important;
            }
            /* 入力欄: 背景グレー、枠は目立たない濃グレー */
            div[data-testid="stForm"] input,
            div[data-testid="stForm"] textarea,
            div[data-testid="stForm"] select,
            div[data-testid="stForm"] [data-testid="stNumberInput"] input,
            div[data-testid="stForm"] input[type="number"] {
                background-color: #3a3a3a !important;
                color: #ffffff !important;
                border-color: #3f3f46 !important;
                box-shadow: none !important;
            }
            div[data-testid="stForm"] input::placeholder,
            div[data-testid="stForm"] textarea::placeholder { color: #d1d5db !important; }
            div[data-testid="stForm"] input:focus,
            div[data-testid="stForm"] textarea:focus,
            div[data-testid="stForm"] select:focus,
            div[data-testid="stForm"] [data-testid="stNumberInput"] input:focus {
                border-color: #525252 !important;
                box-shadow: 0 0 0 1px #525252 inset !important;
                outline: none !important;
            }
            /* 保存ボタンを含むボタン類をグレー系に */
            div[data-testid="stForm"] [data-testid="stFormSubmitButton"] > button,
            div[data-testid="stForm"] .stButton > button,
            .rc-input .stButton > button,
            .stDownloadButton > button {
                background-color: #3a3a3a !important;
                color: #ffffff !important;
                border: 1px solid #545454 !important;
            }
            div[data-testid="stForm"] [data-testid="stFormSubmitButton"] > button:hover,
            div[data-testid="stForm"] .stButton > button:hover,
            .rc-input .stButton > button:hover,
            .stDownloadButton > button:hover {
                background-color: #4a4a4a !important;
                border-color: #6b7280 !important;
            }
            div[data-testid="stForm"] [data-testid="stFormSubmitButton"] > button:active,
            div[data-testid="stForm"] .stButton > button:active,
            .rc-input .stButton > button:active,
            .stDownloadButton > button:active {
                background-color: #2f2f2f !important;
                border-color: #4b5563 !important;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
    # 初期状態
    st.session_state.setdefault("selected", date.today().isoformat())
    st.session_state.setdefault("simple_trades", [])  # [{date, buy, sell, profit}]
    st.session_state.setdefault("input_visible", False)
    st.session_state.setdefault("use_tax", True)

    selected = st.session_state["selected"]

    # 登録済みの収益を日別に集計してイベント化（税引後オプション対応、プラス=赤、マイナス=緑、ゼロ=グレー）
    def _fmt_amount(n: float) -> str:
        sign = '+' if n > 0 else '-' if n < 0 else '±'
        return f"{sign}{abs(n):,.0f}"

    use_tax = bool(st.session_state.get('use_tax', True))
    tax_rate = _get_tax_rate()
    totals = {}
    for e in st.session_state.get("simple_trades", []):
        d = e.get("date")
        p = float(e.get("profit") or 0.0)
        if use_tax:
            p = _net_after_tax(p, tax_rate)
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
        "timeZone": "Asia/Tokyo",
        "firstDay": 0,  # Sunday
        "headerToolbar": {"left": "prev,next today", "center": "title", "right": ""},
        # ヘッダー行（曜日帯）を非表示にして白帯を根本解消
        "dayHeaders": False,
        "weekNumbers": False,
        "navLinks": False,
        "editable": False,
        "selectable": False,
        "height": "auto",
        # Show weeks up to the one that contains the last day of month
        "fixedWeekCount": False,
    }

    zero_color = "#ffffff" if is_dark else "#6b7280"
    pos_color = "#ffffff" if is_dark else "#ef4444"  # red-500
    neg_color = "#ffffff" if is_dark else "#10b981"  # emerald-500
    cal_bg = "#000000" if is_dark else "transparent"
    cal_grid = "#1f2937" if is_dark else "#e5e7eb"
    cal_fg = "#ffffff" if is_dark else "inherit"
    cal_border = "#000000" if is_dark else "transparent"
    # Grid lines inside calendar should remain visible in dark mode
    grid_color = cal_grid  # use dark gray (not pure black)
    custom_css = f"""
    /* remove background/border and bolden text */
    .fc .rc-pos, .fc .rc-neg, .fc .rc-zero {{ background: transparent !important; border: 0 !important; box-shadow: none !important; }}
    .fc .rc-pos .fc-event-main, .fc .rc-pos .fc-event-title {{ color:{pos_color} !important; font-weight:700 !important; text-align:right; white-space:nowrap; padding-right:4px; }}
    .fc .rc-neg .fc-event-main, .fc .rc-neg .fc-event-title {{ color:{neg_color} !important; font-weight:700 !important; text-align:right; white-space:nowrap; padding-right:4px; }}
    .fc .rc-zero .fc-event-main, .fc .rc-zero .fc-event-title {{ color:{zero_color} !important; font-weight:700 !important; text-align:right; white-space:nowrap; padding-right:4px; }}
    /* Force calendar dark background when dark mode */
    .fc-theme-standard .fc-scrollgrid,
    .fc .fc-view-harness,
    .fc .fc-col-header,
    .fc .fc-col-header-cell,
    .fc .fc-daygrid,
    .fc .fc-daygrid-day,
    .fc .fc-daygrid-day-frame,
    .fc .fc-toolbar.fc-header-toolbar {{
        background-color: {cal_bg} !important;
    }}
    .fc .fc-daygrid-day-bg, .fc .fc-daygrid-day-top, .fc .fc-daygrid-body {{
        background-color: {cal_bg} !important;
    }}
    /* Body section right under the header (where white band appears) */
    .fc .fc-scrollgrid-section-body,
    .fc .fc-scrollgrid-section-body table,
    .fc .fc-scrollgrid-section-header + .fc-scrollgrid-section,
    .fc .fc-scrollgrid-section-header + .fc-scrollgrid-section table,
    .fc .fc-daygrid-body,
    .fc .fc-daygrid-body table,
    .fc .fc-scrollgrid .fc-scroller-harness,
    .fc .fc-scrollgrid .fc-scroller-harness-liquid,
    .fc .fc-scrollgrid .fc-scroller {{
        background-color: {cal_bg} !important;
    }}
    /* Header row explicit background */
    .fc .fc-col-header, .fc .fc-col-header * {{
        background-color: {cal_bg} !important;
    }}
    .fc .fc-scrollgrid, .fc .fc-scrollgrid table, .fc .fc-scrollgrid thead,
    .fc .fc-scrollgrid thead tr, .fc .fc-scrollgrid thead th {{
        background-color: {cal_bg} !important;
    }}
    /* Remove outer frame of calendar to avoid border between year-total and input */
    .fc-theme-standard .fc-scrollgrid {{ border: 0 !important; }}
    .fc {{ --fc-border-color: {grid_color} !important; }}
    .fc-theme-standard .fc-scrollgrid, .fc-theme-standard td, .fc-theme-standard th {{ border-color: {grid_color} !important; }}
    /* Explicitly tune header borders to black in dark */
    .fc .fc-toolbar.fc-header-toolbar {{ border-bottom: 1px solid {cal_border} !important; box-shadow: none !important; background-color: {cal_bg} !important; }}
    .fc-theme-standard .fc-scrollgrid {{ border-top: 1px solid {cal_border} !important; }}
    .fc-theme-standard .fc-scrollgrid thead {{ border-top: 1px solid {cal_border} !important; }}
    .fc-theme-standard .fc-col-header,
    .fc-theme-standard .fc-col-header-cell,
    .fc-theme-standard thead th,
    .fc-theme-standard th {{ border-top: 1px solid {cal_border} !important; }}
    .fc-theme-standard th, .fc-theme-standard td {{ border-top-color: {cal_border} !important; }}
    .fc .fc-scrollgrid-section-header, .fc .fc-scrollgrid-section-header table {{
        background-color: {cal_bg} !important;
        border-top: 1px solid {cal_border} !important;
    }}
    /* Simplest fix: completely hide the day header section */
    .fc .fc-scrollgrid-section-header {{ display: none !important; height: 0 !important; border: 0 !important; }}
    .fc .fc-col-header, .fc .fc-col-header * {{ display: none !important; }}
    .fc .fc-scrollgrid-section-header + .fc-scrollgrid-section {{ border-top: 0 !important; }}
    /* If theme variables are used, override calendar page BG to black */
    .fc {{ --fc-page-bg-color: {cal_bg} !important; --fc-neutral-bg-color: {cal_bg} !important; }}
    /* Overlay black lines to mask any residual white hairlines */
    .fc .fc-toolbar.fc-header-toolbar {{ position: relative !important; }}
    .fc .fc-toolbar.fc-header-toolbar::after {{
        content: '';
        position: absolute;
        left: 0; right: 0; bottom: 0;
        height: 1px; background-color: {cal_border};
        z-index: 3; pointer-events: none;
    }}
    .fc .fc-col-header {{ position: relative !important; }}
    .fc .fc-col-header::before {{
        content: '';
        position: absolute;
        left: 0; right: 0; top: 0; bottom: 0;
        background-color: {cal_bg};
        z-index: 0; pointer-events: none;
    }}
    .fc, .fc * {{ color: {cal_fg} !important; }}
    /* container & sums placement */
    .rc-calwrap {{ position: relative; }}
    .rc-sum {{ position:absolute; right:6px; bottom:6px; text-align:right; font-weight:700; background: transparent; }}
    .rc-sum .rc-pos {{ color:{pos_color} !important; }}
    .rc-sum .rc-neg {{ color:{neg_color} !important; }}
    .rc-sum .rc-zero {{ color:{zero_color} !important; }}
    """
    # 保存/読込ユーティリティ
    DATA_DIR = 'data'
    TRADES_JSON = os.path.join(DATA_DIR, 'simple_trades.json')

    def _ensure_data_dir():
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
        except Exception:
            pass

    def _export_csv_text(trades: list[dict]) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(['date','symbol','buy','sell','quantity','profit'])
        for t in (trades or []):
            w.writerow([t.get('date',''), t.get('symbol',''),
                        t.get('buy',0.0), t.get('sell',0.0), t.get('quantity',0.0), t.get('profit',0.0)])
        return buf.getvalue()

    def _save_trades(trades: list[dict]) -> None:
        _ensure_data_dir()
        try:
            with open(TRADES_JSON, 'w', encoding='utf-8') as f:
                json.dump({'items': trades, 'savedAt': datetime.utcnow().isoformat()}, f, ensure_ascii=False)
        except Exception:
            pass

    def _load_trades() -> list[dict]:
        try:
            if os.path.exists(TRADES_JSON):
                with open(TRADES_JSON, encoding='utf-8') as f:
                    obj = json.load(f)
                items = obj.get('items') if isinstance(obj, dict) else None
                if isinstance(items, list):
                    return items
        except Exception:
            pass
        return []

    # Undoスタック（直前状態を保存）
    st.session_state.setdefault("undo_stack", [])  # list[str(JSON)]

    def _push_undo():
        try:
            snapshot = json.dumps(st.session_state.get("simple_trades", []), ensure_ascii=False)
            st.session_state["undo_stack"].append(snapshot)
        except Exception:
            pass

    def _pop_undo():
        try:
            stk = st.session_state.get("undo_stack", [])
            if not stk:
                return False
            snapshot = stk.pop()
            st.session_state["simple_trades"] = json.loads(snapshot)
            return True
        except Exception:
            return False

    # CSVインポート（simple_trades 形式に取り込み）
    def _parse_import_csv(data_bytes: bytes) -> tuple[list[dict], list[str]]:
        errs: list[str] = []
        rows: list[dict] = []
        if not data_bytes:
            return rows, errs
        text = None
        for enc in ("utf-8-sig", "utf-8", "cp932"):
            try:
                text = data_bytes.decode(enc)
                break
            except Exception:
                continue
        if text is None:
            errs.append("CSVのデコードに失敗しました")
            return rows, errs
        reader = csv.DictReader(io.StringIO(text))
        def _get(d, names, default=""):
            for n in names:
                if n in d and d.get(n) not in (None,""):
                    return d.get(n)
            return default
        for i, r in enumerate(reader, start=1):
            try:
                d = str(_get(r, ["date", "日付"]).strip())
                sym = str(_get(r, ["symbol", "銘柄", "コード"]).strip())
                buy = _get(r, ["buy", "買値"]) or ""
                sell = _get(r, ["sell", "売値"]) or ""
                qty = _get(r, ["quantity", "qty", "株数"]) or ""
                prf = _get(r, ["profit", "収益"]) or ""
                def _to_f(x):
                    if x is None or x=="":
                        return None
                    return float(str(x).replace(",",""))
                buy_v = _to_f(buy)
                sell_v = _to_f(sell)
                qty_v = _to_f(qty) or 0.0
                prf_v = _to_f(prf)
                if prf_v is None and (buy_v is not None and sell_v is not None):
                    prf_v = (sell_v - buy_v) * qty_v
                if not d:
                    errs.append(f"{i}行目: dateが空です")
                    continue
                rows.append({
                    "date": d[:10],
                    "symbol": sym,
                    "buy": float(buy_v or 0.0),
                    "sell": float(sell_v or 0.0),
                    "quantity": float(qty_v or 0.0),
                    "profit": float(prf_v or 0.0),
                })
            except Exception as e:
                errs.append(f"{i}行目: {e}")
        return rows, errs

    # 初回ロード時に永続化ファイルから復元（セッションが空の場合）
    if not st.session_state.get("_trades_loaded_once"):
        if not st.session_state.get("simple_trades"):
            loaded = _load_trades()
            if loaded:
                st.session_state["simple_trades"] = loaded
        st.session_state["_trades_loaded_once"] = True

    # 上部右側にオプション（税設定/データ）ポップオーバーを配置
    top_cols = st.columns([8,1])
    with top_cols[1]:
        try:
            pop = st.popover("⋯", use_container_width=True)
        except Exception:
            # st.popover が無い場合のフォールバック
            pop = st.expander("⋯ オプション", expanded=False)
        with pop:
            st.markdown("**オプション**")
            # アプリ内ダークモード切替（ストリームリットの設定が見えない場合の代替）
            dm_default = bool(st.session_state.get('rc_dark_mode', is_dark))
            dm = st.checkbox('ダークモード', value=dm_default, key='rc_dark_mode')
            st.caption("右上の設定からテーマが出ない場合はこのスイッチをご利用ください。")
            use_tax_new = st.checkbox('税引後の値を表示する', value=bool(st.session_state.get('use_tax', True)), key='use_tax_checkbox')
            st.session_state['use_tax'] = use_tax_new
            if use_tax_new:
                pct = st.number_input('税率(%)', min_value=0.0, max_value=100.0, step=0.001, value=float(_get_tax_rate()*100), key='tax_input_global')
                st.session_state['tax_rate'] = float(pct)/100.0

            st.markdown("---")
            st.markdown("**データ**")
            c_up1, c_up2 = st.columns([1,1])
            with c_up1:
                sample = "date,symbol,buy,sell,quantity,profit\n2025-10-01,7203.T,2400,2500,100,10000\n"
                st.download_button("サンプルCSV", data=sample.encode("utf-8"), file_name="sample_trades.csv", mime="text/csv")
            with c_up2:
                if st.button("元に戻す", disabled=not st.session_state.get("undo_stack")):
                    if _pop_undo():
                        st.rerun()
            up = st.file_uploader("CSV取込 (date,symbol,buy,sell,quantity,profit)", type=["csv"], key="uploader_trades")
            if up is not None:
                rows, errs = _parse_import_csv(up.read())
                if rows:
                    _push_undo()
                    st.session_state["simple_trades"].extend(rows)
                    _save_trades(st.session_state["simple_trades"])
                    st.success(f"{len(rows)}件を取り込みました")
                if errs:
                    st.caption("\n".join([f"・{e}" for e in errs]))

            # エクスポート（現在のセッション内容）
            trades_now = st.session_state.get("simple_trades", [])
            exp_csv = _export_csv_text(trades_now).encode('utf-8')
            exp_json = json.dumps({'items': trades_now}, ensure_ascii=False).encode('utf-8')
            c_ex1, c_ex2, c_ex3 = st.columns([1,1,1])
            with c_ex1:
                st.download_button("CSVエクスポート", data=exp_csv, file_name="trades_export.csv", mime="text/csv")
            with c_ex2:
                st.download_button("JSONエクスポート", data=exp_json, file_name="trades_export.json", mime="application/json")
            with c_ex3:
                if st.button("保存(ローカル)"):
                    _save_trades(trades_now)
                    st.success("保存しました (data/simple_trades.json)")

    st.markdown('<div class="rc-calwrap">', unsafe_allow_html=True)
    state = st_calendar(
        events=events,
        options=options,
        callbacks=["dateClick", "datesSet"],
        custom_css=custom_css,
        key=f"month_calendar_{'dark' if is_dark else 'light'}",
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
            val = float(ent.get("profit") or 0.0)
            year_total += _net_after_tax(val, tax_rate) if use_tax else val
            if dt.month == view_month:
                month_total += _net_after_tax(val, tax_rate) if use_tax else val

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
            # ISO日時が来た場合は必ずJSTに変換して日付のみを採用
            if 'T' in s:
                try:
                    z = s.replace('Z', '+00:00')
                    dt = datetime.fromisoformat(z)
                    jst = dt.astimezone(ZoneInfo('Asia/Tokyo'))
                    return jst.date().isoformat()
                except Exception:
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
        st.markdown('<div class="rc-input">', unsafe_allow_html=True)
        st.subheader(f"入力（{sel}）")
        buy_key = f"buy_{sel}"
        sell_key = f"sell_{sel}"
        qty_key = f"qty_{sel}"
        sym_key = f"sym_{sel}"
        st.session_state.setdefault(buy_key, 0.0)
        st.session_state.setdefault(sell_key, 0.0)
        st.session_state.setdefault(qty_key, 100.0)
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
            ("5706.T", "三井金属鉱山"), ("5713.T", "住友金属鉱山"), ("5711.T", "三菱マテリアル"), ("5714.T", "ＤＯＷＡホールディングス"),
            ("2768.T", "双日"), ("4901.T", "富士フイルムＨＤ"), ("4063.T", "信越化学工業"),
            ("4502.T", "武田薬品工業"), ("4503.T", "アステラス製薬"), ("4523.T", "エーザイ"), ("4568.T", "第一三共"), ("4519.T", "中外製薬"),
            ("5108.T", "ブリヂストン"), ("6752.T", "パナソニックＨＤ"), ("2914.T", "日本たばこ産業"),
            ("1605.T", "ＩＮＰＥＸ"), ("5020.T", "ＥＮＥＯＳホールディングス"),
            ("7201.T", "日産自動車"), ("7267.T", "ホンダ"), ("7269.T", "スズキ"), ("7270.T", "ＳＵＢＡＲＵ"), ("6902.T", "デンソー"),
            ("4062.T", "イビデン"), ("6594.T", "ニデック"), ("6762.T", "ＴＤＫ"), ("6988.T", "日東電工"),
            ("6324.T", "ハーモニックドライブ"), ("6367.T", "ダイキン工業"), ("6273.T", "ＳＭＣ"), ("7735.T", "ＳＣＲＥＥＮホールディングス"), ("7731.T", "ニコン"), ("7752.T", "リコー"),
            ("4661.T", "オリエンタルランド"), ("3382.T", "セブン＆アイ・ホールディングス"),
            ("8001.T", "伊藤忠商事"), ("8002.T", "丸紅"), ("8053.T", "住友商事"), ("8591.T", "オリックス"),
            ("5201.T", "ＡＧＣ"), ("3402.T", "東レ"),
            ("6098.T", "リクルートホールディングス"),
            ("9021.T", "ＪＲ西日本"), ("9022.T", "ＪＲ東海"), ("9201.T", "日本航空"), ("9202.T", "ＡＮＡ ＨＤ"),
            ("5401.T", "日本製鉄"), ("5411.T", "ＪＦＥホールディングス"),
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

        # 銘柄入力（タイプ中にプルダウンで候補表示：streamlit-searchbox を優先利用／モード共通）
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
            if is_dark:
                st.markdown('<div class="rc-label">銘柄（直接入力）</div>', unsafe_allow_html=True)
                st.text_input("", key=sym_key, placeholder="例: 7203 / トヨタ / toyota", label_visibility="collapsed")
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

        # 価格取得（フォーム外ボタン）
        if _HAS_YF:
            if st.button("価格取得", key=f"btn_fetch_{sel}"):
                cur_sym = (st.session_state.get(sym_key) or "").strip()
                price, norm, asof = fetch_price(cur_sym)
                if price is not None:
                    st.session_state[buy_key] = float(price)
                    st.session_state[sell_key] = float(price)
                    # 取得結果の通知は行わない（UI上のノイズを減らす）

        with st.form(f"trade_form_{sel}"):
            c1, c2, c3, c4 = st.columns([1,1,1,1])
            # 銘柄に応じてステップを推定（価格帯で可変）。手動取得後にも更新されます。
            step_val = 1.0
            cur_sym_text = st.session_state.get(sym_key) or ""
            if _HAS_YF and cur_sym_text:
                pr, _norm, _asof = fetch_price(cur_sym_text)
                if pr is not None:
                    step_val = _infer_step_from_price(pr)
            with c1:
                buy = st.number_input("買値", min_value=0.0, step=step_val, key=buy_key)
            with c2:
                sell = st.number_input("売値", min_value=0.0, step=step_val, key=sell_key)
            with c3:
                qty = st.number_input("株数", min_value=0.0, step=100.0, key=qty_key)
            gross = (float(st.session_state[sell_key]) - float(st.session_state[buy_key])) * float(st.session_state[qty_key] or 0.0)
            net = _net_after_tax(gross, _get_tax_rate())
            with c4:
                if bool(st.session_state.get('use_tax', True)):
                    st.metric("税引後収益", f"{net:,.2f}")
                else:
                    st.metric("収益", f"{gross:,.2f}")
            submitted = st.form_submit_button("保存")

        if submitted:
            st.session_state["simple_trades"].append({
                "date": sel,
                "symbol": str(st.session_state[sym_key]).strip(),
                "buy": float(st.session_state[buy_key] or 0.0),
                "sell": float(st.session_state[sell_key] or 0.0),
                "quantity": float(st.session_state[qty_key] or 0.0),
                "profit": float(gross),
            })
            _save_trades(st.session_state["simple_trades"])
            st.success("保存しました")

        # 登録済み一覧（当日分）と閉じる
        entries = [x for x in st.session_state["simple_trades"] if x["date"] == sel]
        if entries:
            st.markdown("#### 登録済み")
            for idx, e in enumerate(entries):
                show_tax = bool(st.session_state.get('use_tax', True))
                cols = st.columns([3,2,2,2,2,2,1,1,1] if show_tax else [3,2,2,2,2,1,1,1])
                cols[0].write(f"銘柄: {e.get('symbol','') or '-'}")
                cols[1].write(f"買値: {e['buy']:,.2f}")
                cols[2].write(f"売値: {e['sell']:,.2f}")
                cols[3].write(f"株数: {int(e.get('quantity', 0))}")
                cols[4].write(f"収益: {e['profit']:,.2f}")
                next_col = 5
                if show_tax:
                    cols[5].write(f"税引後: {_net_after_tax(float(e['profit']), _get_tax_rate()):,.2f}")
                    next_col = 6
                if cols[next_col].button("編集", key=f"edit-{sel}-{idx}"):
                    st.session_state[f"_editing_{sel}_{idx}"] = True
                if cols[next_col+1].button("複製", key=f"dup-{sel}-{idx}"):
                    _push_undo()
                    st.session_state["simple_trades"].append(copy.deepcopy(e))
                    _save_trades(st.session_state["simple_trades"])
                    st.success("複製しました")
                if cols[next_col+2].button("削除", key=f"del-{sel}-{idx}"):
                    _push_undo()
                    all_list = st.session_state["simple_trades"]
                    for j, a in enumerate(all_list):
                        if (
                            a.get("date")==sel and
                            a.get("symbol","")==e.get("symbol","") and
                            a.get("buy")==e.get("buy") and
                            a.get("sell")==e.get("sell") and
                            a.get("quantity",0)==e.get("quantity",0) and
                            a.get("profit")==e.get("profit")
                        ):
                            del all_list[j]
                            break
                    # 変更は次の描画で反映されます
                    _save_trades(st.session_state["simple_trades"])

                # インライン編集フォーム
                if st.session_state.get(f"_editing_{sel}_{idx}"):
                    with st.expander("編集", expanded=True):
                        eb = st.number_input("買値", value=float(e.get("buy",0.0)), step=1.0, key=f"_eb_{sel}_{idx}")
                        es = st.number_input("売値", value=float(e.get("sell",0.0)), step=1.0, key=f"_es_{sel}_{idx}")
                        eq = st.number_input("株数", value=float(e.get("quantity",0.0)), step=100.0, key=f"_eq_{sel}_{idx}")
                        esym = st.text_input("銘柄", value=str(e.get("symbol","")), key=f"_esy_{sel}_{idx}")
                        if st.button("更新", key=f"_update_{sel}_{idx}"):
                            _push_undo()
                            e.update({
                                "buy": float(eb or 0.0),
                                "sell": float(es or 0.0),
                                "quantity": float(eq or 0.0),
                                "symbol": str(esym or "").strip(),
                                "profit": (float(es or 0.0) - float(eb or 0.0)) * float(eq or 0.0),
                            })
                            st.session_state[f"_editing_{sel}_{idx}"] = False
                            _save_trades(st.session_state["simple_trades"])
                            st.success("更新しました")

        if st.button("閉じる"):
            st.session_state["input_visible"] = False
        st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.info("日付セルをクリックして入力を開きます。")


if __name__ == "__main__":
    main()
