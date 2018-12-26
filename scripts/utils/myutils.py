from concurrent.futures import ThreadPoolExecutor

from scripts.utils.mylogger import mylogger
from scripts.utils.pythonRedis import LoadType, RedisStorage
from scripts.utils.pythonCassandra import PythonCassandra
from scripts.streaming.streamingDataframe import StreamingDataframe as SD

import pandas as pd
from os.path import join, dirname
from pandas.api.types import is_string_dtype
from datetime import datetime, date
import dask as dd
from bokeh.models import Panel
from bokeh.models.widgets import Div
import numpy as np
from tornado.gen import coroutine
import gc
import calendar
from time import mktime

logger = mylogger(__file__)
executor = ThreadPoolExecutor(max_workers=5)


def mem_usage(pandas_obj):
    if isinstance(pandas_obj,pd.DataFrame):
        usage_b = pandas_obj.memory_usage(deep=True).sum()
    else: # we assume if not a df it's a series
        usage_b = pandas_obj.memory_usage(deep=True)
    usage_mb = usage_b / 1024 ** 2 # convert bytes to megabytes
    return "{:03.2f} MB".format(usage_mb)

def optimize_dataframe(df,timestamp_col='block_timestamp'):
    dtypes = df.drop(timestamp_col, axis=1).dtypes
    dtypes_col = dtypes.index
    dtypes_type = [i.name for i in dtypes.values]
    column_types = dict(zip(dtypes_col, dtypes_type))

    df_read_and_optimized = pd.read_csv(join(dirname(__file__),
                                             '../../data', 'blockdetails.csv'),
                                             dtype=column_types, parse_dates=['block_timestamp'],
                                             infer_datetime_format=True)

    return df_read_and_optimized


def convert_block_timestamp_from_string(df,col):
    if is_string_dtype(df[col]):
        df[col] = df[col].apply(int)
        df[col] = pd.Timestamp(df[col])
    return df


def setdatetimeindex(df):
    # set timestamp as index
    meta = ('block_timestamp', 'datetime64[ns]')
    df['block_timestamp'] = df['block_timestamp']
    df['block_timestamp'] = df.block_timestamp\
        .map_partitions(pd.to_datetime, unit='s',
                                        format="%Y-%m-%d %H:%M:%S",
                                        meta=meta)
    df = df.set_index('block_timestamp')
    return df


def get_breakdown_from_timestamp(ts):
    ns = 1e-6
    mydate = datetime.fromtimestamp(ts).date()
    return mydate

def get_initial_blocks(pc):
    try:
        to_check = tuple(range(0, 50000))
        qry ="""SELECT block_number, difficulty, block_date, 
            block_time, miner_addr FROM block
            WHERE block_number in """+str(to_check)

        df = pd.DataFrame(list(pc.session.execute(qry)))
        df = dd.dataframe.from_pandas(df, npartitions=15)
        #logger.warning('from get initial block: %s',df.head(5))
        return df
    except Exception:
        logger.error('get initial blocks',exc_info=True)


def timestamp_to_datetime(ts):
    return datetime.fromtimestamp(ts)


# when a tab does not work
def tab_error_flag(tabname):

    # Make a tab with the layout
    text = """ERROR CREATING {} TAB, 
    CHECK THE LOGS""".format(tabname.upper())
    div = Div(text=text,
              width=200, height=100)

    tab = Panel(child=div, title=tabname)

    return tab


# convert dates from timestamp[ms] to datetime[ns]
def ms_to_date(ts):
    try:
        if isinstance(ts, int) == True:
            # change milli to seconds
            if ts > 16307632000:
                ts = ts // 1000
            ts = datetime.utcfromtimestamp(ts)
            # convert to nanosecond representation
            ts = np.datetime64(ts).astype(datetime)
            ts = pd.Timestamp(datetime.date(ts))

            logger.warning('from ms_to_date: %s',ts)
        return ts
    except Exception:
        logger.error('ms_to_date', exc_info=True)
        return ts


# nano_secs_to_date
def ns_to_date(ts):
    ns = 1e-9
    try:
        ts = datetime.utcfromtimestamp(ts * ns)
        ts = pd.Timestamp(datetime.date(ts))
        return ts
    except Exception:
        logger.error('ns_to_date', exc_info=True)
        return ts

# date time to ms
def date_to_ms(ts):
    if isinstance(ts, str):
        ts = datetime.strptime(ts, '%Y-%m-%d')

    ts = int(ts.timestamp())
    return ts



#convert ms to string date
def slider_ts_to_str(ts):
    # convert to datetime if necessary
    if isinstance(ts,int) == True:
        ts = ms_to_date(ts)

    ts = datetime.strftime(ts,'%Y-%m-%d')
    return ts


#
# check to see if the current data is within the active dataset
def set_params_to_load(df, req_start_date, req_end_date):
    try:
        if isinstance(req_start_date, int):
            req_start_date = ms_to_date(req_start_date)
            req_end_date = ms_to_date(req_end_date)
        params = dict()
        params['start'] = True
        params['min_date'] = datetime.strptime('2010-01-01', '%Y-%m-%d')
        params['max_date'] = datetime.strptime('2010-01-02', '%Y-%m-%d')
        params['end'] = True
        params['in_memory'] = False
        # convert dates from ms to datetime
        # start_date = ms_to_date(start_date)
        #end_date = ms_to_date(end_date)
        if len(df) > 0:
            params['min_date'], params['max_date'] = \
                dd.compute(df.block_date.min(), df.block_date.max())
            # check start
            logger.warning('start_date from compute:%s', params['min_date'])
            logger.warning('start from slider:%s', req_start_date)


            # set flag to true if data has to be fetched
            if req_start_date <= params['min_date']:
                    params['start'] = False
            if req_end_date >= params['max_date']:
                    params['end'] = False

            logger.warning('set_params_to_load:%s', params)
            # if table already in memory then set in-memory flag
            if params['start'] == False and params['end'] == False:
                params['in_memory'] = True
                return params
        logger.warning("in set_params_to_load:%s",params)
        return params
    except Exception:
        logger.error('set_params_loaded_params', exc_info=True)
        # if error set start date and end_date far in the past
        # this will trigger full cassandra load
        params['min_date'] = datetime.strptime('2010-01-01', '%Y-%m-%d')
        params['max_date'] = datetime.strptime('2010-01-02', '%Y-%m-%d')
        params['start'] = True
        params['end'] = True
        params['in_memory']=False
        return params

# delta is integer: +-
def get_relative_day(day,delta):
    if isinstance(day,str):
        day = datetime.strptime('%Y-%m-%d')
    elif isinstance(day,int):
        day = ms_to_date()
    day = day + datetime.timedelta(days=delta)
    day = datetime.strftime(day, '%Y-%m-%d')
    return day


# get the data differential from the required start range
def construct_df_upon_load(df, table, cols, dedup_cols, req_start_date,
                           req_end_date, load_params):
    pc = PythonCassandra()
    pc.createsession()
    pc.createkeyspace('aion')

    if df is not None:
        if len(df) > 0:
            logger.warning("df original, TAIL:%s", df.tail())

    try:
        redis = RedisStorage()
        # get the data parameters to determine from whence to load
        params = redis.set_load_params(table, req_start_date,
                                       req_end_date, load_params)
        logger.warning("params before hashrate error:%s",params)
        # load all from redis
        logger.warning('construct df, params:%s', params)
        if params['load_type'] & LoadType.REDIS_FULL.value == LoadType.REDIS_FULL.value:
            lst = params['redis_key_full'].split(':')
            sdate = date_to_ms(lst[1])
            edate = date_to_ms(lst[2])
            df = redis.load(table, sdate, edate,params['redis_key_full'],'dataframe',)
        # load all from cassandra
        elif params['load_type'] & LoadType.CASS_FULL.value == LoadType.CASS_FULL.value:
            sdate = pc.date_to_cass_ts(req_start_date)
            edate = pc.date_to_cass_ts(req_end_date)
            logger.warning('construct_df, in cass load, sdate:%s',sdate)
            df = pc.load_from_daterange(table, cols, sdate, edate)

        # load from both cassandra and redis
        else:
            # load start
            streaming_dataframe = SD(table, cols, dedup_cols)
            df_start = streaming_dataframe.get_df()
            df_end = streaming_dataframe.get_df()
            df_temp = None

            # add cass if needed, then add redis if needed
            if params['load_type'] & LoadType.START_CASS.value == LoadType.START_CASS.value:
                lst = params['cass_start_range']
                sdate = date_to_ms(lst[0])
                edate = date_to_ms(lst[1])

                df_temp = pc.load_from_daterange(table, cols, sdate, edate)
                df_start = df_start.append(df_temp)

            if params['load_type'] & LoadType.REDIS_START.value == LoadType.REDIS_START.value:
                lst = params['redis_start_range']
                sdate = date_to_ms(lst[0])
                edate = date_to_ms(lst[1])
                df_temp = redis.load( table, sdate, edate,params['redis_key_start'],'dataframe')
                df_start = df_start.append(df_temp)


            # load end, add redis df, then cass df if needed
            if params['load_type'] & LoadType.REDIS_END.value == LoadType.REDIS_END.value:
                lst = params['redis_end_range']
                sdate = date_to_ms(lst[0])
                edate = date_to_ms(lst[1])
                df_temp = redis.load(table, sdate, edate,params['redis_key_end'],'dataframe')
                df_end = df_end.append(df_temp)

            if params['load_type'] & LoadType.CASS_END.value == LoadType.CASS_END.value:
                lst = params['cass_end_range']
                sdate = date_to_ms(lst[0])
                edate = date_to_ms(lst[1])
                df_temp = pc.load_from_daterange(table, cols, sdate, edate)
                df_end = df_end.append(df_temp)

            # concatenate end and start to original df
            if len(df_start>0):
                df = df_start.append(df).reset_index()
            if len(df_end>0):
                df = df.append(df_end).reset_index()

            del df_temp
            del df_start
            del df_end

            gc.collect()

        #logger.warning("df constructed, HEAD:%s", df.head())
        #logger.warning("df constructed, TAIL:%s", df.tail())

        # save df to  redis
        # clean up by deleting any dfs in redis smaller than the one we just saved
        """
        redis_df      || ---------------- ||
        required  |---------------------------- |

        """
        for key in params['redis_keys_to_delete']:
            redis.conn.delete(key)
            logger.warning('bigger df added so deleted key:%s',
                           str(key, 'utf-8'))

        # save (including overwrite to redis
        # reset index to sort
        if table == 'transaction':
            logger.warning('%s in construct df on load %s',table,df.head())
        # do not save if entire table loaded from redis
        if params['load_type'] & LoadType.REDIS_FULL.value != LoadType.REDIS_FULL.value:
            logger.warning("%s saved to reddis:%s",table.upper(),df.tail(10))
            redis.save(df, table, req_start_date, req_end_date)

        gc.collect()
        return df

    except Exception:
        logger.error('construct df from load', exc_info=True)

