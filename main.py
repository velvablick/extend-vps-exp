import os
import time
import shutil
import requests
from urllib.parse import urlparse
from camoufox.sync_api import Camoufox

def run_automation():
    # 1. 配置代理
    proxy_env = os.getenv('PROXY_SERVER')
    proxy_config = None
    if proxy_env:
        u = urlparse(proxy_env)
        proxy_config = {
            "server": f"{u.scheme}://{u.hostname}:{u.port}",
            "username": u.username,
            "password": u.password
        }

    # 2. 启动 Camoufox
    # 移除了 record_video_dir，增加了 geoip=True
   with Camoufox(
    proxy=proxy_config,
    geoip=True,
    headless=True,
    humanize=True,
    # --- 新增增强配置 ---
    i_am_not_a_bot=True,       # 启用内置的混淆加固
    block_webrtc=True,         # 防止 WebRTC 泄露真实 IP
    # 强制伪装成更常见的系统配置，减少被标记为虚拟机的概率
    os="windows",              # 模拟 Windows 环境
    browser="firefox",         # 明确指定模拟 Firefox
    ) as browser:
        # 使用 context 级别配置，进一步抹除自动化特征
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080}, # 使用更常见的显示分辨率
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
            record_video_dir="./videos/"
        )
        page = context.new_page()
        
        # 在跳转前增加随机等待，模拟人类打开浏览器的延迟
        time.sleep(2) 
    
        try:
            # 使用真实的引荐来源 (Referer)
            page.goto('https://secure.xserver.ne.jp/xapanel/login/xvps/', 
                      wait_until='networkidle', 
                      referer="https://www.google.com/")
    
            # --- 针对 Turnstile 的特殊处理 ---
            # 如果视频中显示卡在验证框，可以尝试显式等待验证框加载
            # Turnstile 通常在 iframe 中，Camoufox 理论上会自动处理
            # 但如果卡住，可以尝试移动鼠标到验证框区域
            page.mouse.move(200, 200) 
            time.sleep(1)

            # --- 业务逻辑开始 ---
            page.locator('#memberid').fill(os.getenv('EMAIL'))
            page.locator('#user_password').fill(os.getenv('PASSWORD'))
            page.get_by_text('ログインする').click()
            page.wait_for_load_state('networkidle')

            print("正在导航至 VPS 更新页面...")
            page.locator('a[href^="/xapanel/xvps/server/detail?id="]').first.click()
            page.get_by_text('更新する').click()
            page.get_by_text('引き続き無料VPSの利用を継続する').click()
            page.wait_for_load_state('networkidle')

            print("正在识别验证码...")
            img_element = page.locator('img[src^="data:"]')
            img_src = img_element.get_attribute('src')
            
            response = requests.post(
                'https://captcha-120546510085.asia-northeast1.run.app', 
                data=img_src,
                timeout=30
            )
            code = response.text.strip()
            print(f"识别结果: {code}")
            
            page.locator('[placeholder="上の画像の数字を入力"]').fill(code)
            print("正在尝试通过 Turnstile...")
            # 等待验证框对应的 iframe 出现
            time.sleep(5) 
            
            # 模拟人类随机移动鼠标，这有助于通过 Turnstile 的行为分析
            for i in range(5):
                page.mouse.move(100 + (i * 50), 100 + (i * 30))
                time.sleep(0.5)
            
            # 如果有显式的复选框，Camoufox 通常会自动处理，但我们可以手动“震慑”一下
            page.screenshot(path="before_turnstile.png")
            page.get_by_text('無料VPSの利用を継続する').click()
            
            time.sleep(5)
            print("任务成功完成！")
            # --- 业务逻辑结束 ---

        except Exception as e:
            print(f"发生错误: {e}")
            page.screenshot(path="error_debug.png")
            raise e
        finally:
            # 必须先关闭页面/上下文，视频才会完成写入
            video = page.video
            page.close() 
            
            if video:
                video_path = video.path()
                print(f"视频已录制到: {video_path}")
                if os.path.exists(video_path):
                    shutil.copy(video_path, 'recording.webm')

if __name__ == "__main__":
    run_automation()
