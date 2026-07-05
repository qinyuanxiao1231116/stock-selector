"""
测试脚本：模拟选股结果并验证 WxPusher / Server酱 推送是否成功
用法: python test_push.py
"""

import datetime
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import SEND_KEYS, WXPUSHER_APP_TOKEN, WXPUSHER_UIDS
from wechat_notifier import WechatNotifier, WxPusherNotifier, MultiNotifier
from stock_server import StockServer


def test_push_only():
    """测试1: 只测试推送通道，发送简单消息"""
    print("=" * 50)
    print("测试1: 推送通道连通性测试")
    print("=" * 50)

    notifiers = []
    if SEND_KEYS:
        notifiers.append(WechatNotifier(SEND_KEYS))
        print(f"  Server酱: 已配置 {len(SEND_KEYS)} 个SendKey")
    else:
        print("  Server酱: 未配置，跳过")

    if WXPUSHER_APP_TOKEN and WXPUSHER_UIDS:
        notifiers.append(WxPusherNotifier(WXPUSHER_APP_TOKEN, WXPUSHER_UIDS))
        print(f"  WxPusher: 已配置 {len(WXPUSHER_UIDS)} 个UID")
    else:
        print("  WxPusher: 未配置，跳过")

    if not notifiers:
        print("\n错误: 未配置任何推送通道！请在 config.py 中配置")
        return False

    notifier = MultiNotifier(notifiers)
    result = notifier.send_message("推送测试", "这是一条测试消息，如果你收到了说明推送通道正常！")
    print(f"\n推送结果: {'成功' if result else '失败'}")
    return result


def test_morning_selection_push():
    """测试2: 模拟集合竞价选股结果并推送"""
    print("\n" + "=" * 50)
    print("测试2: 模拟集合竞价选股推送")
    print("=" * 50)

    server = StockServer()

    # 模拟涨停封单加大的股票
    limit_up_stocks = [
        {'code': '600519', 'name': '贵州茅台', 'price': '1888.00', 'limit_up_price': '1898.88',
         'buy1_volume': '52000', 'change_percent': '9.98', 'industry': '白酒'},
        {'code': '300750', 'name': '宁德时代', 'price': '218.50', 'limit_up_price': '220.15',
         'buy1_volume': '38000', 'change_percent': '10.00', 'industry': '锂电池'},
    ]

    # 模拟跳空高开的股票
    gapping_up_stocks = [
        {'code': '000858', 'name': '五粮液', 'current_price': '168.30', 'prev_close': '165.00',
         'gap_percent': '2.00', 'industry': '白酒'},
        {'code': '601012', 'name': '隆基绿能', 'current_price': '28.50', 'prev_close': '27.80',
         'gap_percent': '2.52', 'industry': '光伏'},
        {'code': '002594', 'name': '比亚迪', 'current_price': '268.00', 'prev_close': '262.00',
         'gap_percent': '2.29', 'industry': '新能源车'},
    ]

    # 模拟抢筹动作的股票
    buying_rush_stocks = [
        {'code': '688981', 'name': '中芯国际', 'current_price': '52.80', 'price_increase': '3.50',
         'buy1_volume': '12000', 'buy_sell_ratio': '5.2', 'industry': '半导体'},
    ]

    content = server.format_notification(limit_up_stocks, gapping_up_stocks, buying_rush_stocks)
    title = f"📈 集合竞价选股 (测试 {datetime.datetime.now().strftime('%H:%M')})"

    print(f"\n推送标题: {title}")
    print(f"选股结果: 涨停{len(limit_up_stocks)}只, 跳空{len(gapping_up_stocks)}只, 抢筹{len(buying_rush_stocks)}只")

    result = server.notifier.send_message(title, content)
    print(f"推送结果: {'成功' if result else '失败'}")
    return result


def test_late_session_push():
    """测试3: 模拟尾盘选股结果并推送"""
    print("\n" + "=" * 50)
    print("测试3: 模拟尾盘选股推送")
    print("=" * 50)

    server = StockServer()

    # 模拟尾盘选股结果（十字星/倒T形态）
    late_session_stocks = [
        {'code': '600036', 'name': '招商银行', 'current_price': '35.20', 'open': '35.18',
         'high': '35.50', 'low': '34.90', 'pattern': '十字星', 'industry': '银行'},
        {'code': '601318', 'name': '中国平安', 'current_price': '48.60', 'open': '48.55',
         'high': '49.10', 'low': '48.50', 'pattern': '倒T', 'industry': '保险'},
    ]

    content = server.format_late_notification(late_session_stocks)
    title = f"📊 尾盘选股 (测试 {datetime.datetime.now().strftime('%H:%M')})"

    print(f"\n推送标题: {title}")
    print(f"选股结果: 尾盘{len(late_session_stocks)}只")

    result = server.notifier.send_message(title, content)
    print(f"推送结果: {'成功' if result else '失败'}")
    return result


if __name__ == '__main__':
    print("A股选股推送测试\n")

    # 检查配置
    print("当前配置:")
    print(f"  Server酱 SendKeys: {len(SEND_KEYS)}个")
    print(f"  WxPusher AppToken: {'已配置' if WXPUSHER_APP_TOKEN else '未配置'}")
    print(f"  WxPusher UIDs: {len(WXPUSHER_UIDS)}个")
    print()

    results = []

    # 运行所有测试
    results.append(("推送连通性", test_push_only()))
    results.append(("集合竞价推送", test_morning_selection_push()))
    results.append(("尾盘推送", test_late_session_push()))

    # 汇总
    print("\n" + "=" * 50)
    print("测试结果汇总")
    print("=" * 50)
    for name, ok in results:
        status = "PASS" if ok else "FAIL"
        print(f"  {name}: {status}")

    all_pass = all(r[1] for r in results)
    print(f"\n总结果: {'全部通过' if all_pass else '存在失败'}")
