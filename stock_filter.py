from data_fetcher import StockDataFetcher

def to_float(val, default=0):
    try:
        return float(val) if val is not None and val != '' else default
    except (ValueError, TypeError):
        return default

def to_int(val, default=0):
    try:
        return int(float(val)) if val is not None and val != '' else default
    except (ValueError, TypeError):
        return default

class StockFilter:
    def __init__(self):
        self.fetcher = StockDataFetcher()
    
    def filter_limit_up_with_increasing_bids(self, threshold=10000):
        bidding_data = self.fetcher.get_collection_bidding()
        if not bidding_data:
            return []
        
        candidates = []
        for stock in bidding_data:
            code = str(stock.get('f12', ''))
            name = str(stock.get('f14', ''))
            price = to_float(stock.get('f2')) / 100
            prev_close = to_float(stock.get('f20')) / 100
            limit_up_price = to_float(stock.get('f15')) / 100
            buy1_volume = to_int(stock.get('f47'))
            
            if price > 0 and limit_up_price > 0:
                price_diff = abs(price - limit_up_price)
                if price_diff <= 0.01 and buy1_volume >= threshold:
                    candidates.append({
                        'code': code,
                        'name': name,
                        'price': price,
                        'limit_up_price': limit_up_price,
                        'buy1_volume': buy1_volume,
                        'prev_close': prev_close
                    })
        
        if not candidates:
            return []
        
        codes = [c['code'] for c in candidates]
        plate_info = self.fetcher.get_stock_plates_batch(codes)
        
        results = []
        for c in candidates:
            plate = plate_info.get(c['code'], {})
            results.append({
                'code': c['code'],
                'name': c['name'],
                'price': round(c['price'], 2),
                'limit_up_price': round(c['limit_up_price'], 2),
                'buy1_volume': c['buy1_volume'],
                'prev_close': round(c['prev_close'], 2),
                'change_percent': round((c['price'] - c['prev_close']) / c['prev_close'] * 100, 2) if c['prev_close'] > 0 else 0,
                'industry': plate.get('industry', ''),
                'concept': plate.get('concept', '')
            })
        
        results.sort(key=lambda x: x['buy1_volume'], reverse=True)
        return results
    
    def filter_gapping_up(self, gap_threshold=1.0):
        bidding_data = self.fetcher.get_collection_bidding()
        if not bidding_data:
            return []
        
        candidates = []
        for stock in bidding_data:
            code = str(stock.get('f12', ''))
            name = str(stock.get('f14', ''))
            current_price = to_float(stock.get('f2')) / 100
            prev_close = to_float(stock.get('f20')) / 100
            open_price = to_float(stock.get('f26')) / 100
            
            if prev_close > 0 and current_price > 0:
                gap_percent = (current_price - prev_close) / prev_close * 100
                if gap_percent >= gap_threshold:
                    candidates.append({
                        'code': code,
                        'name': name,
                        'current_price': current_price,
                        'prev_close': prev_close,
                        'open_price': open_price,
                        'gap_percent': gap_percent
                    })
        
        if not candidates:
            return []
        
        codes = [c['code'] for c in candidates]
        plate_info = self.fetcher.get_stock_plates_batch(codes)
        
        results = []
        for c in candidates:
            plate = plate_info.get(c['code'], {})
            results.append({
                'code': c['code'],
                'name': c['name'],
                'current_price': round(c['current_price'], 2),
                'prev_close': round(c['prev_close'], 2),
                'open_price': round(c['open_price'], 2),
                'gap_percent': round(c['gap_percent'], 2),
                'industry': plate.get('industry', ''),
                'concept': plate.get('concept', '')
            })
        
        results.sort(key=lambda x: x['gap_percent'], reverse=True)
        return results
    
    def filter_buying_rush(self, volume_threshold=5000, price_increase_threshold=2.0):
        bidding_data = self.fetcher.get_collection_bidding()
        if not bidding_data:
            return []
        
        candidates = []
        for stock in bidding_data:
            code = str(stock.get('f12', ''))
            name = str(stock.get('f14', ''))
            current_price = to_float(stock.get('f2')) / 100
            prev_close = to_float(stock.get('f20')) / 100
            buy1_volume = to_int(stock.get('f47'))
            sell1_volume = to_int(stock.get('f48'))
            
            if prev_close > 0 and current_price > 0:
                price_increase = (current_price - prev_close) / prev_close * 100
                buy_sell_ratio = buy1_volume / (sell1_volume + 1)
                if buy1_volume >= volume_threshold and price_increase >= price_increase_threshold and buy_sell_ratio > 2:
                    candidates.append({
                        'code': code,
                        'name': name,
                        'current_price': current_price,
                        'prev_close': prev_close,
                        'price_increase': price_increase,
                        'buy1_volume': buy1_volume,
                        'sell1_volume': sell1_volume,
                        'buy_sell_ratio': buy_sell_ratio
                    })
        
        if not candidates:
            return []
        
        codes = [c['code'] for c in candidates]
        plate_info = self.fetcher.get_stock_plates_batch(codes)
        
        results = []
        for c in candidates:
            plate = plate_info.get(c['code'], {})
            results.append({
                'code': c['code'],
                'name': c['name'],
                'current_price': round(c['current_price'], 2),
                'prev_close': round(c['prev_close'], 2),
                'price_increase': round(c['price_increase'], 2),
                'buy1_volume': c['buy1_volume'],
                'sell1_volume': c['sell1_volume'],
                'buy_sell_ratio': round(c['buy_sell_ratio'], 2),
                'industry': plate.get('industry', ''),
                'concept': plate.get('concept', '')
            })
        
        results.sort(key=lambda x: x['buy_sell_ratio'], reverse=True)
        return results
    
    def has_recent_limit_up(self, klines, days=7):
        for kline in klines[:days]:
            if kline.get('change_percent', 0) >= 9.8:
                return True
        return False
    
    def is_doji(self, kline):
        open_p = kline.get('open', 0)
        close_p = kline.get('close', 0)
        high_p = kline.get('high', 0)
        low_p = kline.get('low', 0)
        
        if high_p == low_p:
            return False
        
        body_size = abs(close_p - open_p)
        range_size = high_p - low_p
        
        return body_size / range_size <= 0.15
    
    def is_inverted_hammer(self, current_price, kline):
        open_p = kline.get('open', 0)
        high_p = kline.get('high', 0)
        low_p = kline.get('low', 0)
        
        if high_p == low_p:
            return False
        
        if not (open_p < current_price < high_p):
            return False
        
        upper_shadow = high_p - max(open_p, current_price)
        body_size = abs(current_price - open_p)
        range_size = high_p - low_p
        
        return upper_shadow / range_size >= 0.6 and body_size / range_size <= 0.3
    
    def filter_late_session(self, days=7):
        bidding_data = self.fetcher.get_collection_bidding()
        if not bidding_data:
            return []
        
        codes = [str(stock.get('f12', '')) for stock in bidding_data]
        kline_info = self.fetcher.get_kline_data_batch(codes, days)
        
        candidates = []
        for stock in bidding_data:
            code = str(stock.get('f12', ''))
            name = str(stock.get('f14', ''))
            klines = kline_info.get(code, [])
            
            if len(klines) < 2:
                continue
            
            if not self.has_recent_limit_up(klines[:-1], days):
                continue
            
            today_kline = klines[-1]
            current_price = to_float(stock.get('f2')) / 100
            
            is_doji_pattern = self.is_doji(today_kline)
            is_inverted_t = self.is_inverted_hammer(current_price, today_kline)
            
            if is_doji_pattern or is_inverted_t:
                candidates.append({
                    'code': code,
                    'name': name,
                    'current_price': current_price,
                    'open': today_kline.get('open', 0),
                    'high': today_kline.get('high', 0),
                    'low': today_kline.get('low', 0),
                    'pattern': '十字星' if is_doji_pattern else '倒T形态'
                })
        
        if not candidates:
            return []
        
        plate_codes = [c['code'] for c in candidates]
        plate_info = self.fetcher.get_stock_plates_batch(plate_codes)
        
        results = []
        for c in candidates:
            plate = plate_info.get(c['code'], {})
            results.append({
                'code': c['code'],
                'name': c['name'],
                'current_price': round(c['current_price'], 2),
                'open': round(c['open'], 2),
                'high': round(c['high'], 2),
                'low': round(c['low'], 2),
                'pattern': c['pattern'],
                'industry': plate.get('industry', ''),
                'concept': plate.get('concept', '')
            })
        
        results.sort(key=lambda x: x['current_price'], reverse=True)
        return results