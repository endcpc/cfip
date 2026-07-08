import socket
import re
import time
import threading
from queue import Queue
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Cloudflare節點測試配置參數
TEST_TIMEOUT = 3  # 測試超時時間(秒)
TEST_PORT = 443   # 測試端口
MAX_THREADS = 3  # 最大線程數
TOP_NODES = 20    # 顯示和保存前N個最快節點
TXT_OUTPUT_FILE = "NL.txt"    # TXT結果保存文件

# 國家代碼到中文國家名稱的映射
COUNTRY_CODES = {
    'US': '美國',
    'CN': '中國',
    'JP': '日本',
    'SG': '新加坡',
    'KR': '韓國',
    'GB': '英國',
    'FR': '法國',
    'DE': '德國',
    'AU': '澳大利亞',
    'CA': '加拿大',
    'HK': '中國香港',
    'TW': '中國臺灣',
    'IN': '印度',
    'RU': '俄羅斯',
    'BR': '巴西',
    'MX': '墨西哥',
    'NL': '荷蘭',
    'SE': '瑞典',
    'CH': '瑞士',
    'IT': '意大利',
    'ES': '西班牙',
    'Unknown': '未知'
}

# IP地理位置查詢函數
def get_ip_country(ip):
    """獲取IP地址對應的國家信息(返回中文)"""
    try:
        # 驗證IP格式
        socket.inet_aton(ip)
        
        # 創建會話並配置重試機制
        import requests
        session = requests.Session()
        retry = Retry(total=3, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        
        # 嘗試使用ipwhois.app API (不需要API密鑰)
        try:
            url = f"https://ipwhois.app/json/{ip}"
            response = session.get(url, timeout=15)
            if response.status_code == 200:
                data = response.json()
                if 'country' in data and data['country']:
                    country = data['country']
                    # 轉換國家名稱爲中文
                    if country == 'United States':
                        return '美國'
                    elif country == 'China':
                        return '中國'
                    elif country == 'Japan':
                        return '日本'
                    elif country == 'Singapore':
                        return '新加坡'
                    elif country == 'South Korea':
                        return '韓國'
                    elif country == 'United Kingdom':
                        return '英國'
                    elif country == 'France':
                        return '法國'
                    elif country == 'Germany':
                        return '德國'
                    elif country == 'Australia':
                        return '澳大利亞'
                    elif country == 'Canada':
                        return '加拿大'
                    elif country == 'Hong Kong':
                        return '中國香港'
                    elif country == 'Taiwan':
                        return '中國臺灣'
                    # 如果是國家代碼，嘗試從映射中獲取中文名稱
                    elif len(country) == 2:
                        return COUNTRY_CODES.get(country, country)
                    return country
        except Exception as e:
            print(f"ipwhois.app錯誤 {ip}: {str(e)}")
        
        # 嘗試使用ip-api.com的備用端點 (使用HTTP而非HTTPS)
        try:
            url = f"http://ip-api.com/json/{ip}?fields=countryCode"
            response = session.get(url, timeout=15)
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'success' and 'countryCode' in data:
                    country_code = data['countryCode']
                    # 從映射中獲取中文國家名稱
                    return COUNTRY_CODES.get(country_code, country_code)
        except Exception as e:
            print(f"ip-api.com錯誤 {ip}: {str(e)}")
        
        # 基於IP地址範圍的簡單判斷 (Cloudflare IP範圍)
        # 這些IP看起來是Cloudflare的IP地址
        octets = ip.split('.')
        if octets[0] == '104' and octets[1] == '18':
            return '美國'  # Cloudflare US IPs
        elif octets[0] == '108' and octets[1] == '162':
            return '美國'  # Cloudflare US IPs
        elif octets[0] == '162' and octets[1] == '159':
            return '美國'  # Cloudflare US IPs
        elif octets[0] == '172' and octets[1] == '64':
            return '美國'  # Cloudflare US IPs
        
        return '未知'
    except Exception as e:
        print(f"IP驗證錯誤 {ip}: {str(e)}")
        return '未知'

def clean_ip(ip_str):
    """清理IP字符串，移除可能的冒號或其他字符"""
    # 移除末尾的冒號和空格
    ip_str = ip_str.strip().rstrip(':')
    # 驗證是否爲有效的IPv4地址
    pattern = r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$'
    if re.match(pattern, ip_str):
        # 進一步驗證每個數字是否在0-255範圍內
        parts = ip_str.split('.')
        if all(0 <= int(part) <= 255 for part in parts):
            return ip_str
    return None

# Cloudflare節點測試類
class CloudflareNodeTester:
    def __init__(self):
        self.nodes = set()  # 存儲節點IP，使用set避免重複
        self.results = []   # 存儲測試結果
        self.lock = threading.Lock()
    
    def fetch_known_nodes(self):
        """從公開來源獲取已知的Cloudflare節點IP"""

        
        # 常見的Cloudflare IP段
        ip_ranges = [
"104.20.0.0/24",
"188.114.96.0/24"
        ]
        
        # 從IP段生成部分IP示例
        for ip_range in ip_ranges:
            base_ip, cidr = ip_range.split('/')
            octets = base_ip.split('.')
            
            # 生成該網段的一些示例IP
            for i in range(1, 10):  # 每個網段生成9個示例IP
                ip = f"{octets[0]}.{octets[1]}.{octets[2]}.{i + int(octets[3])}"
                self.nodes.add(ip)
        
    
    def test_node_speed(self, ip):
        """測試單個節點的連接速度"""
        try:
            start_time = time.time()
            # 創建socket連接
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(TEST_TIMEOUT)
                result = s.connect_ex((ip, TEST_PORT))
                if result == 0:  # 連接成功
                    response_time = (time.time() - start_time) * 1000  # 轉換爲毫秒
                    return {
                        'ip': ip,
                        'reachable': True,
                        'response_time_ms': int(response_time),
                        'timestamp': datetime.now().isoformat()
                    }
                else:
                    return {
                        'ip': ip,
                        'reachable': False,
                        'response_time_ms': None,
                        'timestamp': datetime.now().isoformat()
                    }
        except Exception as e:
            return {
                'ip': ip,
                'reachable': False,
                'response_time_ms': None,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }
    
    def worker(self, queue):
        """線程工作函數"""
        while not queue.empty():
            ip = queue.get()
            try:
                result = self.test_node_speed(ip)
                with self.lock:
                    self.results.append(result)
                    # 每完成360個測試，打印進度
                    if len(self.results) % 360 == 0:
                        print(f"已測試 {len(self.results)}/{len(self.nodes)} 個")
            finally:
                queue.task_done()
    
    def test_all_nodes(self):
        """測試所有節點的速度"""

        
        # 創建任務隊列
        queue = Queue()
        for ip in self.nodes:
            queue.put(ip)
        
        # 啓動線程
        threads = []
        for _ in range(min(MAX_THREADS, len(self.nodes))):
            thread = threading.Thread(target=self.worker, args=(queue,))
            thread.start()
            threads.append(thread)
        
        # 等待所有線程完成
        for thread in threads:
            thread.join()
        

    
    def sort_and_display_results(self):
        """排序並顯示測試結果，包含中文國家信息"""
        # 過濾出可連接的節點並按響應時間排序
        reachable_nodes = [
            node for node in self.results 
            if node['reachable'] and node['response_time_ms'] is not None
        ]
        
        # 按響應時間升序排序(最快的在前)
        sorted_nodes = sorted(
            reachable_nodes, 
            key=lambda x: x['response_time_ms']
        )
        
        
        # 顯示前N個最快節點，包含中文國家信息
        for i, node in enumerate(sorted_nodes[:TOP_NODES], 1):
            country = get_ip_country(node['ip'])
            print(f"{node['ip']}#nl 【荷蘭】 NL")
        
        return sorted_nodes
    
    def save_results(self, results):
        """只保存前30名結果到TXT文件，並顯示中文國家信息"""
        try:
            # 只取前30名結果
            top_results = results[:10]  # 明確只取前30名
            
            with open(TXT_OUTPUT_FILE, 'w', encoding='utf-8') as f:
                # 清空文件並只寫入前30個結果
                for i, node in enumerate(top_results):
                    # 獲取IP的國家信息（已經是中文）
                    country = get_ip_country(node['ip'])
                    line = f"{node['ip']}#nl 【荷蘭】 NL\n"
                    f.write(line)
            
        except Exception as e:
            print(f"保存結果失敗: {e}")

# IP地理位置查詢功能
def batch_query_ip_countries():
    """批量查詢IP地址的國家信息(顯示中文)"""
    print("\n===== IP地址國家信息批量查詢 =====")
    
    # 從cf_IP.txt文件讀取IP地址列表
    try:
        with open(TXT_OUTPUT_FILE, 'r', encoding='utf-8') as f:
            ip_list = []
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and not line.startswith('=') and ':' in line:
                    # 從格式 "IP:端口#備註" 中提取IP
                    ip = line.split(':')[0].strip()
                    ip_list.append(ip)
                elif line and not line.startswith('#') and not line.startswith('=') and ' ' not in line and '.' in line:
                    # 純IP地址行
                    ip_list.append(line)
        print(f"從文件讀取了 {len(ip_list)} 個IP地址")
    except Exception as e:
        print(f"無法從文件讀取IP: {str(e)}")
        print("使用默認IP列表進行演示")
        # 默認IP列表
        ip_list = [
            "108.162.192.3", "108.162.192.7", "108.162.192.4", "108.162.192.9",
            "162.159.0.4", "162.159.0.1", "162.159.0.3", "108.162.192.2"
        ]
    
    # 清理並驗證IP地址列表
    cleaned_ips = []
    for ip in ip_list:
        cleaned_ip = clean_ip(ip)
        if cleaned_ip:
            cleaned_ips.append(cleaned_ip)
        else:
            print(f"無效的IP地址: {ip}")
    
    print(f"清理後有效IP地址數量: {len(cleaned_ips)}")
    
    # 獲取每個IP的國家信息（已經是中文）
    results = []
    for i, ip in enumerate(cleaned_ips):
        print(f"正在查詢 {i+1}/{len(cleaned_ips)}: {ip}")
        country = get_ip_country(ip)
        results.append(f"{ip} {country}")
        
        # 添加足夠的延遲以避免API請求過於頻繁
        if i < len(cleaned_ips) - 1:
            time.sleep(3)  # 增加延遲到3秒
    
    # 將結果寫入文件
    with open(IP_COUNTRIES_FILE, 'w', encoding='utf-8') as f:
        for result in results:
            f.write(result + '\n')
    
    print(f"\n查詢完成！結果已保存到 {IP_COUNTRIES_FILE}")
    print(f"處理的IP地址總數: {len(results)}")
    
    # 顯示有國家信息的IP數量
    successful_queries = sum(1 for r in results if not r.endswith(' 未知'))
    print(f"獲取到國家信息的IP數量: {successful_queries}")
    print("===================================")

# Cloudflare節點測試功能
def test_cloudflare_nodes():
    """運行Cloudflare節點測試"""
    print("\n===== Cloudflare節點測速工具 =====")
    tester = CloudflareNodeTester()
    tester.run()

# CloudflareNodeTester類的run方法
def run_cloudflare_tester(self):
    """運行整個測試流程"""
    start_time = time.time()
    
    # 1. 獲取節點
    self.fetch_known_nodes()
    
    # 2. 測試所有節點
    self.test_all_nodes()
    
    # 3. 排序並顯示結果
    sorted_nodes = self.sort_and_display_results()
    
    # 4. 保存結果
    self.save_results(sorted_nodes)
    
    total_time = int(time.time() - start_time)

# 添加run方法到CloudflareNodeTester類
CloudflareNodeTester.run = run_cloudflare_tester

# 主函數 - 直接執行Cloudflare節點測試
if __name__ == "__main__":

    try:
        # 直接執行Cloudflare節點測試
        tester = CloudflareNodeTester()
        tester.run()
        
    except KeyboardInterrupt:
        print("\n用戶中斷了程序")
    except Exception as e:
        print(f"程序出錯: {e}")

