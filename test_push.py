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

    # 模拟集合竞价选股结果（竞价金额>1000万, 涨幅3%-8%, 9:25较9:24拉升>=2%）
    auction_stocks = [
        {'code': '600519', 'name': '贵州茅台', 'price': '1888.00', 'prev_close': '1800.00',
         'gain': '4.89', 'gain_924': '2.50', 'gain_diff': '2.39', 'amount': '25000.00', 'industry': '白酒'},
        {'code': '300750', 'name': '宁德时代', 'price': '218.50', 'prev_close': '210.00',
         'gain': '4.05', 'gain_924': '1.80', 'gain_diff': '2.25', 'amount': '18000.00', 'industry': '锂电池'},
        {'code': '002594', 'name': '比亚迪', 'price': '268.00', 'prev_close': '258.00',
         'gain': '3.88', 'gain_924': '1.50', 'gain_diff': '2.38', 'amount': '32000.00', 'industry': '新能源车'},
    ]

    content = server.format_auction_notification(auction_stocks)
    title = f"📈 集合竞价选股 (测试 {datetime.datetime.now().strftime('%H:%M')})"

    print(f"\n推送标题: {title}")
    print(f"选股结果: 集合竞价{len(auction_stocks)}只")

    result = server.notifier.send_message(title, content)
    print(f"推送结果: {'成功' if result else '失败'}")
    return result


def test_late_session_push():
    """测试3: 模拟尾盘选股结果并推送"""
    print("\n" + "=" * 50)
    print("测试3: 模拟尾盘选股推送")
    print("=" * 50)

    server = StockServer()

    # 模拟尾盘选股结果
    late_session_stocks = [
        {'code': '600036', 'name': '招商银行', 'current_price': '35.20', 'gain': '1.25',
         'open': '35.18', 'pattern': '十字星', 'scheme': '方案1', 'industry': '银行'},
        {'code': '601318', 'name': '中国平安', 'current_price': '48.60', 'gain': '0.82',
         'open': '48.55', 'pattern': '7连阳', 'scheme': '方案2', 'industry': '保险'},
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
