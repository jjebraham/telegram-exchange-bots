"""Read-only report of Trial Reel DeepSeek calls and preparation outcomes."""
import argparse
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sqlite3

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',type=Path,default=Path.home()/'.local/state/kiani-instagram-trial-reels/deepseek-usage.sqlite3')
    parser.add_argument('--prices',type=Path,help='Optional reviewed JSON mapping model names to USD rates per million tokens: cached, uncached, output.')
    args=parser.parse_args()
    path=args.db
    if path.is_symlink() or not path.is_file(): raise SystemExit('No private usage database yet.')
    con=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
    con.row_factory=sqlite3.Row
    sql='''SELECT r.id,r.origin,r.started,r.ended,r.outcome,r.error_type,
       COUNT(c.id) as calls,
       SUM(CASE WHEN c.usage_known=0 THEN 1 ELSE 0 END) AS unknown_calls,
       SUM(c.prompt_tokens) AS prompt_tokens,SUM(c.cached_tokens) AS cached_tokens,
       SUM(c.uncached_tokens) AS uncached_tokens,SUM(c.output_tokens) AS output_tokens,
       SUM(c.total_tokens) AS total_tokens
       FROM runs r LEFT JOIN calls c ON c.run_id=r.id GROUP BY r.id ORDER BY r.started DESC LIMIT 50'''
    rows=[dict(r) for r in con.execute(sql)]
    prices=json.loads(args.prices.read_text()) if args.prices else {}
    for row in rows:
        row['estimated_usd']=None
        calls=list(con.execute('SELECT model,cached_tokens,uncached_tokens,output_tokens,usage_known FROM calls WHERE run_id=?',(row['id'],)))
        if not calls or not prices: continue
        try:
            cost=Decimal('0')
            for c in calls:
                if not c['usage_known']: raise ValueError('Unknown usage')
                rates=prices[c['model']]
                terms=[(c['cached_tokens'],rates['cached']),(c['uncached_tokens'],rates['uncached']),(c['output_tokens'],rates['output'])]
                for count,rate in terms:
                    price=Decimal(str(rate))
                    if not price.is_finite() or price<0: raise ValueError('Invalid price')
                    cost+=Decimal(count)*price/Decimal(1000000)
            row['estimated_usd']=str(cost)
        except (KeyError,TypeError,ValueError,InvalidOperation):
            pass
    # Null counts mean no reported usage, never zero cost.
    print(json.dumps({'runs':rows,'note':'Counts exclude calls without reported usage. Estimates are null unless every call has usage and a supplied model price.'},ensure_ascii=False,indent=2))

if __name__=='__main__': main()

