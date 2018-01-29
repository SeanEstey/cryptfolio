# views.py
import logging, curses
from datetime import datetime
from dateutil import tz
from app import db, analyze
from app.timer import Timer
from config import *
from config import CURRENCY as cur
from app.screen import c, printrow, pretty, pnlcolor, _colsizes, divider, navmenu
from app.analyze import mcap_diff
localtz = tz.tzlocal()
log = logging.getLogger(__name__)

#----------------------------------------------------------------------
def history(stdscr, symbol):
    log.info("Querying %s ticker history", symbol)

    n_display = 95
    colspace=3
    indent=2
    hdr = ['Date', 'Open', 'High', 'Low', 'Close', 'Market Cap', 'Vol 24h']

    t1 = Timer()
    tickerdata = db.tickers.historical.find({"symbol":symbol}).sort('date',-1).limit(n_display)
    n_datarows = tickerdata.count()
    log.debug("%s tickers queried in %sms", tickerdata.count(), t1.clock(t='ms'))

    if tickerdata.count() == 0:
        log.info("No ticker history found for %s", symbol)
        return False
    strrows=[]
    for tck in tickerdata:
        strrows.append([
            tck['date'].strftime("%m-%d-%Y"),
            pretty(tck['open'], t="money"),
            pretty(tck['high'], t="money"),
            pretty(tck['low'], t="money"),
            pretty(tck['close'], t="money"),
            pretty(tck['mktcap_usd'], t="money", abbr=True),
            pretty(tck['vol_24h_usd'], t="money", abbr=True)
        ])
    colwidths = _colsizes(hdr, strrows)

    stdscr.clear()
    stdscr.addstr(0, indent, "%s History" % symbol)
    navmenu(stdscr)
    printrow(stdscr, 2, hdr, colwidths, [c.WHITE for n in hdr], colspace)
    divider(stdscr, 3, colwidths, colspace)
    for i in range(0, len(strrows)):
        colors = [c.WHITE for n in range(0,7)]
        printrow(stdscr, i+4, strrows[i], colwidths, colors, colspace)

    n_rem_scroll = n_datarows - (curses.LINES - 4)
    log.info("n_datarows=%s, n_rem_scroll=%s", n_datarows, n_rem_scroll)
    return n_rem_scroll

#----------------------------------------------------------------------
def markets(stdscr):
    log.info('Markets view')
    colspace=3
    indent=2
    hdr = ['Market Cap', '24h Vol', 'BTC Cap %', 'Markets', 'Currencies', 'Assets', '1h', '24h', '7d']

    mktdata = list(db.market.find().limit(1).sort('date',-1))
    if len(mktdata) == 0:
        log.info("db.market empty")
        return False

    strrows=[]
    for mkt in mktdata:
        strrows.append([
            pretty(mkt['mktcap_cad'], t="money", abbr=True),
            pretty(mkt['vol_24h_cad'], t="money", abbr=True),
            pretty(mkt['pct_mktcap_btc'], t="pct"),
            pretty(mkt['n_markets']),
            pretty(mkt['n_currencies']),
            pretty(mkt['n_assets']),
            pretty(analyze.mcap_diff('1H', convert='pct'), t="pct", f="sign"),
            pretty(analyze.mcap_diff('24H', convert='pct'), t="pct", f="sign"),
            pretty(analyze.mcap_diff('7D', convert='pct'), t="pct", f="sign")
        ])
    colwidths = _colsizes(hdr, strrows)

    stdscr.clear()
    # Print Title row
    stdscr.addstr(0, indent, "Global (%s)" % cur.upper())
    navmenu(stdscr)
    dt = mktdata[0]["date"].astimezone(localtz).strftime("%I:%M %p")
    stdscr.addstr(0, stdscr.getmaxyx()[1] - len(dt) -2, dt)
    # Print Datatable
    printrow(stdscr, 2, hdr, colwidths, [c.WHITE for n in hdr], colspace)
    divider(stdscr, 3, colwidths, colspace)
    for i in range(0, len(strrows)):
        row = strrows[i]
        colors = [c.WHITE for n in range(0,6)] + [pnlcolor(row[n]) for n in range(6,9)]
        printrow(stdscr, i+4, row, colwidths, colors, colspace)

#----------------------------------------------------------------------
def watchlist(stdscr):
    log.info('Watchlist view')
    hdr = ["Rank", "Sym", "Price", "Market Cap", "24h Vol", "1h", "24h", "7d"]
    indent=2
    colspace=3
    watchlist = db.watchlist.find()
    tickers = list(db.tickers.find())

    if len(tickers) == 0:
        log.error("coinmktcap collection empty")
        return False

    strrows = []
    for watch in watchlist:
        for tckr in tickers:
            if tckr['id'] != watch['id']:
                continue
            strrows.append([
                tckr["rank"],
                tckr["symbol"],
                pretty(tckr["price_cad"], t='money'),
                pretty(tckr["mktcap_cad"], t='money', abbr=True),
                pretty(tckr["vol_24h_cad"], t='money', abbr=True),
                pretty(tckr["pct_1h"], t='pct', f='sign'),
                pretty(tckr["pct_24h"], t='pct', f='sign'),
                pretty(tckr["pct_7d"], t='pct', f='sign')
            ])
    colwidths = _colsizes(hdr, strrows)
    strrows = sorted(strrows, key=lambda x: int(x[0])) #[::-1]
    stdscr.clear()

    # Print Title row
    stdscr.addstr(0, indent, "Watchlist (%s)" % cur.upper())
    navmenu(stdscr)
    dt = tickers[0]["date"].astimezone(localtz).strftime("%I:%M %p")
    stdscr.addstr(0, stdscr.getmaxyx()[1] - len(dt) -2, dt)

    # Print Datatable
    printrow(stdscr, 2, hdr, colwidths, [c.WHITE for n in hdr], colspace)
    divider(stdscr, 3, colwidths, colspace)
    for n in range(0, len(strrows)):
        row = strrows[n]
        colors = [c.WHITE, c.WHITE, c.WHITE, c.WHITE, c.WHITE, pnlcolor(row[5]), pnlcolor(row[6]), pnlcolor(row[7])]
        printrow(stdscr, n+4, row, colwidths, colors, colspace)

#-----------------------------------------------------------------------------
def portfolio(stdscr):
    log.info('Portfolio view')
    hdr = ['Rank', 'Sym', 'Price', 'Mcap', 'Vol 24h', 'Amount', 'Value', '%/100', '1h', '24h', '7d']
    indent = 2
    total = 0.0
    profit = 0
    datarows = []

    # Print title Row
    stdscr.clear()
    stdscr.addstr(0, indent, "Portfolio (%s)" % cur.upper())
    navmenu(stdscr)

    portfolio = db.portfolio.find()

    # Build table data
    tickers = list(db.tickers.find())
    for hold in portfolio:
        for tckr in tickers:
            if tckr['symbol'] != hold['symbol']:
                continue

            value = round(hold['amount'] * tckr['price_cad'], 2)
            profit += (tckr['pct_24h']/ 100) * value if tckr['pct_24h'] else 0.0
            total += value

            datarows.append([
                tckr['rank'], tckr['symbol'], round(tckr['price_cad'],2), tckr['mktcap_cad'], tckr["vol_24h_cad"],
                hold['amount'], value, None, tckr["pct_1h"], tckr["pct_24h"], tckr["pct_7d"]

            ])

    # Calculate porfolio %
    for datarow in datarows:
        datarow[7] = round((float(datarow[6]) / total)*100, 2)
    # Sort by holding %
    datarows = sorted(datarows, key=lambda x: int(x[6]))[::-1]

    strrows = []
    for datarow in datarows:
        strrows.append([
            datarow[0],
            datarow[1],
            pretty(datarow[2], t='money'),
            pretty(datarow[3], t='money', abbr=True),
            pretty(datarow[4], t='money', abbr=True),
            pretty(datarow[5], abbr=True),
            pretty(datarow[6], t='money'),
            pretty(datarow[7], t='pct'),
            pretty(datarow[8], t='pct', f='sign'),
            pretty(datarow[9], t='pct', f='sign'),
            pretty(datarow[10], t='pct', f='sign')
        ])
    colwidths = _colsizes(hdr, strrows)


    dt = tickers[0]["date"].astimezone(localtz).strftime("%I:%M %p")
    stdscr.addstr(0, stdscr.getmaxyx()[1] - len(dt) -2, dt)

    # Print Datatable
    colspace=2
    printrow(stdscr, 2, hdr, colwidths, [c.WHITE for n in hdr], colspace=colspace)
    divider(stdscr, 3, colwidths, colspace)
    for y in range(0,len(strrows)):
        strrow = strrows[y]
        colors = [c.WHITE for x in range(0,8)] + [pnlcolor(strrow[n]) for n in range(8,11)]
        printrow(stdscr, y+4, strrow, colwidths, colors, colspace=colspace)

    # Portfolio value ($)
    printrow(
        stdscr,
        stdscr.getyx()[0]+2,
        [ "Total: ", pretty(total, t='money'), ' (', pretty(int(profit), t="money", f='sign', d=0), ')' ],
        [ 0,0,0,0,0 ],
        [ c.WHITE, c.BOLD, c.WHITE, pnlcolor(profit), c.WHITE ])