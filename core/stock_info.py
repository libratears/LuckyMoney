# -*- coding:utf-8 -*-
"""
@author: Lucy
@file: stock_info.py
@time: 2019/03/03
"""

import logging
import os
import time
import tushare as ts
import pandas as pd
from datetime import datetime
from core.market_info import MarketInfo
from common.constant import const
from sqlalchemy import create_engine
import util.date_util as du


enum_to_int = {
    "list_status": {"L": 0, "D": 1, "P": 2},  # 上市状态
    "is_hs": {"N": 0, "H": 1, "S": 2}  # 是否沪深港通
}


class StockInfo:

    def __init__(self):
        # pro token
        ts.set_token(const.TS_TOKEN)
        # init api
        self._pro = ts.pro_api()

    def save_stock_list(self):
        """
        保存上市股票信息
        该接口只有上市股票数据，没有退市股票数据
        替换已存在数据，保持一份最新
        """
        query_stock_basic = 'stock_basic'
        fields_stock_basic = 'ts_code,symbol,name,area,industry,fullname,enname,market,' \
                     'exchange,curr_type,list_status,list_date,delist_date,is_hs'
        table_stock_basic = 'stock_basic'
        try:
            # create sql connection
            engine = create_engine(const.MYSQL_CONN)
            # ts_code to drop
            stock_exist = pd.read_sql("SELECT ts_code FROM %s" % table_stock_basic, engine)
            ts_code_drop = stock_exist['ts_code']
            # load data from tushare
            stock_list = self._pro.query(query_stock_basic, fields=fields_stock_basic)
            # difference set
            flag = stock_list['ts_code'].isin(ts_code_drop)
            diff_flag = [not f for f in flag]
            stock_list = stock_list[diff_flag]
            # type conversion
            stock_list.replace(to_replace=enum_to_int, inplace=True)
            stock_list['list_date'] = pd.to_datetime(stock_list['list_date'],
                                                     format=const.DATE_FORMAT_TUSHARE,
                                                     errors='coerce')
            stock_list['delist_date'] = pd.to_datetime(stock_list['delist_date'],
                                                       format=const.DATE_FORMAT_TUSHARE,
                                                       errors='coerce')
            # insert new records
            pd.io.sql.to_sql(stock_list, table_stock_basic, con=engine, if_exists='append', index=False, chunksize=5000)
            print("Successfully load stock list: %d" % stock_list.shape[0])
        except Exception as e:
            print(e)
            return False

    def _append_stock_price(self, stock_code, start_date, end_date):
        """
        保存股票行情数据和指标
        :param stock_code: str
            example: '000001.SZ'
        :param start_date: str
            example: '20180101'
        :param end_date: str
            example: '20180101'
        """
        query_stock_price = 'daily'
        fields_stock_price = 'ts_code,trade_date,open,high,low,close,vol,amount'
        query_stock_indication = 'daily_basic'
        fields_stock_indication = 'ts_code,trade_date,pe,pe_ttm,pb,total_share,float_share,total_mv,circ_mv'
        table_stock_price = 'stock_price'
        table_stock_profit = 'stock_profit'
        sql_stock_profit = 'SELECT FROM %s WHERE ts_code=\'%s\'' % (table_stock_profit, stock_code)
        try:
            # create sql connection
            engine = create_engine(const.MYSQL_CONN)
            # load data from tushare and then merge
            stock_price = self._pro.query(query_stock_price, ts_code=stock_code, start_date=start_date, end_date=end_date,
                                          fields=fields_stock_price)
            stock_basic = self._pro.query(query_stock_indication, ts_code=stock_code, start_date=start_date, end_date=end_date,
                                          fields=fields_stock_indication)
            stock_info = pd.merge(stock_price, stock_basic, how='left', on=['ts_code', 'trade_date'])
            # my pe-ttm
            stock_profit = pd.read_sql(sql_stock_profit, con=engine)

            stock_info['pe_ttm_my'] = stock_info['close'] * stock_info['total_share'] / ()
            # type conversion
            stock_info['trade_date'] = pd.to_datetime(stock_info['trade_date'],
                                                     format=const.DATE_FORMAT_TUSHARE,
                                                     errors='coerce')
            pd.io.sql.to_sql(stock_info, table_stock_price, con=engine, if_exists='append', index=False, chunksize=5000)
            print("Successful load stock price: %s" % stock_code)
            time.sleep(3)
        except Exception as e:
            print("Failed to load stock price: %s, start: %s, end: %s" % (stock_code, start_date, end_date))
            raise e

    def save_stock_price(self, from_file_path, to_dir_path):
        """
        按个股保存个股数据，每只个股一个时序文件
        若无存在的数据，则从20000101开始获取至今的数据
        若有存在的数据，则从最后日期的下一天开始获取
        :param from_file_path: str
            path to read stock list
        :param to_dir_path: str
            dir path to save stock info
        """
        start_date = const.DATE_START
        end_date = du.datetime_to_yyyymmdd(datetime.now())
        stock_list = pd.read_csv(from_file_path, encoding='utf-8')
        stock_code = stock_list[stock_list['list_status'] == 'L']['ts_code']
        for item in stock_code:
            file_path = to_dir_path + item + const.CSV_EXTENSION
            if os.path.exists(file_path):
                stock_info_series = pd.read_csv(file_path, encoding='utf-8')
                last_trade_date = str(stock_info_series['trade_date'])
                if last_trade_date.lower() == 'nan':
                    start_date = const.DATE_START
                elif end_date[0:6] != last_trade_date[0:6]:
                    start_date_tmp = du.yyyymmdd_to_datetime(last_trade_date)
                    next_day = du.get_next_day(start_date_tmp)
                    start_date = du.datetime_to_yyyymmdd(next_day)
                else:
                    continue
            self._append_stock_price(item, start_date=start_date, end_date=end_date)

    def _append_daily_info(self, date, dir):
        """
        保存每日行情数据和指标
        :param date: str
            example: '20190101'
        """
        try:
            price_daily = self._pro.query('daily', trade_date=date)
            basic_daily = self._pro.query('daily_basic', trade_date=date,
                                          fields='ts_code,trade_date,pe,pe_ttm,pb,total_share,float_share,total_mv,circ_mv')
            info_daily = pd.merge(price_daily, basic_daily, how='left', on=['ts_code', 'trade_date'])
            print("Successful load daily price: %s" % date)
            return info_daily
        except Exception as e:
            print("Failed to load daily price: %s" % date)
            raise e

    def save_daily_info(self, start_date, end_date, dir):
        """
        按日保存个股数据
        :param start_date: str
            example:'20180101'
        :param end_date:
            example:'20180101'
        :param dir:
            dir path to save daily stock info
        """
        trade_date = start_date
        mi = MarketInfo()
        frames = []
        while int(trade_date) <= int(end_date):
            if not mi.is_trade_date(trade_date):
                print("Not a trade date: %s" % trade_date)
            else:
                res = self._append_daily_info(trade_date, dir)
                frames.append(res)
            trade_date = du.get_next_day(trade_date)
        if len(frames) == 0:
            return
        df = pd.concat(frames, ignore_index=True)
        ts_codes = df['ts_code'].unique()
        for item in ts_codes:
            file_path = dir + item + const.CSV_EXTENSION
            subset = df[df['ts_code'] == item]
            if os.path.exists(file_path):
                subset.to_csv(file_path, header=False, index=False, mode='a', encoding='utf-8')
            else:
                subset.to_csv(file_path, header=True, index=False, encoding='utf-8')

    def _append_stock_profit(self, stock_code, start_date, end_date):
        """
        按个股保存利润数据
        :param stock_code: str
        :param start_date: str
        :param end_date: str
        """
        query_stock_profit = 'income'
        fields_stock_profit = 'ts_code,ann_date,f_ann_date,end_date,report_type,basic_eps,diluted_eps,' \
                              'total_revenue,operate_profit,total_profit,income_tax,n_income,n_income_attr_p'
        table_stock_profit = 'stock_profit'
        try:
            # create sql connection
            engine = create_engine(const.MYSQL_CONN)
            # stock profit exit
            stock_profit = self._pro.query(query_stock_profit, ts_code=stock_code, start_date=start_date,
                                           end_date=end_date, fields=fields_stock_profit)
            # type conversion
            stock_profit['ann_date'] = pd.to_datetime(stock_profit['ann_date'],
                                                     format=const.DATE_FORMAT_TUSHARE,
                                                     errors='coerce')
            stock_profit['f_ann_date'] = pd.to_datetime(stock_profit['f_ann_date'],
                                                       format=const.DATE_FORMAT_TUSHARE,
                                                       errors='coerce')
            stock_profit['end_date'] = pd.to_datetime(stock_profit['end_date'],
                                                         format=const.DATE_FORMAT_TUSHARE,
                                                         errors='coerce')
            # insert latest records
            if stock_profit.shape[0] > 0:
                pd.io.sql.to_sql(stock_profit, table_stock_profit, con=engine, if_exists='append', index=False, chunksize=5000)
                print("Successfully load stock profit: %s, start: %s, end: %s" % (stock_code, start_date, end_date))
            else:
                print("No stock profit: %s, start: %s, end: %s" % (stock_code, start_date, end_date))
            time.sleep(5)
        except Exception as e:
            print("Failed to load stock profit: %s" % stock_code)
            raise e

    def save_stock_profit(self, start_date, end_date):
        """
        按个股保存利润数据
        个股列表来自数据库
        :param start_date: str
            如'20181201'
        :param end_date: str
            如'20181201'
        """
        sql_stock_list = 'SELECT ts_code FROM stock_basic'
        sql_stock_profit = 'SELECT ts_code, MAX(f_ann_date) AS date FROM stock_profit GROUP BY ts_code'
        try:
            # create sql connection
            engine = create_engine(const.MYSQL_CONN)
            # load stock list
            stock_list = pd.read_sql(sql_stock_list, con=engine)
            # iterate
            for stock_code in stock_list['ts_code']:
                self._append_stock_profit(stock_code, start_date=start_date, end_date=end_date)
        except Exception as e:
            print(e)

    def save_stock_profit_auto(self):
        """
        按个股保存利润数据
        个股列表来自数据库
        起始时间为数据库中group by stock_code的max(实际公布日期)的下个月
        结束时间为今日
        """
        sql_stock_list = 'SELECT ts_code FROM stock_basic'
        sql_stock_profit = 'SELECT ts_code, MAX(f_ann_date) AS date FROM stock_profit GROUP BY ts_code'
        try:
            # create sql connection
            engine = create_engine(const.MYSQL_CONN)
            # load historic data
            max_date = {}
            profit_hist = pd.read_sql_query(sql_stock_profit, con=engine)
            for row in profit_hist.iterrows():
                max_date[row[1]['ts_code']] = row[1]['date']
            # load stock list
            stock_list = pd.read_sql(sql_stock_list, con=engine)
            # iterate
            for stock_code in stock_list['ts_code']:
                start_date = max_date.get(stock_code, None)
                end_date = du.datetime_to_yyyymmdd(datetime.now())
                if not start_date is None:
                    start_date = du.datetime_to_yyyymmdd(du.get_first_day_of_next_month(start_date))
                    if start_date > end_date:
                        continue
                self._append_stock_profit(stock_code, start_date=start_date, end_date=end_date)
        except Exception as e:
            print(e)


si = StockInfo()
# si.save_stock_list()
# si.save_stock_info(const.FILE_STOCK_LIST, const.DIR_STOCK_INFO)
# si.save_daily_info('20190302', '20190302', const.DIR_STOCK_INFO)
si.save_stock_profit_auto()
