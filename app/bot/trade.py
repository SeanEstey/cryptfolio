# app.bot.trade
import time
import itertools
import threading
import sys
import logging
import pytz
from pprint import pformat
import inspect
import numpy as np
import pandas as pd
from pprint import pprint
from collections import OrderedDict as odict
from requests import ConnectionError
from binance.client import BinanceRequestException
from docs.conf import *
from docs.botconf import *
import app, app.bot
from app.bot import lock, get_pairs, set_pairs, candles, macd, reports, signals
from app.common.timeutils import strtofreq
from app.common.utils import pct_diff, utc_datetime as now
from app.common.timer import Timer

spinner = itertools.cycle(['-', '/', '|', '\\'])
log = logging.getLogger('trade')
dfW = pd.DataFrame()
start = now()

#---------------------------------------------------------------------------
def run(e_pairs, e_kill):
    """Main trading loop thread. Consumes candle data from queue and
    manages/executes trades.
    TODO: add in code for tracking unclosed candle wicks prices:
        # Clear all partial candle data
        dfW = dfW.drop([(c['pair'], strtofreq(c['freqstr']))])
    """
    from main import q
    db = app.get_db()
    t1 = Timer()
    tmr1 = Timer(name='pos', expire='every 1 clock min utc', quiet=True)
    tmr10 = Timer(name='earn', expire='every 10 clock min utc', quiet=True)

    reports.positions()
    reports.earnings()

    n = 0
    while True:
        if e_kill.isSet():
            break
        ent_ids, ex_ids = [], []

        # Trading algo inner loop.
        while q.empty() == False:
            c = q.get()
            candles.modify_dfc(c)
            ss = snapshot(c)
            query = {'pair':c['pair'], 'freqstr':c['freqstr'], 'status':'open'}

            # Eval position entries/exits

            for trade in db.trades.find(query):
                update_stats(trade, ss)
                ex_ids += eval_exit(trade, c, ss)

            if c['closed'] and c['pair'] in get_pairs():
                ent_ids += eval_entry(c, ss)

            n+=1

        # Reporting outer loop.
        if tmr1.remain() == 0:
            reports.positions()
            tmr1.reset()
        if tmr10.remain() == 0:
            reports.earnings()
            tmr10.reset()
        if len(ent_ids) + len(ex_ids) > 0:
            reports.trades(ent_ids + ex_ids)
        if n>75:
            lock.acquire()
            print('{} queue items processed. [{:,.0f} ms/item]'\
                .format(n, t1.elapsed()/n))
            lock.release()
            t1.reset()
            n=0

        # Outer loop tail
        if len(ex_ids) > 0:
            if c['pair'] not in get_pairs():
                # TODO: check no other open positions hold this pair, safe
                # for disabling.
                set_pairs([c['pair']], 'DISABLED')
        update_spinner()
        time.sleep(0.1)

    print('Trade thread: Terminating...')

#------------------------------------------------------------------------------
def eval_entry(c, ss):
    """
    @c: candle dict
    @ss: snapshot dict
    """
    db = app.get_db()
    ids = []
    for algo in TRD_ALGOS:
        if db.trades.find_one(
            {'freqstr':c['freqstr'], 'algo':algo['name'], 'status':'open'}):
            continue

        # Test conditions eval to True
        try:
            if all([fn(ss['indicators']) for fn in algo['entry']['conditions']]):
                ids.append(buy(ss, algo))
        except Exception as e:
            print("Error evaluating entry conditions. {}".format(str(e)))

    return ids

#------------------------------------------------------------------------------
def eval_exit(t, c, ss):
    """
    @t: trade document dict
    @s: candle dict
    @ss: snapshot dict
    """
    algo = [n for n in TRD_ALGOS if n['name'] == t['algo']][0]

    # Stop loss.
    diff = pct_diff(t['snapshots'][0]['candle']['close'], c['close'])
    if diff < algo['stoploss']:
        return [sell(t, ss, 'stoploss')]

    try:
        # Target (success)
        if all([fn(ss['indicators'], t['stats']) for fn in algo['target']['conditions']]):
            return [sell(t, ss, 'target')]

        # Failure
        if all([fn(ss['indicators'], t['stats']) for fn in algo['failure']['conditions']]):
            return [sell(t, ss, 'failure')]
    except Exception as e:
        print("Error evaluating exit conditions. {}".format(str(e)))

    return []

#------------------------------------------------------------------------------
def buy(ss, algo):
    """Open new position, insert record to DB.
    @ss: snapshot dict
    @algo: algorithm definition dict
    """
    db, client = app.db, app.bot.client

    if ss['book'] is None:
        book = odict(client.get_orderbook_ticker(symbol=ss['pair']))
        del book['symbol']
        [book.update({k:np.float64(v)}) for k,v in book.items()]
        ss['book'] = book

    record = odict({
        'pair': ss['pair'],
        'quote_asset': db.assets.find_one({'symbol':ss['pair']})['quoteAsset'],
        'freqstr': ss['candle']['freqstr'],
        'status': 'open',
        'start_time': now(),
        'algo': algo['name'],
        'stoploss': algo['stoploss'],
        'snapshots': [ss],
        'stats': {},
        'details': [{
            'algo': algo['name'],
            'section': 'entry',
            'desc': algo_to_string(algo['name'], 'entry')
        }],
        'orders': [odict({
            'action':'BUY',
            'ex': 'Binance',
            'time': now(),
            'price': ss['book']['askPrice'],
            'volume': 1.0,
            'quote': TRD_AMT_MAX,
            'fee': TRD_AMT_MAX * (BINANCE_PCT_FEE/100)
        })]
    })

    result = db.trades.insert_one(record)
    update_stats(record, ss)

    lock.acquire()
    print("BUY {} ({})".format(ss['pair'], algo['name']))
    lock.release()

    return result.inserted_id

#------------------------------------------------------------------------------
def sell(trade, ss, section):
    """Close off existing position and calculate earnings.
    @trade: db trade document dict
    @ss: snapshot dict
    @section: key name of evaluated algo conditions
    """
    db, client = app.db, app.bot.client

    # Algorithm criteria details
    algo = [n for n in TRD_ALGOS \
        if n['name'] == trade['algo']][0]
    details = {
        'name': algo['name'],
        'section': section
    }
    if section == 'stoploss':
        details.update({'desc':algo['stoploss']})
    else:
        details.update({'desc':algo_to_string(algo['name'], section)})

    # Get orderbook if not already stored in snapshot.
    if ss['book'] is None:
        try:
            book = odict(client.get_orderbook_ticker(symbol=trade['pair']))
        except (BinanceRequestException, ConnectionError) as e:
            log.debug(str(e))
            lock.acquire()
            print("Error acquiring orderbook. Sell failed.")
            lock.release()
            return []

        del book['symbol']
        [book.update({k:np.float64(v)}) for k,v in book.items()]
        ss['book'] = book

    # Profit/loss calculations.
    pct_fee = BINANCE_PCT_FEE
    bid = ss['book']['bidPrice']
    ask = ss['book']['askPrice']
    buy_vol = np.float64(trade['orders'][0]['volume'])
    buy_quote = np.float64(trade['orders'][0]['quote'])
    p1 = np.float64(trade['orders'][0]['price'])

    pct_gain = pct_diff(p1, bid)
    quote = buy_quote * (1 - pct_fee/100)
    fee = (bid * buy_vol) * (pct_fee/100)
    pct_net_gain = net_earn = pct_gain - (pct_fee*2)
    duration = now() - trade['start_time']

    db.trades.update_one(
        {'_id': trade['_id']},
        {
            '$push': {
                'snapshots':ss,
                'details': details,
                'orders': odict({
                    'action': 'SELL',
                    'ex': 'Binance',
                    'time': now(),
                    'price': bid,
                    'volume': 1.0,
                    'quote': buy_quote,
                    'fee': fee
                })
            },
            '$set': {
                'status': 'closed',
                'end_time': now(),
                'duration': int(duration.total_seconds()),
                'pct_gain': pct_gain.round(4),
                'pct_net_gain': pct_net_gain.round(4)
            }
        }
    )

    lock.acquire()
    print("SELL {} ({}) Details: {}. {}"\
        .format(trade['pair'], details['name'],
            details['section'].title(), details['desc']))
    lock.release()
    return trade['_id']

#------------------------------------------------------------------------------
def snapshot(c):
    """Gather state of trade--candle, indicators--each tick and save to DB.
    """
    global dfW
    book = None
    wick_slope = macd_value = amp_slope = np.nan
    pair, freqstr = c['pair'], c['freqstr']

    buyratio = (c['buy_vol']/c['volume']) if c['volume'] > 0 else 0.0

    # MACD Indicators
    dfm_dict = {}
    df = app.bot.dfc.loc[pair, strtofreq(freqstr)]

    try:
        dfmacd, phases = macd.histo_phases(df, pair, freqstr, 100, to_bson=True)
    except Exception as e:
        lock.acquire()
        print('snapshot exc')
        print(str(e))
        lock.release()

    if len(dfmacd) < 1:
        dfm_dict['bars'] = 0
    else:
        dfm_dict = dfmacd.iloc[-1].to_dict()
        dfm_dict['bars'] = int(dfm_dict['bars'])
        macd_value = phases[-1].iloc[-1]
        amp_slope = phases[-1].diff().ewm(span=min(3,len(phases[-1])), min_periods=0).mean().iloc[-1]

    if c['closed']:
        # Find price EMA WITHIN the wick (i.e. each trade). Very
        # small movements.
        #prices = dfW.loc[c['pair'], c['freqstr']]['close']
        #wick_slope = prices.diff().ewm(span=len(prices)).mean().iloc[-1]
        # FIXME
        wick_slope = 0.0

    return {
        'pair': pair,
        'time': now(),
        'book': None,
        'candle': c,
        'indicators': {
            'buyRatio': round(buyratio, 2),
            'rsi': signals.rsi(df['close'].tail(100), 14),
            'wickSlope': wick_slope,
            'zscore': signals.zscore(df['close'], c['close'], 21),
            'macd': {
                **dfm_dict,
                **{'ampSlope':round(amp_slope,2),
                  'value':round(macd_value,2)
                  }
            }
        }
    }

#------------------------------------------------------------------------------
def update_stats(t, ss):
    """Track min/max key indicator ranges across trade lifetime.
    Snapshots in trade record only cover state at each candle close. This
    method allows us to capture the highs/lows in-between.
    @t: trade record dict
    @ss: snapshot dict (from closed or unclosed candle)
    """
    keys = {
        "buy_ratio":       lambda ss: round(ss['indicators']['buyRatio'],2),
        "macd":            lambda ss: round(ss['indicators']['macd']['value'],2),
        "macd_amp_slope":  lambda ss: round(ss['indicators']['macd']['ampSlope'],2),
        "rsi":             lambda ss: round(ss['indicators']['rsi'],0),
        "wick_slope":      lambda ss: round(ss['indicators']['wickSlope'],2),
        "zscore" :         lambda ss: round(ss['indicators']['zscore'],2),
        "price":           lambda ss: ss['candle']['close']
    }
    snaps = t['snapshots'] + [ss]
    stats = odict()

    # Find Min, Max, and Last values for every indicator in trade history.
    for k,fn in keys.items():
        min_k = "min{}".format(k.title().replace('_',''))
        stats[min_k] = min([fn(ss) for ss in snaps])

        max_k = "max{}".format(k.title().replace('_',''))
        stats[max_k] = max([fn(ss) for ss in snaps])

        last_k = "last{}".format(k.title().replace('_',''))
        stats[last_k] = fn(ss)

    update = {'$set': {'stats':stats}}

    if ss['candle']['closed'] is True:
        update['$push'] = {'snapshots':ss}

    app.db.trades.update_one({'_id':t['_id']}, update)
    return stats

#------------------------------------------------------------------------------
def algo_to_string(name, section):
    algo = [n for n in TRD_ALGOS if n['name'] == name][0]
    conditions = algo[section]['conditions']

    funcstrs = []
    for func in conditions:
        fstr = str(inspect.getsourcelines(func)[0])
        fstr = fstr.strip("['\\n']").split(":")[1]
        fstr = fstr.strip('\\n"').strip()
        funcstrs.append(fstr)

    return funcstrs

#-------------------------------------------------------------------------------
def update_spinner():
    msg = 'listening %s' % next(spinner)
    lock.acquire()
    sys.stdout.write(msg)
    sys.stdout.flush()
    sys.stdout.write('\b'*len(msg))
    lock.release()
