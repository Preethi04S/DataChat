"""Verification Use Case — Demonstrates the data cleaning pipeline.

Run this script to verify that all data quality issues are detected and fixed.
Usage: python scripts/verify_cleaning.py

This script serves as a verification use case for Akaike's data quality standards.
"""
import os
import sys

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["LLM_MODE"] = "stub"

import pandas as pd
import numpy as np
from app.data.schema import infer_schema
from app.data.cleaner import clean_dataset


def print_header(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def print_pass(msg):
    print(f"  [PASS] {msg}")


def print_fail(msg):
    print(f"  [FAIL] {msg}")


def main():
    print_header("DATA CLEANING VERIFICATION USE CASE")
    print("  Akaike Technologies — Enterprise Data Quality Pipeline")
    print("  Verifies outlier handling, column alignment, and data integrity")

    # ── Load raw data ──
    csv_path = os.path.join(os.path.dirname(__file__), "..", "data", "books.csv")
    raw_df = pd.read_csv(csv_path, encoding="utf-8")
    raw_schema = infer_schema(raw_df)

    print(f"\n  Raw dataset: {len(raw_df)} rows, {len(raw_df.columns)} columns")

    # ── Run cleaner ──
    cleaned_df, report = clean_dataset(raw_df.copy(), raw_schema)

    print(f"  Cleaned dataset: {len(cleaned_df)} rows")
    print(f"  Rows fixed: {report.rows_fixed}")
    print(f"  Outliers handled: {report.outliers_found}")

    # ══════════════════════════════════════════════════════════════════
    # USE CASE 1: Logical inconsistency — Rating without reviews
    # ══════════════════════════════════════════════════════════════════
    print_header("USE CASE 1: Rating Without Reviews")
    print("  Books with a rating > 0 but ratings_count = 0 are logically")
    print("  impossible. The cleaner should set their rating to NaN.")

    # Before cleaning
    raw_bad = raw_df[(raw_df["average_rating"] > 0) & (raw_df["ratings_count"] == 0)]
    print(f"\n  BEFORE: {len(raw_bad)} books have rating > 0 with 0 reviews:")
    for _, row in raw_bad.iterrows():
        print(f"    - \"{row['title']}\" rating={row['average_rating']}, count={row['ratings_count']}")

    # After cleaning
    cleaned_bad = cleaned_df[
        (cleaned_df["average_rating"] > 0) & (cleaned_df["ratings_count"] == 0)
    ]
    if len(cleaned_bad) == 0:
        print_pass(f"AFTER: All {len(raw_bad)} inconsistent ratings have been set to NaN")
    else:
        print_fail(f"AFTER: {len(cleaned_bad)} inconsistent ratings remain")

    # Verify the specific books now have NaN rating
    for _, row in raw_bad.iterrows():
        title = row["title"]
        cleaned_row = cleaned_df[cleaned_df["title"] == title]
        if not cleaned_row.empty:
            rating = cleaned_row.iloc[0]["average_rating"]
            if pd.isna(rating):
                print_pass(f"\"{title}\" rating is now NaN (was {row['average_rating']})")
            else:
                print_fail(f"\"{title}\" still has rating={rating}")

    # ══════════════════════════════════════════════════════════════════
    # USE CASE 2: Zero rating and zero count — Missing data
    # ══════════════════════════════════════════════════════════════════
    print_header("USE CASE 2: Zero Rating with Zero Count")
    print("  Books with rating=0 and count=0 represent missing data,")
    print("  not actual zero ratings. Both should become NaN.")

    raw_zero = raw_df[(raw_df["average_rating"] == 0) & (raw_df["ratings_count"] == 0)]
    print(f"\n  BEFORE: {len(raw_zero)} books have rating=0 and count=0:")
    for _, row in raw_zero.iterrows():
        print(f"    - \"{row['title']}\"")

    for _, row in raw_zero.iterrows():
        title = row["title"]
        cleaned_row = cleaned_df[cleaned_df["title"] == title]
        if not cleaned_row.empty:
            r = cleaned_row.iloc[0]
            if pd.isna(r["average_rating"]) and pd.isna(r["ratings_count"]):
                print_pass(f"\"{title}\" both rating and count are now NaN")
            else:
                print_fail(f"\"{title}\" not fully cleaned")

    # ══════════════════════════════════════════════════════════════════
    # USE CASE 3: Zero page count
    # ══════════════════════════════════════════════════════════════════
    print_header("USE CASE 3: Zero Page Count")
    print("  Books with 0 pages represent missing data. Should become NaN.")

    raw_zero_pages = raw_df[raw_df["num_pages"] == 0]
    print(f"\n  BEFORE: {len(raw_zero_pages)} books have 0 pages:")
    for _, row in raw_zero_pages.iterrows():
        print(f"    - \"{row['title']}\" (ratings_count={row['ratings_count']})")

    for _, row in raw_zero_pages.iterrows():
        title = row["title"]
        cleaned_row = cleaned_df[cleaned_df["title"] == title]
        if not cleaned_row.empty and pd.isna(cleaned_row.iloc[0]["num_pages"]):
            print_pass(f"\"{title}\" page count set to NaN")
        else:
            print_fail(f"\"{title}\" page count not cleaned")

    # ══════════════════════════════════════════════════════════════════
    # USE CASE 4: Outlier capping (average_rating)
    # ══════════════════════════════════════════════════════════════════
    print_header("USE CASE 4: Rating Outlier Winsorization")
    print("  Extreme ratings (outside IQR bounds) should be capped.")

    raw_ratings = raw_df["average_rating"].dropna()
    q1 = raw_ratings.quantile(0.25)
    q3 = raw_ratings.quantile(0.75)
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr

    raw_outliers = raw_df[
        (raw_df["average_rating"] < lower) | (raw_df["average_rating"] > upper)
    ]
    print(f"\n  IQR bounds: [{lower:.2f}, {upper:.2f}]")
    print(f"  BEFORE: {len(raw_outliers)} rating outliers")

    # After cleaning — check bounds
    cleaned_ratings = cleaned_df["average_rating"].dropna()
    below = (cleaned_ratings < lower).sum()
    above = (cleaned_ratings > upper).sum()
    if below == 0 and above == 0:
        print_pass(f"AFTER: All ratings within [{lower:.2f}, {upper:.2f}] bounds")
    else:
        print_fail(f"AFTER: {below} below lower, {above} above upper")

    # Show specific examples
    print("\n  Examples of capped ratings:")
    examples = raw_outliers.head(5)
    for _, row in examples.iterrows():
        title = row["title"]
        old_val = row["average_rating"]
        cleaned_row = cleaned_df[cleaned_df["title"] == title]
        if not cleaned_row.empty:
            new_val = cleaned_row.iloc[0]["average_rating"]
            if pd.notna(new_val):
                print(f"    \"{title}\": {old_val} -> {new_val:.2f}")

    # ══════════════════════════════════════════════════════════════════
    # USE CASE 5: Placeholder descriptions
    # ══════════════════════════════════════════════════════════════════
    print_header("USE CASE 5: Placeholder Description Cleanup")
    print("  Descriptions like 'No Marketing Blurb' or 'See:' are placeholders")
    print("  and should be set to NaN.")

    placeholder_examples = ["No Marketing Blurb", "See:"]
    for placeholder in placeholder_examples:
        raw_match = raw_df[raw_df["description"] == placeholder]
        if not raw_match.empty:
            title = raw_match.iloc[0]["title"]
            cleaned_row = cleaned_df[cleaned_df["title"] == title]
            if not cleaned_row.empty and pd.isna(cleaned_row.iloc[0]["description"]):
                print_pass(f"\"{title}\" placeholder description '{placeholder}' -> NaN")
            else:
                print_fail(f"\"{title}\" placeholder not cleaned")

    # ══════════════════════════════════════════════════════════════════
    # USE CASE 6: Duplicate subtitle == title
    # ══════════════════════════════════════════════════════════════════
    print_header("USE CASE 6: Duplicate Subtitle Cleanup")
    print("  Rows where subtitle is identical to title should have")
    print("  the subtitle cleared to NaN.")

    raw_dup_sub = raw_df[raw_df["title"] == raw_df["subtitle"]]
    print(f"\n  BEFORE: {len(raw_dup_sub)} rows with subtitle == title:")
    for _, row in raw_dup_sub.iterrows():
        print(f"    - \"{row['title']}\"")

    for _, row in raw_dup_sub.iterrows():
        title = row["title"]
        cleaned_row = cleaned_df[cleaned_df["title"] == title]
        if not cleaned_row.empty and pd.isna(cleaned_row.iloc[0]["subtitle"]):
            print_pass(f"\"{title}\" subtitle cleared")
        else:
            print_fail(f"\"{title}\" subtitle not cleaned")

    # ══════════════════════════════════════════════════════════════════
    # USE CASE 7: Identifier columns NOT modified
    # ══════════════════════════════════════════════════════════════════
    print_header("USE CASE 7: ISBN & Year Preserved (Not Winsorized)")
    print("  ISBN and published_year should NOT be outlier-capped")
    print("  since they are identifiers/dates, not statistical measures.")

    isbn_match = (raw_df["isbn13"] == cleaned_df["isbn13"]).all()
    if isbn_match:
        print_pass("All ISBN values preserved (not modified by outlier handling)")
    else:
        changed = (raw_df["isbn13"] != cleaned_df["isbn13"]).sum()
        print_fail(f"{changed} ISBN values were modified")

    year_match = True
    for idx in raw_df.index:
        raw_val = raw_df.loc[idx, "published_year"]
        clean_val = cleaned_df.loc[idx, "published_year"]
        if pd.notna(raw_val) and pd.notna(clean_val) and raw_val != clean_val:
            year_match = False
            break
    if year_match:
        print_pass("All published_year values preserved")
    else:
        print_fail("Some published_year values were modified")

    # ══════════════════════════════════════════════════════════════════
    # SUMMARY
    # ══════════════════════════════════════════════════════════════════
    print_header("CLEANING REPORT SUMMARY")
    report_dict = report.to_dict()
    print(f"  Original rows:  {report_dict['original_row_count']}")
    print(f"  Clean rows:     {report_dict['clean_row_count']}")
    print(f"  Rows fixed:     {report_dict['rows_fixed']}")
    print(f"  Rows flagged:   {report_dict['rows_flagged']}")
    print(f"  Outliers found: {report_dict['outliers_found']}")
    print(f"  Total actions:  {report_dict['total_actions']}")
    print()
    for action in report_dict["actions"]:
        print(f"  [{action['type']}] {action['description']}")
    print(f"\n{'='*70}")
    print("  VERIFICATION COMPLETE")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
