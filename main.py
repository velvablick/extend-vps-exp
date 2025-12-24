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
        headless=True,
        humanize=True,
        geoip=True,  # 解决 LeakWarning，根据代理自动配置地理位置
    ) as browser:
        
        # 3. 在创建页面时指定录制视频
        # 在 Camoufox 中，new_page 会调用 Playwright 的 new_context
        page = browser.new_page(
            viewport={"width": 1080, "height": 1024},
            record_video_dir="./videos/", # 视频录制参数移到这里
            record_video_size={"width": 1080, "height": 1024}
        )
        
        try:
            print("正在访问登录页面...")
            page.goto('https://secure.xserver.ne.jp/xapanel/login/xvps/', wait_until='networkidle')

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
