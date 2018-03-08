# tests/testing.py

import os,sys,inspect
currentdir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
parentdir = os.path.dirname(currentdir)
sys.path.insert(0,parentdir)
import logging
import time
from pprint import pprint
from importlib import reload
from datetime import timedelta, datetime
import pandas as pd
import numpy as np

import app
from app import signals
from app.timer import Timer
from app.utils import utc_datetime, utc_dtdate

log = logging.getLogger("testing")
pd.set_option("display.max_columns", 25)
pd.set_option("display.width", 2000)
hosts = ["localhost", "45.79.176.125"]
app.set_db(hosts[0])
db = app.get_db()

dfa = signals.calculate_all()
#df = show_signals()
#dfp = signals.load_db_pairs()
#dfa = signals.load_db_aggregate()


