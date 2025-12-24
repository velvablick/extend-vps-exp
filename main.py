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

    # 2. 启动 Camoufox (已修复缩进)
    with Camoufox(
        proxy=proxy_config,
        geoip=True,
        headless=True,
        humanize=True,
        i_am_not_a_bot=True,       
        block_webrtc=True,         
        os="windows",              
        browser="firefox",         
    ) as browser:
        # 使用 context 级别配置
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080}, 
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
            record_video_dir="./videos/"
        )
        page = context.new_page()
        
        time.sleep(2) 
    
        try:
            # 使用真实的引荐来源
            page.goto('https://secure.xserver.ne.jp/xapanel/login/xvps/', 
                      wait_until='networkidle', 
                      referer="https://www.google.com/")
    
            # 针对 Turnstile 的模拟行为
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
            
            print("正在等待 Turnstile 验证...")
            time.sleep(5) 
            
            # 模拟人类随机移动鼠标
            for i in range(5):
                page.mouse.move(100 + (i * 50), 100 + (i * 30))
                time.sleep(0.5)
            
            page.screenshot(path="before_turnstile.png")
            page.get_by_text('無料VPSの利用を継続する').click()
            
            time.sleep(5)
            print("任务成功完成！")

        except Exception as e:
            print(f"发生错误: {e}")
            page.screenshot(path="error_debug.png")
            raise e
        finally:
            # 保存录屏逻辑
            video = page.video
            context.close() # 必须关闭 context 以释放视频文件锁
            
            if video:
                video_path = video.path()
                if os.path.exists(video_path):
                    shutil.copy(video_path, 'recording.webm')
                    print(f"视频已保存至 recording.webm")

if __name__ == "__main__":
    run_automation()
