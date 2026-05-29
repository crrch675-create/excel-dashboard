"""Google Sheets backend — replaces openpyxl file access."""
import json
import os
import threading

import gspread
from gspread.utils import rowcol_to_a1
from google.oauth2.service_account import Credentials
import streamlit as st

SPREADSHEET_ID = os.environ.get(
    "SPREADSHEET_ID",
    "1MuoPtwRJdrLbcrOGNeE8TKsh4faDt4rFsf3Vu4-pPwU",
)
SHEETS_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit"

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_CREDS_PATH = os.environ.get(
    "GOOGLE_CREDENTIALS_PATH",
    r"C:\Users\crrch\Desktop\jsonキー\winter-surf-497802-r3-a70bf326e01b.json",
)


@st.cache_resource
def _get_spreadsheet():
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        info = json.loads(creds_json)
        creds = Credentials.from_service_account_info(info, scopes=_SCOPES)
    else:
        creds = Credentials.from_service_account_file(_CREDS_PATH, scopes=_SCOPES)
    gc = gspread.authorize(creds)
    return gc.open_by_key(SPREADSHEET_ID)


class _Cell:
    __slots__ = ("value",)

    def __init__(self, v):
        self.value = v


class GSheetWS:
    """Read-only worksheet snapshot.
    data_only=True  → computed values (UNFORMATTED_VALUE)
    data_only=False → formula strings for formula cells (FORMULA)
    """

    def __init__(self, sheet_name: str, data_only: bool = True):
        sh = _get_spreadsheet()
        ws = sh.worksheet(sheet_name)
        opt = "UNFORMATTED_VALUE" if data_only else "FORMULA"
        raw = ws.get_all_values(value_render_option=opt)
        max_col = max((len(r) for r in raw), default=0)
        self._rows: list[list] = [r + [""] * (max_col - len(r)) for r in raw]

    def cell(self, row: int, col: int) -> _Cell:
        r, c = row - 1, col - 1
        if 0 <= r < len(self._rows) and 0 <= c < len(self._rows[r]):
            v = self._rows[r][c]
            return _Cell(None if v == "" else v)
        return _Cell(None)

    @property
    def max_row(self) -> int:
        return len(self._rows)

    @property
    def max_column(self) -> int:
        return len(self._rows[0]) if self._rows else 0

    def close(self):
        pass

    def to_dict(self) -> dict:
        """Convert rows to {1-based-row: {1-based-col: value}} dict."""
        result: dict[int, dict[int, object]] = {}
        for r_idx, row in enumerate(self._rows, 1):
            for c_idx, v in enumerate(row, 1):
                if v != '' and v is not None:
                    result.setdefault(r_idx, {})[c_idx] = v
        return result


def write_cell(sheet_name: str, row: int, col: int, value, force: bool = False) -> None:
    """Write a value to a cell. force=True skips the formula pre-check (saves 1 API call)."""
    sh = _get_spreadsheet()
    ws = sh.worksheet(sheet_name)
    if not force:
        current = ws.acell(rowcol_to_a1(row, col), value_render_option="FORMULA").value
        if isinstance(current, str) and current.startswith("="):
            return
    ws.update_cell(row, col, value)


def _safe_write(sheet_name: str, row: int, col: int, value) -> None:
    try:
        write_cell(sheet_name, row, col, value, force=True)
    except Exception:
        pass


def write_cell_async(sheet_name: str, row: int, col: int, value) -> None:
    """Write to Google Sheets in a background thread (non-blocking)."""
    threading.Thread(target=_safe_write, args=(sheet_name, row, col, value), daemon=True).start()


def write_range(sheet_name: str, start_row: int, start_col: int, data: list[list]) -> None:
    """Batch write a 2-D list starting at (start_row, start_col)."""
    sh = _get_spreadsheet()
    ws = sh.worksheet(sheet_name)
    end_row = start_row + len(data) - 1
    end_col = start_col + max(len(r) for r in data) - 1
    rng = f"{rowcol_to_a1(start_row, start_col)}:{rowcol_to_a1(end_row, end_col)}"
    ws.update(rng, data)


def clear_range(sheet_name: str, start_row: int, end_row: int, end_col: int) -> None:
    """Clear a rectangular block of cells."""
    sh = _get_spreadsheet()
    ws = sh.worksheet(sheet_name)
    rng = f"{rowcol_to_a1(start_row, 1)}:{rowcol_to_a1(end_row, end_col)}"
    ws.batch_clear([rng])


# ─── Column letter utilities (replaces openpyxl.utils) ────────────────────

def get_column_letter(n: int) -> str:
    """1-based column index → letter.  1→A, 26→Z, 27→AA."""
    result = ""
    while n:
        n, r = divmod(n - 1, 26)
        result = chr(65 + r) + result
    return result


def column_index_from_string(s: str) -> int:
    """Column letter → 1-based index.  A→1, Z→26, AA→27."""
    result = 0
    for c in s.upper():
        result = result * 26 + (ord(c) - 64)
    return result
