"""
Data loader: reads the three CSV files, cleans/parses them, and produces
a single unified SQLite in-memory database ready for querying.

Real schema (from actual CSVs):
  game_ids.csv        : appid, name
  game_data.csv       : steam_appid, name, is_free, genres (list-of-dicts),
                        categories (list-of-dicts), supported_languages,
                        price_overview (dict), release_date (dict), metacritic (dict)
  additional_data.csv : appid, name, positive, negative, userscore,
                        owners, price (cents), initialprice, languages, genre, tags
"""
import re
import ast
import sqlite3
import pandas as pd
from pathlib import Path

DATA_DIR = Path(__file__).parent / "csv"


# ── helpers ───────────────────────────────────────────────────────────────────

def _safe_eval(val):
    if pd.isna(val):
        return None
    try:
        return ast.literal_eval(str(val))
    except Exception:
        return str(val)


def _extract_genres(val) -> str:
    """Parse '[{"id":"1","description":"Action"},...]' → 'Action, Indie'."""
    obj = _safe_eval(val)
    if isinstance(obj, list):
        return ", ".join(
            str(item.get("description", "")) for item in obj
            if isinstance(item, dict) and item.get("description")
        )
    if isinstance(obj, str):
        return obj
    return ""


def _extract_categories(val) -> str:
    return _extract_genres(val)


def _extract_price_usd(val) -> float:
    """price_overview dict → USD. 'final' field is in cents."""
    obj = _safe_eval(val)
    if isinstance(obj, dict):
        final = obj.get("final") or obj.get("initial") or 0
        try:
            return round(float(final) / 100, 2)
        except Exception:
            return 0.0
    try:
        return round(float(str(val).replace(",", "")) / 100, 2)
    except Exception:
        return 0.0


def _extract_release_year(val):
    """release_date dict {'coming_soon': False, 'date': '1 Nov, 2000'} → 2000."""
    obj = _safe_eval(val)
    if isinstance(obj, dict):
        date_str = obj.get("date", "")
    else:
        date_str = str(val) if val else ""
    parsed = pd.to_datetime(date_str, errors="coerce")
    return int(parsed.year) if not pd.isna(parsed) else None


def _extract_metacritic(val):
    obj = _safe_eval(val)
    if isinstance(obj, dict):
        return obj.get("score")
    try:
        return float(val)
    except Exception:
        return None


def _clean_languages(val) -> str:
    if pd.isna(val):
        return ""
    return re.sub(r"<[^>]+>", "", str(val)).strip()


def _owners_midpoint(val):
    """'10,000,000 .. 20,000,000' → 15000000.0"""
    try:
        nums = [float(p.replace(",", "")) for p in re.findall(r"[\d,]+", str(val))]
        return sum(nums) / len(nums) if nums else None
    except Exception:
        return None


# ── main loader ───────────────────────────────────────────────────────────────

def load_data() -> tuple:
    """
    Load & clean all three CSVs → unified in-memory SQLite.
    Returns (merged DataFrame, sqlite3 connection).
    """
    csv_dir = DATA_DIR

    game_ids_path        = csv_dir / "game_ids.csv"
    game_data_path       = csv_dir / "game_data.csv"
    additional_data_path = csv_dir / "additional_data.csv"

    if not any(p.exists() for p in [game_ids_path, game_data_path, additional_data_path]):
        raise FileNotFoundError(
            f"No CSV files found in {csv_dir}. "
            "Place game_ids.csv, game_data.csv, additional_data.csv there."
        )

    # ── 1. Read ───────────────────────────────────────────────────────────────
    ids_df = pd.DataFrame()
    if game_ids_path.exists():
        ids_df = pd.read_csv(game_ids_path, low_memory=False)
        ids_df.columns = ids_df.columns.str.strip().str.lower()
        print(f"  game_ids:        {len(ids_df):,} rows")

    gd_df = pd.DataFrame()
    if game_data_path.exists():
        usecols_wanted = {
            "steam_appid", "name", "is_free",
            "genres", "categories", "supported_languages",
            "price_overview", "release_date", "metacritic",
            "developers", "publishers", "platforms", "short_description",
        }
        gd_df = pd.read_csv(
            game_data_path,
            usecols=lambda c: c in usecols_wanted,
            low_memory=False,
        )
        gd_df.rename(columns={"steam_appid": "appid"}, inplace=True)
        print(f"  game_data:       {len(gd_df):,} rows")

    ad_df = pd.DataFrame()
    if additional_data_path.exists():
        ad_df = pd.read_csv(additional_data_path, low_memory=False)
        ad_df.columns = ad_df.columns.str.strip().str.lower()
        print(f"  additional_data: {len(ad_df):,} rows")

    # ── 2. Merge ──────────────────────────────────────────────────────────────
    # Base = additional_data (has ratings, price in cents, languages)
    # Merge game_data columns not already present
    if not ad_df.empty:
        df = ad_df.copy()
    elif not gd_df.empty:
        df = gd_df.copy()
    else:
        df = ids_df.copy()

    if not gd_df.empty and "appid" in df.columns and "appid" in gd_df.columns:
        extra_cols = [c for c in gd_df.columns if c not in df.columns] + ["appid"]
        df = df.merge(gd_df[extra_cols], on="appid", how="left")

    print(f"  Merged shape:    {df.shape}")

    # ── 3. Parse & Clean ─────────────────────────────────────────────────────
    df = _clean(df)

    # ── 4. SQLite ─────────────────────────────────────────────────────────────
    conn = sqlite3.connect(":memory:")
    df.to_sql("games", conn, if_exists="replace", index=False)
    conn.commit()
    print(f"  SQLite ready:    {len(df):,} games")
    return df, conn


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = df.columns.str.strip().str.lower()

    # Name
    for col in ["name", "title", "game_name"]:
        if col in df.columns:
            if col != "name":
                df.rename(columns={col: "name"}, inplace=True)
            break

    # Price (USD) — additional_data 'price' column is in cents
    if "price" in df.columns:
        df["price_usd"] = pd.to_numeric(df["price"], errors="coerce").fillna(0) / 100
    elif "price_overview" in df.columns:
        df["price_usd"] = df["price_overview"].apply(_extract_price_usd)
    else:
        df["price_usd"] = 0.0

    # is_free
    if "is_free" in df.columns:
        df["is_free"] = df["is_free"].map(
            {True: 1, False: 0, "True": 1, "False": 0, 1: 1, 0: 0}
        ).fillna((df["price_usd"] == 0).astype(int))
    else:
        df["is_free"] = (df["price_usd"] == 0).astype(int)

    # Genres — additional_data has plain string 'genre'; game_data has list-of-dicts 'genres'
    if "genre" in df.columns and "genres" not in df.columns:
        df.rename(columns={"genre": "genres"}, inplace=True)
    elif "genres" in df.columns:
        df["genres"] = df["genres"].apply(_extract_genres)

    # Categories
    if "categories" in df.columns:
        df["categories"] = df["categories"].apply(_extract_categories)

    # Languages — prefer 'languages' (additional_data), fallback 'supported_languages'
    if "languages" not in df.columns and "supported_languages" in df.columns:
        df.rename(columns={"supported_languages": "languages"}, inplace=True)
    if "languages" in df.columns:
        df["languages"] = df["languages"].apply(_clean_languages)
    if "supported_languages" in df.columns:
        df["supported_languages"] = df["supported_languages"].apply(_clean_languages)

    # Ratings
    for col in ["positive", "negative", "userscore", "ccu"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Computed rating (positive ratio × 10, 0–10 scale)
    if "positive" in df.columns and "negative" in df.columns:
        total = df["positive"].fillna(0) + df["negative"].fillna(0)
        df["rating"] = (df["positive"].fillna(0) / total.replace(0, float("nan"))) * 10
        df["rating"] = df["rating"].round(2)

    # Metacritic
    if "metacritic" in df.columns:
        df["metacritic_score"] = df["metacritic"].apply(_extract_metacritic)
        df.drop(columns=["metacritic"], inplace=True)

    # Release year
    if "release_date" in df.columns:
        df["release_year"] = df["release_date"].apply(_extract_release_year)

    # Owners
    if "owners" in df.columns:
        df["owners_estimate"] = df["owners"].apply(_owners_midpoint)

    # Multiplayer flag
    multi_src = df.get("categories", df.get("tags", pd.Series([""] * len(df), dtype=str)))
    df["has_multiplayer"] = multi_src.fillna("").str.contains(
        r"Multi-?[Pp]layer|multiplayer|Online Multi-Player", regex=True, na=False
    ).astype(int)

    # Price tier
    def _tier(p):
        if p == 0:   return "Free"
        if p < 5:    return "Budget (<$5)"
        if p < 20:   return "Mid ($5-$20)"
        return "Premium ($20+)"
    df["price_tier"] = df["price_usd"].apply(_tier)

    # Drop bloat columns
    drop_cols = [
        "detailed_description", "about_the_game", "header_image", "website",
        "pc_requirements", "mac_requirements", "linux_requirements",
        "screenshots", "movies", "background", "content_descriptors",
        "support_info", "fullgame", "package_groups", "packages",
        "price_overview", "price",   # replaced by price_usd
        "release_date",              # replaced by release_year
    ]
    df.drop(columns=[c for c in drop_cols if c in df.columns], inplace=True, errors="ignore")

    # Deduplicate on appid
    if "appid" in df.columns:
        df.drop_duplicates(subset=["appid"], keep="first", inplace=True)
    df.reset_index(drop=True, inplace=True)

    return df


# ── schema helper ──────────────────────────────────────────────────────────────

def get_schema_info(conn: sqlite3.Connection) -> dict:
    cur = conn.execute("PRAGMA table_info(games)")
    cols = [row[1] for row in cur.fetchall()]
    sample = pd.read_sql("SELECT * FROM games LIMIT 3", conn)
    return {"columns": cols, "sample": sample.to_dict(orient="records")}
