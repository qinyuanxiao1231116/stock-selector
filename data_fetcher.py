import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

class StockDataFetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'
        })
        self.timeout = 3
    
    def get_collection_bidding(self):
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
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            data = response.json()
            if data['data'] and data['data']['diff']:
                return data['data']['diff']
            return []
        except Exception as e:
            print(f"获取集合竞价数据失败: {e}")
            return []
    
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
    
    def get_stock_plates_batch(self, codes):
        plate_info = {}
        with ThreadPoolExecutor(max_workers=20) as executor:
            future_to_code = {executor.submit(self._get_stock_plate_single, code): code for code in codes}
            for future in as_completed(future_to_code):
                result = future.result()
                plate_info[result['code']] = result
        return plate_info
    
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
    
    def get_kline_data_batch(self, codes, days=7):
        kline_info = {}
        with ThreadPoolExecutor(max_workers=20) as executor:
            future_to_code = {executor.submit(self._get_kline_single, code, days): code for code in codes}
            for future in as_completed(future_to_code):
                result = future.result()
                kline_info[result['code']] = result['klines']
        return kline_info