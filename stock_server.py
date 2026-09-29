import sys
import os
import time
import datetime
import logging

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
        self.snapshot_924 = None  # 9:24 分时行情快照

    def log_and_send(self, title, content):
        logger.info(title)
        logger.info(content[:200] + '...' if len(content) > 200 else content)
        self.notifier.send_message(title, content)

    def capture_924_snapshot(self):
        """采集 9:24 分时的行情快照，用于与 9:25 最终竞价做涨幅对比。

        策略：
        1. 强制使用东方财富主源（新浪在9:24时现价为0，会导致涨幅=-100%或0）
        2. calc_gain_percent 内部已增加 f17(虚拟开盘价) 兜底
        3. 若主源采集失败，退而求其次用降级链（总比没数据好）
        """
        try:
            logger.info("=== 采集 9:24 集合竞价快照（优先东方财富主源）===")
            fetcher = self.filter.fetcher

            # 优先用东方财富主源（不降级），失败后再用降级链
            snap = self._safe_fetch_primary(fetcher)
            if not snap:
                logger.warning("东方财富主源9:24快照失败，尝试降级链...")
                snap = fetcher.get_collection_bidding()

            self.snapshot_924 = snap

            count = len(self.snapshot_924) if self.snapshot_924 else 0
            logger.info(f"9:24 快照采集完成，共 {count} 只股票")
            # 调试日志：抽样检查 f2/f3/f17/f18 字段，确认竞价数据是否已填充
            if self.snapshot_924:
                sample = self.snapshot_924[:3]
                for s in sample:
                    logger.info(f"9:24样本 {s.get('f12')} {s.get('f14')}: "
                                f"f2={s.get('f2')} f3={s.get('f3')} f17={s.get('f17')} "
                                f"f18={s.get('f18')} f21={s.get('f21')}")
        except Exception as e:
            logger.error(f"9:24 快照采集失败: {e}", exc_info=True)
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
            logger.info("=== 开始尾盘选股（14:55） ===")

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
            content += "| 代码 | 名称 | 竞价价 | 涨幅(%) | 9:24涨幅(%) | 拉升 | 竞价金额(万) | 流通市值(亿) | 行业 |\n"
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

    def is_trading_day(self):
        now = datetime.datetime.now()
        return now.weekday() < 5

    def get_next_run_time(self):
        now = datetime.datetime.now()

        if not self.is_trading_day():
            days_ahead = (7 - now.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            next_trading_day = now + datetime.timedelta(days=days_ahead)
            return datetime.datetime(next_trading_day.year, next_trading_day.month, next_trading_day.day, 9, 24, 10)

        run_times = [
            datetime.datetime(now.year, now.month, now.day, 9, 24, 10),  # 9:24:10 采集快照（延后10秒确保竞价数据已填充）
            datetime.datetime(now.year, now.month, now.day, 9, 25, 0),
            datetime.datetime(now.year, now.month, now.day, 14, 55, 0),
        ]

        for run_time in run_times:
            if run_time > now:
                return run_time

        days_ahead = (7 - now.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        next_trading_day = now + datetime.timedelta(days=days_ahead)
        return datetime.datetime(next_trading_day.year, next_trading_day.month, next_trading_day.day, 9, 24, 0)

    def run(self):
        logger.info("=== A股选股服务器启动 ===")
        channels = []
        if SEND_KEYS:
            channels.append(f"Server酱({len(SEND_KEYS)}人)")
        if WXPUSHER_APP_TOKEN and WXPUSHER_UIDS:
            channels.append(f"WxPusher({len(WXPUSHER_UIDS)}人)")
        logger.info(f"推送通道: {', '.join(channels) if channels else '未配置'}")
        logger.info("每日运行时间: 9:24(快照)、9:25(集合竞价选股)、14:55(尾盘)")

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
                key_0924 = f"{date_key}_0924"
                key_0925 = f"{date_key}_0925"
                key_1455 = f"{date_key}_1455"

                executed = False

                # 9:24 采集快照（9:24:00~9:24:59 内只执行一次）
                if hour == 9 and minute == 24 and key_0924 not in self._executed_today:
                    logger.info(f"=== 9:24 快照任务触发（{now.strftime('%H:%M:%S')}）===")
                    self.capture_924_snapshot()
                    self._executed_today.add(key_0924)
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

                # 14:55 尾盘选股（14:55:00~14:55:59 内只执行一次）
                if hour == 14 and minute == 55 and key_1455 not in self._executed_today:
                    logger.info(f"=== 14:55 尾盘选股任务触发（{now.strftime('%H:%M:%S')}）===")
                    self.run_late_session_selection()
                    self._executed_today.add(key_1455)
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
            logger.info("手动测试集合竞价选股（无9:24快照，仅校验金额与涨幅条件）...")
            server.run_morning_selection()
            logger.info("手动测试尾盘选股...")
            server.run_late_session_selection()
            logger.info("测试完成")
        except KeyboardInterrupt:
            logger.info("用户中断，退出测试")
        sys.exit(0)
    else:
        server.run()
