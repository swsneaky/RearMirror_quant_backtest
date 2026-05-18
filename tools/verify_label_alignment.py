"""Verify label_wide alignment with feature_wide"""
import sqlite3
import sys

def main():
    db_path = 'data/quant.db'

    print("=== Database Status Check ===")
    print()

    try:
        con = sqlite3.connect(db_path, timeout=120)
        con.execute("PRAGMA busy_timeout = 60000")  # 60 second timeout

        # label_wide
        cur = con.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM label_wide")
        row = cur.fetchone()
        print(f"label_wide: {row[0]:,} rows, {row[1]} to {row[2]}")

        # feature_wide
        cur = con.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM feature_wide")
        row = cur.fetchone()
        print(f"feature_wide: {row[0]:,} rows, {row[1]} to {row[2]}")

        # Codes
        cur = con.execute("SELECT COUNT(DISTINCT code) FROM label_wide")
        lw_codes = cur.fetchone()[0]
        cur = con.execute("SELECT COUNT(DISTINCT code) FROM feature_wide")
        fw_codes = cur.fetchone()[0]
        print(f"Codes: label_wide={lw_codes}, feature_wide={fw_codes}")

        con.close()
        print()
        print("=== Status: SUCCESS ===")

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
