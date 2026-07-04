import requests

class WechatNotifier:
    def __init__(self, send_key):
        self.send_key = send_key
        self.base_url = 'https://sctapi.ftqq.com'
    
    def send_message(self, title, content):
        if not self.send_key:
            print("未配置Server酱SendKey，无法推送消息")
            return False
        
        url = f'{self.base_url}/{self.send_key}.send'
        params = {
            'title': title,
            'desp': content
        }
        
        try:
            response = requests.post(url, data=params, timeout=10)
            result = response.json()
            
            if result.get('code') == 0:
                print("消息推送成功")
                return True
            else:
                print(f"消息推送失败: {result.get('message', '未知错误')}")
                return False
        except Exception as e:
            print(f"推送消息时出错: {e}")
            return False