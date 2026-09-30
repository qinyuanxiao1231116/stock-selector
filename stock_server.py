import sys
import os
import time
import datetime
import logging
import requests

# 尝试导入 chinese_calendar（自动获取中国法定节假日，每年随库更新）
try:
    import chinese_calendar
    HAS_CHINESE_CALENDAR = True
except ImportError:
    HAS_CHINESE_CALENDAR = False

# 配置常量（带默认值兜底，避免服务器 config.py 未更新导致 ImportError）
import config as _cfg

SEND_KEYS = getattr(_cfg, 'SEND_KEYS', [])
WXPUSHER_APP_TOKEN = getattr(_cfg, 'WXPUSHER_APP_TOKEN', '')
WXPUSHER_UIDS = getattr(_cfg, 'WXPUSHER_UIDS', [])
LOG_FILE = getattr(_cfg, 'LOG_FILE', 'stock_selector.log')

# 早盘集合竞价条件
AUCTION_AMOUNT_THRESHOLD = getattr(_cfg, 'AUCTION_AMOUNT_THRESHOLD', 20000000)  # 2000万
AUCTION_GAIN_MIN = getattr(_cfg, 'AUCTION_GAIN_MIN', 3.0)
AUCTION_GAIN_MAX = getattr(_cfg, 'AUCTION_GAIN_MAX', 8.0)
AUCTION_GAIN_DIFF_THRESHOLD = getattr(_cfg, 'AUCTION_GAIN_DIFF_THRESHOLD', 2.0)
AUCTION_AMOUNT_RATIO_THRESHOLD = getattr(_cfg, 'AUCTION_AMOUNT_RATIO_THRESHOLD', 1.5)
AUCTION_FLOAT_MV_MAX = getattr(_cfg, 'AUCTION_FLOAT_MV_MAX', 20000000000)  # 200亿
AUCTION_SCHEME2_MIN_GAIN = getattr(_cfg, 'AUCTION_SCHEME2_MIN_GAIN', 0.0)  # 方案2今日涨幅下限
AUCTION_SCHEME2_VOLUME_RATIO = getattr(_cfg, 'AUCTION_SCHEME2_VOLUME_RATIO', 2.0)  # 方案2放巨量比阈值

# 尾盘选股条件
LATE_LOOKBACK_DAYS = getattr(_cfg, 'LATE_LOOKBACK_DAYS', 20)

from stock_filter import StockFilter
from wechat_notifier import WechatNotifier, WxPusherNotifier, MultiNotifier

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class StockServer:
    def __init__(self):
        self.filter = StockFilter()
        notifiers = []
        if SEND_KEYS:
            notifiers.append(WechatNotifier(SEND_KEYS))
        if WXPUSHER_APP_TOKEN and WXPUSHER_UIDS:
            notifiers.append(WxPusherNotifier(WXPUSHER_APP_TOKEN, WXPUSHER_UIDS))
        self.notifier = MultiNotifier(notifiers)
        self.is_running = True
        self.snapshot_924 = None  # 9:22 分时行情快照

    def log_and_send(self, title, content):
        logger.info(title)
        logger.info(content[:200] + '...' if len(content) > 200 else content)
        self.notifier.send_message(title, content)

    def capture_924_snapshot(self):
        """采集 9:22 分时的行情快照，用于与 9:25 最终竞价做涨幅对比。

        策略：
        1. 强制使用东方财富主源（新浪在竞价阶段现价可能为0，会导致涨幅异常）
        2. calc_gain_percent 内部已增加 f17(虚拟开盘价) 兜底
        3. 若主源采集失败，退而求其次用降级链（总比没数据好）
        """
        try:
            logger.info("=== 采集 9:22 集合竞价快照（优先东方财富主源）===")
            fetcher = self.filter.fetcher

            # 优先用东方财富主源（不降级），失败后再用降级链
            snap = self._safe_fetch_primary(fetcher)
            if not snap:
                logger.warning("东方财富主源9:22快照失败，尝试降级链...")
                snap = fetcher.get_collection_bidding()

            self.snapshot_924 = snap

            count = len(self.snapshot_924) if self.snapshot_924 else 0
            logger.info(f"9:22 快照采集完成，共 {count} 只股票")
            # 调试日志：抽样检查 f2/f3/f17/f18 字段，确认竞价数据是否已填充
            if self.snapshot_924:
                sample = self.snapshot_924[:3]
                for s in sample:
                    logger.info(f"9:22样本 {s.get('f12')} {s.get('f14')}: "
                                f"f2={s.get('f2')} f3={s.get('f3')} f17={s.get('f17')} "
                                f"f18={s.get('f18')} f21={s.get('f21')}")
        except Exception as e:
            logger.error(f"9:22 快照采集失败: {e}", exc_info=True)
            self.snapshot_924 = None

    def _safe_fetch_primary(self, fetcher):
        """安全调用东方财富主源，失败返回空列表（不降级到新浪）。"""
        try:
            return fetcher._get_collection_bidding_primary()
        except Exception as e:
            logger.warning(f"东方财富主源采集失败: {e}")
            return []

    def run_morning_selection(self):
        try:
            logger.info("=== 开始早盘集合竞价选股 ===")

            auction_stocks = self.filter.filter_auction_momentum(
                snapshot_924=self.snapshot_924,
                amount_threshold=AUCTION_AMOUNT_THRESHOLD,
                gain_min=AUCTION_GAIN_MIN,
                gain_max=AUCTION_GAIN_MAX,
                gain_diff_threshold=AUCTION_GAIN_DIFF_THRESHOLD,
                float_mv_max=AUCTION_FLOAT_MV_MAX,
                amount_ratio_threshold=AUCTION_AMOUNT_RATIO_THRESHOLD,
                scheme2_min_gain=AUCTION_SCHEME2_MIN_GAIN,
                scheme2_volume_ratio=AUCTION_SCHEME2_VOLUME_RATIO
            )

            logger.info(f"集合竞价选股结果: {len(auction_stocks)}只")

            if len(auction_stocks) > 0:
                content = self.format_auction_notification(auction_stocks)
                title = f"📈 集合竞价选股 ({datetime.datetime.now().strftime('%H:%M')})"
                self.log_and_send(title, content)
            else:
                title = f"📊 集合竞价选股 ({datetime.datetime.now().strftime('%H:%M')})"
                content = (
                    f"**时间**: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                    f"今日集合竞价暂无符合条件的股票。\n\n"
                    f"**选股条件**:\n"
                    f"- 方案1：竞价金额>={AUCTION_AMOUNT_THRESHOLD/10000:.0f}万 + 涨幅{AUCTION_GAIN_MIN}%~{AUCTION_GAIN_MAX}% + 拉升>={AUCTION_GAIN_DIFF_THRESHOLD}% + 流通市值<={AUCTION_FLOAT_MV_MAX/100000000:.0f}亿\n"
                    f"- 方案2：昨日涨停放巨量(量比>=2)或炸板 + 今日涨幅>={AUCTION_SCHEME2_MIN_GAIN}%"
                )
                logger.info("暂无符合条件的股票")
                self.notifier.send_message(title, content)

        except Exception as e:
            logger.error(f"集合竞价选股出错: {e}", exc_info=True)
            self.notifier.send_message("⚠️ 选股出错", f"集合竞价选股时发生错误: {e}")

    def run_late_session_selection(self):
        try:
            logger.info("=== 开始尾盘选股（14:48） ===")

            late_session_stocks = self.filter.filter_late_session(lookback=LATE_LOOKBACK_DAYS)
            scheme1_count = sum(1 for s in late_session_stocks if s.get('scheme') == '方案1')
            scheme2_count = sum(1 for s in late_session_stocks if s.get('scheme') == '方案2')
            logger.info(f"尾盘选股结果: 共{len(late_session_stocks)}只（方案1:{scheme1_count}只, 方案2:{scheme2_count}只）")

            if len(late_session_stocks) > 0:
                content = self.format_late_notification(late_session_stocks)
                title = f"📊 尾盘选股 ({datetime.datetime.now().strftime('%H:%M')})"
                self.log_and_send(title, content)
            else:
                title = f"📊 尾盘选股 ({datetime.datetime.now().strftime('%H:%M')})"
                content = (
                    f"**时间**: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                    f"今日尾盘暂无符合条件的股票。\n\n"
                    f"**选股条件**:\n"
                    f"- 方案1：近15日涨停 + 不破最低价 + 昨日回踩EXPMA10十字星/倒T(量≤回调期最大量1/2) + 今日十字星/倒T\n"
                    f"- 方案2：连续6日及以上收阳 + 回调有承接 + 不破5日均线\n"
                    f"- 范围：沪深主板，不含创业板/ST"
                )
                logger.info("暂无符合条件的股票")
                self.notifier.send_message(title, content)

        except Exception as e:
            logger.error(f"尾盘选股出错: {e}", exc_info=True)
            self.notifier.send_message("⚠️ 选股出错", f"尾盘选股时发生错误: {e}")

    def format_auction_notification(self, auction_stocks):
        content = "## A股集合竞价选股结果\n\n"
        content += f"**时间**: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        content += "**选股条件**:\n"
        content += f"- 方案1：竞价金额>={AUCTION_AMOUNT_THRESHOLD/10000:.0f}万 + 涨幅{AUCTION_GAIN_MIN}%~{AUCTION_GAIN_MAX}% + 拉升>={AUCTION_GAIN_DIFF_THRESHOLD}% + 流通市值<={AUCTION_FLOAT_MV_MAX/100000000:.0f}亿\n"
        content += f"- 方案2：昨日涨停放巨量(量比>=2)或炸板 + 今日涨幅>={AUCTION_SCHEME2_MIN_GAIN}%\n\n"

        scheme1 = [s for s in auction_stocks if s.get('scheme') == '方案1']
        scheme2 = [s for s in auction_stocks if s.get('scheme') == '方案2']

        if scheme1:
            content += "### 方案1：竞价拉升型\n\n"
            content += "| 代码 | 名称 | 竞价价 | 涨幅(%) | 9:22涨幅(%) | 拉升 | 竞价金额(万) | 流通市值(亿) | 行业 |\n"
            content += "|------|------|--------|---------|-------------|------|--------------|--------------|------|\n"
            for stock in scheme1[:15]:
                gain_924 = stock.get('gain_924')
                gain_diff = stock.get('gain_diff')
                amount_ratio = stock.get('amount_ratio')
                if gain_diff is not None:
                    surge = f"{gain_diff}%"
                elif amount_ratio is not None:
                    surge = f"{amount_ratio}x"
                else:
                    surge = "-"
                float_mv_yi = round(stock.get('float_mv', 0) / 100000000, 2) if stock.get('float_mv') else '-'
                content += (
                    f"| {stock['code']} | {stock['name']} | {stock['price']} "
                    f"| {stock['gain']} | {gain_924 if gain_924 is not None else '-'} "
                    f"| {surge} | {stock['amount']} | {float_mv_yi} | {stock['industry']} |\n"
                )
            content += "\n"

        if scheme2:
            content += "### 方案2：涨停次日竞价型\n\n"
            content += "| 代码 | 名称 | 竞价价 | 今日涨幅(%) | 昨日涨幅(%) | 昨量比 | 昨日炸板 | 竞价金额(万) | 流通市值(亿) | 行业 |\n"
            content += "|------|------|--------|------------|------------|--------|----------|--------------|--------------|------|\n"
            for stock in scheme2[:15]:
                float_mv_yi = round(stock.get('float_mv', 0) / 100000000, 2) if stock.get('float_mv') else '-'
                burst = "是" if stock.get('yesterday_is_burst') else "否"
                content += (
                    f"| {stock['code']} | {stock['name']} | {stock['price']} "
                    f"| {stock['gain']} | {stock.get('yesterday_change_pct', '-')} "
                    f"| {stock.get('yesterday_volume_ratio', '-')} | {burst} "
                    f"| {stock['amount']} | {float_mv_yi} | {stock['industry']} |\n"
                )
            content += "\n"

        content += f"**合计**: {len(auction_stocks)}只股票（方案1:{len(scheme1)}只, 方案2:{len(scheme2)}只）"
        return content

    def format_late_notification(self, late_session):
        content = "## A股尾盘选股结果\n\n"
        content += f"**时间**: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        content += "**选股条件**:\n"
        content += "- 方案1：近15日涨停 + 不破最低价 + 昨日回踩EXPMA10缩量十字星/倒T + 今日十字星/倒T\n"
        content += "- 方案2：连续6日及以上收阳 + 回调有承接 + 不破5日均线\n"
        content += "- 范围：沪深主板，不含创业板/ST\n\n"

        scheme1 = [s for s in late_session if s.get('scheme') == '方案1']
        scheme2 = [s for s in late_session if s.get('scheme') == '方案2']

        if scheme1:
            content += "### 方案1：涨停后缩量回踩\n\n"
            content += "| 代码 | 名称 | 当前价 | 涨幅(%) | 形态 | 行业 |\n"
            content += "|------|------|--------|---------|------|------|\n"
            for stock in scheme1[:15]:
                content += f"| {stock['code']} | {stock['name']} | {stock['current_price']} | {stock['gain']} | {stock['pattern']} | {stock['industry']} |\n"
            content += "\n"

        if scheme2:
            content += "### 方案2：连阳承接不破均线\n\n"
            content += "| 代码 | 名称 | 当前价 | 涨幅(%) | 连阳天数 | 行业 |\n"
            content += "|------|------|--------|---------|----------|------|\n"
            for stock in scheme2[:15]:
                content += f"| {stock['code']} | {stock['name']} | {stock['current_price']} | {stock['gain']} | {stock['pattern']} | {stock['industry']} |\n"
            content += "\n"

        content += f"**合计**: {len(late_session)}只股票（方案1:{len(scheme1)}只, 方案2:{len(scheme2)}只）"
        return content

    # A股法定节假日休市列表（后备方案，当API获取失败时使用，每年需更新）
    HOLIDAYS = {
        # 2026年
        '2026-01-01', '2026-01-02',          # 元旦
        '2026-02-16', '2026-02-17', '2026-02-18', '2026-02-19', '2026-02-20',  # 春节
        '2026-04-06',                         # 清明
        '2026-05-01', '2026-05-04', '2026-05-05',  # 劳动节
        '2026-06-19',                         # 端午
        '2026-09-25',                         # 中秋
        '2026-10-01', '2026-10-02', '2026-10-05', '2026-10-06', '2026-10-07',  # 国庆
    }

    # 交易日历缓存：{year: set('YYYY-MM-DD', ...)}
    _trading_dates_cache = {}

    def _fetch_trading_dates(self, year):
        """从东方财富获取指定年份的A股交易日列表（以上证指数日K线日期为准）。"""
        if year in self._trading_dates_cache:
            return self._trading_dates_cache[year]

        url = 'http://push2his.eastmoney.com/api/qt/stock/kline/get'
        params = {
            'secid': '1.000001',  # 上证指数
            'fields1': 'f1,f2,f3,f4,f5,f6',
            'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
            'klt': '101',  # 日K
            'fqt': '0',
            'beg': f'{year}0101',
            'end': f'{year}1231',
        }
        try:
            resp = requests.get(url, params=params, timeout=10)
            data = resp.json()
            klines = data.get('data', {}).get('klines', [])
            trading_dates = set()
            for kline in klines:
                date_str = kline.split(',')[0]
                trading_dates.add(date_str)
            if trading_dates:
                self._trading_dates_cache[year] = trading_dates
                logger.info(f"[交易日历] 已获取{year}年交易日，共{len(trading_dates)}天")
                return trading_dates
        except Exception as e:
            logger.warning(f"[交易日历] 获取{year}年交易日失败，使用本地节假日列表: {e}")

        self._trading_dates_cache[year] = None  # 标记为获取失败，不再重复请求
        return None

    def is_trading_day(self):
        now = datetime.datetime.now()
        today = now.date()
        return self._is_trading_date(today)

    @staticmethod
    def _days_to_next_trading_day(weekday):
        """计算从给定 weekday 到下一个交易日的天数。
        周一(0)→1(周二) 周二(1)→1 周三(2)→1 周四(3)→1 周五(4)→3(下周一) 周六(5)→2 周日(6)→1
        """
        if weekday < 4:      # 周一~周四 → 明天
            return 1
        elif weekday == 4:   # 周五 → 下周一（3天）
            return 3
        elif weekday == 5:   # 周六 → 下周一（2天）
            return 2
        else:                # 周日 → 下周一（1天）
            return 1

    def _next_trading_day(self, from_date):
        """从 from_date 开始找下一个交易日（跳过周末和节假日）。"""
        candidate = from_date + datetime.timedelta(days=1)
        while True:
            if self._is_trading_date(candidate):
                return candidate
            candidate += datetime.timedelta(days=1)

    def _is_trading_date(self, date):
        """判断指定日期是否为A股交易日。
        A股只在周一~周五交易，周末即使调休补班也不开盘。
        """
        # 周末一律非交易日（A股周末不开盘）
        if date.weekday() >= 5:
            return False

        # 优先用 chinese_calendar 判断是否法定节假日
        if HAS_CHINESE_CALENDAR:
            try:
                return not chinese_calendar.is_holiday(date)
            except Exception:
                pass

        # 后备方案1：东方财富交易日历
        trading_dates = self._fetch_trading_dates(date.year)
        if trading_dates is not None:
            return date.strftime('%Y-%m-%d') in trading_dates

        # 后备方案2：本地节假日列表
        return date.strftime('%Y-%m-%d') not in self.HOLIDAYS

    def get_next_run_time(self):
        now = datetime.datetime.now()

        if not self.is_trading_day():
            next_trading_day = self._next_trading_day(now.date())
            return datetime.datetime(next_trading_day.year, next_trading_day.month, next_trading_day.day, 9, 22, 0)

        run_times = [
            datetime.datetime(now.year, now.month, now.day, 9, 22, 0),  # 9:22 采集快照
            datetime.datetime(now.year, now.month, now.day, 9, 25, 0),
            datetime.datetime(now.year, now.month, now.day, 14, 48, 0),
        ]

        for run_time in run_times:
            if run_time > now:
                return run_time

        # 今日所有时段已过，取下一个交易日
        next_trading_day = self._next_trading_day(now.date())
        return datetime.datetime(next_trading_day.year, next_trading_day.month, next_trading_day.day, 9, 22, 0)

    def run(self):
        logger.info("=== A股选股服务器启动 ===")
        channels = []
        if SEND_KEYS:
            channels.append(f"Server酱({len(SEND_KEYS)}人)")
        if WXPUSHER_APP_TOKEN and WXPUSHER_UIDS:
            channels.append(f"WxPusher({len(WXPUSHER_UIDS)}人)")
        logger.info(f"推送通道: {', '.join(channels) if channels else '未配置'}")
        logger.info("每日运行时间: 9:22(快照)、9:25(集合竞价选股)、14:48(尾盘)")

        # 记录今日各任务是否已执行，避免同一分钟内重复执行
        self._executed_today = set()  # 元素如 '2026-09-29_0924'

        try:
            while self.is_running:
                now = datetime.datetime.now()

                if not self.is_trading_day():
                    self._executed_today.clear()
                    next_time = self.get_next_run_time()
                    sleep_seconds = (next_time - now).total_seconds()
                    logger.info(f"非交易日({now.strftime('%Y-%m-%d %A')})，下次运行时间: {next_time.strftime('%Y-%m-%d %H:%M:%S')}")
                    logger.info(f"休眠 {int(sleep_seconds // 3600)}小时{int((sleep_seconds % 3600) // 60)}分钟...")
                    time.sleep(min(sleep_seconds, 86400))
                    continue

                hour = now.hour
                minute = now.minute
                date_key = now.strftime('%Y-%m-%d')
                key_0922 = f"{date_key}_0922"
                key_0925 = f"{date_key}_0925"
                key_1448 = f"{date_key}_1448"

                executed = False

                # 9:22 采集快照（9:22:00~9:22:59 内只执行一次）
                if hour == 9 and minute == 22 and key_0922 not in self._executed_today:
                    logger.info(f"=== 9:22 快照任务触发（{now.strftime('%H:%M:%S')}）===")
                    self.capture_924_snapshot()
                    self._executed_today.add(key_0922)
                    executed = True
                    # 快照若耗时过长（跨过9:25），补执行早盘选股
                    after = datetime.datetime.now()
                    if (after.hour == 9 and after.minute >= 25) or after.hour > 9:
                        if key_0925 not in self._executed_today:
                            logger.info(f"快照耗时较长，补执行9:25早盘选股（{after.strftime('%H:%M:%S')}）")
                            self.run_morning_selection()
                            self.snapshot_924 = None
                            self._executed_today.add(key_0925)
                            logger.info("集合竞价选股结束，等待尾盘时段...")

                # 9:25 早盘选股（9:25:00~9:25:59 内只执行一次）
                if hour == 9 and minute == 25 and key_0925 not in self._executed_today:
                    logger.info(f"=== 9:25 早盘选股任务触发（{now.strftime('%H:%M:%S')}）===")
                    self.run_morning_selection()
                    self.snapshot_924 = None
                    self._executed_today.add(key_0925)
                    logger.info("集合竞价选股结束，等待尾盘时段...")
                    executed = True

                # 14:48 尾盘选股（14:48:00~14:48:59 内只执行一次）
                if hour == 14 and minute == 48 and key_1448 not in self._executed_today:
                    logger.info(f"=== 14:48 尾盘选股任务触发（{now.strftime('%H:%M:%S')}）===")
                    self.run_late_session_selection()
                    self._executed_today.add(key_1448)
                    executed = True

                if not executed:
                    next_time = self.get_next_run_time()
                    sleep_seconds = (next_time - now).total_seconds()
                    if sleep_seconds > 60:
                        logger.info(f"等待交易时段，下次运行时间: {next_time.strftime('%Y-%m-%d %H:%M:%S')}")
                        logger.info(f"休眠 {int(sleep_seconds // 60)}分钟...")
                    time.sleep(min(sleep_seconds, 30))
                    continue

                time.sleep(2)

        except KeyboardInterrupt:
            logger.info("=== 服务器已停止 ===")
            self.is_running = False

if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    test_mode = '--test' in args

    if test_mode:
        logger.info("=== 测试模式启动（完成后自动退出，中途按 Ctrl+C 可中断）===")

    server = StockServer()

    if test_mode:
        try:
            logger.info("手动测试集合竞价选股（无9:22快照，仅校验金额与涨幅条件）...")
            server.run_morning_selection()
            logger.info("手动测试尾盘选股...")
            server.run_late_session_selection()
            logger.info("测试完成")
        except KeyboardInterrupt:
            logger.info("用户中断，退出测试")
        sys.exit(0)
    else:
        server.run()
