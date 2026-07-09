import requests
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from sina_fetcher import SinaFetcher

logger = logging.getLogger(__name__)

class StockDataFetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'
        })
        self.timeout = 3
        self.fallback = SinaFetcher()
        self.use_fallback = False

    def _try_with_fallback(self, primary_func, fallback_func, func_name):
        """尝试主数据源，失败时自动降级到备选"""
        if self.use_fallback:
            logger.info(f"[数据源切换] {func_name} -> 备选(新浪)，原因: 已标记降级")
            return fallback_func()

        logger.info(f"[数据源切换] {func_name} -> 主(东方财富)，尝试请求...")
        start_time = time.time()
        result = []

        try:
            result = primary_func()
            elapsed = time.time() - start_time
            if result is not None and len(result) > 0 if isinstance(result, list) else result:
                logger.info(f"[数据源切换] {func_name} <- 主(东方财富) 成功，耗时{elapsed:.2f}s，数据量={len(result) if isinstance(result, list) else 'dict'}")
                return result
            # 主数据源返回空，尝试备选
            logger.warning(f"[数据源切换] {func_name} <- 主(东方财富) 返回空数据，耗时{elapsed:.2f}s，降级到备选")
        except Exception as e:
            elapsed = time.time() - start_time
            logger.warning(f"[数据源切换] {func_name} <- 主(东方财富) 异常: {type(e).__name__}: {e}，耗时{elapsed:.2f}s，降级到备选")

        logger.info(f"[数据源切换] {func_name} -> 备选(新浪)，尝试请求...")
        fallback_start = time.time()

        try:
            result = fallback_func()
            fallback_elapsed = time.time() - fallback_start
            if result:
                logger.info(f"[数据源切换] {func_name} <- 备选(新浪) 成功，耗时{fallback_elapsed:.2f}s，数据量={len(result) if isinstance(result, list) else 'dict'}，后续优先使用备选")
                self.use_fallback = True
                return result
            logger.warning(f"[数据源切换] {func_name} <- 备选(新浪) 返回空数据")
        except Exception as e:
            fallback_elapsed = time.time() - fallback_start
            logger.error(f"[数据源切换] {func_name} <- 备选(新浪) 异常: {type(e).__name__}: {e}，耗时{fallback_elapsed:.2f}s")

        return [] if isinstance(result, list) else {}

    def get_collection_bidding(self):
        return self._try_with_fallback(
            self._get_collection_bidding_primary,
            self.fallback.get_collection_bidding,
            "集合竞价"
        )

    def _get_collection_bidding_primary(self):
        url = 'http://push2.eastmoney.com/api/qt/clist/get'
        params = {
            'pn': '1',
            'pz': '10000',
            'po': '1',
            'np': '1',
            'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
            'fltt': '2',
            'invt': '2',
            'fid': 'f3',
            'fs': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23',
            'fields': 'f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23,f24,f25,f26,f27,f28,f30,f31,f32,f33,f34,f35,f36,f37,f38,f39,f40,f41,f42,f43,f44,f45,f46,f47,f48,f49,f50,f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65'
        }
        response = self.session.get(url, params=params, timeout=self.timeout)
        data = response.json()
        if data['data'] and data['data']['diff']:
            return data['data']['diff']
        return []

    def get_stock_plates_batch(self, codes):
        return self._try_with_fallback(
            lambda: self._get_stock_plates_batch_primary(codes),
            lambda: self.fallback.get_stock_plates_batch(codes),
            "板块信息"
        )

    def _get_stock_plate_single(self, code):
        url = f'http://push2.eastmoney.com/api/qt/stock/get'
        params = {
            'secid': f'0.{code}' if code.startswith('6') else f'1.{code}',
            'fields': 'f102,f103,f104,f105'
        }
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            data = response.json()
            if data['data']:
                return {
                    'code': code,
                    'industry': data['data'].get('f102', ''),
                    'concept': data['data'].get('f103', ''),
                    'region': data['data'].get('f104', ''),
                    'market': data['data'].get('f105', '')
                }
            return {'code': code, 'industry': '', 'concept': '', 'region': '', 'market': ''}
        except Exception:
            return {'code': code, 'industry': '', 'concept': '', 'region': '', 'market': ''}

    def _get_stock_plates_batch_primary(self, codes):
        plate_info = {}
        with ThreadPoolExecutor(max_workers=20) as executor:
            future_to_code = {executor.submit(self._get_stock_plate_single, code): code for code in codes}
            for future in as_completed(future_to_code):
                result = future.result()
                plate_info[result['code']] = result
        return plate_info

    def get_kline_data_batch(self, codes, days=7):
        return self._try_with_fallback(
            lambda: self._get_kline_data_batch_primary(codes, days),
            lambda: self.fallback.get_kline_data_batch(codes, days),
            "K线数据"
        )

    def _get_kline_single(self, code, days=7):
        url = 'http://push2his.eastmoney.com/api/qt/stock/kline/get'
        params = {
            'secid': f'0.{code}' if code.startswith('6') else f'1.{code}',
            'fields1': 'f1,f2,f3,f4,f5,f6',
            'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
            'klt': '101',
            'fqt': '1',
            'beg': '',
            'end': '',
            'smplmt': days
        }
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            data = response.json()
            if data['data'] and data['data']['klines']:
                klines = []
                for kline_str in data['data']['klines']:
                    parts = kline_str.split(',')
                    if len(parts) >= 11:
                        klines.append({
                            'date': parts[0],
                            'open': float(parts[1]),
                            'close': float(parts[2]),
                            'high': float(parts[3]),
                            'low': float(parts[4]),
                            'volume': int(parts[5]),
                            'amount': float(parts[6]),
                            'amplitude': float(parts[7]),
                            'change_percent': float(parts[8]),
                            'change': float(parts[9]),
                            'turnover': float(parts[10])
                        })
                return {'code': code, 'klines': klines}
            return {'code': code, 'klines': []}
        except Exception:
            return {'code': code, 'klines': []}

    def _get_kline_data_batch_primary(self, codes, days=7):
        kline_info = {}
        with ThreadPoolExecutor(max_workers=20) as executor:
            future_to_code = {executor.submit(self._get_kline_single, code, days): code for code in codes}
            for future in as_completed(future_to_code):
                result = future.result()
                kline_info[result['code']] = result['klines']
        return kline_info
