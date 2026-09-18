import sys
import os
import time
import datetime
from stock_filter import StockFilter
from wechat_notifier import WechatNotifier
import config as _cfg
LATE_LOOKBACK_DAYS = getattr(_cfg, 'LATE_LOOKBACK_DAYS', 20)
AUCTION_AMOUNT_THRESHOLD = getattr(_cfg, 'AUCTION_AMOUNT_THRESHOLD', 20000000)
AUCTION_GAIN_MIN = getattr(_cfg, 'AUCTION_GAIN_MIN', 3.0)
AUCTION_GAIN_MAX = getattr(_cfg, 'AUCTION_GAIN_MAX', 8.0)
AUCTION_GAIN_DIFF_THRESHOLD = getattr(_cfg, 'AUCTION_GAIN_DIFF_THRESHOLD', 2.0)
AUCTION_FLOAT_MV_MAX = getattr(_cfg, 'AUCTION_FLOAT_MV_MAX', 20000000000)

class StockSelectorCLI:
    def __init__(self, send_key):
        self.filter = StockFilter()
        self.notifier = WechatNotifier(send_key)
        self.snapshot_924 = None

    def run_once(self, is_late_session=False):
        print(f"开始选股分析... {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        try:
            auction_stocks = []
            late_session_stocks = []

            if is_late_session:
                late_session_stocks = self.filter.filter_late_session(lookback=LATE_LOOKBACK_DAYS)
                s1 = sum(1 for s in late_session_stocks if s.get('scheme') == '方案1')
                s2 = sum(1 for s in late_session_stocks if s.get('scheme') == '方案2')
                print(f"尾盘选股: 共{len(late_session_stocks)}只（方案1:{s1}只, 方案2:{s2}只）")
            else:
                auction_stocks = self.filter.filter_auction_momentum(
                    snapshot_924=self.snapshot_924,
                    amount_threshold=AUCTION_AMOUNT_THRESHOLD,
                    gain_min=AUCTION_GAIN_MIN,
                    gain_max=AUCTION_GAIN_MAX,
                    gain_diff_threshold=AUCTION_GAIN_DIFF_THRESHOLD,
                    float_mv_max=AUCTION_FLOAT_MV_MAX
                )
                print(f"集合竞价选股: {len(auction_stocks)}只")

            total_stocks = len(auction_stocks) + len(late_session_stocks)

            if total_stocks > 0:
                self.send_notification(auction_stocks, late_session_stocks)
            else:
                print("暂无符合条件的股票")

            return {
                'auction': auction_stocks,
                'late_session': late_session_stocks
            }

        except Exception as e:
            print(f"选股过程中出错: {e}")
            return None

    def send_notification(self, auction, late_session=None):
        if late_session is None:
            late_session = []

        all_stocks = []
        for stock in auction:
            stock['type'] = '集合竞价'
            all_stocks.append(stock)
        for stock in late_session:
            stock['type'] = '尾盘形态'
            all_stocks.append(stock)

        all_stocks.sort(key=lambda x: x.get('gain', x.get('current_price', 0)), reverse=True)

        title = f"A股选股结果 ({datetime.datetime.now().strftime('%H:%M')})"

        content = "## A股选股结果\n\n"
        content += f"**时间**: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        if auction:
            content += "### 一、集合竞价选股\n\n"
            content += "| 代码 | 名称 | 竞价价 | 涨幅(%) | 9:24涨幅(%) | 拉升(%) | 竞价金额(万) | 行业 |\n"
            content += "|------|------|--------|---------|-------------|---------|--------------|------|\n"
            for stock in auction[:20]:
                gain_924 = stock.get('gain_924')
                gain_diff = stock.get('gain_diff')
                content += (
                    f"| {stock['code']} | {stock['name']} | {stock['price']} | {stock['gain']} "
                    f"| {gain_924 if gain_924 is not None else '-'} "
                    f"| {gain_diff if gain_diff is not None else '-'} | {stock['amount']} | {stock['industry']} |\n"
                )

        if late_session:
            scheme1 = [s for s in late_session if s.get('scheme') == '方案1']
            scheme2 = [s for s in late_session if s.get('scheme') == '方案2']
            content += f"\n### 二、尾盘选股（方案1+方案2）\n\n"
            if scheme1:
                content += "**方案1：涨停后缩量回踩**\n\n"
                content += "| 代码 | 名称 | 当前价 | 最高 | 最低 | 形态 | 行业 |\n"
                content += "|------|------|--------|------|------|------|------|\n"
                for stock in scheme1[:10]:
                    content += f"| {stock['code']} | {stock['name']} | {stock['current_price']} | {stock['high']} | {stock['low']} | {stock['pattern']} | {stock['industry']} |\n"
                content += "\n"
            if scheme2:
                content += "**方案2：连阳承接不破均线**\n\n"
                content += "| 代码 | 名称 | 当前价 | 最高 | 最低 | 连阳天数 | 行业 |\n"
                content += "|------|------|--------|------|------|----------|------|\n"
                for stock in scheme2[:10]:
                    content += f"| {stock['code']} | {stock['name']} | {stock['current_price']} | {stock['high']} | {stock['low']} | {stock['pattern']} | {stock['industry']} |\n"

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

                if hour == 9 and minute == 24:
                    print(f"\n--- 采集9:24快照: {now.strftime('%H:%M')} ---")
                    self.snapshot_924 = self.filter.fetcher.get_collection_bidding()
                    print(f"快照采集完成，共 {len(self.snapshot_924) if self.snapshot_924 else 0} 只")
                    time.sleep(60)
                elif hour == 9 and minute == 25:
                    print(f"\n--- 集合竞价选股: {now.strftime('%H:%M')} ---")
                    self.run_once(is_late_session=False)
                    self.snapshot_924 = None
                    time.sleep(60)
                elif hour == 14 and minute == 55:
                    print(f"\n--- 尾盘选股: {now.strftime('%H:%M')} ---")
                    self.run_once(is_late_session=True)
                    time.sleep(60)
                else:
                    if now.hour >= 9 and now.hour <= 15:
                        time.sleep(60)
                    else:
                        next_market = now.replace(hour=9, minute=24, second=0, microsecond=0)
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
