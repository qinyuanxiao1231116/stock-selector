from data_fetcher import StockDataFetcher
import datetime
import logging

logger = logging.getLogger(__name__)

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

    注意（集合竞价哨兵值）：
    9:15-9:25 集合竞价阶段，对尚无有效竞价撮合的股票，东方财富返回的不是 0，
    而是哨兵值 f3=-100（部分情况下 f2 也为 0）。此时：
      - 绝不能直接用 f3（会得到 -100%，进而让"拉升"虚高到 100+）
      - 必须校验 f3 是否在 A 股合理涨跌幅区间内
      - f3 无效时回退用 f2/f18 计算；若 f2 也为 0（无竞价价），返回 0
    """
    f3 = to_float(stock.get('f3'))
    # A股含科创板快照，涨跌幅上限 ±20%，留余量取 ±21%；超出即判定为哨兵/无效值
    if -21.0 <= f3 <= 21.0 and f3 != 0:
        return f3

    price = to_float(stock.get('f2'))
    prev_close = to_float(stock.get('f18'))
    if price > 0 and prev_close > 0:
        gain = (price - prev_close) / prev_close * 100
        # 用 f2/f18 算出的结果同样做合理性校验，避免脏数据
        if -21.0 <= gain <= 21.0:
            return gain

    # 9:24集合竞价阶段 f2(现价) 可能为0（未最终撮合），
    # 此时用 f17(虚拟开盘价/竞价价) 计算涨幅
    open_price = to_float(stock.get('f17'))
    if open_price > 0 and prev_close > 0:
        gain = (open_price - prev_close) / prev_close * 100
        if -21.0 <= gain <= 21.0:
            return gain
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
                                amount_threshold=20000000,
                                gain_min=3.0, gain_max=8.0,
                                gain_diff_threshold=2.0,
                                float_mv_max=20000000000,
                                amount_ratio_threshold=1.5,
                                scheme2_min_gain=0.0,
                                scheme2_volume_ratio=2.0):
        """
        早盘集合竞价选股，包含两个方案：

        方案1 - 竞价拉升型：
          1. 竞价金额 >= amount_threshold（元，默认2000万）
          2. 竞价涨幅 >= gain_min 且 <= gain_max（默认 3% ~ 8%）
          3. 9:25 较 9:24 拉升判断：
             - 若9:24有有效价格(f2>0或f17>0)：9:25涨幅 - 9:24涨幅 >= gain_diff_threshold（默认3%）
             - 若9:24无有效价格：用竞价金额增幅判断或跳过
          4. 流通市值 <= float_mv_max（元，默认200亿）

        方案2 - 涨停次日竞价型：
          1. 昨日收盘涨停放巨量（量比>=2）或炸板
          2. 今日9:25涨幅 >= scheme2_min_gain（默认0%）

        参数:
            snapshot_924: 9:24 分时的行情快照列表
            scheme2_min_gain: 方案2今日竞价涨幅下限（%，默认0）
            scheme2_volume_ratio: 方案2放巨量的量比阈值（默认2.0）
        """
        bidding_data = self.fetcher.get_collection_bidding()
        if not bidding_data:
            return []

        # 范围过滤：仅沪深主板，排除ST
        scoped_data = []
        for stock in bidding_data:
            code = str(stock.get('f12', ''))
            name = str(stock.get('f14', ''))
            if self.is_in_scope(code) and not self.is_st_stock(name):
                scoped_data.append(stock)
        bidding_data = scoped_data

        # 构建 code -> 行情 映射（供方案2快速查找）
        bidding_map = {}
        for stock in bidding_data:
            code = str(stock.get('f12', ''))
            if code:
                bidding_map[code] = stock

        results = []

        # ===== 方案1：竞价拉升型 =====
        results.extend(self._filter_auction_scheme1(
            bidding_data, snapshot_924,
            amount_threshold, gain_min, gain_max,
            gain_diff_threshold, float_mv_max, amount_ratio_threshold
        ))

        # ===== 方案2：涨停次日竞价型 =====
        scheme2_results = self._filter_auction_scheme2(
            bidding_map, scheme2_min_gain, scheme2_volume_ratio
        )
        # 去重：方案2中已被方案1选中的股票不重复
        scheme1_codes = {r['code'] for r in results}
        for r in scheme2_results:
            if r['code'] not in scheme1_codes:
                results.append(r)

        return results

    def _filter_auction_scheme1(self, bidding_data, snapshot_924,
                                amount_threshold, gain_min, gain_max,
                                gain_diff_threshold, float_mv_max, amount_ratio_threshold):
        """方案1：竞价拉升型"""
        # 构建 9:24 映射：涨幅、金额、是否有有效价格
        gain_924_map = {}
        amount_924_map = {}
        has_price_924_map = {}
        if snapshot_924:
            for stock in snapshot_924:
                code = str(stock.get('f12', ''))
                if not code:
                    continue
                gain_924_map[code] = calc_gain_percent(stock)
                amount_924_map[code] = to_float(stock.get('f6'))
                f2 = to_float(stock.get('f2'))
                f17 = to_float(stock.get('f17'))
                has_price_924_map[code] = (f2 > 0 or f17 > 0)

        candidates = []
        for stock in bidding_data:
            code = str(stock.get('f12', ''))
            name = str(stock.get('f14', ''))
            price = to_float(stock.get('f2'))
            prev_close = to_float(stock.get('f18'))
            amount = to_float(stock.get('f6'))
            gain = calc_gain_percent(stock)
            float_mv = to_float(stock.get('f21'))

            if amount < amount_threshold:
                continue
            if gain < gain_min or gain > gain_max:
                continue
            if float_mv > float_mv_max:
                continue

            gain_diff = None
            gain_924 = None
            gain_924_valid = False
            amount_ratio = None
            if snapshot_924 is not None:
                if code not in gain_924_map:
                    continue
                gain_924 = gain_924_map[code]
                has_price_924 = has_price_924_map.get(code, False)

                if has_price_924:
                    gain_924_valid = True
                    gain_diff = gain - gain_924
                    if gain_diff < gain_diff_threshold:
                        continue
                else:
                    amount_924 = amount_924_map.get(code, 0)
                    if amount_924 > 0:
                        amount_ratio = safe_div(amount, amount_924)
                        if amount_ratio < amount_ratio_threshold:
                            continue
                    else:
                        # 9:22既无有效价格也无金额，无法判断拉升，跳过
                        continue

            candidates.append({
                'code': code, 'name': name, 'price': price,
                'prev_close': prev_close, 'amount': amount, 'gain': gain,
                'gain_924': gain_924, 'gain_924_valid': gain_924_valid,
                'gain_diff': gain_diff,
                'amount_ratio': amount_ratio, 'float_mv': float_mv,
                'industry_raw': str(stock.get('f100', '') or ''),
                'scheme': '方案1',
            })

        if not candidates:
            return []

        codes = [c['code'] for c in candidates]
        plate_info = self.fetcher.get_stock_plates_batch(codes)

        results = []
        for c in candidates:
            plate = plate_info.get(c['code'], {})
            results.append({
                'code': c['code'], 'name': c['name'],
                'price': round(c['price'], 2),
                'prev_close': round(c['prev_close'], 2),
                'amount': round(c['amount'] / 10000, 2),
                'gain': round(c['gain'], 2),
                'gain_924': round(c['gain_924'], 2) if c['gain_924_valid'] and c['gain_924'] is not None else None,
                'gain_diff': round(c['gain_diff'], 2) if c['gain_diff'] is not None else None,
                'amount_ratio': round(c['amount_ratio'], 2) if c.get('amount_ratio') is not None else None,
                'float_mv': round(c.get('float_mv', 0), 2),
                'industry': c.get('industry_raw') or plate.get('industry', ''),
                'concept': plate.get('concept', ''),
                'scheme': '方案1',
            })

        results.sort(key=lambda x: x['gain'] if x['gain_diff'] is None else x['gain_diff'], reverse=True)
        return results

    def _filter_auction_scheme2(self, bidding_map, min_gain, volume_ratio_threshold):
        """方案2：涨停次日竞价型。
        1. 昨日收盘涨停放巨量（量比>=volume_ratio_threshold）或炸板
        2. 今日9:25涨幅 >= min_gain
        """
        # 获取昨日涨停板股票池
        limit_up_pool = self.fetcher.get_limit_up_pool()
        if not limit_up_pool:
            return []

        candidates = []
        for item in limit_up_pool:
            code = item['code']
            # 范围过滤：仅沪深主板，排除ST
            if not self.is_in_scope(code):
                continue
            if self.is_st_stock(item.get('name', '')):
                continue
            # 条件1：昨日涨停放巨量 或 炸板
            is_huge_volume = item.get('volume_ratio', 0) >= volume_ratio_threshold
            is_burst = item.get('is_burst', False)
            is_limit_up = item.get('is_limit_up', False)
            if not ((is_limit_up and is_huge_volume) or is_burst):
                continue
            # 条件2：今日竞价涨幅 >= min_gain
            stock = bidding_map.get(code)
            if not stock:
                continue
            gain = calc_gain_percent(stock)
            if gain < min_gain:
                continue

            price = to_float(stock.get('f2'))
            prev_close = to_float(stock.get('f18'))
            amount = to_float(stock.get('f6'))
            float_mv = to_float(stock.get('f21'))

            candidates.append({
                'code': code,
                'name': item.get('name', ''),
                'price': price,
                'prev_close': prev_close,
                'amount': amount,
                'gain': gain,
                'float_mv': float_mv,
                'industry_raw': str(stock.get('f100', '') or ''),
                'scheme': '方案2',
                'yesterday_change_pct': item.get('change_pct', 0),
                'yesterday_volume_ratio': item.get('volume_ratio', 0),
                'yesterday_is_burst': is_burst,
            })

        if not candidates:
            return []

        codes = [c['code'] for c in candidates]
        plate_info = self.fetcher.get_stock_plates_batch(codes)

        results = []
        for c in candidates:
            plate = plate_info.get(c['code'], {})
            results.append({
                'code': c['code'], 'name': c['name'],
                'price': round(c['price'], 2),
                'prev_close': round(c['prev_close'], 2),
                'amount': round(c['amount'] / 10000, 2),
                'gain': round(c['gain'], 2),
                'gain_924': None,
                'gain_diff': None,
                'amount_ratio': None,
                'float_mv': round(c.get('float_mv', 0), 2),
                'industry': c.get('industry_raw') or plate.get('industry', ''),
                'concept': plate.get('concept', ''),
                'scheme': '方案2',
                'yesterday_change_pct': round(c['yesterday_change_pct'], 2),
                'yesterday_volume_ratio': round(c['yesterday_volume_ratio'], 2),
                'yesterday_is_burst': c['yesterday_is_burst'],
            })

        results.sort(key=lambda x: x['gain'], reverse=True)
        return results

    @staticmethod
    def is_in_scope(code):
        """判断是否为沪深主板（不含创业板、科创板、北交所）"""
        if not code or len(code) < 3:
            return False
        prefix3 = code[:3]
        # 沪市主板: 600,601,603,605  深市主板: 000,001,002,003
        return prefix3 in ('600', '601', '603', '605', '000', '001', '002', '003')

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
        """倒T（倒T字线）：收盘≈最低（下影线极短，底部平整），上影线长，实体小。
        即 ⊥ 形状：底部一横，上面一竖，下影线不应出头。
        """
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
        # 上影线 >= 60% 振幅；实体 <= 30% 振幅；下影线 <= 10% 振幅（底部几乎平整）
        return (safe_div(upper_shadow, range_size) >= 0.6
                and safe_div(body_size, range_size) <= 0.3
                and safe_div(lower_shadow, range_size) <= 0.1)

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

        方案1 - 涨停后回踩EXPMA10缩量，次日收十字星/倒T：
          1. 最近15个交易日有过涨停
          2. 涨停后未跌破涨停日最低价
          3. 昨日回踩EXPMA10 + 收十字星/倒T
          4. 昨日缩量：成交量 <= 涨停回调期间最大量的1/2
          5. 今日收十字星/倒T（不要求放量上涨）

        方案2 - 连阳承接不破均线：
          1. 连续6个交易日及以上收阳
          2. 当前价 < 近阶段最高价
          3. 今日最低价 > 昨日收盘价
          4. 切分有承接（收盘价在当日振幅上半区）
          5. 不破5日均线

        范围：仅沪深主板，排除创业板/ST。
        """
        bidding_data = self.fetcher.get_collection_bidding()
        if not bidding_data:
            return []

        # 范围过滤：沪深主板，排除ST
        filtered_stocks = []
        for stock in bidding_data:
            code = str(stock.get('f12', ''))
            name = str(stock.get('f14', ''))
            if not self.is_in_scope(code) or self.is_st_stock(name):
                continue
            filtered_stocks.append(stock)

        if not filtered_stocks:
            return []

        # ===== 实时行情粗筛：减少K线请求量（从2000+只降到几百只）=====
        # 方案1和方案2的今日形态都不是涨停/跌停，且需要一定振幅
        pre_filtered = []
        for stock in filtered_stocks:
            gain = calc_gain_percent(stock)
            high = to_float(stock.get('f15'))
            low = to_float(stock.get('f16'))
            pre_close = to_float(stock.get('f18'))
            price = to_float(stock.get('f2'))
            # 排除涨停、跌停
            if gain >= 9.5 or gain <= -9.5:
                continue
            # 排除价格异常
            if price <= 0 or pre_close <= 0:
                continue
            # 排除振幅过小（十字星/倒T/连阳都需要一定振幅）
            if high > 0 and low > 0 and (high - low) / pre_close < 0.008:
                continue
            pre_filtered.append(stock)

        logger.info(f"尾盘粗筛: {len(filtered_stocks)}只 → {len(pre_filtered)}只（排除涨跌停+振幅过小）")
        filtered_stocks = pre_filtered

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
            today_gain = calc_gain_percent(stock)       # 当日涨幅（%）

            # ===== 方案1：涨停后缩量回踩 =====
            scheme1 = self._check_scheme1(code, klines, today, current_price)
            if scheme1:
                scheme1['code'] = code
                scheme1['name'] = name
                scheme1['current_price'] = current_price
                scheme1['gain'] = today_gain
                scheme1['industry_raw'] = str(stock.get('f100', '') or '')  # 行情自带行业
                scheme1['scheme'] = '方案1'
                candidates.append(scheme1)
                continue  # 满足方案1则不再检查方案2，避免重复

            # ===== 方案2：连阳承接不破均线 =====
            scheme2 = self._check_scheme2(klines, today, current_price)
            if scheme2:
                scheme2['code'] = code
                scheme2['name'] = name
                scheme2['current_price'] = current_price
                scheme2['gain'] = today_gain
                scheme2['industry_raw'] = str(stock.get('f100', '') or '')  # 行情自带行业
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
                'gain': round(c.get('gain', 0), 2),
                'open': round(c.get('open', 0), 2),
                'pattern': c.get('pattern', ''),
                'scheme': c['scheme'],
                'industry': c.get('industry_raw') or plate.get('industry', ''),
                'concept': plate.get('concept', '')
            })

        results.sort(key=lambda x: (x['scheme'], x['current_price']), reverse=True)
        return results

    @staticmethod
    def _calc_expma(klines, period=10):
        """计算EXPMA（指数移动平均），返回与klines等长的列表，不足period的位置为None"""
        n = len(klines)
        if n < period:
            return [None] * n
        multiplier = 2.0 / (period + 1)
        expma = [None] * (period - 1)
        # 用前 period 天收盘价均值初始化
        init_sum = sum(klines[i].get('close', 0) for i in range(period))
        expma.append(init_sum / period)
        # 后续用 EMA 递推
        for i in range(period, n):
            prev = expma[-1]
            close = klines[i].get('close', 0)
            expma.append(close * multiplier + prev * (1 - multiplier))
        return expma

    def _check_scheme1(self, code, klines, today, current_price):
        """方案1：涨停后回踩EXPMA10缩量，次日收十字星/倒T
        1. 近15日有涨停（不含今日）
        2. 涨停后不破涨停日最低价
        3. 昨日回踩EXPMA10 + 收十字星/倒T
        4. 昨日缩量：成交量 <= 涨停回调期间最大量的1/2
        5. 今日收十字星或倒T（不要求放量上涨）
        """
        # 至少需要3天K线（前天、昨天、今天）
        if len(klines) < 3:
            return None

        limit_up_pct = self.get_limit_up_pct(code)
        last15 = klines[-15:] if len(klines) >= 15 else klines

        # 1. 近15日有涨停（不含今日）
        limit_up_idx = None
        for i in range(len(last15) - 1):
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

        # 3. 计算EXPMA10
        expma10 = self._calc_expma(klines, 10)
        expma_yesterday = expma10[-2] if len(expma10) >= 2 else None
        if expma_yesterday is None:
            return None

        yesterday = klines[-2]

        # 4. 昨日回踩EXPMA10（最低价触及或跌破EXPMA10）
        if yesterday.get('low', 0) > expma_yesterday:
            return None

        # 5. 昨日收十字星或倒T
        yest_doji = self.is_doji(yesterday)
        yest_inv_t = self.is_inverted_t(yesterday)
        if not (yest_doji or yest_inv_t):
            return None

        # 6. 昨日缩量：成交量 <= 涨停回调期间（涨停次日~昨日）最大量的1/2
        yest_vol = yesterday.get('volume', 0)
        pullback = last15[limit_up_idx + 1:-1]  # 涨停次日到昨日（不含今日）
        pullback_vols = [k.get('volume', 0) for k in pullback] if pullback else []
        max_pullback_vol = max(pullback_vols) if pullback_vols else 0
        if max_pullback_vol > 0 and yest_vol > max_pullback_vol * 0.5:
            return None

        # 7. 今日收十字星或倒T（去掉放量上涨条件）
        today_doji = self.is_doji(today)
        today_inv_t = self.is_inverted_t(today)
        if not (today_doji or today_inv_t):
            return None
        today_pattern = '十字星' if today_doji else '倒T'

        return {
            'open': today.get('open', 0),
            'pattern': today_pattern,
            'volume': today.get('volume', 0),
            'max_volume_pullback': max_pullback_vol,
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
