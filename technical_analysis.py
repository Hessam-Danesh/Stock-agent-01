import sqlite3
from datetime import datetime

DB_NAME = "iran_stock_agent.db"


def ema(values, span, min_periods):
    alpha = 2.0 / (span + 1.0)
    current = None
    valid = 0
    out = []
    for value in values:
        if value is None:
            out.append(None)
            continue
        valid += 1
        current = float(value) if current is None else alpha * float(value) + (1-alpha) * current
        out.append(current if valid >= min_periods else None)
    return out


def wilder(values, period):
    alpha = 1.0 / period
    current = None
    valid = 0
    out = []
    for value in values:
        if value is None:
            out.append(None)
            continue
        valid += 1
        current = float(value) if current is None else alpha * float(value) + (1-alpha) * current
        out.append(current if valid >= period else None)
    return out


def rsi(values, period=14):
    gains = [None]
    losses = [None]
    for i in range(1, len(values)):
        delta = float(values[i]) - float(values[i-1])
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = wilder(gains, period)
    avg_loss = wilder(losses, period)
    out = []
    for g, l in zip(avg_gain, avg_loss):
        if g is None or l is None:
            out.append(None)
        elif l == 0 and g > 0:
            out.append(100.0)
        elif l == 0 and g == 0:
            out.append(50.0)
        else:
            out.append(100.0 - (100.0 / (1.0 + g/l)))
    return out


def rolling(values, window, mode="mean", min_periods=None):
    min_periods = window if min_periods is None else min_periods
    out=[]
    for i in range(len(values)):
        chunk=values[max(0,i-window+1):i+1]
        valid=[float(x) for x in chunk if x is not None]
        if len(valid)<min_periods:
            out.append(None); continue
        if mode=="min": out.append(min(valid))
        elif mode=="max": out.append(max(valid))
        elif mode=="mean": out.append(sum(valid)/len(valid))
        elif mode=="std_pop":
            m=sum(valid)/len(valid); out.append((sum((x-m)**2 for x in valid)/len(valid))**0.5)
    return out


def calculate_indicators(rows):
    rows=sorted(rows,key=lambda r:r[0])
    dates=[r[0] for r in rows]
    close=[float(r[1]) for r in rows]
    high=[float(r[3]) if r[3] and float(r[3])>0 else float(r[1]) for r in rows]
    low=[float(r[2]) if r[2] and float(r[2])>0 else float(r[1]) for r in rows]
    volume=[float(r[4] or 0) for r in rows]
    e20=ema(close,20,20); e50=ema(close,50,50); r14=rsi(close,14)
    e12=ema(close,12,12); e26=ema(close,26,26)
    macd=[None if a is None or b is None else a-b for a,b in zip(e12,e26)]
    macd_sig=ema(macd,9,9)
    macd_hist=[None if a is None or b is None else a-b for a,b in zip(macd,macd_sig)]

    # Bollinger Bands: 20-session population standard deviation, 2 sigma.
    bb_mid=rolling(close,20,"mean"); bb_std=rolling(close,20,"std_pop")
    bb_upper=[None if m is None or sd is None else m+2*sd for m,sd in zip(bb_mid,bb_std)]
    bb_lower=[None if m is None or sd is None else m-2*sd for m,sd in zip(bb_mid,bb_std)]
    bb_width=[]; bb_pb=[]
    for c,m,u,l in zip(close,bb_mid,bb_upper,bb_lower):
        if m is None or u is None or l is None or m==0: bb_width.append(None)
        else: bb_width.append((u-l)/m*100)
        if u is None or l is None: bb_pb.append(None)
        elif u==l: bb_pb.append(0.5)
        else: bb_pb.append((c-l)/(u-l))

    # Wilder ADX / DI / ATR.
    up=[None]; down=[None]; plus_dm=[0.0]; minus_dm=[0.0]; tr=[]
    for i in range(len(rows)):
        if i==0:
            tr.append(abs(high[i]-low[i])); continue
        u=high[i]-high[i-1]; d=low[i-1]-low[i]
        up.append(u); down.append(d)
        plus_dm.append(u if u>d and u>0 else 0.0)
        minus_dm.append(d if d>u and d>0 else 0.0)
        tr.append(max(abs(high[i]-low[i]),abs(high[i]-close[i-1]),abs(low[i]-close[i-1])))
    atr=wilder(tr,14); p_w=wilder(plus_dm,14); m_w=wilder(minus_dm,14)
    plus_di=[]; minus_di=[]; dx=[]
    for p,m,a in zip(p_w,m_w,atr):
        if p is None or m is None or a is None or a==0:
            plus_di.append(None); minus_di.append(None); dx.append(None)
        else:
            pdi=100*p/a; mdi=100*m/a; plus_di.append(pdi); minus_di.append(mdi)
            den=pdi+mdi
            dx.append(0.0 if den==0 else 100*abs(pdi-mdi)/den)
    adx=wilder(dx,14)
    atr_pct=[None if a is None or c==0 else a/c*100 for a,c in zip(atr,close)]

    # Stochastic 14,3.
    lowest14=rolling(low,14,"min"); highest14=rolling(high,14,"max")
    stoch_k=[]
    for c,lo,hi in zip(close,lowest14,highest14):
        if lo is None or hi is None: stoch_k.append(None)
        elif hi==lo: stoch_k.append(50.0)
        else: stoch_k.append(100*(c-lo)/(hi-lo))
    stoch_d=rolling(stoch_k,3,"mean")

    support20=rolling(low,20,"min"); resistance20=rolling(high,20,"max")
    support60=rolling(low,60,"min"); resistance60=rolling(high,60,"max")
    prior_high=[None]+high[:-1]; prior_low=[None]+low[:-1]
    prior_res20=rolling(prior_high,20,"max"); prior_sup20=rolling(prior_low,20,"min")
    breakout=[None if pr is None else float(c>pr) for c,pr in zip(close,prior_res20)]
    breakdown=[None if ps is None else float(c<ps) for c,ps in zip(close,prior_sup20)]

    traded=[v for v in volume if v>0]
    latest_volume=avg_volume20=volume_ratio=None
    if len(traded)>=21:
        latest_volume=traded[-1]; prev=traded[-21:-1]; avg_volume20=sum(prev)/len(prev)
        if avg_volume20>0: volume_ratio=latest_volume/avg_volume20
    n=len(rows); traded_count=len(traded)
    quality="FULL" if n>=60 else ("LIMITED" if n>=35 else "INSUFFICIENT")
    i=n-1; r,e20v,e50v,h=r14[i],e20[i],e50[i],macd_hist[i]
    if quality=="INSUFFICIENT": trend="INSUFFICIENT_DATA"
    elif None in (e20v,e50v,r,h): trend="INDICATORS_NOT_READY"
    elif e20v>e50v and h>0 and r>=50: trend="BULLISH"
    elif e20v<e50v and h<0 and r<50: trend="BEARISH"
    else: trend="NEUTRAL"
    return {
        "trade_date":str(dates[i]),"price_close":close[i],"rsi14":r,"ema20":e20v,"ema50":e50v,
        "macd":macd[i],"macd_signal":macd_sig[i],"macd_hist":h,
        "adx14":adx[i],"plus_di14":plus_di[i],"minus_di14":minus_di[i],"atr14":atr[i],"atr_pct":atr_pct[i],
        "bb_mid":bb_mid[i],"bb_upper":bb_upper[i],"bb_lower":bb_lower[i],"bb_width_pct":bb_width[i],"bb_percent_b":bb_pb[i],
        "stoch_k":stoch_k[i],"stoch_d":stoch_d[i],"breakout20":breakout[i],"breakdown20":breakdown[i],
        "latest_volume":latest_volume,"avg_volume20":avg_volume20,"volume_ratio":volume_ratio,
        "support20":support20[i],"resistance20":resistance20[i],"support60":support60[i],"resistance60":resistance60[i],
        "price_count":n,"traded_count":traded_count,"data_quality":quality,"technical_trend":trend
    }


def main():
    conn=sqlite3.connect(DB_NAME)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS technical_indicators (
            ins_code TEXT PRIMARY KEY,symbol TEXT,trade_date TEXT,price_close REAL,rsi14 REAL,ema20 REAL,ema50 REAL,
            macd REAL,macd_signal REAL,macd_hist REAL,adx14 REAL,plus_di14 REAL,minus_di14 REAL,atr14 REAL,atr_pct REAL,
            bb_mid REAL,bb_upper REAL,bb_lower REAL,bb_width_pct REAL,bb_percent_b REAL,stoch_k REAL,stoch_d REAL,
            breakout20 REAL,breakdown20 REAL,latest_volume REAL,avg_volume20 REAL,volume_ratio REAL,support20 REAL,
            resistance20 REAL,support60 REAL,resistance60 REAL,price_count INTEGER,traded_count INTEGER,
            data_quality TEXT,technical_trend TEXT,updated_at TEXT)
    """)
    existing={r[1] for r in conn.execute("PRAGMA table_info(technical_indicators)")}
    migrations={"adx14":"REAL","plus_di14":"REAL","minus_di14":"REAL","atr14":"REAL","atr_pct":"REAL",
      "bb_mid":"REAL","bb_upper":"REAL","bb_lower":"REAL","bb_width_pct":"REAL","bb_percent_b":"REAL",
      "stoch_k":"REAL","stoch_d":"REAL","breakout20":"REAL","breakdown20":"REAL"}
    for col,typ in migrations.items():
        if col not in existing: conn.execute(f"ALTER TABLE technical_indicators ADD COLUMN {col} {typ}")
    conn.commit()
    stocks=conn.execute("""SELECT i.ins_code,i.symbol FROM instruments i JOIN instrument_classification c
      ON i.ins_code=c.ins_code WHERE c.main_category='stock' ORDER BY i.symbol""").fetchall()
    print("STOCKS FOUND:",len(stocks)); saved=insufficient=errors=0
    cols=["ins_code","symbol","trade_date","price_close","rsi14","ema20","ema50","macd","macd_signal","macd_hist",
      "adx14","plus_di14","minus_di14","atr14","atr_pct","bb_mid","bb_upper","bb_lower","bb_width_pct","bb_percent_b",
      "stoch_k","stoch_d","breakout20","breakdown20","latest_volume","avg_volume20","volume_ratio","support20","resistance20",
      "support60","resistance60","price_count","traded_count","data_quality","technical_trend","updated_at"]
    updates=",".join(f"{c}=excluded.{c}" for c in cols[1:])
    placeholders=",".join("?" for _ in cols)
    sql=f"INSERT INTO technical_indicators ({','.join(cols)}) VALUES ({placeholders}) ON CONFLICT(ins_code) DO UPDATE SET {updates}"
    for index,(ins_code,symbol) in enumerate(stocks):
        try:
            rows=conn.execute("SELECT trade_date,price_close,price_min,price_max,volume FROM daily_prices WHERE ins_code=? AND price_close>0 ORDER BY trade_date ASC",(ins_code,)).fetchall()
            if not rows: insufficient+=1; continue
            result=calculate_indicators(rows)
            if result["data_quality"]=="INSUFFICIENT": insufficient+=1
            values=[ins_code,symbol]+[result[k] for k in cols[2:-1]]+[datetime.now().isoformat(timespec="seconds")]
            conn.execute(sql,values); saved+=1
        except Exception as error:
            errors+=1; print("ERROR:",symbol,str(error))
        if (index+1)%100==0: conn.commit(); print("Processed:",index+1,"/",len(stocks))
    conn.commit()
    print("\nTECHNICAL ANALYSIS COMPLETED\nSaved:",saved,"\nInsufficient data:",insufficient,"\nErrors:",errors)
    print("\nTREND DISTRIBUTION:")
    for row in conn.execute("SELECT technical_trend,COUNT(*) FROM technical_indicators GROUP BY technical_trend ORDER BY COUNT(*) DESC"): print(row)
    print("\nDATA QUALITY DISTRIBUTION:")
    for row in conn.execute("SELECT data_quality,COUNT(*) FROM technical_indicators GROUP BY data_quality"): print(row)
    print("\nTOP 10 BULLISH STOCKS:")
    for row in conn.execute("SELECT symbol,price_close,rsi14,ema20,ema50,macd_hist,volume_ratio FROM technical_indicators WHERE technical_trend='BULLISH' ORDER BY macd_hist DESC LIMIT 10"): print(row)
    conn.close()

if __name__=="__main__": main()
