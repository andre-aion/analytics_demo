from dask.dataframe.utils import make_meta
from tornado.gen import coroutine

from scripts.utils.mylogger import mylogger
from scripts.utils.pythonRedis import RedisStorage
import pandas as pd
import dask as dd
import gc
import re
from dask.dataframe.reshape import melt
import numpy as np
from datetime import date, datetime

r = RedisStorage()
logger = mylogger(__file__)

def remove_char(row):
    return re.sub('\[','',row['transaction_hashes'])



def list_to_rows(df, column, sep=',', keep=False):
    """
    Split the values of a column and expand so the new DataFrame has one split
    value per row. Filters rows where the column is missing.

    Params
    ------
    df : pandas.DataFrame
        dataframe with the column to split and expand
    column : str
        the column to split and expand
    sep : str
        the string used to split the column's values
    keep : bool
        whether to retain the presplit value as it's own row

    Returns
    -------
    pandas.DataFrame
        Returns a dataframe with the same columns as `df`.
    """
    indexes = list()
    new_values = list()
    df = df.dropna(subset=[column])
    for i, presplit in enumerate(df[column].astype(str)):
        values = presplit.split(sep)
        if keep and len(values) > 1:
            indexes.append(i)
            new_values.append(presplit)
        for value in values:
            indexes.append(i)
            # remove stray brackets
            value = re.sub('\[|\]',"",value)
            new_values.append(value)

    new_df = df.iloc[indexes, :].copy()
    new_df[column] = new_values
    return new_df

# explode into new line for each list member
def explode_transaction_hashes(df):
    meta=('transaction_hashes',str)
    try:
        # remove quotes
        # explode the list
        df = list_to_rows(df,"transaction_hashes")

        return df
    except Exception:
        logger.error("explode transaction hashes", exc_info=True)


# make data warehouse only if tier1 and tier2 miner lists do not exits
def make_poolminer_warehouse(df_tx, df_block, start_date, end_date):
    logger.warning("df_tx columns in make_poolminer_warehose:%s",df_tx.columns.tolist())
    logger.warning("df_block columns in make_poolminer_warehose:%s",df_block.columns.tolist())

    df_tx = df_tx[['transaction_hash','from_addr','to_addr','approx_value']]
    df_block = df_block[['miner_address','block_number','transaction_hashes',
                                 'block_date']]
    try:
        key_params = 'block_tx_warehouse'
        meta = make_meta({
                          'block_date': 'M8', 'block_number': 'i8',
                          'miner_address': 'object', 'transaction_hashes': 'object'})
        df_block = df_block.map_partitions(explode_transaction_hashes)
        logger.warning('COLUMNS %s:',df_block.columns.tolist())
        df_block.reset_index()

        # join block and transaction table
        df = df_block.merge(df_tx, how='left',
                                      left_on='transaction_hashes',
                                      right_on='transaction_hash')  # do the merge\
        df = df.drop(['transaction_hashes'],axis=1)
        df = df.reset_index()
        values = {'transaction_hash': 'unknown','approx_value':0,
                  'from_addr':'unknown','to_addr':'unknown','block_number':0}
        df = df.fillna(value=values)
        logger.warning(("merged columns",df.columns.tolist()))
        # save to redis
        r.save(df, key_params, start_date, end_date)
        return df
    except Exception:
        logger.error("make poolminer warehouse",exc_info=True)


def daily_percent(df,x):
    df_perc = df[(df.block_date== x)]
    total = df.block_number.sum()
    return 100*x.block_number/total

def list_by_tx_paid_out(df, delta_days, threshold=5):
    lst = []
    try:
        df_temp = df.groupby('from_addr')['to_addr'].count().reset_index()
        # find daily mean
        logger.warning("tx paid out threshold:%s",threshold)
        df_temp = df_temp[df_temp.to_addr >= threshold*delta_days]
        values = {'from_addr': 'unknown'}
        df_temp = df_temp.fillna(values)
        lst1 = df_temp['from_addr'].unique().compute()
        lst = [str(x) for x in lst1]

        logger.warning("miners found by paid out: %s",len(lst))

        del df_temp
        gc.collect()
        return lst
    except Exception:
        logger.error("tx paid out", exc_info=True)


def list_from_blocks_mined_daily(df,delta_days,threshold=1):
    lst = []
    try:
        df_temp = df.groupby('miner_address')['block_number'].count().reset_index()
        total_blocks_mined_daily = 8640
        # convert percentage threshold to number
        threshold = threshold*delta_days*total_blocks_mined_daily/100
        logger.warning("blocks mined daily threshold:%s",threshold)
        df_temp = df_temp[df_temp.block_number >= threshold]
        values = {'miner_address':'unknown',
                  'block_number': 0}
        df_temp = df_temp.fillna(values)
        lst1 = df_temp['miner_address'].unique().compute()
        lst = [str(x) for x in lst1]
        logger.warning("miners found by blocks mined: %s", len(lst))

        del df_temp
        gc.collect()
        return lst
    except Exception:
        logger.error("block mined daily", exc_info=True)

def get_key_in_redis(key_params,start_date,end_date):
    # get keys
    str_to_match = r.compose_key(key_params,start_date,end_date)
    matches = r.conn.scan_iter(match=str_to_match)
    redis_key = None
    if matches:
        for redis_key in matches:
            redis_key_encoded = redis_key
            redis_key = str(redis_key, 'utf-8')
            logger.warning('redis_key:%s', redis_key)
            break
    return redis_key


def is_tier1_in_memory(start_date, end_date, threshold_tx_paid_out=5,
                    threshold_blocks_mined_per_day=0.5):
    try:
        # check to is if it is saved in redis
        key_params = ['tier1_miners_list', threshold_tx_paid_out,
                      threshold_blocks_mined_per_day]
        redis_key = get_key_in_redis(key_params, start_date, end_date)

        # load data from redis if saved, else compose miner list
        if redis_key is not None:
            return r.load(key_params, start_date, end_date,
                                      key=redis_key, item_type='list')
        else:
            return None
    except Exception:
        logger.error("is_tier1_in_memory:",exc_info=True)

def make_tier1_list(df, start_date, end_date, threshold_tx_paid_out=5,
                    threshold_blocks_mined_per_day=0.5):
    try:
        # Count transactions paid out per day: group transactions by date and miner
        # find min day find max day
        key_params = ['tier1_miners_list', threshold_tx_paid_out,
                      threshold_blocks_mined_per_day]
        delta_days = (end_date - start_date).days
        if delta_days <= 0:
            delta_days = 1

        # tier 1 = percentage mined per day > threshold || transactions paid out > threshold per day#
        # make unique list of tier 1
        lst_a = list_by_tx_paid_out(df,delta_days,threshold_tx_paid_out)
        lst_b = list_from_blocks_mined_daily(df, delta_days,threshold_blocks_mined_per_day)
        # merge lists, drop duplicates
        if lst_a and lst_b:
            tier1_miners_list = list(set(lst_a + lst_b))
        else:
            if lst_a:
                tier1_miners_list = list(set(lst_a))
            elif lst_b:
                tier1_miners_list = list(set(lst_b))
            else:
                tier1_miners_list = []


        # save tier1 miner list to redis
        r.save(tier1_miners_list,key_params,start_date, end_date)

        del lst_a, lst_b
        gc.collect()

        return tier1_miners_list
    except Exception:
        logger.error("make tier 1 miner list", exc_info=True)

def is_tier2_in_memory(start_date, end_date,
                       threshold_tier2_pay_in=1,
                       threshold_tx_paid_out=5,
                       threshold_blocks_mined_per_day=0.5):
    try:
        # check to is if it is saved in redis
        # check to is if it is saved in redis
        key_params = ['tier2_miners_list', threshold_tier2_pay_in,
                      threshold_tx_paid_out, threshold_blocks_mined_per_day,
                      start_date, end_date]
        redis_key = get_key_in_redis(key_params, start_date, end_date)

        # load data from redis if saved, else compose miner list
        if redis_key is not None:
            return r.load(key_params, start_date, end_date,
                          key=redis_key, item_type='list')
        else:
            return None
    except Exception:
        logger.error("is_tier2_in_memory", exc_info=True)

def make_tier2_list(df, start_date, end_date,
                    tier1_miners_list,
                    threshold_tier2_received=1,
                    threshold_tx_paid_out=5,
                    threshold_blocks_mined_per_day=0.5
                    ):
    try:
        key_params = ['tier2_miners_list', threshold_tier2_received,
                      threshold_tx_paid_out, threshold_blocks_mined_per_day]
        # ensure both are datetimes
        if isinstance(end_date,datetime):
            end_date = end_date.date()
        if isinstance(start_date,datetime):
            start_date = start_date.date()

        delta_days = (end_date - start_date).days
        if delta_days <= 0:
            delta_days = 1

        # GET THE POOLS FOR FREQUENT PAYMENTS RECEIVED
        # filter dataframe to retain only great than
        # threshold tx pay-ins from tier1 miner list
        logger.warning("df in make tier 2 columns:%s",df.columns.tolist())

        df_temp = df[df.from_addr.isin(tier1_miners_list)]
        df_temp = df_temp.groupby('to_addr')['from_addr'].count().reset_index()
        threshold = threshold_tier2_received * delta_days
        df_temp = df_temp[df_temp.from_addr >= threshold]
        tier2_miners_list = df_temp.to_addr.unique().compute()
        del df_temp
        gc.collect()
        if tier1_miners_list:
            # save list to redis
            r.save(tier2_miners_list, key_params, start_date, end_date)

            return tier2_miners_list
        return []
        #logger.warning("tier2_miners_list:%s",tier2_miners_list)

    except Exception:
        logger.error("tier 2 miner list", exc_info=True)



