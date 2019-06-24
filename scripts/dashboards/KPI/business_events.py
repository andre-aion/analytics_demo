import random

from bokeh.plotting import figure
from fbprophet import Prophet
from holoviews import streams, dim

from scripts.databases.pythonMongo import PythonMongo
from scripts.utils.mylogger import mylogger
from scripts.utils.myutils import tab_error_flag
from concurrent.futures import ThreadPoolExecutor
from tornado.locks import Lock
from scripts.utils.interfaces.KPI_interface import KPI
from config.dashboard import config as dashboard_config

from bokeh.layouts import gridplot, WidgetBox
from bokeh.models import Panel, Button, Spacer, HoverTool, Range1d, ColumnDataSource, ResetTool, BoxZoomTool, PanTool, \
    ToolbarBox, Toolbar, SaveTool, WheelZoomTool
import gc
from bokeh.models.widgets import Div, \
    DatePicker, Select

from datetime import datetime, timedelta, date

import holoviews as hv
from holoviews import opts
from tornado.gen import coroutine
import numpy as np
import pandas as pd

from static.css.KPI_interface import KPI_card_css

lock = Lock()
executor = ThreadPoolExecutor()
logger = mylogger(__file__)

hv.extension('bokeh', logo=False)
renderer = hv.renderer('bokeh')


@coroutine
def KPI_business_tab(panel_title, DAYS_TO_LOAD=90):
    timeline_source = ColumnDataSource(data=dict(
        Item=[],
        Start=[],
        End=[],
        Color=[],
        start=[],
        end=[],
        ID=[],
        ID1=[]
    ))

    class Thistab(KPI):
        def __init__(self, table, cols=[]):
            KPI.__init__(self, table, name='project', cols=cols)
            self.table = table
            self.df = None
            self.df1 = None
            self.df_pop = None

            self.checkboxgroup = {}
            self.period_to_date_cards = {

            }
            self.ptd_startdate = datetime(datetime.today().year, 1, 1, 0, 0, 0)

            self.timestamp_col = 'timestamp'
            self.pym = PythonMongo('aion')
            self.groupby_dict = {
                'event': 'count',
                'type':'count',
                'rate:':'sum',
                'event_duration': 'sum',
                'start_delay': 'mean',
                'end_delay': ' mean',
                'event_location':'count',

                'patron':'count',
                'patron_likes':'nunique',
                'patron_gender':'count',
                'patron_age':'mean',
                'patron_friend':'nunique',
                'patron_friend_gender':'count',
                'patron_friend_age':'mean',
                'patron_discovery':'nunique',

                'manager':'count',
                'manager_gender':'count',
                'manager_age':'mean',
                'manager_education':'count',
                'manager_parish':'count',

                'staff':'count',
                'staff_gender':'count',
                'staff_age':'mean',
                'staff_education':'count',
                'staff_parish':'count',
                'remuneration':'sum',

            }

            self.menus = {
                'company': [],
                'type': [],
                'patron':[],
                'manager':[],
                'gender': ['all', 'male', 'female'],
                'variables': list(self.groupby_dict.keys()),
                'history_periods': ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10'],
            }

            #self.variables = sorted(list(self.groupby_dict.keys()))
            self.variable = 'event'

            # #########  SETUP FILTERS #########################
            self.selects = {
                'event': Select(title='Select event', value="all",options=[]),

                'company' : Select(title='Select company', value="all",options=[]),

                'patron_likes' : Select(title='Select patron likes/hobbies', value='all',
                                              options=[]),

                'patron' : Select(title='Select patron', value='all', option=[]),



                'manager_education' : Select(title="Select manager's education", value='all',
                                           options=[]),

                'staff_education' : Select(title="Select staff's education", value='all',
                                                   options=[]),




                'manager_gender' : Select(title="Select manager's gender", value='all',
                                         options=self.menus['gender']),
                'staff_gender' : Select(title="Select staff's gender", value='all',
                                         options=self.menus['gender']),
                'patron_gender' : Select(title="Select patron's gender", value='all',
                                         options=self.menus['gender']),

                'manager_parish' : Select(title="Select manager's parish", value='all',
                                         options=[]),
                'staff_parish' : Select(title="Select staff's parish", value='all',
                                       options=[]),
                'patron_parish' : Select(title="Select patron's parish", value='all',
                                        options=[]),
                'type': Select(title="Select event type", value='all',
                                        options=[]),
            }

            self.vars = {
                'event': 'all',

                'company': 'all',

                'patron_likes': 'all',

                'patron': 'all',

                'manager_education': 'all',

                'staff_education': 'all',

                'manager_gender': 'all',

                'staff_gender': 'all',
                'patron_gender': 'all',

                'manager_parish':'all',
                'patron_parish':'all',
                'type':'all'

            }
            self.multiline_vars = {
                'xs' : ['patron_likes','manager_education','staff_education',
                                   'manager_gender','staff_gender','patron_gender','manager_parish',
                                   'patron_parish','type'],
                'ys': ['rate','attendance']
            }
            self.multiline_variable = {
                'x':'manager_gender',
                'y':'rate'
            }
            self.chord_data = {
                'rename': {

                    'patron': 'source',
                    'company': 'target',
                    'rate': 'value'
                },
                'percentile_threshold': .75,

            }

            self.feature_list = self.multiline_vars['xs'] + ['rate','remuneration','start_delay','end_delay',
                                                             'staff_age','manager_age','patron_age']

            self.percentile_threshold = 10
            self.tsa_variable = 'event'
            self.forecast_days = 30

            self.datepicker_pop_start = DatePicker(
                title="Period start", min_date=self.initial_date,
                max_date=dashboard_config['dates']['last_date'], value=dashboard_config['dates']['last_date'])

            # ------- DIVS setup begin
            self.page_width = 1200
            txt = """<hr/><div style="text-align:center;width:{}px;height:{}px;
                                         position:relative;background:black;margin-bottom:200px">
                                         <h1 style="color:#fff;margin-bottom:300px">{}</h1>
                                   </div>""".format(self.page_width, 50, 'Welcome')
            self.notification_div = {
                'top': Div(text=txt, width=self.page_width, height=20),
                'bottom': Div(text=txt, width=self.page_width, height=10),
            }

            self.section_divider = '-----------------------------------'
            self.section_headers = {
                'cards': self.section_header_div(text='Period to date:{}'.format(self.section_divider),
                                                 width=1000, html_header='h2', margin_top=50, margin_bottom=5),
                'pop': self.section_header_div(text='Period over period:{}'.format(self.section_divider),
                                               width=600, html_header='h2', margin_top=5, margin_bottom=-155),
                'chord': self.section_header_div(text='Patron networks:{}'.format(self.section_divider),
                                                 width=600, html_header='h3', margin_top=5, margin_bottom=-155),
                'tsa': self.section_header_div(text='Forecasts (TSA):{}'.format(self.section_divider),
                                                    width=600, html_header='h2', margin_top=5, margin_bottom=-155),
                'multiline': self.section_header_div(text='Comparitive graphs:{}'.format(self.section_divider),
                                               width=600, html_header='h2', margin_top=5, margin_bottom=-155),
                'patron info': self.section_header_div(text='Patron info:{}'.format(self.section_divider),
                                                     width=600, html_header='h2', margin_top=5, margin_bottom=-155),
                'correlations': self.section_header_div(text='Correlations:{}'.format(self.section_divider),
                                                     width=600, html_header='h2', margin_top=5, margin_bottom=-155),
            }
            self.KPI_card_div = self.initialize_cards(self.page_width, height=350)
            start = datetime(2014, 1, 1, 0, 0, 0)
            end = datetime(2019, 5, 15, 0, 0, 0)
            self.tools = [BoxZoomTool(), ResetTool(), PanTool(), SaveTool(), WheelZoomTool()]
            self.timeline_vars = {
                'company': '',
                'event': '',
                'types': ['all'],
                'type': 'all',
                'DF': None,
                'G': figure(
                    title=None, x_axis_type='datetime', width=1200, height=900,
                    y_range=[], x_range=Range1d(start, end), toolbar_location=None),
                'toolbar_box': ToolbarBox()
            }


            # ----- UPDATED DIVS END

        # ----------------------  DIVS ----------------------------
        def section_header_div(self, text, html_header='h2', width=600, margin_top=150, margin_bottom=-150):
            text = """<div style="margin-top:{}px;margin-bottom:-{}px;"><{} style="color:#4221cc;">{}</{}></div>""" \
                .format(margin_top, margin_bottom, html_header, text, html_header)
            return Div(text=text, width=width, height=15)

        def information_div(self, width=400, height=300):
            txt = """
            <div {}>
                <h4 {}>How to interpret sentiment score</h4>
                <ul style='margin-top:-10px;'>
                    <li>
                    </li>
                    <li>
                    </li>
                    <li>
                    </li>
                    <li>
                    </li>

                </ul>
            </div>

            """.format(self.div_style, self.header_style)
            div = Div(text=txt, width=width, height=height)
            return div

        def initialize_cards(self, width, height=250):
            try:
                txt = ''
                for period in ['year', 'quarter', 'month', 'week']:
                    design = random.choice(list(KPI_card_css.keys()))
                    txt += self.card(title='', data='', card_design=design)

                text = """<div style="margin-top:100px;display:flex; flex-direction:row;">
                {}
                </div>""".format(txt)
                div = Div(text=text, width=width, height=height)
                return div
            except Exception:
                logger.error('initialize cards', exc_info=True)

        def load_df(self, req_startdate, req_enddate, table, cols, timestamp_col):
            try:
                # get min and max of loaded df
                if self.df is not None:
                    loaded_min = self.df[timestamp_col].min()
                    loaded_max = self.df[timestamp_col].max()

                    if loaded_min <= req_startdate and loaded_max >= req_enddate:
                        df = self.df[(self.df[timestamp_col] >= req_startdate) &
                                     (self.df[timestamp_col] <= req_enddate)]
                        return df
                return self.pym.load_df(req_startdate, req_enddate, table=table,
                                        cols=cols, timestamp_col=timestamp_col)

            except Exception:
                logger.error('load_df', exc_info=True)

        def load_menus(self,df1):
            try:
                cols = ['event','company','patron_likes','manager_education','staff_education',
                        'manager_parish','staff_parish','patron_parish',
                        'patron','patron_friend']
                for col in cols:
                    self.selects.options = ['all'] + list(df1[col].unique())

            except Exception:
                logger.error('load menus',exc_info=True)

        def filter_df(self, df1):
            try:
                for key in self.vars.keys():
                    if self.vars[key] != 'all':
                        df1 = df1[df1[key] == self.vars['key']]
                self.df1 = df1
                return df1

            except Exception:
                logger.error('period to date', exc_info=True)

        # ------------------------- CARDS END -----------------------------------
        def period_to_date(self, df, timestamp=None, timestamp_filter_col=None, cols=[], period='week'):
            try:
                if timestamp is None:
                    timestamp = datetime.now()
                    timestamp = datetime(timestamp.year, timestamp.month, timestamp.day, timestamp.hour, 0, 0)

                start = self.first_date_in_period(timestamp, period)
                # filter

                df[timestamp_filter_col] = pd.to_datetime(df[timestamp_filter_col], format=self.DATEFORMAT_PTD)
                logger.warning('df:%s', df['timestamp'])

                df = df[(df[timestamp_filter_col] >= start) & (df[timestamp_filter_col] <= timestamp)]
                if len(cols) > 0:
                    df = df[cols]
                return df
            except Exception:
                logger.error('period to date', exc_info=True)

        def period_over_period(self, df, start_date, end_date, period,
                               history_periods=2, timestamp_col='timestamp_of_first_event'):
            try:
                # filter cols if necessary
                string = '0 {}(s) prev(current)'.format(period)

                # filter out the dates greater than today
                df_current = df.copy()
                df_current['period'] = string
                # label the days being compared with the same label
                df_current = self.label_dates_pop(df_current, period, timestamp_col)
                # logger.warning('LINE 244:%s', df_current.head(15))
                # zero out time information
                start = datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0)
                end = datetime(end_date.year, end_date.month, end_date.day, 0, 0, 0)

                cols = list(df.columns)
                counter = 1
                if isinstance(history_periods, str):
                    history_periods = int(history_periods)
                # make dataframes for request no. of periods
                start, end = self.shift_period_range(period, start, end)
                while counter < history_periods and start >= self.initial_date:
                    # load data
                    if period == 'quarter':
                        logger.warning('start:end %s:%s', start, end)
                    if self.crypto != 'all':
                        supplemental_where = "AND crypto = '{}'".format(self.crypto)
                    df_temp = self.load_df(start, end, self.table, cols, timestamp_col)
                    df_temp = df_temp.compute()
                    df_temp[timestamp_col] = pd.to_datetime(df_temp[timestamp_col])
                    if df_temp is not None:
                        if len(df_temp) > 1:
                            string = '{} {}(s) prev'.format(counter, period)
                            # label period
                            df_temp = df_temp.assign(period=string)
                            # relabel days to get matching day of week,doy, dom, for different periods
                            df_temp = self.label_dates_pop(df_temp, period, timestamp_col)
                            # logger.warning('df temp loaded for %s previous: %s',counter,len(df_temp))

                            df_current = pd.concat([df_current, df_temp])
                            del df_temp
                            gc.collect()
                    # shift the loading window
                    counter += 1
                    start, end = self.shift_period_range(period, start, end)
                return df_current
            except Exception:
                logger.error('period over period', exc_info=True)

            # label dates for period over period (pop)

        def label_dates_pop(self, df, period, timestamp_col):
            df[timestamp_col] = pd.to_datetime(df[timestamp_col])

            def label_qtr_pop(y):
                try:
                    curr_quarter = int((y.month - 1) / 3 + 1)
                    start = datetime(y.year, 3 * curr_quarter - 2, 1)
                    return abs((start - y).days)
                except Exception:
                    logger.error('df label quarter', exc_info=True)

            try:
                if period == 'week':
                    df['dayset'] = df[timestamp_col].dt.dayofweek
                elif period == 'month':
                    df['dayset'] = df[timestamp_col].dt.day
                elif period == 'year':
                    df['dayset'] = df[timestamp_col].timetuple().tm_yday
                elif period == 'quarter':
                    df['dayset'] = df[timestamp_col].apply(lambda x: label_qtr_pop(x))

                return df
            except Exception:
                logger.error('label data ', exc_info=True)

        # -------------------- GRAPHS -------------------------------------------
        def graph_periods_to_date(self, df1, timestamp_filter_col, variable):
            try:
                if self.crypto != 'all':
                    df1 = df1[df1.crypto == self.crypto]

                df1 = df1.compute()
                dct = {}
                for idx, period in enumerate(['week', 'month', 'quarter', 'year']):
                    df = self.period_to_date(df1, timestamp=dashboard_config['dates']['last_date'],
                                             timestamp_filter_col=timestamp_filter_col, period=period)

                    # get unique instances
                    df = df[[variable]]
                    df = df.drop_duplicates(keep='first')
                    # logger.warning('post duplicates dropped:%s', df.head(10))
                    if self.groupby_dict[variable] == 'sum':
                        data = int(df[variable].sum())
                    elif self.groupby_dict[variable] == 'mean':
                        data = "{}%".format(round(df[variable].mean(), 3))
                    del df
                    gc.collect()
                    dct[period] = data

                self.update_cards(dct)

            except Exception:
                logger.error('graph periods to date', exc_info=True)

        def graph_period_over_period(self, period):
            try:

                periods = [period]
                start_date = self.pop_start_date
                end_date = self.pop_end_date
                if isinstance(start_date, date):
                    start_date = datetime.combine(start_date, datetime.min.time())
                if isinstance(end_date, date):
                    end_date = datetime.combine(end_date, datetime.min.time())
                today = datetime.combine(datetime.today().date(), datetime.min.time())

                if start_date == today:
                    logger.warning('START DATE of WEEK IS TODAY.!NO DATA DATA')
                    start_date = start_date - timedelta(days=7)
                    self.datepicker_pop_start.value = start_date

                cols = [self.variable, self.timestamp_col]

                df = self.load_df(start_date=start_date, end_date=end_date, cols=cols,
                                  timestamp_col='timestamp')

                if abs(start_date - end_date).days > 7:
                    if 'week' in periods:
                        periods.remove('week')
                if abs(start_date - end_date).days > 31:
                    if 'month' in periods:
                        periods.remove('month')
                if abs(start_date - end_date).days > 90:
                    if 'quarter' in periods:
                        periods.remove('quarter')
                df = df.compute()
                for idx, period in enumerate(periods):
                    df_period = self.period_over_period(df, start_date=start_date, end_date=end_date,
                                                        period=period, history_periods=self.pop_history_periods,
                                                        timestamp_col='timestamp')

                    logger.warning('LINE 368: dayset:%s', df_period.head(30))
                    groupby_cols = ['dayset', 'period']
                    if len(df_period) > 0:
                        # logger.warning('line 150 df_period columns:%s',df.columns)
                        df_period = df_period.groupby(groupby_cols).agg({self.variable: 'sum'})
                        df_period = df_period.reset_index()
                    else:
                        df_period = df_period.rename(index=str, columns={'day': 'dayset'})

                    prestack_cols = list(df_period.columns)

                    df_period = self.split_period_into_columns(df_period, col_to_split='period',
                                                               value_to_copy=self.variable)

                    # short term fix: filter out the unnecessary first day added by a corrupt quarter functionality
                    if period == 'quarter':
                        min_day = df_period['dayset'].min()
                        logger.warning('LINE 252: MINIUMUM DAY:%s', min_day)
                        df_period = df_period[df_period['dayset'] > min_day]

                    poststack_cols = list(df_period.columns)

                    title = "{} over {}".format(period, period)
                    plotcols = list(np.setdiff1d(poststack_cols, prestack_cols))
                    # include current period if not extant
                    df_period, plotcols = self.pop_include_zeros(df_period, plotcols=plotcols, period=period)
                    # logger.warning('line 155 cols to plot:%s',plotcols)
                    if self.groupby_dict[self.variable] == 'sum':
                        xlabel = 'frequency'
                    elif self.groupby_dict[self.variable] == 'mean':
                        xlabel = '%'

                    if idx == 0:
                        p = df_period.hvplot.bar('dayset', plotcols, rot=45, title=title,
                                                 stacked=False, width=1200, height=400, value_label=xlabel)
                    else:
                        p += df_period.hvplot.bar('dayset', plotcols, rot=45, title=title,
                                                  stacked=False, width=1200, height=400, value_label=xlabel)
                return p

            except Exception:
                logger.error('period over period to date', exc_info=True)

        def patron_info_table(self,launch):
            try:
                tmp_df = []
                tmp_df1 = []
                if self.vars['patron'] != 'all':
                    tmp_df = self.df1['patron_friend','patron_friend_gender','patron_friend_parish']
                    tmp_df.drop_duplicates(keep='first', inplace=True)
                    # likes
                    tmp_df1 = self.df1['patron', 'patron_likes', 'patron_gender', 'patron_discovery', 'patron_parish']
                    tmp_df1.drop_duplicates(keep='first', inplace=True)

                p = tmp_df.hvplot.table(width=400)
                q =  tmp_df1.hvplot.table(width=600)

                return q + p


            except Exception:
                logger.error('patron friends table', exc_info=True)

        def chord_diagram(self, launch):
            try:
                def normalize_value(x, total):
                    x = int((x / total) * 1000)
                    if x <= 0:
                        return 1
                    return x

                df = self.df.copy()
                # chord setup
                var1 = 'staff'
                var2 = 'patron'
                # --------------  nodes
                data = {}
                data['nodes'] = []
                source_list = df[var1].tolist()
                names = list(set(source_list))



                var1_dict = dict(zip(df[var2], df.type))
                type_dict = {}
                types = list(set(df['type'].tolist()))
                name_dict = {}
                for idx, name in enumerate(names):
                    name_dict[name] = idx

                for idx, name in enumerate(names):
                    type_tmp = var1_dict[name]
                    index = name_dict[name]
                    data['nodes'].append({'OwnerID': index, 'index': idx, 'Type': type_tmp})

                nodes = hv.Dataset(pd.DataFrame(data['nodes']), 'index')

                # --------- make the links

                data['links'] = []

                for idx, row in df.iterrows():
                    src = name_dict[row[var1]]
                    tgt = name_dict[row[var2]]
                    val = row['rate']
                    data['links'].append({'source': src, 'target': tgt, 'value': val})

                links = pd.DataFrame(data['links'])
                # get the individual links
                links = links.groupby(['source', 'target'])['value'].sum()
                links = links.reset_index()
                total = links['value'].sum()
                links['value'] = links['value'].apply(lambda x: normalize_value(x, total))

                # filter for top percentile
                quantile_val = links['value'].quantile(self.chord_data['percentile_threshold'])
                links = links[links['value'] >= quantile_val]
                # logger.warning('after quantile filter:%s',len(links))

                chord_ = hv.Chord((links, nodes), ['source', 'target'], ['value'])
                chord_.opts(opts.Chord(cmap='Category20', edge_cmap='Category20', edge_color=dim('source').str(),
                                       labels='Type', node_color=dim('index').str(), width=1000, height=1000))

                return chord_

            except Exception:
                logger.error('chord diagram', exc_info=True)

        def tsa_freq(self, launch):
            try:
                logger.warning('df columns:%s', list(self.df.columns))
                df = self.df1.set_index('timestamp')
                if self.tsa_variable in ['remuneration','rate']:
                    df = df.resample('D').agg({self.tsa_variable: 'sum'})
                else:
                    # calculate attendance
                    df = df.groupby('Event').resample('D')['patron'].count()

                df = df.reset_index()
                df = df.compute()
                label = 'freq_diff'
                df[label] = df[self.tsa_variable].diff()
                df = df.fillna(0)

                rename = {'timestamp': 'ds', self.tsa_variable: 'y'}
                df = df.rename(columns=rename)
                logger.warning('df:%s', df.head())
                df = df[['ds', 'y']]
                logger.warning('df:%s', df.tail())
                m = Prophet()
                m.fit(df)

                future = m.make_future_dataframe(periods=self.forecast_days)
                forecast = m.predict(future)

                print(forecast[['ds', 'yhat', 'yhat_lower', 'yhat_upper']].tail())
                print(list(forecast.columns))

                if self.tsa_variable in ['rate','remuneration']:
                    value_label = '$'
                else:
                    value_label = '#'


                for idx, col in enumerate(['yhat', 'yhat_lower', 'yhat_upper']):
                    if idx == 0:
                        p = forecast.hvplot.line(x='ds', y=col, width=600,
                                                 height=250, value_label=value_label).relabel(col)
                    else:
                        p *= forecast.hvplot.scatter(x='ds'
                                                     , y=col, width=600,
                                                     height=250, value_label=value_label).relabel(col)

                for idx, col in enumerate(['trend', 'weekly']):
                    if idx == 0:
                        q = forecast.hvplot.line(x='ds', y=col, width=550,
                                                 height=250, value_label=value_label).relabel(col)
                    else:
                        q *= forecast.hvplot.line(x='ds', y=col,
                                                  width=550, height=250, value_label=value_label).relabel(col)

                return p + q
            except Exception:
                logger.error("box plot:", exc_info=True)

        def multiline(self, launch=1):
            try:
                yvar = self.multiline_variable['y']
                if self.multiline_variable['y'] == 'attendance':
                    yvar = 'patron'

                xvar = self.multiline_variable['x']
                df = self.df.copy()
                df = df[[xvar, yvar, self.timestamp_col]]
                df = df.set_index(self.timestamp_col)
                df = df.groupby(xvar).resample(self.resample_period).agg({yvar: 'mean'})
                df = df.reset_index()
                lines = df[xvar].unique()
                # split data frames
                dfs = {}
                for idx, line in enumerate(lines):
                    dfs[line] = df[df[xvar] == line]
                    dfs[line] = dfs[line].fillna(0)
                    logger.warning('LINE 428:%s - %s:', line, dfs[line].head())
                    if idx == 0:
                        p = dfs[line].hvplot.line(x=self.timestamp_col, y=yvar, width=1200, height=500).relabel(line)
                    else:
                        p *= dfs[line].hvplot.line(x=self.timestamp_col, y=yvar, width=2, height=500).relabel(line)
                return p
            except Exception:
                logger.error('multiline plot', exc_info=True)

        def correlation_table(self, launch):
            try:

                corr_dict = {
                    'Variable 1': [],
                    'Variable 2': [],
                    'Relationship': [],
                    'r': [],
                    'p-value': []
                }
                # prep df
                df = self.df1
                df = df.drop(self.timestamp_col, axis=1)

                for col in self.feature_list:
                    logger.warning('col :%s', col)
                    if col != self.variable:
                        # group by variables
                        if self.groupby_dict[self.variable] not in ['mean', 'sum']:
                            df_tmp = df.groupby(self.variable).agg({col: self.groupby_dict[col]})
                        else:
                            if self.self.groupby_dict[col] not in ['mean','sum']:
                                df_tmp = df.groupby(col).agg({col: self.groupby_dict[self.variable]})

                        a = df_tmp[self.variable].tolist()

                        logger.warning('%s:%s', col, self.variable)
                        b = df_tmp[col].tolist()
                        slope, intercept, rvalue, pvalue, txt = self.corr_label(a, b)
                        # add to dict
                        corr_dict['Variable 1'].append(self.variable)
                        corr_dict['Variable 2'].append(col)
                        corr_dict['Relationship'].append(txt)
                        corr_dict['r'].append(round(rvalue, 4))
                        corr_dict['p-value'].append(round(pvalue, 4))

                df = pd.DataFrame(
                    {
                        'Variable 1': corr_dict['Variable 1'],
                        'Variable 2': corr_dict['Variable 2'],
                        'Relationship': corr_dict['Relationship'],
                        'r': corr_dict['r'],
                        'p-value': corr_dict['p-value']

                    })
                # logger.warning('df:%s',df.head(23))
                return df.hvplot.table(columns=['Variable 1', 'Variable 2', 'Relationship', 'r', 'p-value'],
                                       width=550, height=200, title='Correlation between variables')
            except Exception:
                logger.error('correlation table', exc_info=True)

    def update(attrname, old, new):
        thistab.notification_updater("Calculations underway. Please be patient")
        for key in thistab.vars.keys():
            thistab.vars[key] = thistab.selects[key]
        thistab.filter_df(thistab.df)
        thistab.load_menus(thistab.df)
        thistab.graph_periods_to_date(thistab.df, 'timestamp', thistab.variable)
        thistab.trigger += 1
        stream_launch.event(launch=thistab.trigger)
        stream_launch_corr.event(launch=thistab.trigger)
        thistab.notification_updater("ready")

    def update_period_over_period():
        thistab.notification_updater("Calculations underway. Please be patient")
        thistab.pop_history_periods = pop_number_select.value
        thistab.pop_start_date = thistab.datepicker_pop_start.value  # trigger period over period
        thistab.pop_end_date = datepicker_pop_end.value
        thistab.trigger += 1
        stream_launch.event(launch=thistab.trigger)
        stream_tsa_variable_launch.event(launch=thistab.trigger)
        thistab.multiline_variable['x'] = multiline_x_select.value
        thistab.multiline_variable['y'] = multiline_y_select.value
        thistab.trigger += 1
        stream_tsa_variable_launch.event(launch=thistab.trigger)
        thistab.notification_updater("ready")

    def update_tsa_variables():
        thistab.notification_updater("Calculations underway. Please be patient")
        for key in thistab.vars.keys():
            thistab.vars[key] = thistab.selects[key]
        thistab.filter_df(thistab.df)
        thistab.tsa_variable = tsa_variable_select.value
        thistab.forecast_days = int(select_forecast_days.value)
        thistab.trigger += 1
        stream_tsa_variable_launch.event(launch=thistab.trigger)
        thistab.notification_updater("ready")

    def update_multiline_variables():
        thistab.notification_updater("Calculations underway. Please be patient")
        for key in thistab.vars.keys():
            thistab.vars[key] = thistab.selects[key]
        thistab.filter_df(thistab.df)
        thistab.multiline_variable['x'] = multiline_x_select.value
        thistab.multiline_variable['y'] = multiline_y_select.value
        thistab.trigger += 1
        stream_multiline_variable_launch.event(launch=thistab.trigger)
        thistab.notification_updater("ready")


    try:
        cols = []
        thistab = Thistab(table='external_daily', cols=cols)
        # -------------------------------------  SETUP   ----------------------------
        # format dates
        first_date_range = thistab.initial_date
        last_date_range = datetime.now().date()
        last_date = dashboard_config['dates']['last_date']
        first_date = datetime(last_date.year, 1, 1, 0, 0, 0)

        loadcols = []
        thistab.df = thistab.load_df(first_date, last_date, loadcols, timestamp_col='timestamp')
        thistab.load_menus(thistab.df)
        thistab.filter_df(thistab.df)

        thistab.graph_periods_to_date(thistab.df, timestamp_filter_col='timestamp', variable=thistab.variable)
        thistab.section_header_updater('cards', label='')
        thistab.section_header_updater('pop', label='')

        # MANAGE STREAM
        # date comes out stream in milliseconds
        # --------------------------------CREATE WIDGETS ---------------------------------
        thistab.pop_end_date = last_date
        thistab.pop_start_date = thistab.first_date_in_period(thistab.pop_end_date, 'week')

        stream_launch = streams.Stream.define('Launch', launch=-1)()
        stream_tsa_variable_launch = streams.Stream.define('Launch', launch=-1)()
        stream_multiline_variable_launch = streams.Stream.define('Launch', launch=-1)()
        stream_launch_corr = streams.Stream.define('Launch_corr', launch=-1)()


        datepicker_pop_end = DatePicker(title="Period end", min_date=first_date_range,
                                max_date=last_date_range, value=thistab.pop_end_date)

        pop_number_select = Select(title='Select # of comparative periods',
                           value=str(5),
                           options=thistab.menus['history_periods'])
        pop_button = Button(label="Select dates/periods, then click me!", width=15, button_type="success")

        filter_button = Button(label="Select filters, then click me!", width=15, button_type="success")
        multiline_button = Button(label="Select multiline variables, then click me!", width=15, button_type="success")

        tsa_variable_select = Select(title='Select forecast variable',
                           value='rate',options=['rate','remuneration','attendance'])
        tsa_button = Button(label="Select forecast variables, then click me!", width=15, button_type="success")
        
        select_forecast_days = Select(title='Select # of days which you want forecasted',
                                      value=str(thistab.forecast_days),
                                      options=['10', '20', '30', '40', '50', '60', '70', '80', '90'])

        multiline_y_select = Select(title='Select y variable for comparison',
                             value=thistab.multiline_variable['y'], options=thistab.multiline_vars['ys'])

        multiline_x_select = Select(title='Select x variable for comparison',
                            value=thistab.multiline_variable['x'], options=thistab.multiline_vars['xs'])

        # ---------------------------------  GRAPHS ---------------------------

        hv_pop_week = hv.DynamicMap(thistab.pop_week, streams=[stream_launch])
        pop_week = renderer.get_plot(hv_pop_week)

        hv_pop_month = hv.DynamicMap(thistab.pop_month, streams=[stream_launch])
        pop_month = renderer.get_plot(hv_pop_month)

        hv_pop_quarter = hv.DynamicMap(thistab.pop_quarter, streams=[stream_launch])
        pop_quarter = renderer.get_plot(hv_pop_quarter)

        hv_tsa = hv.DynamicMap(thistab.pop_quarter, streams=[stream_tsa_variable_launch])
        tsa = renderer.get_plot(hv_tsa)

        hv_chord = hv.DynamicMap(thistab.chord_diagram, streams=[stream_launch])
        chord = renderer.get_plot(hv_chord)

        hv_patron_info = hv.DynamicMap(thistab.patron_info_table, streams=[stream_launch])
        patron_info = renderer.get_plot(hv_patron_info)

        hv_corr_table = hv.DynamicMap(thistab.correlation_table,streams=[stream_launch_corr])
        corr_table = renderer.get_plot(hv_patron_info)

        # -------------------------------- CALLBACKS ------------------------

        filter_button.on_click(update)
        pop_button.on_click(update_period_over_period)  # lags array
        tsa_button.on_click(update_tsa_variables)
        multiline_button.on_click(update_multiline_variables)

        # controls
        controls_multiline_ = WidgetBox(
            multiline_x_select,
            multiline_y_select,
            multiline_button
        )

        controls_tsa = WidgetBox(
            tsa_variable_select,
            select_forecast_days,
            tsa_button

        )
        
        controls_pop = WidgetBox(
            pop_button,
        )
        
        controls_filters = WidgetBox(
            thistab.selects['event'],
            thistab.selects['company'],
            thistab.selects['patron'],
            thistab.selects['patron_likes'],
            thistab.selects['manager_education'],
            thistab.selects['staff_education'],
            thistab.selects['manager_gender'],
            thistab.selects['staff_gender'],
            thistab.selects['patron_gender'],
            thistab.selects['manager_parish'],
            thistab.selects['staff_parish'],
            thistab.selects['patron_parish'],
            thistab.selects['type'],
        )

        # create the dashboards
        grid_data = [
            [thistab.notification_div['top']],
            [Spacer(width=20, height=40)],
            [thistab.section_headers['correlations']],
            [Spacer(width=20, height=25)],
            [corr_table.state, controls_filters],
            [thistab.section_headers['cards']],
            [Spacer(width=20, height=2)],
            [thistab.KPI_card_div],
            [thistab.section_headers['pop']],
            [Spacer(width=20, height=25)],
            [pop_week.state, controls_pop],
            [pop_month.state],
            [pop_quarter.state],
            [thistab.section_headers['patron info']],
            [Spacer(width=20, height=25)],
            [patron_info.state],
            [chord.state],
            [thistab.section_headers['tsa']],
            [Spacer(width=20, height=25)],
            [tsa.state,controls_tsa],
            [thistab.notification_div['bottom']]
        ]


    except Exception:
        logger.error('rendering err:', exc_info=True)
        return tab_error_flag(panel_title)

