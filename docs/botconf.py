"""botconf.py

Settings for formatting/subscribing to API data and trading bot.
"""

# Max simultaneous open trades
max_positions = 10

# Trade pairs for Binance WSS client to subcribe
trade_pairs = [
    'ADABTC',
    'AIONBTC',
    #'BNBBTC',
    #'BTCUSDT',
    #'DGDBTC',
    #'DNTBTC',
    'ELFBTC',
    'ETHUSDT',
    'FUNBTC',
    'EOSBTC',
    #'ENJBTC',
    'ICXBTC',
    'LRCBTC',
    #'ONTBTC',
    'OSTBTC',
    #'SALTBTC',
    #'XVGBTC',
    #'WANBTC',
    'WTCBTC',
    'ZILBTC'
]

### Trade Algorithms ###########################################################
# It's possible to have any number of simultaneously running strategies, with
# any config/callback combination. "name" is used as the primary key.
################################################################################
strategies = [
    {
        "name": "macd_1h_mean",
        "ema": (12, 26, 9),
        "stop_loss": {
            "freq": ["1h"],
            "pct": -0.75
        },
        "entry": {
            "filters": [lambda c, ss: c['freq'] in ['1h']],
            "conditions": [
                lambda c,ss: ss['macd']['value'] > 0,
                lambda c,ss: ss['macd']['value'] == ss['macd']['desc']['max'],
                lambda c,ss: ss['macd']['trend'] == 'UPWARD'
            ]
        },
        "exit": {
            "filters": [lambda c, ss, doc: c['freq'] in ['1h']],
            "conditions": [
                lambda c,ss,doc: ss['macd']['value'] < 0,
                lambda c,ss,doc: ss['macd']['value'] < ss['macd']['desc']['mean']
            ]
        }
    },
    {
        "name": "macd_5m_max",
        "ema": (12, 26, 9),
        "stop_loss": {
            "freq": ["1m", "5m"],
            "pct": -0.75
        },
        "entry": {
            "filters": [lambda c, ss: c['freq'] in ['5m']],
            "conditions": [
                lambda c,ss: ss['macd']['value'] > 0,
                lambda c,ss: ss['macd']['value'] == ss['macd']['desc']['max'],
                lambda c,ss: ss['macd']['trend'] == 'UPWARD'
            ]
        },
        "exit": {
            "filters": [lambda c, ss, doc: c['freq'] in ['5m']],
            "conditions": [
                lambda c,ss,doc: ss['macd']['value'] < 0,
                lambda c,ss,doc: ss['macd']['value'] < ss['macd']['desc']['max']
            ]
        }
    },
    {
        "name": "macd_5m_mean",
        "ema": (12, 26, 9),
        "stop_loss": {
            "freq": ['1m', '5m'],
            "pct": -0.75
        },
        "entry": {
            "filters": [lambda c, ss: c['freq'] in ['5m']],
            "conditions": [
                lambda c,ss: ss['macd']['value'] > 0,
                lambda c,ss: ss['macd']['value'] == ss['macd']['desc']['max'],
                lambda c,ss: ss['macd']['trend'] == 'UPWARD'
            ]
        },
        "exit": {
            "filters": [lambda c, ss, doc: c['freq'] in ['5m']],
            "conditions": [
                lambda c,ss,doc: ss['macd']['value'] < 0,
                lambda c,ss,doc: ss['macd']['value'] < ss['macd']['desc']['mean']
            ]
        }
    },
    {
        "name": "macd_5m_uptrend",
        "ema": (12, 26, 9),
        "stop_loss": {
            "freq": ['1m', '5m'],
            "pct": -0.75
        },
        "entry": {
            "filters": [lambda c, ss: c['freq'] in ['5m']],
            "conditions": [
                lambda c,ss: ss['macd']['value'] > 0,
                lambda c,ss: ss['macd']['value'] == ss['macd']['desc']['max'],
                lambda c,ss: ss['macd']['trend'] == 'UPWARD'
            ]
        },
        "exit": {
            "filters": [lambda c, ss, doc: c['freq'] in ['5m']],
            "conditions": [
                lambda c,ss,doc: ss['macd']['value'] < 0,
                lambda c,ss,doc: ss['macd']['trend'] == 'DOWNWARD'
            ]
        }
    }
]