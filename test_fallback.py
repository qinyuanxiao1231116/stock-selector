"""
三源降级链（东方财富 → 新浪 → 腾讯）测试脚本
验证降级逻辑是否正常生效，以及腾讯fetcher字段映射正确
"""
import sys
import logging
from unittest.mock import patch

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


def test_primary_timeout_fallback():
    """测试1: 东方财富超时 -> 自动降级到新浪（腾讯不应被调用）"""
    logger.info("=" * 60)
    logger.info("测试1: 模拟东方财富超时，验证降级到新浪")
    logger.info("=" * 60)

    from data_fetcher import StockDataFetcher
    fetcher = StockDataFetcher()

    mock_data = [
        {'f12': '000001', 'f14': '平安银行', 'f2': 12.0, 'f18': 11.5}
    ]

    with patch.object(fetcher, '_get_collection_bidding_primary',
                      side_effect=TimeoutError("东方财富连接超时")):
        with patch.object(fetcher.fallback, 'get_collection_bidding', return_value=mock_data):
            with patch.object(fetcher.tencent, 'get_collection_bidding') as tc_mock:
                tc_mock.return_value = []
                result = fetcher.get_collection_bidding()

    assert result == mock_data, f"预期返回新浪数据，实际: {result}"
    assert tc_mock.call_count == 0, "新浪成功时不应调用腾讯"
    logger.info(f"✓ 测试1通过: 超时后自动降级到新浪，腾讯未被调用")
    return True


def test_primary_empty_fallback():
    """测试2: 东方财富返回空 -> 降级到新浪"""
    logger.info("\n" + "=" * 60)
    logger.info("测试2: 模拟东方财富返回空数据，验证降级")
    logger.info("=" * 60)

    from data_fetcher import StockDataFetcher
    fetcher = StockDataFetcher()

    with patch.object(fetcher, '_get_collection_bidding_primary', return_value=[]):
        mock_data = [{'f12': '600000', 'f14': '浦发银行', 'f2': 8.0, 'f18': 7.9}]
        with patch.object(fetcher.fallback, 'get_collection_bidding', return_value=mock_data):
            with patch.object(fetcher.tencent, 'get_collection_bidding') as tc_mock:
                tc_mock.return_value = []
                result = fetcher.get_collection_bidding()

    assert result == mock_data, f"预期返回新浪数据，实际: {result}"
    assert tc_mock.call_count == 0
    logger.info(f"✓ 测试2通过: 空数据后自动降级到新浪")
    return True


def test_primary_json_error_fallback():
    """测试3: 东方财富返回非JSON -> 降级到新浪"""
    logger.info("\n" + "=" * 60)
    logger.info("测试3: 模拟东方财富JSON解析失败，验证降级")
    logger.info("=" * 60)

    from data_fetcher import StockDataFetcher
    fetcher = StockDataFetcher()

    with patch.object(fetcher, '_get_collection_bidding_primary',
                      side_effect=ValueError("Expecting value: line 1 column 1")):
        mock_data = [{'f12': '300001', 'f14': '特锐德', 'f2': 15.0, 'f18': 14.5}]
        with patch.object(fetcher.fallback, 'get_collection_bidding', return_value=mock_data):
            with patch.object(fetcher.tencent, 'get_collection_bidding') as tc_mock:
                tc_mock.return_value = []
                result = fetcher.get_collection_bidding()

    assert result == mock_data, f"预期返回新浪数据，实际: {result}"
    assert tc_mock.call_count == 0
    logger.info(f"✓ 测试3通过: JSON解析失败后自动降级到新浪")
    return True


def test_primary_sina_fail_to_tencent():
    """测试4: 东方财富+新浪都失败 -> 降级到腾讯"""
    logger.info("\n" + "=" * 60)
    logger.info("测试4: 主源+新浪都失败，验证降级到腾讯")
    logger.info("=" * 60)

    from data_fetcher import StockDataFetcher
    fetcher = StockDataFetcher()

    tc_data = [{'f12': '300750', 'f14': '宁德时代', 'f2': 300.0, 'f18': 295.0}]

    with patch.object(fetcher, '_get_collection_bidding_primary',
                      side_effect=TimeoutError("东方财富超时")):
        with patch.object(fetcher.fallback, 'get_collection_bidding',
                          side_effect=ConnectionError("新浪也无法连接")):
            with patch.object(fetcher.tencent, 'get_collection_bidding', return_value=tc_data):
                result = fetcher.get_collection_bidding()

    assert result == tc_data, f"预期返回腾讯数据，实际: {result}"
    logger.info(f"✓ 测试4通过: 主源+新浪失败，降级到腾讯成功")
    return True


def test_all_three_fail():
    """测试5: 三源全失败 -> 返回空列表"""
    logger.info("\n" + "=" * 60)
    logger.info("测试5: 三数据源都失败，验证返回空列表")
    logger.info("=" * 60)

    from data_fetcher import StockDataFetcher
    fetcher = StockDataFetcher()

    with patch.object(fetcher, '_get_collection_bidding_primary',
                      side_effect=TimeoutError("东方财富超时")):
        with patch.object(fetcher.fallback, 'get_collection_bidding',
                          side_effect=ConnectionError("新浪失败")):
            with patch.object(fetcher.tencent, 'get_collection_bidding',
                              side_effect=Exception("腾讯失败")):
                result = fetcher.get_collection_bidding()

    assert result == [], f"预期返回空列表，实际: {result}"
    logger.info(f"✓ 测试5通过: 三数据源失败返回空列表")
    return True


def test_primary_success_no_fallback():
    """测试6: 东方财富正常 -> 不降级（新浪和腾讯均不被调用）"""
    logger.info("\n" + "=" * 60)
    logger.info("测试6: 东方财富正常返回，不触发降级")
    logger.info("=" * 60)

    from data_fetcher import StockDataFetcher
    fetcher = StockDataFetcher()

    mock_data = [
        {'f12': '000002', 'f14': '万科A', 'f2': 9.0, 'f18': 8.8}
    ]
    with patch.object(fetcher, '_get_collection_bidding_primary', return_value=mock_data):
        with patch.object(fetcher.fallback, 'get_collection_bidding') as sina_mock:
            sina_mock.return_value = []
            with patch.object(fetcher.tencent, 'get_collection_bidding') as tc_mock:
                tc_mock.return_value = []
                result = fetcher.get_collection_bidding()

    assert result == mock_data, f"预期返回东方财富数据，实际: {result}"
    assert sina_mock.call_count == 0, "主源成功时不应调用新浪"
    assert tc_mock.call_count == 0, "主源成功时不应调用腾讯"
    logger.info(f"✓ 测试6通过: 东方财富正常时不降级")
    return True


def test_kline_fallback():
    """测试7: K线数据三源降级链"""
    logger.info("\n" + "=" * 60)
    logger.info("测试7: K线数据降级测试")
    logger.info("=" * 60)

    from data_fetcher import StockDataFetcher
    fetcher = StockDataFetcher()

    mock_klines = {'600519': [{'date': '2026-07-09', 'open': 1800, 'close': 1820, 'high': 1830, 'low': 1790}]}

    with patch.object(fetcher, '_get_kline_data_batch_primary',
                      side_effect=TimeoutError("K线接口超时")):
        with patch.object(fetcher.fallback, 'get_kline_data_batch', return_value=mock_klines):
            with patch.object(fetcher.tencent, 'get_kline_data_batch') as tc_mock:
                tc_mock.return_value = {}
                result = fetcher.get_kline_data_batch(['600519'])

    assert result == mock_klines, f"预期返回新浪K线数据，实际: {result}"
    assert tc_mock.call_count == 0
    logger.info(f"✓ 测试7通过: K线数据降级到新浪成功")
    return True


def test_kline_fallback_to_tencent():
    """测试8: K线主源+新浪失败 -> 降级到腾讯"""
    logger.info("\n" + "=" * 60)
    logger.info("测试8: K线主源+新浪失败，降级到腾讯")
    logger.info("=" * 60)

    from data_fetcher import StockDataFetcher
    fetcher = StockDataFetcher()

    tc_klines = {'600519': [{'date': '2026-07-09', 'open': 1800, 'close': 1820, 'high': 1830, 'low': 1790}]}

    with patch.object(fetcher, '_get_kline_data_batch_primary',
                      side_effect=TimeoutError("K线主源超时")):
        with patch.object(fetcher.fallback, 'get_kline_data_batch',
                          side_effect=ConnectionError("新浪K线失败")):
            with patch.object(fetcher.tencent, 'get_kline_data_batch', return_value=tc_klines):
                result = fetcher.get_kline_data_batch(['600519'])

    assert result == tc_klines, f"预期返回腾讯K线数据，实际: {result}"
    logger.info(f"✓ 测试8通过: K线主源+新浪失败，降级到腾讯成功")
    return True


def test_plate_fallback():
    """测试9: 板块数据降级"""
    logger.info("\n" + "=" * 60)
    logger.info("测试9: 板块数据降级测试")
    logger.info("=" * 60)

    from data_fetcher import StockDataFetcher
    fetcher = StockDataFetcher()

    mock_plates = {'000001': {'code': '000001', 'industry': '银行', 'concept': '', 'region': '', 'market': ''}}

    with patch.object(fetcher, '_get_stock_plates_batch_primary',
                      side_effect=ConnectionError("板块接口连接失败")):
        with patch.object(fetcher.fallback, 'get_stock_plates_batch', return_value=mock_plates):
            with patch.object(fetcher.tencent, 'get_stock_plates_batch') as tc_mock:
                tc_mock.return_value = {}
                result = fetcher.get_stock_plates_batch(['000001'])

    assert result == mock_plates, f"预期返回新浪板块数据，实际: {result}"
    assert tc_mock.call_count == 0
    logger.info(f"✓ 测试9通过: 板块数据降级成功")
    return True


def test_safe_div():
    """测试10: safe_div安全除法"""
    logger.info("\n" + "=" * 60)
    logger.info("测试10: safe_div安全除法函数")
    logger.info("=" * 60)

    from stock_filter import safe_div

    assert safe_div(10, 2) == 5.0, "10/2 应该=5"
    assert safe_div(10, 0) == 0, "除零应返回0"
    assert safe_div(10, 0, default=-1) == -1, "除零应返回自定义默认值"
    assert safe_div(0, 5) == 0, "0/5 应该=0"
    assert safe_div(-10, 2) == -5.0, "负数除法"
    assert safe_div('a', 2) == 0, "非数字应返回0"
    assert safe_div(10, 'b') == 0, "非数字分母应返回0"
    logger.info(f"✓ 测试10通过: safe_div所有场景正确")
    return True


def test_to_float_to_int():
    """测试11: to_float和to_int类型转换"""
    logger.info("\n" + "=" * 60)
    logger.info("测试11: to_float/to_int类型转换")
    logger.info("=" * 60)

    from stock_filter import to_float, to_int

    # to_float
    assert to_float('188800') == 188800.0
    assert to_float('') == 0
    assert to_float(None) == 0
    assert to_float('abc') == 0
    assert to_float('-') == 0
    assert to_float('3.14') == 3.14

    # to_int
    assert to_int('188800') == 188800
    assert to_int('') == 0
    assert to_int(None) == 0
    assert to_int('abc') == 0
    assert to_int('3.14') == 3

    logger.info(f"✓ 测试11通过: to_float/to_int类型转换正确")
    return True


def test_tencent_quote_parsing():
    """测试12: 腾讯行情字段解析"""
    logger.info("\n" + "=" * 60)
    logger.info("测试12: 腾讯行情字段解析")
    logger.info("=" * 60)

    from tencent_fetcher import TencentFetcher
    f = TencentFetcher()

    # 模拟一行腾讯行情数据
    # v_sh600519="1~贵州茅台~600519~1266.98~1258.00~1257.98~17554~8912~8641~..."
    # 字段35格式: 价格/成交量/成交额
    fake_line = 'v_sh600519="1~贵州茅台~600519~1266.98~1258.00~1257.98~17554~8912~8641~1266.98~3~1266.97~1~1266.95~9~1266.91~2~1266.88~6~1266.99~14~1267.00~29~1267.08~1~1267.12~1~1267.14~1~~20260917161459~8.98~0.71~1267.60~1254.00~1266.98/17554/2217338283"'
    stock = f._parse_quote_line(fake_line)

    assert stock is not None, "解析失败"
    assert stock['f12'] == '600519'
    assert stock['f14'] == '贵州茅台'
    assert stock['f2'] == 1266.98
    assert stock['f18'] == 1258.00
    assert stock['f17'] == 1257.98
    assert stock['f3'] == 0.71
    assert stock['f15'] == 1267.60
    assert stock['f16'] == 1254.00
    # 成交额来自字段35：2217338283元 ≈ 22.17亿
    assert abs(stock['f6'] - 2217338283) < 1, f"成交额应为2217338283，实际{stock['f6']}"
    logger.info(f"✓ 测试12通过: 腾讯行情字段解析正确，成交额={stock['f6']/1e8:.2f}亿")
    return True


if __name__ == '__main__':
    tests = [
        ("超时降级新浪", test_primary_timeout_fallback),
        ("空数据降级新浪", test_primary_empty_fallback),
        ("JSON失败降级新浪", test_primary_json_error_fallback),
        ("主源+新浪失败降级腾讯", test_primary_sina_fail_to_tencent),
        ("三源全失败", test_all_three_fail),
        ("主数据源正常不降级", test_primary_success_no_fallback),
        ("K线降级新浪", test_kline_fallback),
        ("K线降级腾讯", test_kline_fallback_to_tencent),
        ("板块数据降级", test_plate_fallback),
        ("safe_div安全除法", test_safe_div),
        ("to_float/to_int转换", test_to_float_to_int),
        ("腾讯行情字段解析", test_tencent_quote_parsing),
    ]

    passed = 0
    failed = 0
    for name, test_func in tests:
        try:
            test_func()
            passed += 1
        except AssertionError as e:
            logger.error(f"✗ {name} 失败: {e}")
            failed += 1
        except Exception as e:
            logger.error(f"✗ {name} 异常: {type(e).__name__}: {e}")
            failed += 1

    logger.info("\n" + "=" * 60)
    logger.info(f"测试结果: {passed}通过 / {failed}失败 / 共{len(tests)}项")
    logger.info("=" * 60)

    sys.exit(0 if failed == 0 else 1)
