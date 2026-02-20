"""
Data loader: reads the three CSV files, cleans them, and produces
a single unified SQLite in-memory database ready for querying.
"""
import os
import re
import sqlite3
import pandas as pd
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data" / "csv"

# ── helpers ──────────────────────────────────────────────────────────────────

def _parse_price(val) -> float:
    """Convert '$9.99', 'Free', 0, etc. to a float."""
    if pd.isna(val):
        return 0.0
    s = str(val).strip().lower()
    if s in ("free", "0", "0.0", ""):
        return 0.0
    s = re.sub(r"[^\d.]", "", s)
    try:
        return float(s)
    except ValueError:
        return 0.0


def _parse_bool(val) -> int:
    if pd.isna(val):
        return 0
    s = str(val).strip().lower()
    return 1 if s in ("true", "1", "yes") else 0


def _to_list_str(val) -> str:
    """Normalise list-like columns (genres, languages) to comma-separated strings."""
    if pd.isna(val):
        return ""
    s = str(val).strip()
    # Remove brackets/quotes
    s = re.sub(r"[\[\]'\"]", "", s)
    return s


# ── main loader ───────────────────────────────────────────────────────────────

def load_data() -> tuple[pd.DataFrame, sqlite3.Connection]:
    """
    Load & clean game_ids, game_data, additional_data CSVs.
    Returns (merged DataFrame, in-memory SQLite connection).
    """
    csv_dir = DATA_DIR

    game_ids_path       = csv_dir / "game_ids.csv"
    game_data_path      = csv_dir / "game_data.csv"
    additional_data_path= csv_dir / "additional_data.csv"

    # ── 1. Read files (tolerate missing files gracefully) ────────────────────
    dfs = {}
    for name, path in [
        ("game_ids",        game_ids_path),
        ("game_data",       game_data_path),
        ("additional_data", additional_data_path),
    ]:
        if path.exists():
            dfs[name] = pd.read_csv(path, low_memory=False)
            print(f"  Loaded {name}: {len(dfs[name])} rows")
        else:
            print(f"  WARNING: {path} not found — skipping")
            dfs[name] = pd.DataFrame()

    # ── 2. Merge ─────────────────────────────────────────────────────────────
    # Identify the common key (usually 'AppID' or 'app_id')
    df = _merge_dfs(dfs)
    print(f"  Merged dataset: {len(df)} rows, {len(df.columns)} columns")

    # ── 3. Clean / Normalise ─────────────────────────────────────────────────
    df = _clean(df)

    # ── 4. Write to SQLite ───────────────────────────────────────────────────
    conn = sqlite3.connect(":memory:")
    df.to_sql("games", conn, if_exists="replace", index=False)
    conn.commit()

    return df, conn


def _merge_dfs(dfs: dict) -> pd.DataFrame:
    base = dfs.get("game_ids", pd.DataFrame())
    data = dfs.get("game_data", pd.DataFrame())
    extra = dfs.get("additional_data", pd.DataFrame())

    # Normalise column names to lower snake_case
    for key in list(dfs.keys()):
        dfs[key].columns = [c.strip().lower().replace(" ", "_") for c in dfs[key].columns]

    base  = dfs["game_ids"]
    data  = dfs["game_data"]
    extra = dfs["additional_data"]

    # Find join key
    id_cols = ["appid", "app_id", "id", "gameid", "game_id", "steamappid"]
    key = None
    for c in id_cols:
        if c in base.columns:
            key = c
            break

    if base.empty:
        df = data if not data.empty else extra
    elif data.empty and extra.empty:
        df = base
    else:
        if key and not data.empty and key in data.columns:
            df = base.merge(data, on=key, how="outer", suffixes=("", "_data"))
        elif not data.empty:
            df = pd.concat([base, data], axis=1) if len(base) == len(data) else base
            df = data  # fallback
        else:
            df = base

        if key and not extra.empty and key in extra.columns:
            df = df.merge(extra, on=key, how="left", suffixes=("", "_extra"))
        elif not extra.empty:
            # Try to concat by rows if shapes differ
            pass

    return df


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    # Standardise column names
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    # Price
    for col in ["price", "price_usd", "original_price", "initialprice"]:
        if col in df.columns:
            df[col] = df[col].apply(_parse_price)
            df.rename(columns={col: "price"}, inplace=True)
            break
    if "price" not in df.columns:
        df["price"] = 0.0

    # is_free flag
    if "is_free" not in df.columns:
        df["is_free"] = (df["price"] == 0.0).astype(int)
    else:
        df["is_free"] = df["is_free"].apply(_parse_bool)

    # Release year
    for col in ["release_date", "releasedate", "released"]:
        if col in df.columns:
            df["release_year"] = pd.to_datetime(df[col], errors="coerce").dt.year
            break
    if "release_year" not in df.columns:
        df["release_year"] = None

    # Ratings / scores
    for col in ["rating", "positive_ratings", "score", "metacritic_score",
                "positive", "review_score"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # List columns → clean strings
    for col in ["genres", "categories", "supported_languages", "languages"]:
        if col in df.columns:
            df[col] = df[col].apply(_to_list_str)

    # Name fallback
    for col in ["name", "title", "game_name", "gamename"]:
        if col in df.columns:
            df.rename(columns={col: "name"}, inplace=True)
            break

    # Drop fully-duplicate rows
    df.drop_duplicates(inplace=True)

    return df


# ── column introspection helpers ──────────────────────────────────────────────

def get_schema_info(conn: sqlite3.Connection) -> dict:
    """Return column names and sample values for the games table."""
    cur = conn.execute("PRAGMA table_info(games)")
    cols = [row[1] for row in cur.fetchall()]
    sample = pd.read_sql("SELECT * FROM games LIMIT 3", conn)
    return {"columns": cols, "sample": sample.to_dict(orient="records")}
