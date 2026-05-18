"""
导入行业数据到数据库

将 data/raw/stock_industry_map.parquet 中的行业数据导入到 stock_info 表。
股票列表通过 JOIN 查询获取行业，无需更新 daily_bar 表。
"""
import sqlite3
import pandas as pd

# 直接使用 sqlite3 连接，避免连接池问题
DB_PATH = "data/quant.db"
INDUSTRY_PATH = "data/raw/stock_industry_map.parquet"

def main():
    print(f"Loading industry data from {INDUSTRY_PATH}")
    industry_df = pd.read_parquet(INDUSTRY_PATH)
    print(f"Loaded {len(industry_df)} industry records")

    # 直接连接数据库
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")

    try:
        cursor = conn.cursor()

        # 使用批量插入提高性能
        print("Updating stock_info table...")
        data = [(row['code'], row['industry'], row['industry']) for _, row in industry_df.iterrows()]

        cursor.executemany('''
            INSERT INTO stock_info (code, industry, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(code) DO UPDATE SET industry = ?, updated_at = datetime('now')
        ''', data)

        conn.commit()
        print(f"Updated {len(data)} stock_info records")

        # 验证
        cursor.execute('''
            SELECT code, name, industry
            FROM stock_info
            WHERE industry IS NOT NULL AND industry != ""
            LIMIT 5
        ''')
        results = cursor.fetchall()
        print("\nSample stock_info with industry:")
        for r in results:
            print(f"  {r[0]}: {r[1]} - {r[2]}")

        # 统计
        cursor.execute('SELECT COUNT(*) FROM stock_info WHERE industry IS NOT NULL AND industry != ""')
        count = cursor.fetchone()[0]
        print(f"\nTotal stock_info with industry: {count}")

    finally:
        conn.close()

if __name__ == "__main__":
    main()
