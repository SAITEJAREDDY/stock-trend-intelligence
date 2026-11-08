"""Read-only Yahoo Finance historical-data MCP service. No provider API key."""
import json
import os
import re
import threading
import time
import io
import hashlib
import itertools
import hmac
import queue
import requests
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

import pandas as pd
import yfinance as yf
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse, Response

host = os.getenv('RENDER_EXTERNAL_HOSTNAME') or os.getenv('PUBLIC_HOST')
allowed_hosts = ['localhost', 'localhost:*', '127.0.0.1', '127.0.0.1:*'] + ([host, f'{host}:*'] if host else [])
mcp = FastMCP(
    'Yahoo Historical Stock Data', host='0.0.0.0',
    port=int(os.getenv('PORT', '8000')), stateless_http=True, json_response=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True, allowed_hosts=allowed_hosts,
        allowed_origins=['http://localhost:*'] + ([f'https://{host}'] if host else [])),
)
lock = threading.Lock()
chart_lock = threading.Lock()
charts = {}
telegram_status = {'configured': False, 'username': None, 'webhook_registered': False,
                   'received': 0, 'completed': 0, 'failed': 0}
telegram_queue = queue.Queue(maxsize=4)
telegram_seen = {}
telegram_last = {}
telegram_state_lock = threading.Lock()


def telegram_secret():
    token=os.getenv('TELEGRAM_BOT_TOKEN','')
    return hashlib.sha256(('stock-webhook:'+token).encode()).hexdigest() if token else ''


def telegram_api(method, payload=None, files=None):
    """Never log the request URL: Telegram credentials are embedded in it."""
    token=os.getenv('TELEGRAM_BOT_TOKEN','')
    if not token: raise RuntimeError('Telegram token not configured')
    try:
        response=requests.post('https://api.telegram.org/bot'+token+'/'+method,
                               data=payload or {},files=files,timeout=30)
        result=response.json()
        if not response.ok or not result.get('ok'):
            raise RuntimeError('Telegram API request failed')
        return result.get('result')
    except Exception:
        raise RuntimeError('Telegram API request failed') from None


def parse_telegram(text):
    aliases={'MICROSOFT':'MSFT','APPLE':'AAPL','NVIDIA':'NVDA','AMAZON':'AMZN',
             'TESLA':'TSLA','GOOGLE':'GOOGL','ALPHABET':'GOOGL','META':'META'}
    tokens=re.split(r'[\s,]+',text.strip().upper())
    if tokens and tokens[0].split('@')[0] in ('/COMPARE','/STOCK','/CHART','COMPARE','CHART','ANALYZE'):
        tokens=tokens[1:]
    symbols=[]
    for part in tokens:
        part=part.lstrip('$')
        if not part: continue
        part=aliases.get(part,part)
        if not re.fullmatch(r'[A-Z0-9^][A-Z0-9.^=\-]{0,19}',part):
            raise ValueError('Send tickers such as MSFT or COMPARE MSFT NVDA.')
        if part not in symbols: symbols.append(part)
    if not 1<=len(symbols)<=5: raise ValueError('Send one to five tickers, for example MSFT NVDA.')
    return ','.join(symbols)


def telegram_summary(result):
    def pct(v): return 'N/A' if v is None else f'{v:+.2f}%'
    lines=[f"Stock analysis | {result['as_of']}", 'Yahoo Finance | latest completed session',result['basis'],'']
    for symbol,info in result['metadata'].items():
        lines.append(f"{symbol} ({info.get('currency') or 'currency unknown'})")
        lines.append(' | '.join(p+': '+pct(result['performance'][p][symbol].get('return_pct')) for p in result['performance']))
    if any(result['correlations'].values()):
        lines += ['', 'Return correlations (r; paired observations n):']
        for pair in result['correlations']['3Y']:
            lines.append(pair)
            lines.append(' | '.join(p+': '+('N/A' if r[pair]['r'] is None else f"{r[pair]['r']:.2f}")+f" (n={r[pair]['n']})" for p,r in result['correlations'].items()))
    lines += ['', '1W needs 10 paired returns; normally N/A. 1D uses US 5-minute returns.',
              'Historical data, not a forecast. No FX conversion.']
    return '\n'.join(lines)


def telegram_process(chat_id,symbols):
    result=get_stock_history(symbols,analysis=True)
    if result.get('error'):
        telegram_api('sendMessage',{'chat_id':chat_id,'text':'Stock data could not be retrieved. Check the tickers and try again later.'})
        return
    text=telegram_summary(result)
    # Respect Telegram's 4096-character limit without discarding results.
    for pos in range(0,len(text),3900):
        telegram_api('sendMessage',{'chat_id':chat_id,'text':text[pos:pos+3900]})
    for chart_info in result['charts']:
        chart_id,name=chart_info['url'].rsplit('/',2)[-2:]
        entry=charts.get(chart_id)
        content=entry[1].get(name.removesuffix('.png')) if entry else None
        if content:
            telegram_api('sendPhoto',{'chat_id':chat_id,'caption':chart_info['title']},
                         {'photo':(name,content,'image/png')})


def telegram_worker():
    while True:
        chat_id,symbols=telegram_queue.get()
        try:
            telegram_process(chat_id,symbols)
            telegram_status['completed']+=1
        except Exception:
            telegram_status['failed']+=1
            # Credentials, chat IDs and message contents must not appear in logs.
            try: telegram_api('sendMessage',{'chat_id':chat_id,'text':'The request could not finish. Please retry in a minute.'})
            except Exception: pass
        finally: telegram_queue.task_done()


def telegram_bootstrap():
    telegram_status['configured']=bool(os.getenv('TELEGRAM_BOT_TOKEN'))
    if not telegram_status['configured'] or not host: return
    threading.Thread(target=telegram_worker,daemon=True).start()
    for attempt in range(6):
        try:
            me=telegram_api('getMe')
            telegram_status['username']=me.get('username')
            telegram_api('setWebhook',{'url':'https://'+host+'/telegram/webhook',
                'secret_token':telegram_secret(),'allowed_updates':json.dumps(['message']),
                'max_connections':1})
            telegram_status['webhook_registered']=True
            return
        except Exception:
            time.sleep(min(5*(attempt+1),30))


def number(value):
    return round(float(value), 4) if pd.notna(value) and np.isfinite(value) else None


def calculate(prices, frames):
    """Exact daily analytics. Return dates define the correlation window."""
    offsets = {'1W': pd.DateOffset(weeks=1), '1M': pd.DateOffset(months=1),
               '3M': pd.DateOffset(months=3), '1Y': pd.DateOffset(years=1),
               '3Y': pd.DateOffset(years=3)}
    returns = prices.pct_change(fill_method=None)
    anchor = min(s.dropna().index[-1] for _, s in prices.items())
    metrics, correlations = {}, {}
    for period in ['1D', *offsets]:
        cutoff = anchor - offsets[period] if period != '1D' else None
        metrics[period] = {}
        for symbol, series in prices.items():
            s = series.dropna().loc[:anchor]
            baseline = s.iloc[-2:] if period == '1D' else s.loc[s.index <= cutoff].tail(1)
            if len(baseline) < (2 if period == '1D' else 1):
                metrics[period][symbol] = {'return_pct': None, 'reason': 'Insufficient baseline history'}
                continue
            window = s.loc[baseline.index[0]:anchor]
            daily_log = np.log(window).diff().dropna()
            frame = frames[symbol].reindex(window.index)
            factor = window / frame['close']
            metrics[period][symbol] = {
                'start': str(window.index[0].date()), 'end': str(window.index[-1].date()),
                'start_price': number(window.iloc[0]), 'end_price': number(window.iloc[-1]),
                'return_pct': number((window.iloc[-1]/window.iloc[0]-1)*100),
                'change': number(window.iloc[-1]-window.iloc[0]),
                'annualized_volatility_pct': number(daily_log.std(ddof=1)*np.sqrt(252)*100),
                'max_drawdown_pct': number((window/window.cummax()-1).min()*100),
                'high': number((frame['high']*factor).max()),
                'low': number((frame['low']*factor).min()),
                'average_volume': number(frame['volume'].mean()), 'observations': len(window)}
        correlations[period] = {}
        for a,b in itertools.combinations(prices.columns,2):
            pair = returns[[a,b]].loc[:anchor].dropna()
            pair = pair.iloc[0:0] if period == '1D' else pair.loc[pair.index > cutoff]
            enough = len(pair)>=10 and pair[a].std()>0 and pair[b].std()>0 and all(metrics[period][x].get('return_pct') is not None for x in (a,b))
            correlations[period][f'{a}/{b}'] = {'r': number(pair[a].corr(pair[b])) if enough else None,
                'n': len(pair), 'reason': None if enough else 'Requires 10 nonconstant paired returns; 1D needs intraday data'}
    return metrics, correlations, returns, anchor


def analyze(symbols, end):
    symbols = list(dict.fromkeys(x.strip().upper() for x in symbols.split(',')))
    if not 1 <= len(symbols) <= 5:
        raise ValueError('Provide one to five comma-separated tickers')
    today = datetime.now(timezone.utc).date()
    end_date = min(date.fromisoformat(end) if end else today+timedelta(days=1), today+timedelta(days=1))
    start = (pd.Timestamp(end_date)-pd.DateOffset(years=3)-pd.Timedelta(days=16)).date().isoformat()
    daily, metadata, intraday, warnings = {}, {}, {}, []
    for symbol in symbols:
        validate(symbol,start,end_date.isoformat(),'1d')
        data = fetch(symbol,start,end_date.isoformat(),'1d',int(time.time()//900))
        frame = pd.read_csv(io.StringIO(data['csv']),parse_dates=['timestamp']).set_index('timestamp')
        local = pd.Timestamp.now(tz=data.get('exchange_timezone') or 'UTC')
        # Conservative for non-US exchanges: use completed days only.
        us_closed = data.get('exchange') in ('NMS','NYQ','NGM','NCM','PCX','ASE') and (local.hour*60+local.minute>=16*60+15)
        if not us_closed:
            frame = frame.loc[frame.index.date < local.date()]
        if frame.empty: raise ValueError('No completed sessions for '+symbol)
        daily[symbol]=frame
        metadata[symbol]={k:data[k] for k in ('currency','exchange','exchange_timezone','retrieved_at_utc','company_name')}
    adjusted = all('adjusted_close' in f and f.adjusted_close.notna().all() and (f.adjusted_close>0).all() for f in daily.values())
    prices = pd.DataFrame({s:f['adjusted_close' if adjusted else 'close'] for s,f in daily.items()})
    metrics,corr,returns,anchor = calculate(prices,daily)
    for symbol in symbols:
        try:
            data=fetch(symbol,(anchor-pd.Timedelta(days=5)).date().isoformat(),(anchor+pd.Timedelta(days=1)).date().isoformat(),'5m',int(time.time()//900))
            f=pd.read_csv(io.StringIO(data['csv']))
            t=pd.to_datetime(f.timestamp,utc=True).dt.tz_convert(metadata[symbol]['exchange_timezone'] or 'UTC')
            # Explicit US regular-session scope; other exchanges unavailable for 1D correlation.
            if metadata[symbol]['exchange'] not in ('NMS','NYQ','NGM','NCM','PCX','ASE'):
                raise ValueError('Intraday regular-session filtering currently supports US stocks')
            mask=(t.dt.date==anchor.date()) & (t.dt.hour*60+t.dt.minute>=570) & (t.dt.hour*60+t.dt.minute<960)
            intraday[symbol]=pd.Series(f.loc[mask,'close'].to_numpy(), index=pd.DatetimeIndex(t[mask])).pct_change(fill_method=None)
        except Exception:
            warnings.append('1D intraday data unavailable for '+symbol)
    for a,b in itertools.combinations(symbols,2):
        pair=pd.concat([intraday.get(a,pd.Series(dtype=float)),intraday.get(b,pd.Series(dtype=float))],axis=1).dropna()
        enough=len(pair)>=10 and (pair.std()>0).all()
        corr['1D'][f'{a}/{b}']={'r':number(pair.iloc[:,0].corr(pair.iloc[:,1])) if enough else None,'n':len(pair),
                              'reason':None if enough else 'Insufficient synchronized intraday returns'}
    chart_id=hashlib.sha256((json.dumps(metadata,sort_keys=True)+str(end_date)).encode()).hexdigest()[:24]
    urls=[]
    public_base='https://'+host if host else 'http://localhost:'+os.getenv('PORT','8000')
    with chart_lock:
        images={}
        def save(fig,name):
            buf=io.BytesIO(); fig.savefig(buf,format='png',dpi=125,bbox_inches='tight'); plt.close(fig)
            images[name]=buf.getvalue(); urls.append({'title':name.replace('_',' '),'url':f'{public_base}/charts/{chart_id}/{name}.png'})
        shared=prices.loc[:anchor].dropna()
        if len(shared)>1:
            fig,ax=plt.subplots(figsize=(9,4)); (shared/shared.iloc[0]*100).plot(ax=ax)
            ax.set(title='Normalized performance — daily observations',ylabel='Index (first shared date = 100)',xlabel='Date'); ax.grid(alpha=.2); save(fig,'normalized_performance')
            fig,ax=plt.subplots(figsize=(9,4)); shared.plot(ax=ax)
            ax.set(title='Adjusted prices' if adjusted else 'Price history',ylabel='Price in each listing currency',xlabel='Date'); ax.grid(alpha=.2); save(fig,'price_history')
        if len(symbols)>1:
            matrix=np.full((len(symbols),len(symbols)),np.nan)
            for i,a in enumerate(symbols):
                matrix[i,i]=1
                for j,b in enumerate(symbols[i+1:],i+1): matrix[i,j]=matrix[j,i]=corr['3Y'][f'{a}/{b}']['r'] if corr['3Y'][f'{a}/{b}']['r'] is not None else np.nan
            fig,ax=plt.subplots(figsize=(5,4)); im=ax.imshow(np.ma.masked_invalid(matrix),vmin=-1,vmax=1,cmap='RdBu_r')
            ax.set_xticks(range(len(symbols)),symbols); ax.set_yticks(range(len(symbols)),symbols); ax.set_title('3Y daily return correlation (N/A if <10 pairs)')
            for i in range(len(symbols)):
                for j in range(len(symbols)): ax.text(j,i,f'{matrix[i,j]:.2f}' if np.isfinite(matrix[i,j]) else 'N/A',ha='center',va='center')
            fig.colorbar(im,ax=ax); save(fig,'correlation_heatmap')
            a,b=symbols[:2]; fig,ax=plt.subplots(figsize=(9,4))
            for n in (30,90):
                # Retain missing dates so a rolling window cannot skip missing returns.
                rolling=returns[a].rolling(n,min_periods=n).corr(returns[b]); ax.plot(rolling.index,rolling,label=f'{n} trading observations')
            ax.set(title=f'{a} / {b} rolling daily-return correlation',ylim=(-1,1),ylabel='Pearson r',xlabel='Date'); ax.legend(); ax.grid(alpha=.2); save(fig,'rolling_correlation')
            fig,ax=plt.subplots(figsize=(9,4))
            for pair in corr['3Y']:
                ax.plot(list(corr),[corr[p][pair]['r'] for p in corr],marker='o',label=pair)
            ax.set(title='Return correlation by period',ylim=(-1,1),ylabel='Pearson r (missing points = N/A)'); ax.legend(); ax.grid(alpha=.2); save(fig,'correlation_by_period')
        charts[chart_id]=(time.time(),images)
        while len(charts)>16: charts.pop(next(iter(charts)))
    return {'source':'Yahoo Finance via yfinance','as_of':str(anchor.date()),'metadata':metadata,
            'basis':'Provider split/dividend-adjusted close; dividend adjustment approximates reinvestment' if adjusted else 'Price returns',
            'methodology':'Exact daily observations; sample log-return volatility annualized sqrt(252); Pearson simple-return correlation; min 10 paired nonconstant returns. 1D correlations use 5m US regular-session returns.',
            'performance':metrics,'correlations':corr,'charts':urls,
            'limitations':warnings+['1W daily correlation is N/A with fewer than 10 returns.','No forecasts or causality. Historical results can change.','Different currencies are not FX-adjusted. Charts expire on restart or eviction.']}


def validate(symbol: str, start: str, end: str, interval: str):
    symbol = symbol.strip().upper()
    if not re.fullmatch(r'[A-Z0-9^][A-Z0-9.^=\-]{0,19}', symbol):
        raise ValueError('Use a ticker such as MSFT, NVDA, BRK-B, or ^GSPC.')
    if interval not in ('1d', '5m', '15m', '60m'):
        raise ValueError('interval must be 1d, 5m, 15m, or 60m')
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first >= last:
        raise ValueError('start must precede end; end is exclusive')
    if (last - first).days > (366 * 4 if interval == '1d' else 59):
        raise ValueError('Maximum range: 4 years daily or 59 days intraday')
    if interval != '1d' and first < datetime.now(timezone.utc).date() - timedelta(days=59):
        raise ValueError('Intraday requests must start within the last 59 days')
    return symbol


def encode(frame: pd.DataFrame, interval: str) -> str:
    if frame.empty:
        raise ValueError('Yahoo returned no observations; check ticker, dates, or provider availability')
    columns = {'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close',
               'Adj Close': 'adjusted_close', 'Volume': 'volume',
               'Dividends': 'dividends', 'Stock Splits': 'stock_splits'}
    out = frame.rename(columns=columns).copy()
    out = out.loc[~out.index.duplicated(keep='last')].sort_index()
    out = out.loc[pd.to_numeric(out['close'], errors='coerce').gt(0)]
    if out.empty:
        raise ValueError('No valid positive closing prices')
    # Never turn exchange-local daily sessions into UTC dates: that can shift dates.
    out.insert(0, 'timestamp', [x.strftime('%Y-%m-%d') if interval == '1d'
                             else x.isoformat() for x in out.index])
    selected = ['timestamp'] + [x for x in columns.values() if x in out.columns]
    return out[selected].to_csv(index=False, float_format='%.8g', na_rep='')


@lru_cache(maxsize=64)
def fetch(symbol: str, start: str, end: str, interval: str, cache_bucket: int) -> dict:
    # Serialize provider requests to limit bursts. Cache at most 64 results for 15m.
    with lock:
        ticker = yf.Ticker(symbol)
        frame = ticker.history(start=start, end=end, interval=interval,
                               auto_adjust=False, actions=True, raise_errors=True,
                               timeout=20)
        csv = encode(frame, interval)
        metadata = getattr(ticker, 'history_metadata', {}) or {}
    return {
        'symbol': symbol, 'source': 'Yahoo Finance via unofficial yfinance',
        'retrieved_at_utc': datetime.now(timezone.utc).isoformat(),
        'start_inclusive': start, 'end_exclusive': end, 'interval': interval,
        'currency': metadata.get('currency'),
        'exchange': metadata.get('exchangeName'),
        'exchange_timezone': metadata.get('exchangeTimezoneName'),
        'company_name': metadata.get('longName') or metadata.get('shortName'),
        'adjustment': 'Provider adjusted_close when supplied; close is provider-reported, not dividend-adjusted. Never assume raw pre-split prices.',
        'observations': len(csv.strip().splitlines()) - 1,
        'limitations': ['Unofficial source; personal/research use subject to Yahoo terms.',
                       'May be delayed, throttled, blocked, incomplete, or revised.',
                       'Latest bar may be incomplete. Check exchange session before using it.',
                       'Intraday adjusted_close may be unavailable; label price returns accordingly.'],
        'csv': csv,
    }


@mcp.tool()
def get_stock_history(symbol: str, start: str = '', end: str = '', interval: str = '1d', analysis: bool = False) -> dict:
    """Get real OHLCV history for ONE verified Yahoo ticker, without a provider key.

    RECOMMENDED: analysis=True with symbol='MSFT,NVDA' returns exact six-period
    metrics, return correlations and ready-to-display chart URLs. No raw series
    enter the model context. Omit start/end for the latest completed session.
    Render chart URLs as Markdown images. Supports up to five tickers.
    For raw data use analysis=False with ONE ticker and explicit ISO dates.
    ISO YYYY-MM-DD start inclusive, end exclusive. Daily: up to four years;
    intraday 5m/15m/60m: recent 59 days only. CSV text is data for Code Interpreter:
    parse it directly there; no internet fetch inside Code Interpreter is needed.
    Retrieve each stock daily from three years plus a 14-day baseline buffer ago.
    Retrieve recent intraday separately for 1D return correlations. Do not use
    this tool for ticker search or invent values on errors. An error is not data.
    """
    try:
        if analysis:
            return analyze(symbol,end)
        symbol = validate(symbol, start, end, interval)
        return fetch(symbol, start, end, interval, int(time.time() // 900))
    except Exception as exc:
        # Do not expose provider exception text or host details to callers.
        return {'error': type(exc).__name__,
                'message': str(exc) if isinstance(exc, ValueError) else
                'Historical data retrieval failed. Yahoo may be throttling/blocking this host. Retry later or upload CSV.',
                'symbol': symbol, 'csv': None}


@mcp.custom_route('/health', methods=['GET'])
async def health(request):
    return JSONResponse({'status': 'ok', 'service': 'yahoo-stock-mcp','telegram':telegram_status})


@mcp.custom_route('/telegram/webhook', methods=['POST'])
async def telegram_webhook(request):
    expected=telegram_secret()
    if not expected or not hmac.compare_digest(request.headers.get('X-Telegram-Bot-Api-Secret-Token',''),expected):
        return Response('Forbidden',status_code=403)
    try: content_length=int(request.headers.get('content-length','0'))
    except ValueError: return Response('Invalid content length',status_code=400)
    if content_length>16384:
        return Response('Too large',status_code=413)
    raw=await request.body()
    if len(raw)>16384: return Response('Too large',status_code=413)
    try: update=json.loads(raw)
    except (ValueError,TypeError): return Response('Invalid JSON',status_code=400)
    if not isinstance(update,dict): return Response('Invalid update',status_code=400)
    update_id=update.get('update_id')
    message=update.get('message',{})
    if not isinstance(message,dict): return JSONResponse({'ok':True})
    chat=message.get('chat',{})
    if not isinstance(chat,dict): return JSONResponse({'ok':True})
    chat_id=chat.get('id')
    if not isinstance(update_id,int) or not isinstance(chat_id,int) or chat.get('type')!='private':
        return JSONResponse({'ok':True})
    allowed=os.getenv('TELEGRAM_ALLOWED_CHAT_IDS','').strip()
    if allowed and str(chat_id) not in {x.strip() for x in allowed.split(',')}:
        return JSONResponse({'ok':True})
    text=message.get('text','')
    if not isinstance(text,str) or len(text)>250:
        return JSONResponse({'method':'sendMessage','chat_id':chat_id,'text':'Send one to five stock tickers, such as MSFT NVDA.'})
    now=time.time()
    with telegram_state_lock:
        for old,stamp in list(telegram_seen.items()):
            if now-stamp>86400: telegram_seen.pop(old,None)
        if update_id in telegram_seen: return JSONResponse({'ok':True})
        telegram_seen[update_id]=now
        while len(telegram_seen)>1000: telegram_seen.pop(next(iter(telegram_seen)))
        if len(telegram_last)>1000:
            for key,stamp in list(telegram_last.items()):
                if now-stamp>60: telegram_last.pop(key,None)
    command=text.split('@')[0].strip().lower()
    if command in ('/start','/help'):
        return JSONResponse({'method':'sendMessage','chat_id':chat_id,
            'text':'Send MSFT, NVIDIA, or COMPARE MSFT NVDA. I return six-period performance, return correlations, and chart images. Up to five tickers; one analysis per minute. Uses latest completed sessions, not live trading quotes. Historical data is not investment advice.'})
    try: symbols=parse_telegram(text)
    except ValueError as exc:
        return JSONResponse({'method':'sendMessage','chat_id':chat_id,'text':str(exc)})
    with telegram_state_lock:
        if now-telegram_last.get(chat_id,0)<60:
            return JSONResponse({'method':'sendMessage','chat_id':chat_id,'text':'Please wait one minute between analyses.'})
        try: telegram_queue.put_nowait((chat_id,symbols))
        except queue.Full:
            return JSONResponse({'method':'sendMessage','chat_id':chat_id,'text':'The bot is busy. Please retry in a minute.'})
        telegram_last[chat_id]=now
        telegram_status['received']+=1
    return JSONResponse({'method':'sendMessage','chat_id':chat_id,'text':'Retrieving stock data and generating your charts. This may take a minute.'})


@mcp.custom_route('/charts/{chart_id}/{name}.png', methods=['GET'])
async def chart(request):
    item=charts.get(request.path_params['chart_id'])
    name=request.path_params['name']
    if not item or time.time()-item[0]>3600 or name not in item[1]:
        return Response('Chart expired. Run the analysis again.',status_code=404)
    return Response(item[1][name],media_type='image/png',headers={'Cache-Control':'public, max-age=900'})


if __name__ == '__main__':
    threading.Thread(target=telegram_bootstrap,daemon=True).start()
    mcp.run(transport='streamable-http')
