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
    # 注意：这里只保留属于启动阶段的参数
    with Camoufox(
        proxy=proxy_config,
        geoip=True,
        headless=True,
        humanize=True,
        # i_am_not_a_bot 不在这里设置
    ) as browser:
        
        # 3. 在创建上下文时设置隐身增强和视频录制
        # 将 i_am_not_a_bot, block_webrtc 等参数放在这里
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080}, 
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
            record_video_dir="./videos/",
            # --- 隐身增强配置移至此处 ---
            i_am_not_a_bot=True,
            block_webrtc=True,
            os="windows",
            browser="firefox"
        )
        page = context.new_page()
        
        time.sleep(2) 
    
        try:
            print("正在访问登录页面...")
            page.goto('https://secure.xserver.ne.jp/xapanel/login/xvps/', 
                      wait_until='networkidle', 
                      referer="https://www.google.com/")
    
            # 模拟随机行为
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
            
            print("正在等待 Turnstile 验证并模拟人为操作...")
            time.sleep(5) 
            
            # 模拟人类随机移动鼠标以辅助通过验证
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
            # 获取视频路径
            video = page.video
            # 必须关闭 context，Playwright 才会将视频从内存写入磁盘
            context.close() 
            
            if video:
                video_path = video.path()
                if os.path.exists(video_path):
                    shutil.copy(video_path, 'recording.webm')
                    print(f"视频已保存至 recording.webm")

if __name__ == "__main__":
    run_automation()
