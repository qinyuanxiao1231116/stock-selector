import sys
import os
import time
import datetime
import logging
from config import SEND_KEY, LOG_FILE, LIMIT_UP_THRESHOLD, GAP_THRESHOLD, BUY_VOLUME_THRESHOLD, BUY_PRICE_THRESHOLD
from stock_filter import StockFilter
from wechat_notifier import WechatNotifier

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
        self.notifier = WechatNotifier(SEND_KEY)
        self.is_running = True
    
    def log_and_send(self, title, content):
        logger.info(title)
        logger.info(content[:200] + '...' if len(content) > 200 else content)
        self.notifier.send_message(title, content)
    
    def run_morning_selection(self):
        try:
            logger.info("=== 开始集合竞价选股 ===")
            
            limit_up_stocks = self.filter.filter_limit_up_with_increasing_bids(threshold=LIMIT_UP_THRESHOLD)
            gapping_up_stocks = self.filter.filter_gapping_up(gap_threshold=GAP_THRESHOLD)
            buying_rush_stocks = self.filter.filter_buying_rush(
                volume_threshold=BUY_VOLUME_THRESHOLD,
                price_increase_threshold=BUY_PRICE_THRESHOLD
            )
            
            logger.info(f"涨停封单加大: {len(limit_up_stocks)}只")
            logger.info(f"跳空高开: {len(gapping_up_stocks)}只")
            logger.info(f"抢筹动作: {len(buying_rush_stocks)}只")
            
            total_stocks = len(limit_up_stocks) + len(gapping_up_stocks) + len(buying_rush_stocks)
            
            if total_stocks > 0:
                content = self.format_notification(limit_up_stocks, gapping_up_stocks, buying_rush_stocks)
                title = f"📈 集合竞价选股 ({datetime.datetime.now().strftime('%H:%M')})"
                self.log_and_send(title, content)
            else:
                logger.info("暂无符合条件的股票")
            
        except Exception as e:
            logger.error(f"集合竞价选股出错: {e}", exc_info=True)
            self.notifier.send_message("⚠️ 选股出错", f"集合竞价选股时发生错误: {e}")
    
    def run_late_session_selection(self):
        try:
            logger.info("=== 开始尾盘选股 ===")
            
            late_session_stocks = self.filter.filter_late_session(days=7)
            logger.info(f"尾盘选股(十字星/倒T): {len(late_session_stocks)}只")
            
            if len(late_session_stocks) > 0:
                content = self.format_late_notification(late_session_stocks)
                title = f"📊 尾盘选股 ({datetime.datetime.now().strftime('%H:%M')})"
                self.log_and_send(title, content)
            else:
                logger.info("暂无符合条件的股票")
            
        except Exception as e:
            logger.error(f"尾盘选股出错: {e}", exc_info=True)
            self.notifier.send_message("⚠️ 选股出错", f"尾盘选股时发生错误: {e}")
    
    def format_notification(self, limit_up, gapping_up, buying_rush):
        content = "## A股集合竞价选股结果\n\n"
        content += f"**时间**: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        
        if limit_up:
            content += "### 一、涨停封单加大\n\n"
            content += "| 代码 | 名称 | 当前价 | 涨停价 | 封单(手) | 涨幅(%) | 行业 |\n"
            content += "|------|------|--------|--------|----------|---------|------|\n"
            for stock in limit_up[:10]:
                content += f"| {stock['code']} | {stock['name']} | {stock['price']} | {stock['limit_up_price']} | {stock['buy1_volume']} | {stock['change_percent']} | {stock['industry']} |\n"
        
        if gapping_up:
            content += "\n### 二、跳空高开\n\n"
            content += "| 代码 | 名称 | 当前价 | 昨收 | 跳空(%) | 行业 |\n"
            content += "|------|------|--------|------|---------|------|\n"
            for stock in gapping_up[:10]:
                content += f"| {stock['code']} | {stock['name']} | {stock['current_price']} | {stock['prev_close']} | {stock['gap_percent']} | {stock['industry']} |\n"
        
        if buying_rush:
            content += "\n### 三、抢筹动作\n\n"
            content += "| 代码 | 名称 | 当前价 | 涨幅(%) | 买一量 | 买卖比 | 行业 |\n"
            content += "|------|------|--------|---------|--------|--------|------|\n"
            for stock in buying_rush[:10]:
                content += f"| {stock['code']} | {stock['name']} | {stock['current_price']} | {stock['price_increase']} | {stock['buy1_volume']} | {stock['buy_sell_ratio']} | {stock['industry']} |\n"
        
        content += f"\n**合计**: {len(limit_up) + len(gapping_up) + len(buying_rush)}只股票"
        return content
    
    def format_late_notification(self, late_session):
        content = "## A股尾盘选股结果\n\n"
        content += f"**时间**: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        content += "**选股条件**: 近7日涨停 + 当日十字星/倒T形态\n\n"
        
        if late_session:
            content += "| 代码 | 名称 | 当前价 | 开盘 | 最高 | 最低 | 形态 | 行业 |\n"
            content += "|------|------|--------|------|------|------|------|------|\n"
            for stock in late_session[:10]:
                content += f"| {stock['code']} | {stock['name']} | {stock['current_price']} | {stock['open']} | {stock['high']} | {stock['low']} | {stock['pattern']} | {stock['industry']} |\n"
        
        content += f"\n**合计**: {len(late_session)}只股票"
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
            return datetime.datetime(next_trading_day.year, next_trading_day.month, next_trading_day.day, 9, 20, 0)
        
        run_times = []
        for m in range(20, 25):
            run_times.append(datetime.datetime(now.year, now.month, now.day, 9, m, 0))
        run_times.append(datetime.datetime(now.year, now.month, now.day, 9, 25, 0))
        run_times.append(datetime.datetime(now.year, now.month, now.day, 14, 45, 0))
        
        for run_time in run_times:
            if run_time > now:
                return run_time
        
        days_ahead = (7 - now.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        next_trading_day = now + datetime.timedelta(days=days_ahead)
        return datetime.datetime(next_trading_day.year, next_trading_day.month, next_trading_day.day, 9, 20, 0)
    
    def run(self):
        logger.info("=== A股选股服务器启动 ===")
        logger.info(f"SendKey: {SEND_KEY[:10]}...")
        logger.info("每日运行时间: 9:20-9:24(每分钟)、9:25(最后一次)、14:45(尾盘)")
        
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
                
                if hour == 9 and 20 <= minute <= 24:
                    self.run_morning_selection()
                    time.sleep(2)
                elif hour == 9 and minute == 25:
                    self.run_morning_selection()
                    logger.info("集合竞价选股结束，等待尾盘时段...")
                    time.sleep(2)
                elif hour == 14 and minute == 45:
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
        logger.info("手动测试集合竞价选股...")
        server.run_morning_selection()
        logger.info("手动测试尾盘选股...")
        server.run_late_session_selection()
        logger.info("测试完成")
    else:
        server.run()