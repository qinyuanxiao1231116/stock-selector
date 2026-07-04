import sys
import os
import time
import datetime
from stock_filter import StockFilter
from wechat_notifier import WechatNotifier

class StockSelectorCLI:
    def __init__(self, send_key):
        self.filter = StockFilter()
        self.notifier = WechatNotifier(send_key)
    
    def run_once(self, is_late_session=False):
        print(f"开始选股分析... {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        try:
            limit_up_stocks = []
            gapping_up_stocks = []
            buying_rush_stocks = []
            late_session_stocks = []
            
            if is_late_session:
                late_session_stocks = self.filter.filter_late_session(days=7)
                print(f"尾盘选股(十字星/倒T): {len(late_session_stocks)}只")
            else:
                limit_up_stocks = self.filter.filter_limit_up_with_increasing_bids(threshold=10000)
                gapping_up_stocks = self.filter.filter_gapping_up(gap_threshold=1.0)
                buying_rush_stocks = self.filter.filter_buying_rush(volume_threshold=5000, price_increase_threshold=2.0)
                print(f"涨停封单加大: {len(limit_up_stocks)}只")
                print(f"跳空高开: {len(gapping_up_stocks)}只")
                print(f"抢筹动作: {len(buying_rush_stocks)}只")
            
            total_stocks = len(limit_up_stocks) + len(gapping_up_stocks) + len(buying_rush_stocks) + len(late_session_stocks)
            
            if total_stocks > 0:
                self.send_notification(limit_up_stocks, gapping_up_stocks, buying_rush_stocks, late_session_stocks)
            else:
                print("暂无符合条件的股票")
            
            return {
                'limit_up': limit_up_stocks,
                'gapping_up': gapping_up_stocks,
                'buying_rush': buying_rush_stocks,
                'late_session': late_session_stocks
            }
        
        except Exception as e:
            print(f"选股过程中出错: {e}")
            return None
    
    def send_notification(self, limit_up, gapping_up, buying_rush, late_session=None):
        if late_session is None:
            late_session = []
        
        all_stocks = []
        for stock in limit_up:
            stock['type'] = '涨停封单'
            all_stocks.append(stock)
        for stock in gapping_up:
            stock['type'] = '跳空高开'
            all_stocks.append(stock)
        for stock in buying_rush:
            stock['type'] = '抢筹动作'
            all_stocks.append(stock)
        for stock in late_session:
            stock['type'] = '尾盘形态'
            all_stocks.append(stock)
        
        all_stocks.sort(key=lambda x: x.get('change_percent', x.get('gap_percent', x.get('price_increase', 0))), reverse=True)
        
        title = f"A股选股结果 ({datetime.datetime.now().strftime('%H:%M')})"
        
        content = "## A股选股结果\n\n"
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
        
        if late_session:
            content += "\n### 四、尾盘选股（近7日涨停+十字星/倒T）\n\n"
            content += "| 代码 | 名称 | 当前价 | 开盘 | 最高 | 最低 | 形态 | 行业 |\n"
            content += "|------|------|--------|------|------|------|------|------|\n"
            for stock in late_session[:10]:
                content += f"| {stock['code']} | {stock['name']} | {stock['current_price']} | {stock['open']} | {stock['high']} | {stock['low']} | {stock['pattern']} | {stock['industry']} |\n"
        
        content += f"\n**合计**: {len(all_stocks)}只股票"
        
        self.notifier.send_message(title, content)
    
    def run_scheduled(self):
        print("启动定时选股监控...")
        print("按 Ctrl+C 退出")
        
        try:
            while True:
                now = datetime.datetime.now()
                hour = now.hour
                minute = now.minute
                
                if (hour == 9 and 20 <= minute <= 25) or (hour == 9 and minute == 29):
                    print(f"\n--- 集合竞价选股: {now.strftime('%H:%M')} ---")
                    self.run_once(is_late_session=False)
                    time.sleep(60)
                elif hour == 14 and 50 <= minute <= 59:
                    print(f"\n--- 尾盘选股: {now.strftime('%H:%M')} ---")
                    self.run_once(is_late_session=True)
                    time.sleep(60)
                else:
                    if now.hour >= 9 and now.hour <= 15:
                        time.sleep(60)
                    else:
                        next_market = now.replace(hour=9, minute=15, second=0, microsecond=0)
                        if now > next_market:
                            next_market += datetime.timedelta(days=1)
                        wait_seconds = (next_market - now).total_seconds()
                        print(f"市场未开盘，下次选股时间: {next_market.strftime('%Y-%m-%d %H:%M')}")
                        time.sleep(min(wait_seconds, 3600))
        
        except KeyboardInterrupt:
            print("\n监控已停止")

def main():
    if len(sys.argv) < 2:
        print("用法: python stock_selector_cli.py <Server酱SendKey> [--once|--late]")
        print("")
        print("参数说明:")
        print("  SendKey: Server酱的SendKey，用于微信推送")
        print("  --once: 仅执行一次集合竞价选股")
        print("  --late: 仅执行一次尾盘选股")
        print("")
        print("获取SendKey: https://sct.ftqq.com/")
        sys.exit(1)
    
    send_key = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) >= 3 else 'scheduled'
    
    selector = StockSelectorCLI(send_key)
    
    if mode == '--once':
        selector.run_once(is_late_session=False)
    elif mode == '--late':
        selector.run_once(is_late_session=True)
    else:
        selector.run_scheduled()

if __name__ == "__main__":
    main()