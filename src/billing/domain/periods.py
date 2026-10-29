"""Meses como claves 'AAAA-MM'."""

from datetime import date


def month_key(d: date) -> str:
    return d.strftime("%Y-%m")


def month_bounds(month: str) -> tuple[date, date]:
    """'2026-10' -> (2026-10-01, 2026-11-01)."""
    start = date.fromisoformat(f"{month}-01")
    end = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
    return start, end


def last_months(n: int, today: date | None = None) -> list[str]:
    """Las claves de los últimos `n` meses, de la más antigua a la actual."""
    today = today or date.today()
    keys, y, m = [], today.year, today.month
    for _ in range(n):
        keys.append(f"{y:04d}-{m:02d}")
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return keys[::-1]


def add_months(month: str, n: int) -> str:
    """'2026-11' + 2 -> '2027-01' (n puede ser negativo)."""
    y, m = int(month[:4]), int(month[5:7])
    index = y * 12 + (m - 1) + n
    return f"{index // 12:04d}-{index % 12 + 1:02d}"
