import os
import sys

from numpy import long

module_path = os.path.abspath(os.getcwd() + '\\..')
if module_path not in sys.path:
    sys.path.append(module_path)

from scripts.utils.pythonCassandra import PythonCassandra
from scripts.utils import myutils
from scripts.streaming.streamingDataframe import StreamingDataframe
from config import columns, dedup_cols, create_table_sql
from tornado.gen import coroutine
from tornado.locks import Condition, Semaphore
from concurrent.futures import ThreadPoolExecutor

import json
import datetime

from pyspark.streaming import StreamingContext
from pyspark.streaming.kafka import KafkaUtils, TopicAndPartition
from pyspark.streaming import StreamingContext
from pyspark.sql import SQLContext, SparkSession
from pyspark.context import SparkConf, SparkContext

import gc

from scripts.utils.mylogger import mylogger
logger = mylogger(__file__)


executor = ThreadPoolExecutor(max_workers=10)
CHECKPOINT_DIR = '/data/sparkcheckpoint'
ZOOKEEPER_SERVERS = "127.0.0.1:2181"
ZK_CHECKPOINT_PATH = '/opt/zookeeper/aion_analytics/offsets/'
ZK_CHECKPOINT_PATH = 'consumers/'


class KafkaConnectPyspark:
    # cassandra setup
    pc = PythonCassandra()
    pc.setlogger()
    pc.createsession()
    pc.createkeyspace('aion')

    table = 'block'
    block = StreamingDataframe(table, columns[table], dedup_cols[table])
    pc.create_table_block(table)

    table = 'transaction'
    transaction = StreamingDataframe(table, columns[table], dedup_cols[table])
    pc.create_table_block(table)


    checkpoint_dir = CHECKPOINT_DIR
    zk_checkpoint_dir = ZK_CHECKPOINT_PATH


    def __init__(self):
        '''
        cls.client = Client('127.0.0.1:8786')
        cls.input_queue = Queue()
        cls.remote_queue = cls.client.scatter(cls.input_queue)
        '''

    @classmethod
    def set_ssc(cls, ssc):
        if 'cls.ssc' not in locals():
            cls.ssc = ssc

    @classmethod
    def get_df(cls):
        return cls.block.get_df()

    @classmethod
    @coroutine
    def update_cassandra(cls, table, messages):
        cls.pc.insert_data(table, messages)

    @classmethod
    def transaction_to_tuple(cls, taken):
        messages_cass = list()
        message_dask = {}
        counter = 1

        for mess in taken:
            print('block # loaded from tx:%s', mess['block_number'])

            def munge_data():
                message_temp = {}
                for col in cls.transaction.columns:
                    message_temp[col] = mess[col]

                message = (message_temp['transaction_hash'],message_temp['transaction_index'],
                           message_temp['block_number'],
                           message_temp['transaction_timestamp'],message_temp['block_timestamp'],
                           message_temp['from_addr'],message_temp['to_addr'],
                           message_temp['value'],message_temp['nrg_consumed'],
                           message_temp['nrg_price'],message_temp['nonce'],
                           message_temp['contract_addr'],message_temp['transaction_year'],
                           message_temp['transaction_month'],message_temp['transaction_day'])

                return message

            message_cass = munge_data()
            messages_cass.append(message_cass)# regulate # messages in one dict
            if counter >= 10:
                #  update streaming dataframe
                cls.update_cassandra('block', messages_cass)
                messages_cass = list()
                print("++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
                print("++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
                logger.warning('tx message counter:{}'.format(counter))
                print("++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
                print("++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
                counter = 1
            else:
                counter += 1
                del mess
                gc.collect()

        cls.update_cassandra('block', messages_cass)
        del messages_cass



    @classmethod
    def block_to_tuple(cls, taken):
        messages_cass = list()
        message_dask = {}
        counter = 1

        for mess in taken:
            #print("++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
            #print("++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
            #print(message)
            #print('message counter in taken:{}'.format(counter))
            print('block # loaded from taken:{}'.format(mess['block_number']))

            #print("++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
            #print("++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")


            # convert timestamp, add miner_addr
            #@coroutine
            def munge_data():
                message_temp = {}
                for col in cls.block.columns:
                    if col in mess:
                        if col == 'block_timestamp':  # get time columns
                            block_timestamp = datetime.datetime.fromtimestamp(mess[col])
                            if col not in message_dask:
                                message_dask[col] = []
                            message_dask[col].append(block_timestamp)
                            message_temp[col] = block_timestamp
                            block_month, block_date = myutils.get_breakdown_from_timestamp(mess[col])
                            if 'block_date' not in message_dask:
                                message_dask['block_date'] = []
                            message_dask['block_date'].append(block_date)
                            message_temp['block_date'] = block_date


                        elif col == 'miner_address': # truncate miner address
                            if col not in message_dask:
                                message_dask[col] = []
                            message_dask[col].append(mess[col])
                            message_temp[col] = mess[col]

                            if 'miner_addr' not in message_dask:
                                message_dask['miner_addr'] = []
                            message_dask['miner_addr'].append(mess[col][0:10])
                            message_temp['miner_addr'] = mess[col][0:10]
                            
                        # convert difficulty
                        elif col == 'difficulty':
                            if col not in message_dask:
                                message_dask[col] = []
                            message_dask[col].append(int(mess[col], base=16))
                            message_temp[col] = (int(mess[col], base=16))
                        else:
                            if col not in message_dask:
                                message_dask[col] = []
                            message_dask[col].append(mess[col])
                            message_temp[col] = mess[col]

                message = (message_temp["block_number"], message_temp["miner_address"],
                           message_temp["miner_addr"],message_temp["nonce"], message_temp["difficulty"],
                           message_temp["total_difficulty"], message_temp["nrg_consumed"], message_temp["nrg_limit"],
                           message_temp["size"], message_temp["block_timestamp"],
                           message_temp["block_date"], message_temp['block_year'],
                           message_temp["block_month"],message_temp['block_day'],
                           message_temp["num_transactions"],
                           message_temp["block_time"], message_temp["nrg_reward"], message_temp["transaction_id"],
                           message_temp["transaction_list"])

                return message
                # insert to cassandra
            message_cass = munge_data()
            messages_cass.append(message_cass)

            # regulate # messages in one dict
            if counter >= 10:
                #  update streaming dataframe
                cls.update_cassandra('block', messages_cass)
                messages_cass = list()
                print("++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
                print("++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
                print('block message counter:{}'.format(counter))
                print("++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
                print("++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
                counter = 1
                message_dask = {}
            else:
                counter += 1
                del mess
                gc.collect()

        cls.update_cassandra('block', messages_cass)
        del messages_cass
        del message_dask


    @classmethod
    def handle_block_rdds(cls,rdd):
        if rdd.isEmpty():
            print("++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
            logger.print(' RDD IS NONE')
            print("++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
            return
        try:
            taken = rdd.take(10000)
            cls.block_to_tuple(taken)

        except Exception:
            logger.error('HANDLE RDDS:{}',exc_info=True)

    @classmethod
    def handle_transaction_rdds(cls, rdd):
        if rdd.isEmpty():
            print("++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
            logger.print(' RDD IS NONE')
            print("++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
            return
        try:
            taken = rdd.take(10000)
            cls.block_to_tuple(taken)

        except Exception:
            logger.error('HANDLE RDDS:{}', exc_info=True)

    @classmethod
    def get_zookeeper_instance(cls):
        from kazoo.client import KazooClient

        if 'KazooSingletonInstance' not in globals():
            globals()['KazooSingletonInstance'] = KazooClient(ZOOKEEPER_SERVERS)
            globals()['KazooSingletonInstance'].start()
        return globals()['KazooSingletonInstance']

    @classmethod
    def read_offsets(cls, zk, topics):
        try:
            from_offsets = {}
            for topic in topics:
                logger.warning("TOPIC:%s", topic)
                #create path if it does not exist
                topic_path = ZK_CHECKPOINT_PATH + topic

                try:
                    partitions = zk.get_children(topic_path)
                    for partition in partitions:
                        topic_partition = TopicAndPartition(topic, int(partition))
                        partition_path = topic_path + '/' + partition
                        offset = int(zk.get(partition_path)[0])
                        from_offsets[topic_partition] = offset
                except Exception:
                    try:
                        topic_partition = TopicAndPartition(topic, int(0))
                        zk.ensure_path(topic_path+'/'+"0")
                        zk.set(topic_path, str(0).encode())
                        from_offsets[topic_partition] = int(0)
                        logger.warning("NO OFFSETS")
                    except Exception:
                        logger.error('MAKE FIRST OFFSET:{}', exc_info=True)

            #logger.warning("FROM_OFFSETS:%s",from_offsets)
            return from_offsets
        except Exception:
            logger.error('READ OFFSETS:{}',exc_info=True)

    @classmethod
    @coroutine
    def save_offsets(cls, rdd):
        try:
            zk = cls.get_zookeeper_instance()
            #logger.warning("inside save offsets:%s", zk)
            for offset in rdd.offsetRanges():
                #logger.warning("offset saved:%s",offset)
                path = ZK_CHECKPOINT_PATH + offset.topic + '/' + str(offset.partition)
                zk.ensure_path(path)
                zk.set(path, str(offset.untilOffset).encode())
        except Exception:
            logger.error('SAVE OFFSETS:%s',exc_info=True)

    @classmethod
    def reset_partition_offset(cls, zk, topic, partitions):
        """Delete the specified partitions within the topic that the consumer
                is subscribed to.
                :param: groupid: The consumer group ID for the consumer.
                :param: topic: Kafka topic.
                :param: partitions: List of partitions within the topic to be deleted.
        """
        for partition in partitions:
            path = "/consumers/{topic}/{partition}".format(
                topic=topic,
                partition=partition
            )
        zk.delete(path)

    @classmethod
    def create_streaming_context(cls):
        # NOTE THAT MAXRATEPERPARTIOINS DETERMINES THE KAFKA CHECKPOINTING PERIODS
        conf = SparkConf() \
            .set("spark.streaming.kafka.backpressure.initialRate", 150) \
            .set("spark.streaming.kafka.backpressure.enabled", 'true') \
            .set('spark.streaming.kafka.maxRatePerPartition', 250) \
            .set('spark.streaming.receiver.writeAheadLog.enable', 'true') \
            .set("spark.streaming.concurrentJobs", 4)
        spark_context = SparkContext(appName='aion_analytics',
                                     conf=conf)

        ssc = StreamingContext(spark_context, 1)

        return ssc

    @classmethod
    @coroutine
    def kafka_stream(cls,table,stream):
        stream = stream.map(lambda x: json.loads(x[1]))
        stream = stream.map(lambda x: x['payload']['after'])
        # kafka_stream.pprint()
        if table == 'block':
            stream.foreachRDD(lambda rdd: cls.handle_block_rdds(rdd) \
                if not rdd.isEmpty() else None)
        else:
            stream.foreachRDD(lambda rdd: cls.handle_transaction_rdds(rdd) \
                if not rdd.isEmpty() else None)
        stream.foreachRDD(lambda rdd: cls.save_offsets(rdd))

    @classmethod
    def run(cls):
        try:
            # Get StreamingContext from checkpoint data or create a new one
            cls.ssc = cls.create_streaming_context()

            # SETUP KAFKA SOURCE
            block_topic = ['mainnetserver.aion.block']
            transaction_topic = [ 'mainnet.aion.transaction']
            topics=[block_topic, transaction_topic]
            # setup checkpointing
            zk = cls.get_zookeeper_instance()
            #cls.reset_partition_offset(zk,topics[0],[0]) #reset if necessary
            from_offsets = cls.read_offsets(zk, topics)

            kafka_params = {"metadata.broker.list": "localhost:9092",
                            "auto.offset.reset": "smallest"}


            block_stream = KafkaUtils \
                .createDirectStream(cls.ssc, block_topic, kafka_params,
                                    fromOffsets=from_offsets)
            transaction_stream = KafkaUtils \
                .createDirectStream(cls.ssc, transaction_topic, kafka_params,
                                    fromOffsets=from_offsets)

            cls.kafka_stream(block_stream)
            cls.kafka_stream(transaction_stream)


            # Start the context
            cls.ssc.start()
            cls.ssc.awaitTermination()

        except Exception as ex:
            print('KAFKA/SPARK RUN :{}'.format(ex))




