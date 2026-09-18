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
AUCTION_FLOAT_MV_MAX = getattr(_cfg, 'AUCTION_FLOAT_MV_MAX', 20000000000)  # 200亿

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
        """采集 9:24 分时的行情快照，用于与 9:25 最终竞价做涨幅对比"""
        try:
            logger.info("=== 采集 9:24 集合竞价快照 ===")
            self.snapshot_924 = self.filter.fetcher.get_collection_bidding()
            logger.info(f"9:24 快照采集完成，共 {len(self.snapshot_924) if self.snapshot_924 else 0} 只股票")
        except Exception as e:
            logger.error(f"9:24 快照采集失败: {e}", exc_info=True)
            self.snapshot_924 = None

    def run_morning_selection(self):
        try:
            logger.info("=== 开始早盘集合竞价选股 ===")

            auction_stocks = self.filter.filter_auction_momentum(
                snapshot_924=self.snapshot_924,
                amount_threshold=AUCTION_AMOUNT_THRESHOLD,
                gain_min=AUCTION_GAIN_MIN,
                gain_max=AUCTION_GAIN_MAX,
                gain_diff_threshold=AUCTION_GAIN_DIFF_THRESHOLD,
                float_mv_max=AUCTION_FLOAT_MV_MAX
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
                    f"- 竞价金额 >= {AUCTION_AMOUNT_THRESHOLD / 10000:.0f}万\n"
                    f"- 竞价涨幅 {AUCTION_GAIN_MIN}% ~ {AUCTION_GAIN_MAX}%\n"
                    f"- 9:25较9:24拉升 >= {AUCTION_GAIN_DIFF_THRESHOLD}%\n"
                    f"- 流通市值 <= {AUCTION_FLOAT_MV_MAX / 100000000:.0f}亿"
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
                    f"- 方案1：近15日涨停 + 涨停后不破最低价 + 今日十字星/倒T/小阴线 + 缩量\n"
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
        content += f"- 竞价金额 >= {AUCTION_AMOUNT_THRESHOLD / 10000:.0f}万\n"
        content += f"- 竞价涨幅 {AUCTION_GAIN_MIN}% ~ {AUCTION_GAIN_MAX}%\n"
        content += f"- 9:25较9:24拉升 >= {AUCTION_GAIN_DIFF_THRESHOLD}%\n"
        content += f"- 流通市值 <= {AUCTION_FLOAT_MV_MAX / 100000000:.0f}亿\n\n"

        content += "| 代码 | 名称 | 竞价价 | 涨幅(%) | 9:24涨幅(%) | 拉升(%) | 竞价金额(万) | 流通市值(亿) | 行业 |\n"
        content += "|------|------|--------|---------|-------------|---------|--------------|--------------|------|\n"
        for stock in auction_stocks[:20]:
            gain_924 = stock.get('gain_924')
            gain_diff = stock.get('gain_diff')
            float_mv_yi = round(stock.get('float_mv', 0) / 100000000, 2) if stock.get('float_mv') else '-'
            content += (
                f"| {stock['code']} | {stock['name']} | {stock['price']} "
                f"| {stock['gain']} | {gain_924 if gain_924 is not None else '-'} "
                f"| {gain_diff if gain_diff is not None else '-'} | {stock['amount']} | {float_mv_yi} | {stock['industry']} |\n"
            )

        content += f"\n**合计**: {len(auction_stocks)}只股票"
        return content

    def format_late_notification(self, late_session):
        content = "## A股尾盘选股结果\n\n"
        content += f"**时间**: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        content += "**选股条件**:\n"
        content += "- 方案1：近15日涨停 + 涨停后不破最低价 + 今日十字星/倒T/小阴线 + 缩量\n"
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
            return datetime.datetime(next_trading_day.year, next_trading_day.month, next_trading_day.day, 9, 24, 0)

        run_times = [
            datetime.datetime(now.year, now.month, now.day, 9, 24, 0),
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

        try:
            while self.is_running:
                now = datetime.datetime.now()

                if not self.is_trading_day():
                    next_time = self.get_next_run_time()
                    sleep_seconds = (next_time - now).total_seconds()
                    logger.info(f"非交易日({now.strftime('%Y-%m-%d %A')})，下次运行时间: {next_time.strftime('%Y-%m-%d %H:%M:%S')}")
                    logger.info(f"休眠 {int(sleep_seconds // 3600)}小时{int((sleep_seconds % 3600) // 60)}分钟...")
                    time.sleep(min(sleep_seconds, 86400))
                    continue

                hour = now.hour
                minute = now.minute
                second = now.second

                if second != 0:
                    next_time = self.get_next_run_time()
                    sleep_seconds = (next_time - now).total_seconds()
                    if sleep_seconds > 60:
                        logger.info(f"等待交易时段，下次运行时间: {next_time.strftime('%Y-%m-%d %H:%M:%S')}")
                        logger.info(f"休眠 {int(sleep_seconds // 60)}分钟...")
                    time.sleep(min(sleep_seconds, 3600))
                    continue

                if hour == 9 and minute == 24:
                    self.capture_924_snapshot()
                    time.sleep(2)
                elif hour == 9 and minute == 25:
                    self.run_morning_selection()
                    # 选股完成后清空快照
                    self.snapshot_924 = None
                    logger.info("集合竞价选股结束，等待尾盘时段...")
                    time.sleep(2)
                elif hour == 14 and minute == 55:
                    self.run_late_session_selection()
                    time.sleep(2)
                else:
                    next_time = self.get_next_run_time()
                    sleep_seconds = (next_time - now).total_seconds()
                    if sleep_seconds > 60:
                        logger.info(f"等待交易时段，下次运行时间: {next_time.strftime('%Y-%m-%d %H:%M:%S')}")
                        logger.info(f"休眠 {int(sleep_seconds // 60)}分钟...")
                    time.sleep(min(sleep_seconds, 3600))

        except KeyboardInterrupt:
            logger.info("=== 服务器已停止 ===")
            self.is_running = False

if __name__ == "__main__":
    import sys

    test_mode = False
    if len(sys.argv) > 1 and sys.argv[1] == '--test':
        test_mode = True
        logger.info("=== 测试模式启动 ===")

    server = StockServer()

    if test_mode:
        logger.info("手动测试集合竞价选股（无9:24快照，仅校验金额与涨幅条件）...")
        server.run_morning_selection()
        logger.info("手动测试尾盘选股...")
        server.run_late_session_selection()
        logger.info("测试完成")
    else:
        server.run()
