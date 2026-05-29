# Google Sheets-Backed Business Dashboard
# 起動: streamlit run app.py

import streamlit as st
import pandas as pd
import re
import html as _html_mod
import threading
from datetime import datetime
import gsheets
import time as _time

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# グローバルインメモリキャッシュ（オンデマンド方式）
# 初回アクセス時にシートをAPIからロードしてメモリに保存。
# バックグラウンドで15秒ごとに全シートを自動更新する。
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_OrigGSheetWS = gsheets.GSheetWS  # モンキーパッチ前に保存

_SHEETS_CFG = [
    ('年次計画',                  True, True),
    ('月次計画',                  True, True),
    ('値上げ効果計算表',           True, True),
    ('収益構造シミュレーション ', True, True),
    ('ロジック',                  True, True),
]


def _fetch_dict(sheet_name: str, data_only: bool) -> dict:
    ws = _OrigGSheetWS(sheet_name, data_only=data_only)
    result = ws.to_dict()
    ws.close()
    return result


def _bg_loop(store: dict) -> None:
    """バックグラウンドで15秒ごとに全シートを更新する。"""
    while True:
        _time.sleep(15)
        for sname, do_v, do_f in _SHEETS_CFG:
            try:
                if do_v:
                    d = _fetch_dict(sname, True)
                    with store['lock']:
                        store['data'][sname + '_v'] = d
                if do_f:
                    d = _fetch_dict(sname, False)
                    with store['lock']:
                        store['data'][sname + '_f'] = d
            except Exception:
                pass


@st.cache_resource
def _get_store() -> dict:
    """プロセス内で共有するインメモリストア。バックグラウンドスレッドを起動。"""
    store: dict = {'data': {}, 'lock': threading.Lock()}
    threading.Thread(target=_bg_loop, args=(store,), daemon=True).start()
    return store


class _CachedWS:
    """GSheetWSの代替。
    キャッシュヒット時はメモリから即時返却。
    キャッシュミス時は実APIで取得してキャッシュに保存（初回のみ低速）。
    """

    def __init__(self, sheet_name: str, data_only: bool = True) -> None:
        store = _get_store()
        key = sheet_name + ('_v' if data_only else '_f')

        with store['lock']:
            src = store['data'].get(key)  # None = 未ロード

        if src is None:
            # キャッシュミス: 実APIで取得してストアに保存
            ws = _OrigGSheetWS(sheet_name, data_only=data_only)
            src = ws.to_dict()
            ws.close()
            with store['lock']:
                store['data'][key] = src

        self._d: dict = {r: dict(c) for r, c in src.items()}
        self._mr = max(self._d.keys(), default=0)
        self._mc = max(
            (max(cd.keys(), default=0) for cd in self._d.values() if cd),
            default=0,
        )

    def cell(self, row: int, col: int):
        return gsheets._Cell(self._d.get(row, {}).get(col))

    @property
    def max_row(self) -> int:
        return self._mr

    @property
    def max_column(self) -> int:
        return self._mc

    def close(self) -> None:
        pass


gsheets.GSheetWS = _CachedWS  # type: ignore[assignment]


def _cache_set(sheet: str, row: int, col: int, value) -> None:
    """ユーザー入力値をメモリキャッシュに即時反映する。"""
    store = _get_store()
    with store['lock']:
        store['data'].setdefault(sheet + '_v', {}).setdefault(row, {})[col] = value


NAVY = "#1A3A5C"
GOLD = "#C8973A"
BG   = "#F8F9FA"

st.set_page_config(
    page_title="経営管理ダッシュボード",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# グローバル CSS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;700&display=swap');

html, body, [class*="css"] {{
    font-family: 'Noto Sans JP', 'BIZ UDPGothic', sans-serif !important;
}}
.main .block-container {{
    background-color: {BG};
    padding-top: 1.5rem;
    max-width: 1400px;
}}

/* Dashboard Header */
.dash-header {{
    background: linear-gradient(135deg, {NAVY} 0%, #1e4d7a 100%);
    color: white;
    padding: 1.5rem 2rem;
    border-radius: 12px;
    margin-bottom: 1.5rem;
    box-shadow: 0 4px 20px rgba(26,58,92,.28);
}}
.dash-header h1 {{ margin:0; font-size:1.65rem; font-weight:700; letter-spacing:.04em; }}
.dash-header p  {{ margin:.35rem 0 0; opacity:.72; font-size:.87rem; }}

/* Section Title */
.sec-title {{
    color: {NAVY};
    font-size: .95rem;
    font-weight: 700;
    border-left: 4px solid {GOLD};
    padding-left: .55rem;
    margin-bottom: .8rem;
    margin-top: .2rem;
}}

/* Number Input */
div[data-testid="stNumberInput"] input {{
    border: 1.5px solid {GOLD} !important;
    border-radius: 6px !important;
    color: {NAVY} !important;
    font-weight: 600 !important;
    background: white !important;
    padding: .45rem .7rem !important;
}}
div[data-testid="stNumberInput"] input:focus {{
    border-color: {NAVY} !important;
    box-shadow: 0 0 0 3px {GOLD}44 !important;
    outline: none !important;
}}
div[data-testid="stNumberInput"] input:disabled {{
    color: {NAVY} !important;
    -webkit-text-fill-color: {NAVY} !important;
    opacity: 1 !important;
}}
div[data-testid="stNumberInput"] label {{
    color: {NAVY} !important;
    font-weight: 600 !important;
    font-size: .85rem !important;
    letter-spacing: .02em !important;
}}

/* Text Input */
div[data-testid="stTextInput"] input {{
    border: 1.5px solid {GOLD} !important;
    border-radius: 6px !important;
    color: {NAVY} !important;
    font-weight: 600 !important;
    background: white !important;
    padding: .45rem .7rem !important;
}}
div[data-testid="stTextInput"] input:focus {{
    border-color: {NAVY} !important;
    box-shadow: 0 0 0 3px {GOLD}44 !important;
    outline: none !important;
}}
div[data-testid="stTextInput"] input:disabled {{
    color: {NAVY} !important;
    -webkit-text-fill-color: {NAVY} !important;
    opacity: 1 !important;
}}
div[data-testid="stTextInput"] label {{
    color: {NAVY} !important;
    font-weight: 600 !important;
    font-size: .85rem !important;
    letter-spacing: .02em !important;
}}
div[data-testid="stNumberInput"] .step-down,
div[data-testid="stNumberInput"] .step-up {{
    color: {GOLD} !important;
}}

/* KPI Card */
.kpi-card {{
    background: white;
    border-left: 4px solid {GOLD};
    border-radius: 8px;
    padding: .9rem 1.2rem;
    margin-bottom: .7rem;
    box-shadow: 0 2px 8px rgba(26,58,92,.07);
}}
.kpi-badge {{
    font-size: .7rem;
    background: {GOLD}22;
    color: {GOLD};
    border-radius: 4px;
    padding: 1px 7px;
    font-weight: 700;
    margin-bottom: .35rem;
    display: inline-block;
    letter-spacing: .05em;
}}
.kpi-label {{ color: #444; font-size: .83rem; font-weight: 600; margin-bottom: .1rem; }}
.kpi-value {{ color: {NAVY}; font-size: 1.45rem; font-weight: 700; line-height: 1.3; }}
.kpi-unit  {{ color: #888; font-size: .76rem; margin-left: .15rem; }}

/* Divider */
.divider {{
    border: none;
    border-top: 1px solid #e0e0e0;
    margin: 1.2rem 0;
}}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {{
    background: white;
    border-radius: 8px;
    padding: 4px;
    gap: 4px;
    box-shadow: 0 1px 5px rgba(0,0,0,.08);
    margin-bottom: 1.2rem;
}}
.stTabs [data-baseweb="tab"] {{
    background: transparent;
    color: #555;
    border-radius: 6px;
    font-weight: 600;
    padding: .4rem 1.4rem;
    font-size: .9rem;
}}
.stTabs [aria-selected="true"] {{
    background: {NAVY} !important;
    color: white !important;
}}

/* Buttons */
.stButton > button {{
    background: {NAVY} !important;
    color: white !important;
    border: none !important;
    border-radius: 6px !important;
    font-weight: 600 !important;
    font-size: .88rem !important;
    transition: background .15s, transform .1s, box-shadow .15s;
}}
.stButton > button:hover {{
    background: {GOLD} !important;
    transform: translateY(-1px) !important;
    box-shadow: 0 4px 12px {GOLD}77 !important;
}}

/* Admin Header */
.admin-header {{
    background: {NAVY};
    color: white;
    padding: 1rem 1.5rem;
    border-radius: 8px;
    margin-bottom: 1.2rem;
}}
.admin-header h2 {{ margin:0; font-size:1.15rem; font-weight:700; }}
.admin-header p  {{ margin:.2rem 0 0; opacity:.72; font-size:.82rem; }}

/* Expander */
details summary {{
    color: {NAVY} !important;
    font-weight: 600 !important;
    font-size: .88rem !important;
}}

/* Annual Plan Table (static) */
.bs-tbl {{
    width: 100%;
    border-collapse: collapse;
    font-size: .83rem;
    font-family: 'Noto Sans JP', sans-serif;
}}
.bs-tbl thead th {{
    background: {NAVY};
    color: white;
    padding: 8px 14px;
    text-align: right;
    font-weight: 600;
    white-space: nowrap;
}}
.bs-tbl thead th:first-child {{ text-align: left; min-width: 200px; }}
.bs-tbl .r-total td {{
    background: rgba(26,58,92,0.10);
    font-weight: 700;
    color: {NAVY};
    padding: 7px 14px;
    border-top: 1.5px solid rgba(26,58,92,0.22);
    border-bottom: 1.5px solid rgba(26,58,92,0.22);
    text-align: right;
}}
.bs-tbl .r-total td:first-child {{ text-align: left; }}
.bs-tbl .r-sub td {{
    background: #f5f7fc;
    padding: 6px 14px 6px 18px;
    color: {NAVY};
    font-weight: 600;
    border-bottom: 1px solid #e8eaf0;
    text-align: right;
}}
.bs-tbl .r-sub td:first-child {{ text-align: left; }}
.bs-tbl .r-item td {{
    padding: 5px 14px 5px 28px;
    color: #444;
    border-bottom: 1px solid #f0f0f0;
    text-align: right;
}}
.bs-tbl .r-item td:first-child {{ text-align: left; }}
.bs-tbl tbody tr:hover td {{ background: {GOLD}18 !important; }}

/* Annual Plan Interactive Table */
.yp-hdr,.yp-hdr-yr,.yp-section,.yp-group,.yp-total,.yp-sub,.yp-item {{
    font-family: 'Yu Gothic','Meiryo','MS PGothic','Noto Sans JP',sans-serif;
    text-rendering: optimizeSpeed;
    -webkit-font-smoothing: subpixel-antialiased;
}}
.yp-hdr     {{ background:{NAVY}; color:white; font-weight:600; font-size:.83rem; padding:8px 6px; min-height:36px; }}
.yp-hdr-yr  {{ background:{NAVY}; color:white; font-weight:600; font-size:.83rem; padding:8px 4px; text-align:center; white-space:nowrap; }}
.yp-section {{ background:{NAVY}; color:white; font-weight:700; font-size:.83rem; padding:7px 10px; }}
.yp-group   {{ background:{NAVY}; color:white; font-weight:700; font-size:.88rem; padding:8px 14px; display:block; }}
.yp-total   {{ background:rgba(26,58,92,0.10); color:{NAVY}; font-weight:700; font-size:.83rem; padding:7px 10px; border-top:1.5px solid rgba(26,58,92,0.22); border-bottom:1.5px solid rgba(26,58,92,0.22); }}
.yp-sub     {{ background:#f5f7fc; color:{NAVY}; font-weight:600; font-size:.83rem; padding:6px 10px 6px 14px; border-bottom:1px solid #e8eaf0; }}
.yp-item    {{ background:white; color:#444; font-size:.83rem; padding:5px 10px 5px 14px; border-bottom:1px solid #f0f0f0; }}
.yp-empty   {{ min-height:32px; background:white; border-bottom:1px solid #f0f0f0; }}
.yp-sep     {{ border:none; border-top:2px solid rgba(26,58,92,0.3); margin:10px 0 2px 0; }}

/* Monthly Plan Table */
.mp-tbl {{ width:100%; border-collapse:collapse; font-size:.80rem; font-family:'Yu Gothic','Meiryo','MS PGothic','Noto Sans JP',sans-serif; }}
.mp-tbl th,.mp-tbl td {{ padding:4px 8px; border:1px solid #b8c8de; white-space:nowrap; vertical-align:middle; }}
.mp-hdr  {{ background:{NAVY}; color:white; font-weight:700; text-align:center; }}
.mp-hsub {{ background:#2a4e7a; color:white; font-weight:600; text-align:center; font-size:.75rem; }}
.mp-cat  {{ background:{NAVY}; color:white; font-weight:700; text-align:center; }}
.mp-sub  {{ background:#2a5580; color:white; font-weight:600; text-align:center; }}
.mp-sub-total {{ background:#1e3f5e; color:white; font-weight:700; text-align:center; border-top:1.5px solid {GOLD}; }}
.mp-goal {{ background:#fef9ee; color:#5a3a00; font-weight:700; text-align:right; border-left:2px solid {GOLD}; border-right:2px solid {GOLD}; }}
.mp-ltan {{ background:#dce8f8; color:{NAVY}; font-weight:700; text-align:center; font-size:.74rem; }}
.mp-lcum {{ background:#eef2f8; color:#445; font-weight:500; text-align:center; font-size:.74rem; }}
.mp-0mo  {{ background:#f0f0f0; color:#555; text-align:right; font-size:.78rem; border-right:2px solid #b0b8cc; }}
.mp-tan  {{ background:white; color:#333; text-align:right; }}
.mp-cum  {{ background:#f4f7fc; color:#555; text-align:right; font-size:.78rem; }}

/* Read-only display cell (replaces disabled text_input) */
.disp-cell {{
    background: #f8f9fa;
    border: 1px solid #d0d8e8;
    border-radius: 6px;
    padding: .45rem .7rem;
    font-size: .83rem;
    color: #1A3A5C;
    font-weight: 600;
    text-align: right;
    min-height: 36px;
    line-height: 1.6;
    white-space: nowrap;
    overflow: hidden;
    box-sizing: border-box;
    display: flex;
    align-items: center;
    justify-content: flex-end;
}}
.disp-cell-total {{
    background: rgba(26,58,92,0.08);
    border: 1px solid rgba(26,58,92,0.2);
    border-radius: 6px;
    padding: .45rem .7rem;
    font-size: .83rem;
    color: #1A3A5C;
    font-weight: 700;
    text-align: right;
    min-height: 36px;
    line-height: 1.6;
    white-space: nowrap;
    overflow: hidden;
    box-sizing: border-box;
    display: flex;
    align-items: center;
    justify-content: flex-end;
}}
/* ─── 年次計画 スプレッドシート風高密度レイアウト ─── */
[data-testid="stHorizontalBlock"] {{
    gap: 0.06rem !important;
}}
[data-testid="column"] {{
    padding: 0 0.03rem !important;
    min-width: 0 !important;
}}
.np-hdr {{
    background: {NAVY};
    color: white;
    font-weight: 700;
    font-size: .78rem;
    padding: 3px 5px;
    min-height: 24px;
    display: flex;
    align-items: center;
    justify-content: center;
    border: 1px solid {NAVY};
    white-space: nowrap;
}}
.np-section {{
    background: {NAVY};
    color: white;
    font-weight: 700;
    font-size: .78rem;
    padding: 2px 5px;
    min-height: 22px;
    display: flex;
    align-items: center;
    border: 1px solid rgba(26,58,92,0.5);
}}
.np-total {{
    background: rgba(26,58,92,0.10);
    color: {NAVY};
    font-weight: 700;
    font-size: .78rem;
    padding: 2px 5px;
    min-height: 22px;
    display: flex;
    align-items: center;
    border: 1px solid rgba(26,58,92,0.3);
    border-top: 1.5px solid rgba(26,58,92,0.5);
}}
.np-sub {{
    background: #eff3f8;
    color: {NAVY};
    font-weight: 600;
    font-size: .78rem;
    padding: 2px 5px 2px 10px;
    min-height: 22px;
    display: flex;
    align-items: center;
    border: 1px solid #d0dcea;
}}
.np-item {{
    background: white;
    color: #333;
    font-size: .78rem;
    padding: 2px 5px 2px 16px;
    min-height: 22px;
    display: flex;
    align-items: center;
    border: 1px solid #e2eaf4;
}}
.np-empty {{
    background: white;
    min-height: 22px;
    border: 1px solid #e8eef6;
}}
.np-val {{
    background: #f8f9fa;
    color: {NAVY};
    font-weight: 600;
    font-size: .78rem;
    padding: 2px 5px;
    min-height: 22px;
    display: flex;
    align-items: center;
    justify-content: flex-end;
    border: 1px solid #d5e1ee;
    white-space: nowrap;
}}
.np-val-total {{
    background: rgba(26,58,92,0.07);
    color: {NAVY};
    font-weight: 700;
    font-size: .78rem;
    padding: 2px 5px;
    min-height: 22px;
    display: flex;
    align-items: center;
    justify-content: flex-end;
    border: 1px solid rgba(26,58,92,0.3);
    border-top: 1.5px solid rgba(26,58,92,0.5);
    white-space: nowrap;
}}
.np-title {{
    font-size: .88rem;
    font-weight: 700;
    color: {NAVY};
    margin: 0 0 0.1rem 0;
    padding: 0;
}}
/* テキスト入力をスプレッドシートセル風に（ラベル・補足テキスト行を完全に非表示） */
div[data-testid="stTextInput"] {{
    margin: 0 !important;
    padding: 0 !important;
    overflow: hidden !important;
    max-height: 28px !important;
}}
div[data-testid="stTextInput"] > label {{
    display: none !important;
    height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
}}
div[data-testid="stTextInput"] > div {{
    margin: 0 !important;
    padding: 0 !important;
    overflow: hidden !important;
}}
div[data-testid="stTextInput"] > div > div {{
    margin: 0 !important;
    padding: 0 !important;
}}
div[data-testid="stTextInput"] input {{
    border-radius: 0 !important;
    padding: 2px 5px !important;
    min-height: 22px !important;
    height: 22px !important;
    font-size: .78rem !important;
    box-sizing: border-box !important;
    margin: 0 !important;
}}
</style>
""", unsafe_allow_html=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 年次計画 - 貸借対照表（デフォルト仕様）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# E列=5(0年目/実績), F列=6(1年目)～J列=10(5年目)
BS_YEAR_COLS = [
    (5,  '0年目（実績）'),
    (6,  '1年目'),
    (7,  '2年目'),
    (8,  '3年目'),
    (9,  '4年目'),
    (10, '5年目'),
]

_BS_SKIP = {'貸借対照表', '利益計画', '商品別販売計画', '0年目', '１年目', '２年目', '３年目', '４年目', '５年目',
            '実績値', '計画値', '見込値'}


@st.cache_data(ttl=60)
def _detect_nenji_boundaries(_v: int = 0) -> tuple:
    """年次計画シートのBS・PL区切り行をスキャンで動的に検出する。
    B列が非空 かつ E列以降に年度ラベルを持つ行をセクション区切りとみなす。
    （B列の条件を加えることで、BS内部の小見出し行による誤検知を防ぐ）
    Returns: (bs_row, pl_row, pl_end_row)
      BSスキャン: range(bs_row, pl_row)
      PLスキャン: range(pl_row, pl_end_row)
    """
    ws = gsheets.GSheetWS('年次計画', data_only=True)
    _yr_set = {v for v in _BS_SKIP if v != '貸借対照表'}

    sep: list[int] = []
    max_col = ws.max_column
    for r in range(1, min(ws.max_row + 1, 300)):
        b_v = ws.cell(r, 2).value
        if not b_v or not str(b_v).strip():
            continue  # B列が空ならセクション区切りではない
        for col in range(5, max_col + 1):
            v = ws.cell(r, col).value
            if v is not None and str(v).strip() in _yr_set:
                sep.append(r)
                break
    ws.close()

    sep = sorted(set(sep))
    if len(sep) >= 3:
        return sep[0], sep[1], sep[2]
    if len(sep) == 2:
        return sep[0], sep[1], sep[1] + 60
    return 2, 31, 67


@st.cache_data(ttl=60)
def _detect_year_cols(_v: int = 0) -> list:
    """年次計画シートの年度列を動的に検出する。
    セクションヘッダー行のE列以降にある全ての非空セルを年度列として返す。
    これにより K列など追加列も自動的に含まれる。
    Returns: [(col_index, label_str), ...]
    """
    ws = gsheets.GSheetWS('年次計画', data_only=True)
    _yr_set = {v for v in _BS_SKIP if v != '貸借対照表'}
    max_col = ws.max_column

    header_row = None
    for r in range(1, min(ws.max_row + 1, 300)):
        b_v = ws.cell(r, 2).value
        if not b_v or not str(b_v).strip():
            continue
        for col in range(5, max_col + 1):
            v = ws.cell(r, col).value
            if v is not None and str(v).strip() in _yr_set:
                header_row = r
                break
        if header_row:
            break

    if header_row is None:
        ws.close()
        return list(BS_YEAR_COLS)

    year_cols: list[tuple[int, str]] = []
    for col in range(5, max_col + 1):
        v = ws.cell(header_row, col).value
        if v is not None and str(v).strip():
            year_cols.append((col, str(v).strip()))

    ws.close()
    return year_cols if year_cols else list(BS_YEAR_COLS)


# 年次計画シートの初期BS構造: (C列ラベル, D列ラベル)
_BS_INIT_ITEMS = [
    ('流動資産合計',       None),
    (None,                '現金及び預金'),
    (None,                '受取手形・売掛金'),
    (None,                '棚卸資産'),
    (None,                'その他流動資産'),
    ('固定資産合計',       None),
    ('　有形固定資産',     None),
    ('　無形固定資産',     None),
    ('　投資その他の資産', None),
    ('資産合計',          None),
    ('流動負債合計',       None),
    (None,                '買掛金'),
    (None,                '短期借入金'),
    (None,                'その他流動負債'),
    ('固定負債合計',       None),
    (None,                '長期借入金'),
    (None,                'その他固定負債'),
    ('負債合計',          None),
    ('純資産合計',         None),
    (None,                '資本金'),
    (None,                '利益剰余金'),
    (None,                'その他純資産'),
    ('負債純資産合計',     None),
]


def init_bs_sheet() -> None:
    pass  # Google Sheetsのシートは事前設定済み


def _load_bs_interactive():
    """年次計画シートのBS部分を読み込む。行・列ともスプレッドシートから動的に検出する。"""
    _nv = st.session_state.get('_nenji_ver', 0)
    _bs_row, _pl_row, _ = _detect_nenji_boundaries(_nv)
    _year_cols = _detect_year_cols(_nv)
    ws_v = gsheets.GSheetWS('年次計画', data_only=True)
    ws_f = gsheets.GSheetWS('年次計画', data_only=False)

    rows = []
    for r in range(_bs_row, _pl_row):
        b_val = ws_v.cell(r, 2).value
        c_val = ws_v.cell(r, 3).value
        d_val = ws_v.cell(r, 4).value

        b_str = str(b_val).strip() if b_val is not None else ''
        c_str = str(c_val).strip() if c_val is not None else ''
        d_str = str(d_val).strip() if d_val is not None else ''

        # 全列が空ならスキップ
        if not b_str and not c_str and not d_str:
            # 年度列にも値がなければ本当の空行
            if not any(ws_v.cell(r, col).value is not None for col, _ in _year_cols):
                continue

        if b_str in _BS_SKIP or c_str in _BS_SKIP or d_str in _BS_SKIP:
            continue

        if b_str and not c_str and not d_str:
            label, rtype = b_str, 'section'
        elif c_str and not d_str:
            label = c_str
            rtype = 'sub' if str(c_val or '').startswith('　') else 'total'
        elif d_str:
            label, rtype = d_str, 'item'
        elif b_str:
            label, rtype = b_str, 'section'
        elif c_str:
            label = c_str
            rtype = 'sub' if str(c_val or '').startswith('　') else 'total'
        else:
            continue  # B/C/D全て空かつ年度列にもデータなし → スキップ

        year_vals = {}
        for col, yr in _year_cols:
            cf = ws_f.cell(r, col)
            cv = ws_v.cell(r, col)
            is_fm = isinstance(cf.value, str) and cf.value.startswith('=')
            year_vals[yr] = {
                'is_formula': is_fm,
                'value':      cv.value,
                'formula':    cf.value if is_fm else None,
                'row_idx':    r,
                'col_idx':    col,
            }

        rows.append({'label': label, 'type': rtype, 'row_idx': r, 'years': year_vals})

    ws_v.close()
    ws_f.close()
    return rows


@st.cache_data(ttl=60)
def load_bs(_v: int = 0):
    return _load_bs_interactive()


def write_input_to_excel_bs(row_idx: int, col_idx: int, value: float) -> None:
    gsheets.write_cell_async('年次計画', row_idx, col_idx, value)


def _save_to_excel_bs(row_idx: int, col_idx: int, key: str) -> None:
    """年次計画タブ用 on_change コールバック"""
    try:
        raw = str(st.session_state.get(key) or '0').replace(',', '')
        val = float(raw) if raw else 0.0
        st.session_state[key] = f'{val:,.0f}'
        _cache_set('年次計画', row_idx, col_idx, val)
        write_input_to_excel_bs(row_idx, col_idx, val)
        _recalc_nenji_local()
        load_bs.clear()
        _detect_nenji_boundaries.clear()
        _detect_year_cols.clear()
        load_pl.clear()
        load_sales.clear()
    except Exception:
        pass


def calc_from_state_bs(rows: list) -> dict:
    """Google Sheetsが計算済みの数式セル値を返す（キーは row_idx で一意）"""
    result_map: dict[tuple, float | None] = {}
    for row in rows:
        ridx = row['row_idx']
        for yr, info in row['years'].items():
            if info['is_formula']:
                result_map[(ridx, yr)] = info['value']
    return result_map


def _he(text: str) -> str:
    """非ASCII文字をHTML数値文字参照に変換し、文字化けを防ぐ"""
    return ''.join(f'&#{ord(c)};' if ord(c) > 127 else c for c in text)


def _safe_num(v, fmt: str = ',.0f') -> str:
    """Google Sheetsの値を安全に数値フォーマットして返す。変換不可なら '0'。"""
    if v is None:
        return '0'
    try:
        return f'{float(str(v).replace(",", "")):>{fmt}}'
    except (TypeError, ValueError):
        return '0'


def render_bs_interactive(rows: list, calc_results: dict) -> None:
    """貸借対照表をスプレッドシート風高密度デザインで描画"""
    if not rows:
        st.info('データがありません。')
        return

    # 実際に読み込まれた年度列からラベルを取得（動的）
    yr_labels = list(rows[0]['years'].keys()) if rows else [yr for _, yr in BS_YEAR_COLS]
    COL_W = [0.8, 1.0, 1.2] + [1.0] * len(yr_labels)

    hdr = st.columns(COL_W, gap="small")
    for i in range(3):
        hdr[i].markdown('<div class="np-hdr">&nbsp;</div>', unsafe_allow_html=True)
    for ci, yr in enumerate(yr_labels):
        hdr[ci + 3].markdown(f'<div class="np-hdr">{_he(yr)}</div>', unsafe_allow_html=True)

    for row in rows:
        label = row['label']
        rtype = row['type']
        rc = st.columns(COL_W, gap="small")
        lh = _he(label)
        is_total = rtype in ('total', 'section')
        if rtype == 'section':
            rc[0].markdown(f'<div class="np-section">{lh}</div>', unsafe_allow_html=True)
            rc[1].markdown('<div class="np-section">&nbsp;</div>', unsafe_allow_html=True)
            rc[2].markdown('<div class="np-section">&nbsp;</div>', unsafe_allow_html=True)
        elif rtype == 'total':
            rc[0].markdown('<div class="np-empty"></div>', unsafe_allow_html=True)
            rc[1].markdown(f'<div class="np-total">{lh}</div>', unsafe_allow_html=True)
            rc[2].markdown('<div class="np-total">&nbsp;</div>', unsafe_allow_html=True)
        elif rtype == 'sub':
            rc[0].markdown('<div class="np-empty"></div>', unsafe_allow_html=True)
            rc[1].markdown(f'<div class="np-sub">{lh}</div>', unsafe_allow_html=True)
            rc[2].markdown('<div class="np-sub">&nbsp;</div>', unsafe_allow_html=True)
        else:
            rc[0].markdown('<div class="np-empty"></div>', unsafe_allow_html=True)
            rc[1].markdown('<div class="np-empty"></div>', unsafe_allow_html=True)
            rc[2].markdown(f'<div class="np-item">{lh}</div>', unsafe_allow_html=True)

        val_css = 'np-val-total' if is_total else 'np-val'
        row_idx = row['row_idx']
        for ci, yr in enumerate(yr_labels):
            info = row['years'].get(yr, {})
            if info.get('is_formula'):
                val = calc_results.get((row_idx, yr))
                disp = _safe_num(val)
                rc[ci + 3].markdown(f'<div class="{val_css}">{disp}</div>', unsafe_allow_html=True)
            else:
                inp_key = f'bs_inp_{row_idx}_{yr}'
                rc[ci + 3].text_input(
                    '', key=inp_key,
                    label_visibility='collapsed',
                    on_change=_save_to_excel_bs,
                    args=(info.get('row_idx'), info.get('col_idx'), inp_key),
                )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 年次計画 利益計画（損益計算書）関数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _load_pl_interactive():
    """年次計画シートのPL部分を読み込む。行・列ともスプレッドシートから動的に検出する。"""
    _nv = st.session_state.get('_nenji_ver', 0)
    _, _pl_row, _pl_end = _detect_nenji_boundaries(_nv)
    _year_cols = _detect_year_cols(_nv)
    ws_v = gsheets.GSheetWS('年次計画', data_only=True)
    ws_f = gsheets.GSheetWS('年次計画', data_only=False)

    rows = []
    for r in range(_pl_row + 1, _pl_end):  # +1 でPLヘッダー行（「利益計画」等）をスキップ
        b_val = ws_v.cell(r, 2).value
        c_val = ws_v.cell(r, 3).value
        d_val = ws_v.cell(r, 4).value

        b_str = str(b_val).strip() if b_val is not None else ''
        c_str = str(c_val).strip() if c_val is not None else ''
        d_str = str(d_val).strip() if d_val is not None else ''

        if not b_str and not c_str and not d_str:
            if not any(ws_v.cell(r, col).value is not None for col, _ in _year_cols):
                continue

        if b_str in _BS_SKIP or c_str in _BS_SKIP or d_str in _BS_SKIP:
            continue

        if b_str and not c_str and not d_str:
            label, rtype = b_str, 'section'
        elif c_str and not d_str:
            label = c_str
            rtype = 'sub' if str(c_val or '').startswith('　') else 'total'
        elif d_str:
            label, rtype = d_str, 'item'
        elif b_str:
            label, rtype = b_str, 'section'
        elif c_str:
            label = c_str
            rtype = 'sub' if str(c_val or '').startswith('　') else 'total'
        else:
            continue

        year_vals = {}
        for col, yr in _year_cols:
            cf = ws_f.cell(r, col)
            cv = ws_v.cell(r, col)
            is_fm = isinstance(cf.value, str) and cf.value.startswith('=')
            year_vals[yr] = {
                'is_formula': is_fm,
                'value':      cv.value,
                'formula':    cf.value if is_fm else None,
                'row_idx':    r,
                'col_idx':    col,
            }

        rows.append({'label': label, 'type': rtype, 'row_idx': r, 'years': year_vals})

    ws_v.close()
    ws_f.close()
    return rows


@st.cache_data(ttl=60)
def load_pl(_v: int = 0):
    return _load_pl_interactive()


def write_input_to_excel_pl(row_idx: int, col_idx: int, value: float) -> None:
    gsheets.write_cell_async('年次計画', row_idx, col_idx, value)


def _save_to_excel_pl(row_idx: int, col_idx: int, key: str) -> None:
    """利益計画タブ用 on_change コールバック"""
    try:
        raw = str(st.session_state.get(key) or '0').replace(',', '')
        val = float(raw) if raw else 0.0
        st.session_state[key] = f'{val:,.0f}'
        _cache_set('年次計画', row_idx, col_idx, val)
        write_input_to_excel_pl(row_idx, col_idx, val)
        _recalc_nenji_local()
        load_bs.clear()
        _detect_nenji_boundaries.clear()
        _detect_year_cols.clear()
        load_pl.clear()
        load_sales.clear()
    except Exception:
        pass


def calc_from_state_pl(rows: list) -> dict:
    """Google Sheetsが計算済みの数式セル値を返す（キーは row_idx で一意）"""
    result_map: dict[tuple, float | None] = {}
    for row in rows:
        ridx = row['row_idx']
        for yr, info in row['years'].items():
            if info['is_formula']:
                result_map[(ridx, yr)] = info['value']
    return result_map


def render_pl_interactive(rows: list, calc_results: dict) -> None:
    """利益計画をスプレッドシート風高密度デザインで描画"""
    if not rows:
        st.info('データがありません。')
        return

    yr_labels = list(rows[0]['years'].keys()) if rows else [yr for _, yr in BS_YEAR_COLS]
    COL_W = [0.8, 1.0, 1.2] + [1.0] * len(yr_labels)

    hdr = st.columns(COL_W, gap="small")
    for i in range(3):
        hdr[i].markdown('<div class="np-hdr">&nbsp;</div>', unsafe_allow_html=True)
    for ci, yr in enumerate(yr_labels):
        hdr[ci + 3].markdown(f'<div class="np-hdr">{_he(yr)}</div>', unsafe_allow_html=True)

    for row in rows:
        label = row['label']
        rtype = row['type']
        rc = st.columns(COL_W, gap="small")
        lh = _he(label)
        is_total = rtype in ('total', 'section')
        if rtype == 'section':
            rc[0].markdown(f'<div class="np-section">{lh}</div>', unsafe_allow_html=True)
            rc[1].markdown('<div class="np-section">&nbsp;</div>', unsafe_allow_html=True)
            rc[2].markdown('<div class="np-section">&nbsp;</div>', unsafe_allow_html=True)
        elif rtype == 'total':
            rc[0].markdown('<div class="np-empty"></div>', unsafe_allow_html=True)
            rc[1].markdown(f'<div class="np-total">{lh}</div>', unsafe_allow_html=True)
            rc[2].markdown('<div class="np-total">&nbsp;</div>', unsafe_allow_html=True)
        elif rtype == 'sub':
            rc[0].markdown('<div class="np-empty"></div>', unsafe_allow_html=True)
            rc[1].markdown(f'<div class="np-sub">{lh}</div>', unsafe_allow_html=True)
            rc[2].markdown('<div class="np-sub">&nbsp;</div>', unsafe_allow_html=True)
        else:
            rc[0].markdown('<div class="np-empty"></div>', unsafe_allow_html=True)
            rc[1].markdown('<div class="np-empty"></div>', unsafe_allow_html=True)
            rc[2].markdown(f'<div class="np-item">{lh}</div>', unsafe_allow_html=True)

        val_css = 'np-val-total' if is_total else 'np-val'
        row_idx = row['row_idx']
        for ci, yr in enumerate(yr_labels):
            info = row['years'].get(yr, {})
            if info.get('is_formula'):
                val = calc_results.get((row_idx, yr))
                disp = _safe_num(val)
                rc[ci + 3].markdown(f'<div class="{val_css}">{disp}</div>', unsafe_allow_html=True)
            else:
                inp_key = f'pl_inp_{row_idx}_{yr}'
                rc[ci + 3].text_input(
                    '', key=inp_key,
                    label_visibility='collapsed',
                    on_change=_save_to_excel_pl,
                    args=(info.get('row_idx'), info.get('col_idx'), inp_key),
                )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 年次計画 商品別販売計画
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _load_sales_interactive():
    """商品別販売計画を動的境界・動的年度列で読み込む。"""
    _nv = st.session_state.get('_nenji_ver', 0)
    _, _, _sales_hdr_row = _detect_nenji_boundaries(_nv)
    _year_cols = _detect_year_cols(_nv)
    ws_v = gsheets.GSheetWS('年次計画', data_only=True)
    ws_f = gsheets.GSheetWS('年次計画', data_only=False)
    rows = []
    first_group = True
    # _sales_hdr_row はセクションヘッダー行（「商品別販売計画」等）→ +1 でスキップ
    scan_start = _sales_hdr_row + 1
    scan_end   = ws_v.max_row + 1

    for r in range(scan_start, scan_end):
        b_val = ws_v.cell(r, 2).value
        c_val = ws_v.cell(r, 3).value
        d_val = ws_v.cell(r, 4).value
        b_str = str(b_val).strip() if b_val is not None else ''
        c_str = str(c_val).strip() if c_val is not None else ''
        d_str = str(d_val).strip() if d_val is not None else ''
        if not b_str and not c_str and not d_str:
            continue
        if b_str in _BS_SKIP or c_str in _BS_SKIP or d_str in _BS_SKIP:
            continue

        def _year_vals(row_r, _yc=_year_cols):
            yv = {}
            for col, yr in _yc:
                cf = ws_f.cell(row_r, col)
                cv = ws_v.cell(row_r, col)
                is_fm = isinstance(cf.value, str) and cf.value.startswith('=')
                yv[yr] = {
                    'is_formula': is_fm,
                    'value':      cv.value,
                    'formula':    cf.value if is_fm else None,
                    'row_idx':    row_r,
                    'col_idx':    col,
                }
            return yv

        if b_str:
            rows.append({'label': b_str, 'type': 'section', 'row_idx': r,
                         'years': {}, 'group_break': not first_group})
            first_group = False
            if d_str:
                rows.append({'label': d_str, 'type': 'item', 'row_idx': r,
                             'years': _year_vals(r), 'group_break': False})
        elif c_str:
            rows.append({'label': c_str, 'type': 'total', 'row_idx': r,
                         'years': _year_vals(r), 'group_break': False})
        elif d_str:
            rows.append({'label': d_str, 'type': 'item', 'row_idx': r,
                         'years': _year_vals(r), 'group_break': False})
    ws_v.close()
    ws_f.close()
    return rows


@st.cache_data(ttl=60)
def load_sales(_v: int = 0):
    return _load_sales_interactive()


def write_input_to_excel_sales(row_idx: int, col_idx: int, value: float) -> None:
    gsheets.write_cell_async('年次計画', row_idx, col_idx, value)


def _save_to_excel_sales(row_idx: int, col_idx: int, key: str) -> None:
    try:
        raw = str(st.session_state.get(key) or '0').replace(',', '')
        val = float(raw) if raw else 0.0
        st.session_state[key] = f'{val:,.0f}'
        _cache_set('年次計画', row_idx, col_idx, val)
        write_input_to_excel_sales(row_idx, col_idx, val)
        _recalc_nenji_local()
        load_bs.clear()
        _detect_nenji_boundaries.clear()
        _detect_year_cols.clear()
        load_pl.clear()
        load_sales.clear()
    except Exception:
        pass


def calc_from_state_sales(rows: list) -> dict:
    """Google Sheetsが計算済みの数式セル値を返す"""
    result_map: dict[tuple, float | None] = {}
    for row in rows:
        for yr, info in row['years'].items():
            if info['is_formula']:
                result_map[(info['row_idx'], yr)] = info['value']
    return result_map


def render_sales_interactive(rows: list, calc_results: dict) -> None:
    if not rows:
        st.info('データがありません。')
        return

    yr_labels = [yr for _, yr in BS_YEAR_COLS]
    COL_W = [0.8, 1.0, 1.2] + [1.0] * len(yr_labels)

    hdr = st.columns(COL_W)
    for i in range(3):
        hdr[i].markdown('<div class="yp-hdr">&nbsp;</div>', unsafe_allow_html=True)
    for ci, yr in enumerate(yr_labels):
        hdr[ci + 3].markdown(
            f'<div class="yp-hdr-yr">{_he(yr)}</div>',
            unsafe_allow_html=True)

    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)

    for row in rows:
        label = row['label']
        rtype = row['type']
        lh    = _he(label)

        if rtype == 'section':
            if row['group_break']:
                st.markdown('<hr class="yp-sep">', unsafe_allow_html=True)
            st.markdown(f'<div class="yp-group">{lh}</div>', unsafe_allow_html=True)
            continue

        rc = st.columns(COL_W)

        if rtype == 'total':
            rc[0].markdown('<div class="yp-empty"></div>', unsafe_allow_html=True)
            rc[1].markdown(f'<div class="yp-total">{lh}</div>', unsafe_allow_html=True)
            rc[2].markdown('<div class="yp-total">&nbsp;</div>', unsafe_allow_html=True)
        else:
            rc[0].markdown('<div class="yp-empty"></div>', unsafe_allow_html=True)
            rc[1].markdown('<div class="yp-empty"></div>', unsafe_allow_html=True)
            rc[2].markdown(f'<div class="yp-item">{lh}</div>', unsafe_allow_html=True)

        row_idx = row['row_idx']
        for ci, yr in enumerate(yr_labels):
            info = row['years'].get(yr, {})
            if info.get('is_formula'):
                val  = calc_results.get((row_idx, yr))
                try:
                    disp = _safe_num(val, ',.2f')
                except (TypeError, ValueError):
                    disp = '0'
                rc[ci + 3].markdown(f'<div class="disp-cell">{disp}</div>', unsafe_allow_html=True)
            else:
                inp_key = f'sales_inp_{row_idx}_{yr}'
                rc[ci + 3].text_input(
                    '', key=inp_key,
                    label_visibility='collapsed',
                    on_change=_save_to_excel_sales,
                    args=(info.get('row_idx'), info.get('col_idx'), inp_key),
                )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 月次計画 - データ読込・描画
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_MO_INPUT_ROWS = {14, 16, 18, 20, 22, 29, 38, 44, 46, 48}
_MO_DATA_COLS  = list(range(8, 20))   # H=8..S=19 (12か月)

_CF_INPUT_ROWS = {60, 61, 66, 68, 69, 71, 72, 75, 76, 78, 79, 80, 83, 84, 85, 86, 88, 89}

_SP_INPUT_ROWS = {103, 105, 113, 115, 117, 125, 127, 129, 137}

_MO_ITEMS = [
    # (cat, sub, tan_row, cum_row, goal_row, fmt, tan_is_input)
    (None,        '売上高',           6,  7,  6, 'num', False),
    (None,        '変動費',           8,  9,  8, 'num', False),
    (None,        '粗利益',          10, 11, 10, 'num', False),
    (None,        '粗利益率',        12, 13, 12, 'pct', False),
    ('固定費',    '給与・福利費',    14, 15, 14, 'num', True),
    ('固定費',    '賞与',            16, 17, 16, 'num', True),
    ('固定費',    '販促宣伝費',      18, 19, 18, 'num', True),
    ('固定費',    '経費',            20, 21, 20, 'num', True),
    ('固定費',    '減価償却費',      22, 23, 22, 'num', True),
    ('固定費',    '合計',            24, 25, 24, 'num', False),
    (None,        '経常利益',        26, 27, 26, 'num', False),
    (None,        '損益分岐点',      None, 28, 28, 'num', False),
    (None,        '正社員換算数',    29, None, 29, 'num', True),
    ('1人当たり', '売上高',          30, 31, 30, 'num', False),
    ('1人当たり', '粗利益',          32, 33, 32, 'num', False),
    ('1人当たり', '経常利益',        34, 35, 34, 'num', False),
    (None,        '労働分配率',      36, 37, 36, 'pct', False),
    (None,        '総稼働時間',      38, 39, 38, 'num', True),
    (None,        '時間当たり粗利額', 40, 41, 40, 'num', False),
    ('変動費',    '商品仕入',        42, 43, 42, 'num', False),
    ('変動費',    '原材料仕入',      44, 45, 44, 'num', True),
    ('変動費',    '外注費',          46, 47, 46, 'num', True),
    ('変動費',    '他',              48, 49, 48, 'num', True),
    ('変動費',    '在庫増減',        50, 51, 50, 'num', False),
    ('変動費',    '合計',            52, 53, 52, 'num', False),
]

_MO_MONTHS = ['０か月目', '４月', '５月', '６月', '７月', '８月', '９月',
               '１０月', '１１月', '１２月', '１月', '２月', '３月']
_MO_COL_W  = [0.9, 0.9, 0.7, 0.5] + [0.68] * 13


def _fv_mo(v, fmt='num'):
    if v is None:
        return ''
    s = str(v)
    if s.startswith('#'):
        return ''
    try:
        f = float(s)
        if fmt == 'pct':
            return f'{f * 100:.1f}%' if abs(f) <= 2.0 else f'{f:.1f}%'
        return f'{f:,.0f}'
    except (TypeError, ValueError):
        return s


@st.cache_data(ttl=15)
def load_monthly_full():
    """月次計画シートの値を読み込む（Google Sheetsが数式を評価済み）"""
    ws_v = gsheets.GSheetWS('月次計画', data_only=True)

    raw = {}
    for r in range(4, 54):
        raw[r] = {}
        for c in range(2, 20):
            raw[r][c] = ws_v.cell(r, c).value
    for r in range(54, 166):
        raw[r] = {}
        for c in range(7, 20):
            raw[r][c] = ws_v.cell(r, c).value

    for r in [103, 115, 127, 139]:
        raw[r][2] = ws_v.cell(r, 2).value
    for r in range(103, 151):
        raw[r][5] = ws_v.cell(r, 5).value

    ws_v.close()
    return raw, {}


def _save_to_excel_monthly(row_idx: int, col_idx: int, key: str) -> None:
    """月次計画タブ用 on_change コールバック"""
    try:
        raw_val = str(st.session_state.get(key) or '0').replace(',', '')
        val = float(raw_val) if raw_val else 0.0
        st.session_state[key] = f'{val:,.0f}'
        _cache_set('月次計画', row_idx, col_idx, val)
        gsheets.write_cell_async('月次計画', row_idx, col_idx, val)
        _recalc_monthly_local()
    except Exception:
        pass


def calc_monthly_from_state(raw: dict, formulas: dict) -> dict:
    """Google Sheetsが計算済みの値をそのまま返す"""
    res: dict[tuple, float | None] = {}
    for r in range(4, 54):
        for c in range(7, 20):
            res[(r, c)] = raw.get(r, {}).get(c)
    for r in range(56, 93):
        for c in range(7, 20):
            res[(r, c)] = raw.get(r, {}).get(c)
    for r in range(103, 151):
        for c in range(7, 20):
            res[(r, c)] = raw.get(r, {}).get(c)
        res[(r, 5)] = raw.get(r, {}).get(5)
    return res


def render_monthly_interactive(raw: dict, calc_res: dict) -> None:
    """月次計画を年次計画と同じ st.columns 機構でインタラクティブ描画"""
    hdr = st.columns(_MO_COL_W)
    for lbl, i in [('大分類', 0), ('項目', 1), ('目標', 2), ('', 3)]:
        hdr[i].markdown(f'<div class="yp-hdr">{_he(lbl)}</div>', unsafe_allow_html=True)
    for i, m in enumerate(_MO_MONTHS):
        hdr[4 + i].markdown(f'<div class="yp-hdr-yr">{_he(m)}</div>', unsafe_allow_html=True)

    _MO_DIVIDER_BEFORE = {28, 29, 30, 38, 42}

    _sentinel = object()
    prev_cat: object = _sentinel

    for (cat, sub, tan_r, cum_r, goal_r, fmt, tan_is_input) in _MO_ITEMS:
        if goal_r in _MO_DIVIDER_BEFORE:
            st.markdown('<hr style="border:none;border-top:1.5px solid #b8c8de;margin:2px 0;">', unsafe_allow_html=True)
        show_cat = cat is not None and cat != prev_cat
        if cat is not None:
            prev_cat = cat

        goal_v = _fv_mo(raw.get(goal_r, {}).get(4), fmt)

        if tan_r is not None:
            rc = st.columns(_MO_COL_W)
            if show_cat:
                rc[0].markdown(f'<div class="yp-section">{_he(cat)}</div>', unsafe_allow_html=True)
            else:
                rc[0].markdown('<div class="yp-empty"></div>', unsafe_allow_html=True)
            rc[1].markdown(f'<div class="yp-item">{_he(sub)}</div>', unsafe_allow_html=True)
            rc[2].markdown(f'<div class="mp-goal">{goal_v or "&nbsp;"}</div>', unsafe_allow_html=True)
            rc[3].markdown(f'<div class="mp-ltan">{_he("単月")}</div>', unsafe_allow_html=True)
            g0 = _fv_mo(calc_res.get((tan_r, 7)), fmt)
            rc[4].markdown(f'<div class="disp-cell">{g0}</div>', unsafe_allow_html=True)
            for ci, c in enumerate(_MO_DATA_COLS):
                if tan_is_input:
                    inp_key = f'mo_inp_{tan_r}_{c}'
                    rc[5 + ci].text_input(
                        '', key=inp_key, label_visibility='collapsed',
                        on_change=_save_to_excel_monthly,
                        args=(tan_r, c, inp_key),
                    )
                else:
                    v = _fv_mo(calc_res.get((tan_r, c)), fmt)
                    rc[5 + ci].markdown(f'<div class="disp-cell">{v}</div>', unsafe_allow_html=True)

        if cum_r is not None:
            rc2 = st.columns(_MO_COL_W)
            if tan_r is None:
                rc2[0].markdown('<div class="yp-empty"></div>', unsafe_allow_html=True)
                rc2[1].markdown(f'<div class="yp-item">{_he(sub)}</div>', unsafe_allow_html=True)
                g2v = _fv_mo(raw.get(cum_r, {}).get(4), fmt)
                rc2[2].markdown(f'<div class="mp-goal">{g2v or "&nbsp;"}</div>', unsafe_allow_html=True)
            else:
                rc2[0].markdown('<div class="yp-empty"></div>', unsafe_allow_html=True)
                rc2[1].markdown('<div class="yp-empty"></div>', unsafe_allow_html=True)
                rc2[2].markdown('<div class="yp-empty"></div>', unsafe_allow_html=True)
            rc2[3].markdown(f'<div class="mp-lcum">{_he("累計")}</div>', unsafe_allow_html=True)
            g1 = _fv_mo(calc_res.get((cum_r, 7)), fmt)
            rc2[4].markdown(f'<div class="disp-cell">{g1}</div>', unsafe_allow_html=True)
            for ci, c in enumerate(_MO_DATA_COLS):
                v2 = _fv_mo(calc_res.get((cum_r, c)), fmt)
                rc2[5 + ci].markdown(f'<div class="disp-cell">{v2}</div>', unsafe_allow_html=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Google Sheets 操作関数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def init_excel() -> None:
    pass  # Google Sheetsは事前設定済み


@st.cache_data(ttl=30)
def read_cell_map(_version: int = 0) -> tuple:
    ws_f = gsheets.GSheetWS('ロジック', data_only=False)
    ws_v = gsheets.GSheetWS('ロジック', data_only=True)

    years = {}
    for col in range(2, ws_f.max_column + 1):
        v = ws_f.cell(1, col).value
        if v is not None:
            years[col] = str(v)

    items = {}
    for row in range(2, ws_f.max_row + 1):
        v = ws_f.cell(row, 1).value
        if v is not None:
            items[row] = str(v)

    cell_map = {}
    for row, item in items.items():
        for col, year in years.items():
            cf = ws_f.cell(row, col)
            cv = ws_v.cell(row, col)
            is_formula = isinstance(cf.value, str) and cf.value.startswith("=")
            cell_map[(item, year)] = {
                "is_formula": is_formula,
                "value": cv.value,
                "formula": cf.value if is_formula else None,
            }

    ws_f.close()
    ws_v.close()
    return years, items, cell_map


def write_input_to_excel(item: str, year: str, value: float) -> bool:
    """社長入力値を該当セルへ転記（数値のみ。数式セルは上書きしない）"""
    ws = gsheets.GSheetWS('ロジック', data_only=False)
    tgt_col = tgt_row = None
    for col in range(2, ws.max_column + 1):
        if str(ws.cell(1, col).value) == year:
            tgt_col = col
            break
    for row in range(2, ws.max_row + 1):
        if str(ws.cell(row, 1).value) == item:
            tgt_row = row
            break
    if tgt_col and tgt_row:
        existing = ws.cell(tgt_row, tgt_col).value
        if not (isinstance(existing, str) and existing.startswith("=")):
            gsheets.write_cell('ロジック', tgt_row, tgt_col, value)
            return True
    return False


def try_xlwings_calc() -> bool:
    return False  # Google Sheets側で自動計算済み


@st.cache_data(ttl=30)
def get_formula_df(_version: int = 0) -> tuple:
    """管理者用: 数式文字列込みのDataFrameと列ヘッダーを返す"""
    ws = gsheets.GSheetWS('ロジック', data_only=False)
    headers = ["項目"]
    year_cols: dict[int, str] = {}
    for col in range(2, ws.max_column + 1):
        v = ws.cell(1, col).value
        if v is not None:
            headers.append(str(v))
            year_cols[col] = str(v)
    rows = []
    for row in range(2, ws.max_row + 1):
        item = ws.cell(row, 1).value
        if item is None:
            continue
        rd = {"項目": str(item)}
        for col, yr in year_cols.items():
            cell = ws.cell(row, col)
            rd[yr] = str(cell.value) if cell.value is not None else ""
        rows.append(rd)
    ws.close()
    df = pd.DataFrame(rows, columns=headers) if rows else pd.DataFrame(columns=headers)
    return headers, df


def save_admin_df(df: pd.DataFrame) -> None:
    """管理者編集済みDFをGoogle Sheetsのロジックシートへ保存。"""
    years = [c for c in df.columns if c != "項目"]
    header_row = ["項目"] + years
    data_rows = []
    for rec in df.to_dict("records"):
        row_data = [rec.get("項目", "")]
        for yr in years:
            raw = str(rec.get(yr, "") or "").strip()
            if raw.startswith("="):
                row_data.append(raw)
            else:
                try:
                    row_data.append(float(raw.replace(",", "")) if raw else 0)
                except ValueError:
                    row_data.append(raw)
        data_rows.append(row_data)

    all_data = [header_row] + data_rows
    gsheets.write_range('ロジック', 1, 1, all_data)
    get_formula_df.clear()
    read_cell_map.clear()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Python 数式評価エンジン（xlwings不要・即時計算）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _eval_formula(formula_str: str, coord_values: dict) -> float | None:
    """
    シンプルなExcel数式を Python で評価して数値を返す。
    対応: 四則演算, セル参照, SUM/AVERAGE/MIN/MAX(範囲またはカンマ区切り)
    非対応の場合は None を返す。
    """
    if not isinstance(formula_str, str) or not formula_str.startswith("="):
        return None
    expr = formula_str[1:].upper()

    def _range_vals(range_str: str) -> list[float]:
        m = re.match(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", range_str.strip())
        if not m:
            return []
        c1 = gsheets.column_index_from_string(m.group(1))
        r1, r2 = int(m.group(2)), int(m.group(4))
        c2 = gsheets.column_index_from_string(m.group(3))
        vals = []
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                k = gsheets.get_column_letter(c) + str(r)
                v = coord_values.get(k, 0)
                vals.append(float(v) if v is not None else 0.0)
        return vals

    def _parse_args(args_str: str) -> list[float]:
        result = []
        for part in args_str.split(","):
            part = part.strip()
            if ":" in part:
                result.extend(_range_vals(part))
            elif re.match(r"^[A-Z]+\d+$", part):
                v = coord_values.get(part, 0)
                result.append(float(v) if v is not None else 0.0)
            else:
                try:
                    result.append(float(part))
                except ValueError:
                    pass
        return result

    for fn, py_fn in [
        ("SUM",     lambda vals: sum(vals)),
        ("AVERAGE", lambda vals: sum(vals) / len(vals) if vals else 0.0),
        ("MIN",     lambda vals: min(vals) if vals else 0.0),
        ("MAX",     lambda vals: max(vals) if vals else 0.0),
    ]:
        expr = re.sub(
            rf"{fn}\(([^)]+)\)",
            lambda m, f=py_fn: str(f(_parse_args(m.group(1)))),
            expr,
        )

    def _ref(m: re.Match) -> str:
        v = coord_values.get(m.group(0), 0)
        return str(float(v) if v is not None else 0.0)

    expr = re.sub(r"[A-Z]+\d+", _ref, expr)

    # 四則演算のみ許可（セキュリティ上 eval は数字と演算子のみ）
    if not re.match(r"^[\d\s\+\-\*\/\(\)\.eE]+$", expr):
        return None
    try:
        return float(eval(expr))  # noqa: S307
    except Exception:
        return None


def python_eval_formulas() -> dict[tuple, float | None]:
    """Google Sheetsから計算済み値を取得して返す。"""
    _, _, cell_map = read_cell_map()
    return {k: v["value"] for k, v in cell_map.items()}


def _recalc_nenji_local() -> None:
    """年次計画の数式セルをsession_stateの値からローカル評価して即時更新する。"""
    v = st.session_state.get('_nenji_ver', 0)
    bs_rows = load_bs(v)
    pl_rows = load_pl(v)
    sales_rows = load_sales(v)

    coord: dict[str, float] = {}

    def _addr(info: dict) -> str:
        return gsheets.get_column_letter(info['col_idx']) + str(info['row_idx'])

    def _fv(s: str) -> float:
        try:
            return float(str(s).replace(',', '').replace('%', ''))
        except Exception:
            return 0.0

    # 入力セルと既存の数式セルの値をcoordマップに収集
    for row in bs_rows:
        ridx = row['row_idx']
        for yr, info in row['years'].items():
            if not info.get('col_idx'):
                continue
            key = f'bs_calc_{ridx}_{yr}' if info['is_formula'] else f'bs_inp_{ridx}_{yr}'
            coord[_addr(info)] = _fv(st.session_state.get(key, '0'))

    for row in pl_rows:
        ridx = row['row_idx']
        for yr, info in row['years'].items():
            if not info.get('col_idx'):
                continue
            key = f'pl_calc_{ridx}_{yr}' if info['is_formula'] else f'pl_inp_{ridx}_{yr}'
            coord[_addr(info)] = _fv(st.session_state.get(key, '0'))

    for row in sales_rows:
        ridx = row['row_idx']
        for yr, info in row['years'].items():
            if not info.get('col_idx'):
                continue
            key = f'sales_calc_{ridx}_{yr}' if info['is_formula'] else f'sales_inp_{ridx}_{yr}'
            coord[_addr(info)] = _fv(st.session_state.get(key, '0'))

    # 数式セルを2パスで評価（依存チェーン対応）
    for _ in range(2):
        for row in bs_rows:
            ridx = row['row_idx']
            for yr, info in row['years'].items():
                if info.get('is_formula') and info.get('formula'):
                    res = _eval_formula(info['formula'], coord)
                    if res is not None:
                        st.session_state[f'bs_calc_{ridx}_{yr}'] = f'{res:,.0f}'
                        coord[_addr(info)] = res
                        _cache_set('年次計画', info['row_idx'], info['col_idx'], res)

        for row in pl_rows:
            ridx = row['row_idx']
            for yr, info in row['years'].items():
                if info.get('is_formula') and info.get('formula'):
                    res = _eval_formula(info['formula'], coord)
                    if res is not None:
                        st.session_state[f'pl_calc_{ridx}_{yr}'] = f'{res:,.0f}'
                        coord[_addr(info)] = res
                        _cache_set('年次計画', info['row_idx'], info['col_idx'], res)

        for row in sales_rows:
            ridx = row['row_idx']
            for yr, info in row['years'].items():
                if info.get('is_formula') and info.get('formula'):
                    res = _eval_formula(info['formula'], coord)
                    if res is not None:
                        st.session_state[f'sales_calc_{ridx}_{yr}'] = f'{res:,.0f}'
                        coord[_addr(info)] = res
                        _cache_set('年次計画', info['row_idx'], info['col_idx'], res)

    load_bs.clear()
    _detect_nenji_boundaries.clear()
    load_pl.clear()
    load_sales.clear()


def _recalc_ne_local() -> None:
    """値上げ効果計算表の数式セルをローカルで即時評価する。"""
    store = _get_store()
    with store['lock']:
        f_cache = {r: dict(c) for r, c in store['data'].get('値上げ効果計算表_f', {}).items()}
        v_cache = {r: dict(c) for r, c in store['data'].get('値上げ効果計算表_v', {}).items()}

    coord: dict[str, float] = {}
    for r in range(2, 34):
        for c in range(2, 13):
            addr = gsheets.get_column_letter(c) + str(r)
            if (r, c) in _NE_INPUT_CELLS:
                raw = str(st.session_state.get(f'ne_inp_{r}_{c}', '0')).replace(',', '').replace('%', '')
                try:
                    coord[addr] = float(raw)
                except Exception:
                    coord[addr] = 0.0
            else:
                v = v_cache.get(r, {}).get(c)
                try:
                    coord[addr] = float(v) if v is not None else 0.0
                except Exception:
                    coord[addr] = 0.0

    for _ in range(2):
        for r in range(2, 34):
            for c in range(2, 13):
                if (r, c) in _NE_INPUT_CELLS:
                    continue
                formula = f_cache.get(r, {}).get(c)
                if isinstance(formula, str) and formula.startswith('='):
                    res = _eval_formula(formula, coord)
                    if res is not None:
                        addr = gsheets.get_column_letter(c) + str(r)
                        coord[addr] = res
                        _cache_set('値上げ効果計算表', r, c, res)

    load_ne_full.clear()


def _recalc_sim_local() -> None:
    """収益構造シミュレーションの数式セルをローカルで即時評価する。"""
    store = _get_store()
    with store['lock']:
        f_cache = {r: dict(c) for r, c in store['data'].get('収益構造シミュレーション _f', {}).items()}
        v_cache = {r: dict(c) for r, c in store['data'].get('収益構造シミュレーション _v', {}).items()}

    coord: dict[str, float] = {}
    for r in range(1, 52):
        for c in range(1, 25):
            addr = gsheets.get_column_letter(c) + str(r)
            if (r, c) in _SIM_ALL_INPUT_CELLS:
                raw = str(st.session_state.get(f'sim_inp_{r}_{c}', '0')).replace(',', '')
                try:
                    coord[addr] = float(raw)
                except Exception:
                    coord[addr] = 0.0
            else:
                v = v_cache.get(r, {}).get(c)
                try:
                    coord[addr] = float(v) if v is not None else 0.0
                except Exception:
                    coord[addr] = 0.0

    for _ in range(2):
        for r in range(1, 52):
            for c in range(1, 25):
                if (r, c) in _SIM_ALL_INPUT_CELLS:
                    continue
                formula = f_cache.get(r, {}).get(c)
                if isinstance(formula, str) and formula.startswith('='):
                    res = _eval_formula(formula, coord)
                    if res is not None:
                        addr = gsheets.get_column_letter(c) + str(r)
                        coord[addr] = res
                        _cache_set(_SIM_SHEET, r, c, res)

    load_sim_full.clear()


def _recalc_monthly_local() -> None:
    """月次計画の数式セルをローカルで即時評価する。"""
    store = _get_store()
    with store['lock']:
        f_cache = {r: dict(c) for r, c in store['data'].get('月次計画_f', {}).items()}
        v_cache = {r: dict(c) for r, c in store['data'].get('月次計画_v', {}).items()}

    _pct_rows = {113, 125, 137}

    coord: dict[str, float] = {}
    for r in range(4, 166):
        for c in range(2, 20):
            addr = gsheets.get_column_letter(c) + str(r)
            is_mo_inp  = r in _MO_INPUT_ROWS and c in _MO_DATA_COLS
            is_cf_inp  = r in _CF_INPUT_ROWS and c in _MO_DATA_COLS
            is_sp_inp  = r in _SP_INPUT_ROWS and c in _MO_DATA_COLS
            if is_mo_inp:
                raw = str(st.session_state.get(f'mo_inp_{r}_{c}', '0')).replace(',', '')
                try:
                    coord[addr] = float(raw)
                except Exception:
                    coord[addr] = 0.0
            elif is_cf_inp:
                raw = str(st.session_state.get(f'cf_inp_{r}_{c}', '0')).replace(',', '')
                try:
                    coord[addr] = float(raw)
                except Exception:
                    coord[addr] = 0.0
            elif is_sp_inp:
                raw = str(st.session_state.get(f'sp_inp_{r}_{c}', '0')).replace(',', '').replace('%', '')
                try:
                    fv = float(raw)
                    coord[addr] = fv / 100.0 if r in _pct_rows and fv > 1.0 else fv
                except Exception:
                    coord[addr] = 0.0
            else:
                v = v_cache.get(r, {}).get(c)
                try:
                    coord[addr] = float(v) if v is not None else 0.0
                except Exception:
                    coord[addr] = 0.0

    for _ in range(2):
        for r in range(4, 166):
            for c in range(2, 20):
                is_inp = (
                    (r in _MO_INPUT_ROWS and c in _MO_DATA_COLS) or
                    (r in _CF_INPUT_ROWS and c in _MO_DATA_COLS) or
                    (r in _SP_INPUT_ROWS and c in _MO_DATA_COLS)
                )
                if is_inp:
                    continue
                formula = f_cache.get(r, {}).get(c)
                if isinstance(formula, str) and formula.startswith('='):
                    res = _eval_formula(formula, coord)
                    if res is not None:
                        addr = gsheets.get_column_letter(c) + str(r)
                        coord[addr] = res
                        _cache_set('月次計画', r, c, res)

    load_monthly_full.clear()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ダッシュボード用関数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _save_to_excel(item: str, year: str, key: str) -> None:
    """text_input の on_change から呼ばれる。カンマ付き文字列をfloatに変換してExcel保存。"""
    try:
        raw = str(st.session_state.get(key) or "0").replace(",", "")
        val = float(raw) if raw else 0.0
        st.session_state[key] = f"{val:,.0f}"
        threading.Thread(target=write_input_to_excel, args=(item, year, val), daemon=True).start()
    except Exception:
        pass


def calc_from_state(years: dict, items: dict, cell_map: dict) -> dict:
    """Google Sheetsが計算済みの値をそのまま返す"""
    result_map: dict[tuple, float | None] = {}
    for (item, year), info in cell_map.items():
        result_map[(item, year)] = info["value"]
    return result_map


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# アプリ起動
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

tab1, tab_nenji, tab_monthly, tab_ne, tab_sim, tab2 = st.tabs(["📊　社長用ダッシュボード", "📋　年次計画", "📅　月次計画", "💹　値上げ効果計算表", "📈　収益構造シミュレーション", "⚙️　管理者用ロジック編集"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# タブ①: 社長用ダッシュボード
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@st.fragment
def _render_tab1():
    st.markdown("""
    <div class="dash-header">
        <h1>📊 経営管理ダッシュボード</h1>
        <p>数値を入力すると自動的に計算結果が反映されます。</p>
    </div>""", unsafe_allow_html=True)

    years, items, cell_map = read_cell_map()

    if not years or not items:
        st.warning("Excelに項目が定義されていません。「管理者用ロジック編集」タブでExcelを開いて設定してください。")
        st.stop()

    year_list = list(years.values())
    item_list = list(items.values())

    # 入力セルの初期値を session_state に登録（未登録のときだけ Excel 値でカンマ表記初期化）
    for _yr in year_list:
        for _it in item_list:
            _info = cell_map.get((_it, _yr), {})
            if not _info.get("is_formula"):
                _k = f"inp_{_yr}_{_it}"
                if _k not in st.session_state:
                    try:
                        st.session_state[_k] = f"{float(_info.get('value') or 0):,.0f}"
                    except (TypeError, ValueError):
                        st.session_state[_k] = "0"

    # session_state の現在値から数式を即時計算
    calc_results: dict = calc_from_state(years, items, cell_map)

    # 年度ごとにカラムを動的生成
    cols = st.columns(len(year_list), gap="large")
    for ci, year in enumerate(year_list):
        with cols[ci]:
            st.markdown(f'<div class="sec-title">&#128197; {_he(year)}</div>', unsafe_allow_html=True)
            st.markdown("")

            for item in item_list:
                info = cell_map.get((item, year), {"is_formula": False, "value": 0})

                if info["is_formula"]:
                    # 計算式セル：カンマ表記で HTML表示
                    val = calc_results.get((item, year))
                    display_str = _safe_num(val)
                    st.markdown(f'<div style="font-size:.85rem;font-weight:600;color:{NAVY};margin-bottom:.1rem;">{_he(item)}</div><div class="disp-cell">{display_str}</div>', unsafe_allow_html=True)
                else:
                    # 入力セル：カンマ表記テキスト入力
                    inp_key = f"inp_{year}_{item}"
                    st.text_input(
                        label=item,
                        key=inp_key,
                        help=f"{item}（{year}）の数値を入力してください",
                        on_change=_save_to_excel,
                        args=(item, year, inp_key),
                    )

    # ── 管理者がExcelを変更した後の手動反映ボタン ──
    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    _, bc_reload, _ = st.columns([3, 2, 3])
    with bc_reload:
        if st.button("🔄　管理者Excelの変更を反映", use_container_width=True, key="btn_reload"):
            for _yr in year_list:
                for _it in item_list:
                    st.session_state.pop(f"inp_{_yr}_{_it}", None)
            st.rerun(scope="app")


with tab1:
    _render_tab1()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# タブ②: 年次計画
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _render_nenji_tab():
    st.markdown(
        f'<div class="dash-header">'
        f'<h1>&#128203; {_he("年次計画")}</h1>'
        f'<p>{_he("数値を入力すると自動的に計算結果が反映されます。")}</p>'
        f'</div>',
        unsafe_allow_html=True,
    )

    with st.container(border=True):
        st.markdown(f'<p class="np-title">&#128194; {_he("貸借対照表")}</p>', unsafe_allow_html=True)

        _nv = st.session_state.get('_nenji_ver', 0)
        bs_rows = load_bs(_nv)

        for _row in bs_rows:
            _ridx = _row['row_idx']
            for _yr, _info in _row['years'].items():
                if not _info['is_formula']:
                    _k = f"bs_inp_{_ridx}_{_yr}"
                    if _k not in st.session_state:
                        try:
                            st.session_state[_k] = f"{float(_info.get('value') or 0):,.0f}"
                        except (TypeError, ValueError):
                            st.session_state[_k] = '0'

        calc_results_bs = calc_from_state_bs(bs_rows)
        render_bs_interactive(bs_rows, calc_results_bs)

    with st.container(border=True):
        st.markdown(f'<p class="np-title">&#128200; {_he("利益計画")}</p>', unsafe_allow_html=True)

        pl_rows = load_pl(_nv)

        for _row in pl_rows:
            _ridx = _row['row_idx']
            for _yr, _info in _row['years'].items():
                if not _info['is_formula']:
                    _k = f"pl_inp_{_ridx}_{_yr}"
                    if _k not in st.session_state:
                        try:
                            st.session_state[_k] = f"{float(_info.get('value') or 0):,.0f}"
                        except (TypeError, ValueError):
                            st.session_state[_k] = '0'

        calc_results_pl = calc_from_state_pl(pl_rows)
        render_pl_interactive(pl_rows, calc_results_pl)

    with st.container(border=True):
        st.markdown(f'<p class="np-title">&#128230; {_he("商品別販売計画")}</p>', unsafe_allow_html=True)

        sales_rows = load_sales(_nv)

        for _row in sales_rows:
            _ridx = _row['row_idx']
            for _yr, _info in _row['years'].items():
                if not _info['is_formula']:
                    _k = f"sales_inp_{_ridx}_{_yr}"
                    if _k not in st.session_state:
                        try:
                            st.session_state[_k] = f"{float(_info.get('value') or 0):,.0f}"
                        except (TypeError, ValueError):
                            st.session_state[_k] = '0'

        calc_results_sales = calc_from_state_sales(sales_rows)
        render_sales_interactive(sales_rows, calc_results_sales)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 月次資金計画 - 描画
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_CF_ITEMS = [
    # (section, label, row, is_input, style)
    ('月初残高',     '月初残高',             58, False, 'balance'),
    ('経常収支',     '現金売上・売掛回収',   59, False, 'item'),
    ('経常収支',     'その他',               60, True,  'item'),
    ('経常収支',     '',                     61, True,  'item'),
    ('経常収支',     '収入合計',             63, False, 'subtotal'),
    ('経常収支',     '消費税等預り金',       64, False, 'item'),
    ('経常収支',     '現金仕入・買掛支払い', 65, False, 'item'),
    ('経常収支',     '外注費支払い',         66, True,  'item'),
    ('経常収支',     '給与・福利・賞与支払い', 67, False, 'item'),
    ('経常収支',     '○○支払い',            68, True,  'item'),
    ('経常収支',     '○○支払い',            69, True,  'item'),
    ('経常収支',     'その他経費支払い',     70, False, 'item'),
    ('経常収支',     '支払い利息',           71, True,  'item'),
    ('経常収支',     '減価償却費（－）',     72, True,  'item'),
    ('経常収支',     '支出合計',             73, False, 'subtotal'),
    ('経常収支',     '差引過不足',           74, False, 'total'),
    ('経常外収支',   '固定資産等売却収入',   75, True,  'item'),
    ('経常外収支',   '',                     76, True,  'item'),
    ('経常外収支',   '収入合計',             77, False, 'subtotal'),
    ('経常外収支',   '消費税',               78, True,  'item'),
    ('経常外収支',   '法人税',               79, True,  'item'),
    ('経常外収支',   '固定資産等購入支払',   80, True,  'item'),
    ('経常外収支',   '支出合計',             81, False, 'subtotal'),
    ('経常外収支',   '差引過不足',           82, False, 'total'),
    ('財務収支',     '長期借入金調達',       83, True,  'item'),
    ('財務収支',     '短期借入金調達',       84, True,  'item'),
    ('財務収支',     '手形割引',             85, True,  'item'),
    ('財務収支',     '増資',                 86, True,  'item'),
    ('財務収支',     '収入合計',             87, False, 'subtotal'),
    ('財務収支',     '長期借入金返済',       88, True,  'item'),
    ('財務収支',     '短期借入金返済',       89, True,  'item'),
    ('財務収支',     '支出合計',             90, False, 'subtotal'),
    ('財務収支',     '差引過不足',           91, False, 'total'),
    ('月末残高',     '月末残高',             92, False, 'balance'),
]

_CF_COL_W = [1.0, 1.4] + [0.72] * 13


def _save_to_excel_cf(row_idx: int, col_idx: int, key: str) -> None:
    """月次資金計画タブ用 on_change コールバック"""
    try:
        raw_val = str(st.session_state.get(key) or '0').replace(',', '')
        val = float(raw_val) if raw_val else 0.0
        st.session_state[key] = f'{val:,.0f}'
        _cache_set('月次計画', row_idx, col_idx, val)
        gsheets.write_cell_async('月次計画', row_idx, col_idx, val)
        _recalc_monthly_local()
    except Exception:
        pass


def render_cf_interactive(raw: dict, calc_res: dict) -> None:
    """月次資金計画を st.columns 機構でインタラクティブ描画"""
    hdr = st.columns(_CF_COL_W)
    hdr[0].markdown(f'<div class="yp-hdr">{_he("区分")}</div>', unsafe_allow_html=True)
    hdr[1].markdown(f'<div class="yp-hdr">{_he("項目")}</div>', unsafe_allow_html=True)
    for i, m in enumerate(_MO_MONTHS):
        hdr[2 + i].markdown(f'<div class="yp-hdr-yr">{_he(m)}</div>', unsafe_allow_html=True)

    _STYLE_MAP = {
        'balance':  ('mp-sub-total', 'mp-sub-total'),
        'total':    ('yp-total',     'yp-total'),
        'subtotal': ('yp-sub',       'yp-sub'),
        'item':     ('yp-section',   'yp-item'),
    }

    _sentinel = object()
    prev_sec: object = _sentinel

    for (section, label, row, is_input, style) in _CF_ITEMS:
        show_sec = section != prev_sec
        prev_sec = section

        sec_css, lbl_css = _STYLE_MAP[style]

        rc = st.columns(_CF_COL_W)
        if show_sec:
            rc[0].markdown(f'<div class="{sec_css}">{_he(section)}</div>', unsafe_allow_html=True)
        else:
            rc[0].markdown(f'<div class="yp-empty"></div>', unsafe_allow_html=True)
        rc[1].markdown(f'<div class="{lbl_css}">{_he(label) if label else "&nbsp;"}</div>', unsafe_allow_html=True)

        # G col (0-month): always display-only
        g0 = _fv_mo(calc_res.get((row, 7)))
        rc[2].markdown(f'<div class="disp-cell">{g0}</div>', unsafe_allow_html=True)

        # H-S monthly cols
        for ci, c in enumerate(_MO_DATA_COLS):
            if is_input:
                inp_key = f'cf_inp_{row}_{c}'
                rc[3 + ci].text_input(
                    '', key=inp_key, label_visibility='collapsed',
                    on_change=_save_to_excel_cf,
                    args=(row, c, inp_key),
                )
            else:
                v = _fv_mo(calc_res.get((row, c)))
                rc[3 + ci].markdown(f'<div class="disp-cell">{v}</div>', unsafe_allow_html=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 商品別販売計画 - 描画
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# (name_row, [(sub_label, tan_row, cum_row, is_input, fmt), ...])
_SP_GROUPS = [
    (103, [
        ('単価',     103, 104, True,  'num'),
        ('数量',     105, 106, True,  'num'),
        ('売上',     107, 108, False, 'num'),
        ('変動費',   109, 110, False, 'num'),
        ('粗利益',   111, 112, False, 'num'),
        ('粗利益率', 113, 114, True,  'pct'),
    ]),
    (115, [
        ('単価',     115, 116, True,  'num'),
        ('数量',     117, 118, True,  'num'),
        ('売上',     119, 120, False, 'num'),
        ('変動費',   121, 122, False, 'num'),
        ('粗利益',   123, 124, False, 'num'),
        ('粗利益率', 125, 126, True,  'pct'),
    ]),
    (127, [
        ('単価',     127, 128, True,  'num'),
        ('数量',     129, 130, True,  'num'),
        ('売上',     131, 132, False, 'num'),
        ('変動費',   133, 134, False, 'num'),
        ('粗利益',   135, 136, False, 'num'),
        ('粗利益率', 137, 138, True,  'pct'),
    ]),
    (139, [
        ('単価',     139, 140, False, 'num'),
        ('数量',     141, 142, False, 'num'),
        ('売上',     143, 144, False, 'num'),
        ('変動費',   145, 146, False, 'num'),
        ('粗利益',   147, 148, False, 'num'),
        ('粗利益率', 149, 150, False, 'pct'),
    ]),
]

_SP_COL_W = [0.8, 0.7, 0.7, 0.68, 0.45] + [0.68] * 13
_SP_D_LABELS = {'単価', '数量'}


def _save_to_excel_sp(row_idx: int, col_idx: int, key: str) -> None:
    """商品別販売計画タブ用 on_change コールバック"""
    try:
        raw_val = str(st.session_state.get(key) or '0').replace(',', '')
        val = float(raw_val) if raw_val else 0.0
        if '_pct_' in key:
            val = val / 100.0 if val > 1.0 else val
        st.session_state[key] = f'{val:,.0f}' if '_pct_' not in key else f'{val * 100:.2f}%'
        _cache_set('月次計画', row_idx, col_idx, val)
        gsheets.write_cell_async('月次計画', row_idx, col_idx, val)
        _recalc_monthly_local()
    except Exception:
        pass


def _save_to_excel_sp_pct(row_idx: int, col_idx: int, key: str) -> None:
    """粗利益率セル用 on_change コールバック（%入力→小数で保存）"""
    try:
        raw_val = str(st.session_state.get(key) or '0').replace(',', '').replace('%', '')
        val_pct = float(raw_val) if raw_val else 0.0
        val_dec = val_pct / 100.0 if val_pct > 1.0 else val_pct
        st.session_state[key] = f'{val_dec * 100:.2f}%'
        _cache_set('月次計画', row_idx, col_idx, val_dec)
        gsheets.write_cell_async('月次計画', row_idx, col_idx, val_dec)
        _recalc_monthly_local()
    except Exception:
        pass


def _save_to_excel_sp_num(row_idx: int, col_idx: int, key: str) -> None:
    """数値セル用 on_change コールバック"""
    try:
        raw_val = str(st.session_state.get(key) or '0').replace(',', '')
        val = float(raw_val) if raw_val else 0.0
        st.session_state[key] = f'{val:,.0f}'
        _cache_set('月次計画', row_idx, col_idx, val)
        gsheets.write_cell_async('月次計画', row_idx, col_idx, val)
        _recalc_monthly_local()
    except Exception:
        pass


def render_sp_interactive(raw: dict, calc_res: dict) -> None:
    """商品別販売計画を st.columns 機構でインタラクティブ描画"""
    # ヘッダー行: 商品 | C項目 | D項目 | E目標 | (当月累計) | ０か月目 | ４月～３月
    hdr = st.columns(_SP_COL_W)
    hdr[0].markdown(f'<div class="yp-hdr">{_he("商品")}</div>', unsafe_allow_html=True)
    hdr[1].markdown(f'<div class="yp-hdr">{_he("項目")}</div>', unsafe_allow_html=True)
    hdr[2].markdown(f'<div class="yp-hdr">&nbsp;</div>', unsafe_allow_html=True)
    hdr[3].markdown(f'<div class="yp-hdr-yr">{_he("目標")}</div>', unsafe_allow_html=True)
    hdr[4].markdown(f'<div class="yp-hdr">&nbsp;</div>', unsafe_allow_html=True)
    for i, m in enumerate(_MO_MONTHS):
        hdr[5 + i].markdown(f'<div class="yp-hdr-yr">{_he(m)}</div>', unsafe_allow_html=True)

    for gi, (name_row, subs) in enumerate(_SP_GROUPS):
        product_name = str(raw.get(name_row, {}).get(2) or f'商品{gi + 1}')
        is_total_group = (name_row == 139)
        grp_css = 'mp-sub-total' if is_total_group else 'yp-section'

        for si, (sub_lbl, tan_r, cum_r, is_input, fmt) in enumerate(subs):
            show_product = (si == 0)
            c_lbl = '' if sub_lbl in _SP_D_LABELS else sub_lbl
            d_lbl = sub_lbl if sub_lbl in _SP_D_LABELS else ''

            # ── 当月行 ──
            rc = st.columns(_SP_COL_W)
            if show_product:
                rc[0].markdown(f'<div class="{grp_css}">{_he(product_name)}</div>', unsafe_allow_html=True)
            else:
                rc[0].markdown('<div class="yp-empty"></div>', unsafe_allow_html=True)
            rc[1].markdown(f'<div class="yp-item">{_he(c_lbl) if c_lbl else "&nbsp;"}</div>', unsafe_allow_html=True)
            rc[2].markdown(f'<div class="yp-item">{_he(d_lbl) if d_lbl else "&nbsp;"}</div>', unsafe_allow_html=True)
            # E列（目標）
            e0 = _fv_mo(calc_res.get((tan_r, 5)), fmt)
            rc[3].markdown(f'<div class="disp-cell">{e0}</div>', unsafe_allow_html=True)
            rc[4].markdown(f'<div class="mp-ltan">{_he("当月")}</div>', unsafe_allow_html=True)
            # G col (0か月目)
            g0 = _fv_mo(calc_res.get((tan_r, 7)), fmt)
            rc[5].markdown(f'<div class="disp-cell">{g0}</div>', unsafe_allow_html=True)
            # H-S monthly
            for ci, c in enumerate(_MO_DATA_COLS):
                if is_input:
                    inp_key = f'sp_inp_{tan_r}_{c}'
                    if fmt == 'pct':
                        rc[6 + ci].text_input(
                            '', key=inp_key, label_visibility='collapsed',
                            on_change=_save_to_excel_sp_pct,
                            args=(tan_r, c, inp_key),
                        )
                    else:
                        rc[6 + ci].text_input(
                            '', key=inp_key, label_visibility='collapsed',
                            on_change=_save_to_excel_sp_num,
                            args=(tan_r, c, inp_key),
                        )
                else:
                    v = _fv_mo(calc_res.get((tan_r, c)), fmt)
                    rc[6 + ci].markdown(f'<div class="disp-cell">{v}</div>', unsafe_allow_html=True)

            # ── 累計行 ──
            rc2 = st.columns(_SP_COL_W)
            rc2[0].markdown('<div class="yp-empty"></div>', unsafe_allow_html=True)
            rc2[1].markdown('<div class="yp-empty"></div>', unsafe_allow_html=True)
            rc2[2].markdown('<div class="yp-empty"></div>', unsafe_allow_html=True)
            # E列（目標）累計行
            e1 = _fv_mo(calc_res.get((cum_r, 5)), fmt)
            rc2[3].markdown(f'<div class="disp-cell">{e1}</div>', unsafe_allow_html=True)
            rc2[4].markdown(f'<div class="mp-lcum">{_he("累計")}</div>', unsafe_allow_html=True)
            g1 = _fv_mo(calc_res.get((cum_r, 7)), fmt)
            rc2[5].markdown(f'<div class="disp-cell">{g1}</div>', unsafe_allow_html=True)
            for ci, c in enumerate(_MO_DATA_COLS):
                v2 = _fv_mo(calc_res.get((cum_r, c)), fmt)
                rc2[6 + ci].markdown(f'<div class="disp-cell">{v2}</div>', unsafe_allow_html=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 値上げ効果計算表 定数・関数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_NE_INPUT_CELLS = frozenset([
    (3, 3), (3, 5),
    (4, 3), (4, 5),
    (6, 3), (6, 5), (6, 7), (6, 9), (6, 11),
    (10, 3),
    (12, 3), (13, 3),
    (19, 3), (20, 3), (21, 3),
    (27, 3), (28, 3), (29, 3),
])
_NE_PCT_COLS = frozenset([4, 6, 8, 10, 12])
_NE_PCT_ROWS_VALS = frozenset([17, 25, 33])
_NE_COL_W = [1.3, 0.7, 0.45, 0.7, 0.45, 0.7, 0.45, 0.7, 0.45, 0.7, 0.45]
_NE_S1 = [
    (3,  '売上',     False),
    (4,  '変動費',   False),
    (5,  '粗利益',   True),
    (6,  '固定費',   False),
    (7,  '営業利益', True),
]
_NE_PROD_ROWS = [
    (list(range(10, 18)), '商品1'),
    (list(range(18, 26)), '商品2'),
    (list(range(26, 34)), '商品3'),
]
_NE_ROW_LABELS = {
    3: '売上', 4: '変動費', 5: '粗利益', 6: '固定費', 7: '営業利益',
    10: '数量', 11: '単価', 12: '売上', 13: '１単位変動費',
    14: '粗利益', 15: '許容販売減', 16: '最低販売数', 17: '許容減少割合',
    18: '数量', 19: '単価', 20: '売上', 21: '仕入原価',
    22: '粗利益', 23: '許容販売減', 24: '最低販売数', 25: '許容減少割合',
    26: '数量', 27: '単価', 28: '売上', 29: '仕入原価',
    30: '粗利益', 31: '許容販売減', 32: '最低販売数', 33: '許容減少割合',
}


def _ne_is_pct(r: int, c: int) -> bool:
    return c in _NE_PCT_COLS or (r in _NE_PCT_ROWS_VALS and c in {7, 9, 11})


def _fv_ne(v, is_pct: bool = False) -> str:
    if v is None:
        return ''
    if isinstance(v, str) and v.startswith('#'):
        return ''
    try:
        f = float(v)
        if is_pct:
            return f'{f * 100:.1f}%'
        if f == round(f):
            return f'{f:,.0f}'
        return f'{f:,.2f}'
    except (TypeError, ValueError):
        return ''


@st.cache_data(ttl=15)
def load_ne_full():
    ws_v = gsheets.GSheetWS('値上げ効果計算表', data_only=True)
    raw: dict = {}
    for r in range(2, 34):
        raw[r] = {}
        for c in range(2, 13):
            raw[r][c] = ws_v.cell(r, c).value
    ws_v.close()
    return raw, {}


def _save_to_excel_ne(row_idx: int, col_idx: int, key: str) -> None:
    try:
        raw_val = str(st.session_state.get(key) or '0').replace(',', '').replace('%', '')
        val = float(raw_val) if raw_val else 0.0
        is_pct = _ne_is_pct(row_idx, col_idx)
        st.session_state[key] = _fv_ne(val, is_pct) or '0'
        _cache_set('値上げ効果計算表', row_idx, col_idx, val)
        gsheets.write_cell_async('値上げ効果計算表', row_idx, col_idx, val)
        _recalc_ne_local()
    except Exception:
        pass


def calc_ne_from_state(raw: dict, formulas: dict) -> dict:
    """Google Sheetsが計算済みの値をそのまま返す"""
    res: dict[tuple, float | None] = {}
    for r in range(2, 34):
        for c in range(2, 13):
            res[(r, c)] = raw.get(r, {}).get(c)
    return res


def render_ne_interactive(calc_res: dict) -> None:
    def _render_hdr() -> None:
        hdr = st.columns(_NE_COL_W)
        hdr[0].markdown(f'<div class="yp-hdr">{_he("項目")}</div>', unsafe_allow_html=True)
        for lbl, ui_i in [('現在', 1), ('10%増販', 3), ('10%値上げ', 5), ('15%値上げ', 7), ('20%値上げ', 9)]:
            hdr[ui_i].markdown(f'<div class="yp-hdr-yr">{_he(lbl)}</div>', unsafe_allow_html=True)
            hdr[ui_i + 1].markdown(f'<div class="yp-hdr">&nbsp;</div>', unsafe_allow_html=True)

    def _render_data_row(r: int, lbl: str, is_total: bool) -> None:
        rc = st.columns(_NE_COL_W)
        css = 'mp-sub-total' if is_total else 'yp-item'
        rc[0].markdown(f'<div class="{css}">{_he(lbl)}</div>', unsafe_allow_html=True)
        for c, ui_i in [(3,1),(4,2),(5,3),(6,4),(7,5),(8,6),(9,7),(10,8),(11,9),(12,10)]:
            is_pct = _ne_is_pct(r, c)
            is_inp = (r, c) in _NE_INPUT_CELLS
            disp = _fv_ne(calc_res.get((r, c)), is_pct)
            if is_inp:
                key = f'ne_inp_{r}_{c}'
                rc[ui_i].text_input('', key=key, label_visibility='collapsed',
                    on_change=_save_to_excel_ne, args=(r, c, key))
            else:
                rc[ui_i].markdown(f'<div class="disp-cell">{_he(disp)}</div>', unsafe_allow_html=True)

    _render_hdr()
    for r, lbl, is_total in _NE_S1:
        _render_data_row(r, lbl, is_total)

    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    st.markdown(f'<div class="sec-title">{_he("商品別")}</div>', unsafe_allow_html=True)
    _render_hdr()

    for rows, prod_name in _NE_PROD_ROWS:
        st.markdown(f'<div class="yp-section" style="margin-top:8px;">{_he(prod_name)}</div>', unsafe_allow_html=True)
        for r in rows:
            lbl = _NE_ROW_LABELS.get(r, '')
            is_total = lbl in {'粗利益', '営業利益'}
            _render_data_row(r, lbl, is_total)


def _render_ne_tab() -> None:
    st.markdown(
        f'<div class="dash-header">'
        f'<h1>&#128200; {_he("値上げ効果計算表")}</h1>'
        f'<p>{_he("数値を入力すると自動的に計算結果が反映されます。")}</p>'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.markdown(f'<div class="sec-title">{_he("全体効果")}</div>', unsafe_allow_html=True)

    raw, formulas = load_ne_full()

    for (r, c) in _NE_INPUT_CELLS:
        key = f'ne_inp_{r}_{c}'
        if key not in st.session_state:
            v = raw.get(r, {}).get(c)
            is_pct = _ne_is_pct(r, c)
            try:
                fv = float(v) if v is not None and not (isinstance(v, str) and v.startswith('#')) else 0.0
                st.session_state[key] = _fv_ne(fv, is_pct) or '0'
            except (TypeError, ValueError):
                st.session_state[key] = '0'

    calc_res = calc_ne_from_state(raw, formulas)
    render_ne_interactive(calc_res)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 収益構造シミュレーション 定数・関数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_SIM_SHEET = '収益構造シミュレーション '  # 末尾スペースあり
_SIM_VGROUP_BASE_ROWS = [3, 20, 37]
_SIM_VGROUP_NAMES = ['商品1', '商品2', '商品3']
_SIM_HBLOCK_COL_STARTS = [2, 6, 10, 14, 18, 22]
_SIM_HBLOCK_NAMES = [
    '現状', '固定費削減', '変動費削減',
    '単価アップ', '数量アップ', 'ミックス',
]
_SIM_HBLOCK_COLORS = ['#1A3A5C', '#2E7D32', '#BF360C', '#6A1B9A', '#1565C0', '#00695C']


def _sim_build_input_cells() -> frozenset:
    cells = set()
    for base in _SIM_VGROUP_BASE_ROWS:
        cells.update([
            (base + 4, 3), (base + 8, 3), (base + 10, 3), (base + 11, 3),
            (base + 11, 7),
            (base + 5, 12),
            (base + 3, 16),
            (base + 4, 20), (base + 11, 19), (base + 12, 19),
            (base + 3, 24), (base + 4, 24), (base + 5, 24), (base + 11, 23),
        ])
    return frozenset(cells)


_SIM_ALL_INPUT_CELLS = _sim_build_input_cells()


@st.cache_data(ttl=15)
def load_sim_full():
    ws_v = gsheets.GSheetWS(_SIM_SHEET, data_only=True)
    raw: dict = {}
    for r in range(1, 52):
        raw[r] = {}
        for c in range(1, 25):
            raw[r][c] = ws_v.cell(r, c).value
    ws_v.close()
    return raw, {}


def _save_to_excel_sim(row: int, col: int, key: str) -> None:
    try:
        raw_val = str(st.session_state.get(key) or '0').replace(',', '')
        val = float(raw_val) if raw_val else 0.0
        st.session_state[key] = f'{val:g}'
        _cache_set(_SIM_SHEET, row, col, val)
        gsheets.write_cell_async(_SIM_SHEET, row, col, val)
        _recalc_sim_local()
    except Exception:
        pass


def calc_sim_from_state(raw: dict, formulas: dict) -> dict:
    """Google Sheetsが計算済みの値をそのまま返す"""
    res: dict = {}
    for r in range(1, 52):
        for c in range(1, 25):
            res[(r, c)] = raw.get(r, {}).get(c)
    return res


def _fv_s(v, pct: bool = False) -> str:
    if v is None:
        return ''
    if isinstance(v, str):
        return _he(v)
    try:
        f = float(v)
        if pct:
            return f'{f * 100:.1f}%'
        if f == round(f):
            return f'{int(f):,}'
        return f'{f:,.2f}'
    except (TypeError, ValueError):
        return ''


def _render_sim_group(g: int, calc_res: dict) -> None:
    base = _SIM_VGROUP_BASE_ROWS[g]

    def _td(v, is_inp=False, is_pct=False, is_total=False):
        text = _fv_s(v, pct=is_pct)
        if is_inp:
            style = f'background:#FFF8E6;border:1.5px solid {GOLD};font-weight:700;'
        elif is_total:
            style = f'background:#EBF3FA;font-weight:700;color:{NAVY};'
        else:
            style = 'background:transparent;'
        return (
            f'<td style="padding:4px 7px;text-align:right;font-size:.78rem;{style}">'
            f'{text}</td>'
        )

    def _label_td(text, is_total=False, is_sep=False):
        if is_sep:
            return (
                f'<td colspan="13" style="padding:3px 8px;font-size:.72rem;font-weight:700;'
                f'color:{NAVY};background:#EEF2F7;border-top:1px solid {NAVY}30;">'
                f'{_he(text)}</td>'
            )
        fw = '700' if is_total else '600'
        bg = '#EBF3FA' if is_total else '#F7F9FC'
        return (
            f'<td style="padding:4px 8px;font-size:.78rem;font-weight:{fw};'
            f'background:{bg};color:{NAVY};white-space:nowrap;">{_he(text)}</td>'
        )

    sub_right = ['―', '増減', '削減率', '倍率', '倍率', '倍率']

    hdr1 = f'<tr><td style="background:#F0F4F8;padding:5px 8px;font-size:.72rem;color:#888;">{_he("項目")}</td>'
    for bname, color in zip(_SIM_HBLOCK_NAMES, _SIM_HBLOCK_COLORS):
        hdr1 += (
            f'<td colspan="2" style="background:{color};color:white;text-align:center;'
            f'padding:6px 4px;font-size:.82rem;font-weight:700;">{_he(bname)}</td>'
        )
    hdr1 += '</tr>'

    hdr2 = '<tr><td style="background:#F0F4F8;"></td>'
    for color, rl in zip(_SIM_HBLOCK_COLORS, sub_right):
        hdr2 += (
            f'<td style="background:{color}22;color:{color};text-align:center;'
            f'padding:2px 5px;font-size:.68rem;font-weight:600;">{_he("金額")}</td>'
            f'<td style="background:{color}22;color:{color};text-align:center;'
            f'padding:2px 5px;font-size:.68rem;font-weight:600;">{_he(rl)}</td>'
        )
    hdr2 += '</tr>'

    param_offsets = [(2, '売上高'), (3, '単価'), (4, '数量'), (5, '変動費単価')]
    param_rows_html = ''
    for p_off, p_lab in param_offsets:
        row = base + p_off
        param_rows_html += '<tr>' + _label_td(p_lab)
        for col_start in _SIM_HBLOCK_COL_STARTS:
            vc = col_start + 1
            rc = col_start + 2
            param_rows_html += _td(calc_res.get((row, vc)), is_inp=(row, vc) in _SIM_ALL_INPUT_CELLS)
            param_rows_html += _td(calc_res.get((row, rc)), is_inp=(row, rc) in _SIM_ALL_INPUT_CELLS)
        param_rows_html += '</tr>'

    result_defs = [
        (8, '売上高', False),
        (9, '変動費', False),
        (10, '粗利益', True),
        (11, '固定費', False),
        (12, '経常利益', True),
        (13, '損益分岐点', False),
        (14, 'BEP比率', False),
    ]
    result_rows_html = ''
    for r_off, r_lab, is_total in result_defs:
        row = base + r_off
        result_rows_html += '<tr>' + _label_td(r_lab, is_total=is_total)
        is_pct = r_off <= 12
        for col_start in _SIM_HBLOCK_COL_STARTS:
            vc = col_start + 1
            rc = col_start + 2
            v_val = calc_res.get((row, vc))
            r_val = calc_res.get((row, rc))
            result_rows_html += _td(v_val, is_inp=(row, vc) in _SIM_ALL_INPUT_CELLS, is_total=is_total)
            if isinstance(r_val, str):
                result_rows_html += (
                    f'<td style="padding:4px 5px;text-align:center;font-size:.68rem;'
                    f'color:#888;font-style:italic;">{_he(r_val)}</td>'
                )
            else:
                result_rows_html += _td(r_val, is_pct=is_pct, is_total=is_total)
        result_rows_html += '</tr>'

    html = (
        f'<div style="overflow-x:auto;margin-bottom:.5rem;">'
        f'<table style="border-collapse:collapse;width:100%;'
        f'font-family:\'Noto Sans JP\',sans-serif;border:2px solid {NAVY}30;">'
        f'{hdr1}{hdr2}'
        f'<tr>{_label_td(_he("▼ 基本パラメータ"), is_sep=True)}</tr>'
        f'{param_rows_html}'
        f'<tr>{_label_td(_he("▼ シナリオ結果"), is_sep=True)}</tr>'
        f'{result_rows_html}'
        f'</table></div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def _render_sim_inputs(g: int, raw: dict) -> None:
    base = _SIM_VGROUP_BASE_ROWS[g]
    block_inputs = [
        (0, _SIM_HBLOCK_NAMES[0], [
            (base + 4, 3, '数量'),
            (base + 8, 3, '売上高'),
            (base + 10, 3, '粗利益'),
            (base + 11, 3, '固定費'),
        ]),
        (1, _SIM_HBLOCK_NAMES[1], [
            (base + 11, 7, '削減後固定費'),
        ]),
        (2, _SIM_HBLOCK_NAMES[2], [
            (base + 5, 12, '変動費削減率'),
        ]),
        (3, _SIM_HBLOCK_NAMES[3], [
            (base + 3, 16, '単価アップ率'),
        ]),
        (4, _SIM_HBLOCK_NAMES[4], [
            (base + 4, 20, '数量アップ倍率'),
            (base + 11, 19, '固定費'),
            (base + 12, 19, '経常利益'),
        ]),
        (5, _SIM_HBLOCK_NAMES[5], [
            (base + 3, 24, '単価率'),
            (base + 4, 24, '数量率'),
            (base + 5, 24, '変動費率'),
            (base + 11, 23, '固定費'),
        ]),
    ]
    cols = st.columns(6)
    for bi, bname, cell_defs in block_inputs:
        with cols[bi]:
            color = _SIM_HBLOCK_COLORS[bi]
            st.markdown(
                f'<div style="background:{color};color:white;text-align:center;padding:.3rem .2rem;'
                f'border-radius:5px;font-weight:700;font-size:.78rem;margin-bottom:.4rem;">'
                f'{_he(bname)}</div>',
                unsafe_allow_html=True,
            )
            for row, col_, desc in cell_defs:
                key = f'sim_inp_{row}_{col_}'
                st.text_input(
                    _he(desc), key=key, label_visibility='visible',
                    on_change=_save_to_excel_sim, args=(row, col_, key),
                )


def _render_sim_tab() -> None:
    st.markdown(
        f'<div class="dash-header">'
        f'<h1>&#128202; {_he("収益構造シミュレーション")}</h1>'
        f'<p>{_he("数値を変更するとシナリオ結果が即時更新されます。黄色セルが入力項目、青色セルが合計です。")}</p>'
        f'</div>',
        unsafe_allow_html=True,
    )

    raw, formulas = load_sim_full()

    for (r, c) in _SIM_ALL_INPUT_CELLS:
        key = f'sim_inp_{r}_{c}'
        if key not in st.session_state:
            v = raw.get(r, {}).get(c)
            try:
                fv = float(v) if v is not None else 0.0
                st.session_state[key] = f'{fv:g}'
            except (TypeError, ValueError):
                st.session_state[key] = '0'

    calc_res = calc_sim_from_state(raw, formulas)

    for g, gname in enumerate(_SIM_VGROUP_NAMES):
        st.markdown(f'<div class="sec-title">{_he(gname)}</div>', unsafe_allow_html=True)
        _render_sim_inputs(g, raw)
        st.markdown('<div style="height:.4rem;"></div>', unsafe_allow_html=True)
        _render_sim_group(g, calc_res)
        if g < 2:
            st.markdown('<hr class="divider">', unsafe_allow_html=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# タブ③: 月次計画
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _render_monthly_tab():
    st.markdown(
        f'<div class="dash-header">'
        f'<h1>&#128197; {_he("月次計画")}</h1>'
        f'<p>{_he("数値を入力すると自動的に計算結果が反映されます。")}</p>'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.markdown(f'<div class="sec-title">{_he("月次利益計画表")}</div>', unsafe_allow_html=True)

    raw, formulas = load_monthly_full()

    for r in _MO_INPUT_ROWS:
        for c in _MO_DATA_COLS:
            key = f'mo_inp_{r}_{c}'
            if key not in st.session_state:
                v = raw.get(r, {}).get(c)
                try:
                    st.session_state[key] = f'{float(v):,.0f}' if v is not None else '0'
                except (TypeError, ValueError):
                    st.session_state[key] = '0'

    # CF 入力セル初期化
    for r in _CF_INPUT_ROWS:
        for c in _MO_DATA_COLS:
            key = f'cf_inp_{r}_{c}'
            if key not in st.session_state:
                v = raw.get(r, {}).get(c)
                try:
                    st.session_state[key] = f'{float(v):,.0f}' if v is not None else '0'
                except (TypeError, ValueError):
                    st.session_state[key] = '0'

    calc_res = calc_monthly_from_state(raw, formulas)
    render_monthly_interactive(raw, calc_res)

    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    st.markdown(f'<div class="sec-title">{_he("月次資金計画表")}</div>', unsafe_allow_html=True)
    render_cf_interactive(raw, calc_res)

    # SP 入力セル初期化
    for r in _SP_INPUT_ROWS:
        for c in _MO_DATA_COLS:
            key = f'sp_inp_{r}_{c}'
            if key not in st.session_state:
                v = raw.get(r, {}).get(c)
                row_fmt = 'pct' if r in {113, 125, 137} else 'num'
                try:
                    fv = float(v) if v is not None else 0.0
                    st.session_state[key] = f'{fv * 100:.2f}%' if row_fmt == 'pct' else f'{fv:,.0f}'
                except (TypeError, ValueError):
                    st.session_state[key] = '0'

    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    st.markdown(f'<div class="sec-title">{_he("商品別販売計画表")}</div>', unsafe_allow_html=True)
    render_sp_interactive(raw, calc_res)


@st.fragment
def _frag_nenji():
    _render_nenji_tab()


@st.fragment
def _frag_monthly():
    _render_monthly_tab()


@st.fragment
def _frag_ne():
    _render_ne_tab()


@st.fragment
def _frag_sim():
    _render_sim_tab()


with tab_nenji:
    _frag_nenji()

with tab_monthly:
    _frag_monthly()

with tab_ne:
    _frag_ne()

with tab_sim:
    _frag_sim()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# タブ③: 管理者用ロジック編集（純粋 Excel モード）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@st.fragment
def _render_tab2():
    st.markdown(f"""
    <div class="admin-header">
        <h2>⚙️ 管理者用ロジック編集モード</h2>
        <p>Googleスプレッドシートを直接開いて、数式・数値・項目を自由に編集できます。保存すると自動的にダッシュボードに反映されます。</p>
    </div>""", unsafe_allow_html=True)

    # ── スプレッドシートを開くメインボタン ──
    st.markdown(f"""
    <div style="background:#fff8e6;border-left:4px solid {GOLD};border-radius:6px;
                padding:.9rem 1.2rem;margin-bottom:1rem;font-size:.87rem;line-height:1.9;">
        <b>📋 使い方</b><br>
        ① 下の「Googleスプレッドシートで開く」リンクをクリック<br>
        ② スプレッドシートで数式（<code>=B2-B3</code> 等）・数値・項目名を自由に編集<br>
        ③ Googleスプレッドシートは自動保存されます<br>
        ④ 「変更を今すぐ反映」ボタンを押すとダッシュボードに反映されます
    </div>""", unsafe_allow_html=True)

    open_col, info_col = st.columns([2, 3])
    with open_col:
        st.link_button("📂　Googleスプレッドシートで開く", gsheets.SHEETS_URL, use_container_width=True)

    with info_col:
        st.info(f"🔗 データソース: Googleスプレッドシート（スプレッドシート上で直接編集できます）")

    if st.button("🔄　スプレッドシートの変更を今すぐ反映", use_container_width=False, key="btn_admin_reload"):
        read_cell_map.clear()
        get_formula_df.clear()
        load_bs.clear()
        _detect_nenji_boundaries.clear()
        _detect_year_cols.clear()
        load_pl.clear()
        load_sales.clear()
        load_monthly_full.clear()
        load_ne_full.clear()
        load_sim_full.clear()
        _nv = st.session_state.get('_nenji_ver', 0) + 1
        st.session_state['_nenji_ver'] = _nv
        for _k in list(st.session_state.keys()):
            if (_k.startswith('bs_inp_') or _k.startswith('bs_calc_') or
                    _k.startswith('pl_inp_') or _k.startswith('pl_calc_') or
                    _k.startswith('sales_inp_') or _k.startswith('sales_calc_') or
                    _k.startswith('mo_inp_') or _k.startswith('mo_disp_') or
                    _k.startswith('cf_inp_') or _k.startswith('cf_disp_') or
                    _k.startswith('sp_inp_') or _k.startswith('sp_disp_') or
                    _k.startswith('ne_inp_') or _k.startswith('ne_disp_') or
                    _k.startswith('sim_inp_')):
                del st.session_state[_k]
        st.rerun(scope="app")

    # ── 現在のロジックプレビュー（数式込み） ──
    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    st.markdown(f'<div class="sec-title">&#128202; {_he("現在のロジック内容プレビュー（数式はそのまま表示）")}</div>', unsafe_allow_html=True)
    _, preview_df = get_formula_df()
    st.dataframe(preview_df, use_container_width=True)

    # ── 行・列の簡易操作（Excelを開かずに追加削除したい場合） ──
    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    st.markdown(f'<div class="sec-title">&#128295; {_he("項目・年度の簡易追加削除")}</div>', unsafe_allow_html=True)

    headers, df_admin = get_formula_df()

    ea, eb, ec = st.columns(3, gap="medium")

    with ea:
        with st.expander("➕ 項目行を追加"):
            new_item = st.text_input("新しい項目名", placeholder="例：1人当たり粗利", key="new_item_inp")
            if st.button("行を追加", key="btn_add_item"):
                nm = new_item.strip()
                if nm and nm not in df_admin.get("項目", pd.Series()).tolist():
                    new_row = {"項目": nm}
                    for col in headers[1:]:
                        new_row[col] = "0"
                    new_df = pd.concat([df_admin, pd.DataFrame([new_row])], ignore_index=True)
                    save_admin_df(new_df)
                    st.success(f"「{nm}」を追加しました。")
                    st.rerun()
                elif not nm:
                    st.warning("項目名を入力してください。")
                else:
                    st.warning("同名の項目が既に存在します。")

    with eb:
        with st.expander("➖ 項目行を削除"):
            item_opts = df_admin["項目"].dropna().tolist() if "項目" in df_admin.columns and not df_admin.empty else []
            if item_opts:
                del_item = st.selectbox("削除する項目", item_opts, key="del_item_sel")
                if st.button("行を削除", key="btn_del_item"):
                    filtered = df_admin[df_admin["項目"] != del_item].reset_index(drop=True)
                    save_admin_df(filtered)
                    st.success(f"「{del_item}」を削除しました。")
                    st.rerun()
            else:
                st.info("削除できる項目がありません。")

    with ec:
        with st.expander("📅 年度列を管理（追加・削除）"):
            yr_inp = st.text_input("追加する年度名", placeholder="例：5年目", key="yr_add_inp")
            if st.button("年度列を追加", key="btn_yr_add"):
                yr = yr_inp.strip()
                if yr and yr not in df_admin.columns:
                    add_df = df_admin.copy()
                    add_df[yr] = "0"
                    save_admin_df(add_df)
                    st.success(f"「{yr}」列を追加しました。")
                    st.rerun()
                elif not yr:
                    st.warning("年度名を入力してください。")
                else:
                    st.warning("同名の列が既に存在します。")

            yr_cols = [c for c in df_admin.columns if c != "項目"] if not df_admin.empty else []
            if yr_cols:
                yr_del = st.selectbox("削除する年度", yr_cols, key="yr_del_sel")
                if st.button("年度列を削除", key="btn_yr_del"):
                    del_df = df_admin.drop(columns=[yr_del], errors="ignore")
                    save_admin_df(del_df)
                    st.success(f"「{yr_del}」列を削除しました。")
                    st.rerun()

    # ── ダウンロード / セル番地早見表 ──
    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    cs1, cs2, _ = st.columns([2, 2, 4])

    with cs1:
        st.link_button("📥　スプレッドシートを開く（ダウンロードはファイル→ダウンロード）", gsheets.SHEETS_URL, use_container_width=True)

    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    with st.expander("📍 セル番地早見表（数式を書くときに参照してください）"):
        year_cols_ref = [c for c in headers if c != "項目"]
        col_map = {yr: gsheets.get_column_letter(i + 2) for i, yr in enumerate(year_cols_ref)}
        row_map = {rec["項目"]: i + 2 for i, rec in enumerate(preview_df.to_dict("records"))}

        ref_rows = []
        for item, row_idx in row_map.items():
            for yr, col_letter in col_map.items():
                ref_rows.append({
                    "項目": item, "年度": yr,
                    "セル番地": f"{col_letter}{row_idx}",
                    "例：この値を2倍にする数式": f"={col_letter}{row_idx}*2",
                })
        if ref_rows:
            st.markdown(f"""
            <div style="background:#fff8e6;border-left:4px solid {GOLD};border-radius:6px;padding:.8rem 1rem;margin-bottom:.8rem;">
            <b>読み方：</b>　列アルファベット（B, C, D…）＝年度　／　行番号（2, 3, 4…）＝項目<br>
            例）<b>B2</b> ＝「{year_cols_ref[0] if year_cols_ref else '1年目'}」×「{list(row_map.keys())[0] if row_map else '売上高'}」のセル
            </div>""", unsafe_allow_html=True)
            st.dataframe(pd.DataFrame(ref_rows), use_container_width=True, hide_index=True)

            leg1, leg2 = st.columns(2)
            with leg1:
                st.markdown("**列（アルファベット）一覧**")
                st.table(pd.DataFrame([{"列": v, "年度": k} for k, v in col_map.items()]))
            with leg2:
                st.markdown("**行（番号）一覧**")
                st.table(pd.DataFrame([{"行": v, "項目": k} for k, v in row_map.items()]))


with tab2:
    _render_tab2()
