"""
模拟东方财富接口超时/异常的测试脚本
验证降级逻辑是否正常生效
"""
import sys
import logging
from unittest.mock import patch, MagicMock

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

def test_primary_timeout_fallback():
    """测试1: 东方财富超时 -> 自动降级到新浪"""
    logger.info("=" * 60)
    logger.info("测试1: 模拟东方财富超时，验证降级到新浪")
    logger.info("=" * 60)

    from data_fetcher import StockDataFetcher
    fetcher = StockDataFetcher()

    # 模拟东方财富超时
    with patch.object(fetcher, '_get_collection_bidding_primary',
                      side_effect=TimeoutError("东方财富连接超时")):
        # 新浪返回正常数据
        mock_data = [
            {'f12': '000001', 'f14': '平安银行', 'f2': 1200, 'f20': 1150}
        ]
        with patch.object(fetcher.fallback, 'get_collection_bidding', return_value=mock_data):
            result = fetcher.get_collection_bidding()

    assert result == mock_data, f"预期返回新浪数据，实际: {result}"
    assert fetcher.use_fallback == True, "降级标记未设置"
    logger.info(f"✓ 测试1通过: 超时后自动降级到新浪，数据量={len(result)}")

    # 验证后续请求直接走新浪
    logger.info("验证后续请求是否直接走备选...")
    with patch.object(fetcher.fallback, 'get_collection_bidding', return_value=mock_data):
        result2 = fetcher.get_collection_bidding()
    assert result2 == mock_data, "后续请求未走备选"
    logger.info("✓ 后续请求正确走备选数据源")

    fetcher.use_fallback = False
    return True


def test_primary_empty_fallback():
    """测试2: 东方财富返回空 -> 降级到新浪"""
    logger.info("\n" + "=" * 60)
    logger.info("测试2: 模拟东方财富返回空数据，验证降级")
    logger.info("=" * 60)

    from data_fetcher import StockDataFetcher
    fetcher = StockDataFetcher()

    with patch.object(fetcher, '_get_collection_bidding_primary', return_value=[]):
        mock_data = [{'f12': '600000', 'f14': '浦发银行', 'f2': 800, 'f20': 790}]
        with patch.object(fetcher.fallback, 'get_collection_bidding', return_value=mock_data):
            result = fetcher.get_collection_bidding()

    assert result == mock_data, f"预期返回新浪数据，实际: {result}"
    assert fetcher.use_fallback == True, "降级标记未设置"
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
        mock_data = [{'f12': '300001', 'f14': '特锐德', 'f2': 1500, 'f20': 1450}]
        with patch.object(fetcher.fallback, 'get_collection_bidding', return_value=mock_data):
            result = fetcher.get_collection_bidding()

    assert result == mock_data, f"预期返回新浪数据，实际: {result}"
    assert fetcher.use_fallback == True
    logger.info(f"✓ 测试3通过: JSON解析失败后自动降级到新浪")
    return True


def test_both_fail():
    """测试4: 东方财富和新浪都失败 -> 返回空"""
    logger.info("\n" + "=" * 60)
    logger.info("测试4: 双数据源都失败，验证返回空列表")
    logger.info("=" * 60)

    from data_fetcher import StockDataFetcher
    fetcher = StockDataFetcher()

    with patch.object(fetcher, '_get_collection_bidding_primary',
                      side_effect=TimeoutError("东方财富超时")):
        with patch.object(fetcher.fallback, 'get_collection_bidding',
                          side_effect=ConnectionError("新浪也无法连接")):
            result = fetcher.get_collection_bidding()

    assert result == [], f"预期返回空列表，实际: {result}"
    logger.info(f"✓ 测试4通过: 双数据源失败返回空列表")
    return True


def test_primary_success_no_fallback():
    """测试5: 东方财富正常 -> 不降级"""
    logger.info("\n" + "=" * 60)
    logger.info("测试5: 东方财富正常返回，不触发降级")
    logger.info("=" * 60)

    from data_fetcher import StockDataFetcher
    fetcher = StockDataFetcher()

    mock_data = [
        {'f12': '000002', 'f14': '万科A', 'f2': 900, 'f20': 880}
    ]
    with patch.object(fetcher, '_get_collection_bidding_primary', return_value=mock_data):
        result = fetcher.get_collection_bidding()

    assert result == mock_data, f"预期返回东方财富数据，实际: {result}"
    assert fetcher.use_fallback == False, "不应设置降级标记"
    logger.info(f"✓ 测试5通过: 东方财富正常时不降级")
    return True


def test_kline_fallback():
    """测试6: K线数据降级"""
    logger.info("\n" + "=" * 60)
    logger.info("测试6: K线数据降级测试")
    logger.info("=" * 60)

    from data_fetcher import StockDataFetcher
    fetcher = StockDataFetcher()

    mock_klines = {'600519': [{'date': '2026-07-09', 'open': 1800, 'close': 1820, 'high': 1830, 'low': 1790}]}

    with patch.object(fetcher, '_get_kline_data_batch_primary',
                      side_effect=TimeoutError("K线接口超时")):
        with patch.object(fetcher.fallback, 'get_kline_data_batch', return_value=mock_klines):
            result = fetcher.get_kline_data_batch(['600519'])

    assert result == mock_klines, f"预期返回新浪K线数据，实际: {result}"
    assert fetcher.use_fallback == True
    logger.info(f"✓ 测试6通过: K线数据降级成功")
    return True


def test_plate_fallback():
    """测试7: 板块数据降级"""
    logger.info("\n" + "=" * 60)
    logger.info("测试7: 板块数据降级测试")
    logger.info("=" * 60)

    from data_fetcher import StockDataFetcher
    fetcher = StockDataFetcher()

    mock_plates = {'000001': {'code': '000001', 'industry': '银行', 'concept': '', 'region': '', 'market': ''}}

    with patch.object(fetcher, '_get_stock_plates_batch_primary',
                      side_effect=ConnectionError("板块接口连接失败")):
        with patch.object(fetcher.fallback, 'get_stock_plates_batch', return_value=mock_plates):
            result = fetcher.get_stock_plates_batch(['000001'])

    assert result == mock_plates, f"预期返回新浪板块数据，实际: {result}"
    assert fetcher.use_fallback == True
    logger.info(f"✓ 测试7通过: 板块数据降级成功")
    return True


def test_safe_div():
    """测试8: safe_div安全除法"""
    logger.info("\n" + "=" * 60)
    logger.info("测试8: safe_div安全除法函数")
    logger.info("=" * 60)

    from stock_filter import safe_div

    assert safe_div(10, 2) == 5.0, "10/2 应该=5"
    assert safe_div(10, 0) == 0, "除零应返回0"
    assert safe_div(10, 0, default=-1) == -1, "除零应返回自定义默认值"
    assert safe_div(0, 5) == 0, "0/5 应该=0"
    assert safe_div(-10, 2) == -5.0, "负数除法"
    assert safe_div('a', 2) == 0, "非数字应返回0"
    assert safe_div(10, 'b') == 0, "非数字分母应返回0"
    logger.info(f"✓ 测试8通过: safe_div所有场景正确")
    return True


def test_to_float_to_int():
    """测试9: to_float和to_int类型转换"""
    logger.info("\n" + "=" * 60)
    logger.info("测试9: to_float/to_int类型转换")
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

    logger.info(f"✓ 测试9通过: to_float/to_int类型转换正确")
    return True


if __name__ == '__main__':
    tests = [
        ("超时降级", test_primary_timeout_fallback),
        ("空数据降级", test_primary_empty_fallback),
        ("JSON解析失败降级", test_primary_json_error_fallback),
        ("双数据源失败", test_both_fail),
        ("主数据源正常不降级", test_primary_success_no_fallback),
        ("K线数据降级", test_kline_fallback),
        ("板块数据降级", test_plate_fallback),
        ("safe_div安全除法", test_safe_div),
        ("to_float/to_int转换", test_to_float_to_int),
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
