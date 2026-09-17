from data_fetcher import StockDataFetcher
import datetime

def to_float(val, default=0):
    try:
        return float(val) if val is not None and val != '' else default
    except (ValueError, TypeError):
        return default

def to_int(val, default=0):
    try:
        return int(float(val)) if val is not None and val != '' else default
    except (ValueError, TypeError):
        return default

def safe_div(a, b, default=0):
    """安全除法，分母为0时返回default"""
    try:
        return a / b if b != 0 else default
    except (TypeError, ZeroDivisionError):
        return default

def calc_gain_percent(stock):
    """根据行情快照计算涨幅（%）。
    东方财富 clist 接口 fltt=2 下 f3 已直接是百分比（如 4.89 表示 +4.89%），
    f2 现价、f18 昨收均已直接是元，无需再除以100。
    """
    f3 = to_float(stock.get('f3'))
    if f3 != 0:
        return f3
    price = to_float(stock.get('f2'))
    prev_close = to_float(stock.get('f18'))
    if prev_close > 0:
        return (price - prev_close) / prev_close * 100
    return 0.0

class StockFilter:
    def __init__(self):
        self.fetcher = StockDataFetcher()

    def get_market_status(self):
        """获取当前市场状态"""
        now = datetime.datetime.now()
        hour = now.hour
        minute = now.minute
        weekday = now.weekday()

        if weekday >= 5:
            return 'after_market'

        total_minutes = hour * 60 + minute

        if total_minutes < 9 * 60 + 15:
            return 'before_market'
        elif total_minutes < 9 * 60 + 20:
            return 'collection_bidding_1'
        elif total_minutes < 9 * 60 + 25:
            return 'collection_bidding_2'
        elif total_minutes < 9 * 60 + 30:
            return 'collection_bidding_2'
        elif total_minutes < 11 * 60 + 30:
            return 'continuous_trading_morning'
        elif total_minutes < 13 * 60:
            return 'lunch_break'
        elif total_minutes < 14 * 60 + 57:
            return 'continuous_trading_afternoon'
        elif total_minutes < 15 * 60:
            return 'auction_trading_afternoon'
        else:
            return 'after_market'

    def filter_auction_momentum(self, snapshot_924=None,
                                amount_threshold=10000000,
                                gain_min=3.0, gain_max=8.0,
                                gain_diff_threshold=2.0):
        """
        早盘集合竞价选股（尾盘拉升型）：
        1. 竞价金额 > amount_threshold（元，默认1000万）
        2. 竞价涨幅 >= gain_min 且 <= gain_max（默认 3% ~ 8%）
        3. 9:25 涨幅 - 9:24 涨幅 >= gain_diff_threshold（默认 2%，即最后一分钟至少拉升2%）

        参数:
            snapshot_924: 9:24 分时的行情快照列表（东方财富 clist 格式），用于对比最后一分钟拉升
        """
        bidding_data = self.fetcher.get_collection_bidding()
        if not bidding_data:
            return []

        # 范围过滤：仅沪深主板 + 创业板，排除ST
        scoped_data = []
        for stock in bidding_data:
            code = str(stock.get('f12', ''))
            name = str(stock.get('f14', ''))
            if self.is_in_scope(code) and not self.is_st_stock(name):
                scoped_data.append(stock)
        bidding_data = scoped_data

        # 构建 9:24 涨幅映射 {code: gain_percent}
        gain_924_map = {}
        if snapshot_924:
            for stock in snapshot_924:
                code = str(stock.get('f12', ''))
                if code:
                    gain_924_map[code] = calc_gain_percent(stock)

        candidates = []
        for stock in bidding_data:
            code = str(stock.get('f12', ''))
            name = str(stock.get('f14', ''))
            price = to_float(stock.get('f2'))            # 现价（元）
            prev_close = to_float(stock.get('f18'))      # 昨收（元）
            amount = to_float(stock.get('f6'))           # 成交额（元）
            gain = calc_gain_percent(stock)

            # 条件1：竞价金额 > 阈值
            if amount <= amount_threshold:
                continue

            # 条件2：竞价涨幅在区间内
            if gain < gain_min or gain > gain_max:
                continue

            # 条件3：9:25 较 9:24 拉升 >= gain_diff_threshold
            if snapshot_924 is not None:
                gain_924 = gain_924_map.get(code)
                if gain_924 is None:
                    continue
                gain_diff = gain - gain_924
                if gain_diff < gain_diff_threshold:
                    continue
            else:
                gain_924 = None
                gain_diff = None

            candidates.append({
                'code': code,
                'name': name,
                'price': price,
                'prev_close': prev_close,
                'amount': amount,
                'gain': gain,
                'gain_924': gain_924,
                'gain_diff': gain_diff,
            })

        if not candidates:
            return []

        codes = [c['code'] for c in candidates]
        plate_info = self.fetcher.get_stock_plates_batch(codes)

        results = []
        for c in candidates:
            plate = plate_info.get(c['code'], {})
            results.append({
                'code': c['code'],
                'name': c['name'],
                'price': round(c['price'], 2),
                'prev_close': round(c['prev_close'], 2),
                'amount': round(c['amount'] / 10000, 2),  # 转为万元展示
                'gain': round(c['gain'], 2),
                'gain_924': round(c['gain_924'], 2) if c['gain_924'] is not None else None,
                'gain_diff': round(c['gain_diff'], 2) if c['gain_diff'] is not None else None,
                'industry': plate.get('industry', ''),
                'concept': plate.get('concept', '')
            })

        results.sort(key=lambda x: x['gain'] if x['gain_diff'] is None else x['gain_diff'], reverse=True)
        return results

    @staticmethod
    def is_in_scope(code):
        """判断是否为沪深主板或创业板（不含科创板、北交所）"""
        if not code or len(code) < 3:
            return False
        prefix3 = code[:3]
        # 沪市主板: 600,601,603,605  深市主板: 000,001,002,003  创业板: 300,301
        return prefix3 in ('600', '601', '603', '605', '000', '001', '002', '003', '300', '301')

    @staticmethod
    def is_st_stock(name):
        """判断是否为ST股"""
        return 'ST' in name or 'st' in name

    @staticmethod
    def get_limit_up_pct(code):
        """根据板块返回涨停涨幅阈值（%）"""
        if code and (code.startswith('300') or code.startswith('301')):
            return 19.5  # 创业板 20% 涨停
        return 9.8  # 主板 10% 涨停

    @staticmethod
    def _sort_klines(klines):
        """按日期升序排序K线（最旧在前，最新在后）"""
        return sorted(klines, key=lambda k: k.get('date', ''))

    @staticmethod
    def is_doji(kline):
        """十字星：实体占振幅比例 <= 15%"""
        open_p = kline.get('open', 0)
        close_p = kline.get('close', 0)
        high_p = kline.get('high', 0)
        low_p = kline.get('low', 0)
        if high_p <= low_p:
            return False
        body_size = abs(close_p - open_p)
        range_size = high_p - low_p
        return safe_div(body_size, range_size) <= 0.15

    @staticmethod
    def is_inverted_t(kline):
        """倒T：上影线长，实体小，下影线短"""
        open_p = kline.get('open', 0)
        close_p = kline.get('close', 0)
        high_p = kline.get('high', 0)
        low_p = kline.get('low', 0)
        if high_p <= low_p:
            return False
        body_top = max(open_p, close_p)
        upper_shadow = high_p - body_top
        lower_shadow = min(open_p, close_p) - low_p
        body_size = abs(close_p - open_p)
        range_size = high_p - low_p
        return (safe_div(upper_shadow, range_size) >= 0.6
                and safe_div(body_size, range_size) <= 0.3
                and lower_shadow <= body_size)

    @staticmethod
    def is_small_bearish(kline):
        """小阴线：收阴且实体较小（实体占振幅 <= 50%，且实体/昨收 <= 1%）"""
        open_p = kline.get('open', 0)
        close_p = kline.get('close', 0)
        high_p = kline.get('high', 0)
        low_p = kline.get('low', 0)
        prev_close = kline.get('prev_close', 0) or open_p
        if close_p >= open_p:
            return False
        if high_p <= low_p:
            return False
        body_size = open_p - close_p
        range_size = high_p - low_p
        body_ratio = safe_div(body_size, range_size)
        body_pct = safe_div(body_size, prev_close) * 100
        return body_ratio <= 0.5 and body_pct <= 1.0

    def _calc_ma(self, klines, period, end_idx):
        """计算 end_idx 位置（含）往前 period 天的收盘价均线，klines 已升序"""
        if end_idx < period - 1 or end_idx >= len(klines):
            return None
        closes = [klines[i].get('close', 0) for i in range(end_idx - period + 1, end_idx + 1)]
        if any(c <= 0 for c in closes):
            return None
        return sum(closes) / period

    def filter_late_session(self, lookback=20):
        """
        尾盘选股（14:55），包含两个方案：

        方案1 - 涨停后缩量回踩：
          1. 最近15个交易日有过涨停
          2. 涨停后未跌破涨停日最低价
          3. 今日收十字星 / 倒T / 小阴线
          4. 今日成交量 <= 近15日最大成交量的 1/3

        方案2 - 连阳承接不破均线：
          1. 连续6个交易日及以上收阳
          2. 当前价 < 近阶段最高价
          3. 今日最低价 > 昨日收盘价
          4. 切分有承接（收盘价在当日振幅上半区）
          5. 不破5日均线

        范围：仅沪深主板 + 创业板，排除ST。
        """
        bidding_data = self.fetcher.get_collection_bidding()
        if not bidding_data:
            return []

        # 范围过滤：沪深主板 + 创业板，排除ST
        filtered_stocks = []
        for stock in bidding_data:
            code = str(stock.get('f12', ''))
            name = str(stock.get('f14', ''))
            if not self.is_in_scope(code) or self.is_st_stock(name):
                continue
            filtered_stocks.append(stock)

        if not filtered_stocks:
            return []

        codes = [str(s.get('f12', '')) for s in filtered_stocks]
        kline_info = self.fetcher.get_kline_data_batch(codes, lookback)

        candidates = []
        for stock in filtered_stocks:
            code = str(stock.get('f12', ''))
            name = str(stock.get('f14', ''))
            raw_klines = kline_info.get(code, [])
            if len(raw_klines) < 10:
                continue

            klines = self._sort_klines(raw_klines)
            today = klines[-1]
            current_price = to_float(stock.get('f2'))  # 现价（元，fltt=2 无需除100）

            # ===== 方案1：涨停后缩量回踩 =====
            scheme1 = self._check_scheme1(code, klines, today, current_price)
            if scheme1:
                scheme1['code'] = code
                scheme1['name'] = name
                scheme1['current_price'] = current_price
                scheme1['scheme'] = '方案1'
                candidates.append(scheme1)
                continue  # 满足方案1则不再检查方案2，避免重复

            # ===== 方案2：连阳承接不破均线 =====
            scheme2 = self._check_scheme2(klines, today, current_price)
            if scheme2:
                scheme2['code'] = code
                scheme2['name'] = name
                scheme2['current_price'] = current_price
                scheme2['scheme'] = '方案2'
                candidates.append(scheme2)

        if not candidates:
            return []

        plate_codes = [c['code'] for c in candidates]
        plate_info = self.fetcher.get_stock_plates_batch(plate_codes)

        results = []
        for c in candidates:
            plate = plate_info.get(c['code'], {})
            results.append({
                'code': c['code'],
                'name': c['name'],
                'current_price': round(c['current_price'], 2),
                'open': round(c.get('open', 0), 2),
                'high': round(c.get('high', 0), 2),
                'low': round(c.get('low', 0), 2),
                'pattern': c.get('pattern', ''),
                'scheme': c['scheme'],
                'industry': plate.get('industry', ''),
                'concept': plate.get('concept', '')
            })

        results.sort(key=lambda x: (x['scheme'], x['current_price']), reverse=True)
        return results

    def _check_scheme1(self, code, klines, today, current_price):
        """方案1：涨停后缩量回踩"""
        limit_up_pct = self.get_limit_up_pct(code)
        last15 = klines[-15:] if len(klines) >= 15 else klines

        # 1. 最近15日有过涨停
        limit_up_idx = None
        for i in range(len(last15) - 1):  # 不含今日
            if last15[i].get('change_percent', 0) >= limit_up_pct:
                limit_up_idx = i
        if limit_up_idx is None:
            return None

        limit_up_day = last15[limit_up_idx]
        limit_up_low = limit_up_day.get('low', 0)

        # 2. 涨停后（含今日）未跌破涨停日最低价
        after_limit = last15[limit_up_idx:]
        for k in after_limit:
            if k.get('low', 0) < limit_up_low:
                return None

        # 3. 今日收十字星 / 倒T / 小阴线
        today_k = today
        is_doji = self.is_doji(today_k)
        is_inv_t = self.is_inverted_t(today_k)
        # 小阴线需要昨收，用昨日收盘价
        if len(klines) >= 2:
            today_k = dict(today)
            today_k['prev_close'] = klines[-2].get('close', 0)
        is_small_bear = self.is_small_bearish(today_k)

        pattern = None
        if is_doji:
            pattern = '十字星'
        elif is_inv_t:
            pattern = '倒T'
        elif is_small_bear:
            pattern = '小阴线'
        if pattern is None:
            return None

        # 4. 今日成交量 <= 近15日最大成交量的 1/3
        volumes = [k.get('volume', 0) for k in last15]
        max_vol = max(volumes) if volumes else 0
        today_vol = today.get('volume', 0)
        if max_vol > 0 and today_vol > max_vol / 3:
            return None

        return {
            'open': today.get('open', 0),
            'high': today.get('high', 0),
            'low': today.get('low', 0),
            'pattern': pattern,
            'volume': today_vol,
            'max_volume_15d': max_vol,
        }

    def _check_scheme2(self, klines, today, current_price):
        """方案2：连阳承接不破均线"""
        # 1. 连续6个交易日及以上收阳（close > open），允许今日为连阳的一部分或回调日
        # 从今日往前找连续阳线
        bullish_run = 0
        run_start_idx = len(klines) - 1
        for i in range(len(klines) - 1, -1, -1):
            k = klines[i]
            if k.get('close', 0) > k.get('open', 0):
                bullish_run += 1
                run_start_idx = i
            else:
                break

        # 若今日非阳线，则从昨日往前找连阳
        if bullish_run < 6:
            bullish_run = 0
            run_start_idx = len(klines) - 2
            for i in range(len(klines) - 2, -1, -1):
                k = klines[i]
                if k.get('close', 0) > k.get('open', 0):
                    bullish_run += 1
                    run_start_idx = i
                else:
                    break

        if bullish_run < 6:
            return None

        # 连阳区间（含今日或到昨日）
        run_end_idx = len(klines) - 1
        run_klines = klines[run_start_idx:run_end_idx + 1]

        # 2. 当前价 < 近阶段最高价
        highest = max(k.get('high', 0) for k in run_klines)
        if current_price >= highest:
            return None

        # 3. 今日最低价 > 昨日收盘价
        if len(klines) < 2:
            return None
        yest_close = klines[-2].get('close', 0)
        if today.get('low', 0) <= yest_close:
            return None

        # 4. 切分有承接：收盘价在当日振幅上半区（close > (high+low)/2）
        mid = (today.get('high', 0) + today.get('low', 0)) / 2
        if today.get('close', 0) <= mid:
            return None

        # 5. 不破5日均线
        ma5 = self._calc_ma(klines, 5, len(klines) - 1)
        if ma5 is not None and today.get('close', 0) < ma5:
            return None

        return {
            'open': today.get('open', 0),
            'high': today.get('high', 0),
            'low': today.get('low', 0),
            'pattern': f'{bullish_run}连阳',
            'bullish_days': bullish_run,
            'ma5': round(ma5, 2) if ma5 else None,
        }
