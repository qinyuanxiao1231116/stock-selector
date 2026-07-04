import requests

class WechatNotifier:
    def __init__(self, send_keys):
        if isinstance(send_keys, str):
            self.send_keys = [send_keys]
        else:
            self.send_keys = list(send_keys)
        self.base_url = 'https://sctapi.ftqq.com'

    def send_message(self, title, content):
        if not self.send_keys:
            print("未配置Server酱SendKey，无法推送消息")
            return False

        all_success = True
        for i, send_key in enumerate(self.send_keys):
            url = f'{self.base_url}/{send_key}.send'
            params = {
                'title': title,
                'desp': content
            }

            try:
                response = requests.post(url, data=params, timeout=10)
                result = response.json()

                if result.get('code') == 0:
                    print(f"消息推送成功 (第{i+1}个人)")
                else:
                    print(f"消息推送失败 (第{i+1}个人): {result.get('message', '未知错误')}")
                    all_success = False
            except Exception as e:
                print(f"推送消息时出错 (第{i+1}个人): {e}")
                all_success = False

        return all_success
