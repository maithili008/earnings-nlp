import sqlite3

conn = sqlite3.connect('data/transcripts.db')
conn.row_factory = sqlite3.Row

rows = conn.execute('''
    SELECT symbol,
           AVG(CASE WHEN composite_rel > 0 AND direction_t1 = 'down' THEN 1.0
                    WHEN composite_rel <= 0 AND direction_t1 = 'up'  THEN 1.0
                    ELSE 0.0 END) as normal_acc,
           AVG(CASE WHEN composite_rel > 0 AND direction_t1 = 'up'   THEN 1.0
                    WHEN composite_rel <= 0 AND direction_t1 = 'down' THEN 1.0
                    ELSE 0.0 END) as inverted_acc,
           COUNT(*) as n
    FROM transcripts
    WHERE composite_rel IS NOT NULL AND direction_t1 IS NOT NULL
    GROUP BY symbol ORDER BY normal_acc DESC
''').fetchall()

print(f"{'Ticker':<6} {'Normal':>8} {'Inverted':>10} {'Best':>8}  n   Direction")
print("-" * 55)
total_correct = 0
total = 0
for r in rows:
    best = max(r['normal_acc'], r['inverted_acc'])
    direction = 'normal' if r['normal_acc'] >= r['inverted_acc'] else 'INVERTED'
    print(f"{r['symbol']:<6} {r['normal_acc']:>8.1%} {r['inverted_acc']:>10.1%} {best:>8.1%}  {r['n']}   {direction}")
    total_correct += best * r['n']
    total += r['n']

print(f"\nCurrent overall accuracy  : {sum(max(r['normal_acc'],r['inverted_acc'])*0 + r['normal_acc'] for r in rows)/len(rows):.1%} (averaged)")
print(f"If we flip inverted tickers: {total_correct/total:.1%}")
conn.close()
