import os
import time
import shutil
import requests
from urllib.parse import urlparse
from camoufox.sync_api import Camoufox

def run_automation():
    proxy_env = os.getenv('PROXY_SERVER')
    proxy_config = None
    if proxy_env:
        u = urlparse(proxy_env)
        proxy_config = {
            "server": f"{u.scheme}://{u.hostname}:{u.port}",
            "username": u.username,
            "password": u.password
        }

    with Camoufox(
        proxy=proxy_config,
        geoip=True,
        headless=True,
        humanize=True,
    ) as browser:
        
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080}, 
            record_video_dir="./videos/"
        )
        page = context.new_page()
        page.set_extra_http_headers({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0"
        })
        
        try:
            print("正在访问登录页面...")
            page.goto('https://secure.xserver.ne.jp/xapanel/login/xvps/', wait_until='networkidle')
    
            # --- 登录步骤 ---
            page.locator('#memberid').fill(os.getenv('EMAIL'))
            page.locator('#user_password').fill(os.getenv('PASSWORD'))
            page.get_by_text('ログインする').click()
            page.wait_for_load_state('networkidle')

            # --- 导航至更新页面 ---
            print("正在导航至详情页...")
            page.locator('a[href^="/xapanel/xvps/server/detail?id="]').first.click()
            page.wait_for_selector('text=更新する', timeout=10000)
            page.get_by_text('更新する').click()
            page.wait_for_selector('text=引き続き無料VPSの利用を継続する', timeout=10000)
            page.get_by_text('引き続き無料VPSの利用を継続する').click()
            page.wait_for_load_state('networkidle')

            # --- 识别验证码 ---
            img_element = page.locator('img[src^="data:"]')
            img_src = img_element.get_attribute('src')
            response = requests.post('https://captcha-120546510085.asia-northeast1.run.app', data=img_src, timeout=30)
            code = response.text.strip()
            print(f"验证码识别结果: {code}")
            page.locator('[placeholder="上の画像の数字を入力"]').fill(code)
            
            # --- 核心改进：Turnstile 深度处理 ---
            print("检测 Turnstile 状态...")
            # 循环等待验证码完成渲染
            time.sleep(5) 
            
            turnstile_solved = False
            for _ in range(10): # 最多尝试 20 秒
                # 检查页面是否生成了 cf-turnstile-response (这是验证成功的标志)
                token = page.evaluate("() => document.querySelector('[name=\"cf-turnstile-response\"]')?.value")
                if token and len(token) > 10:
                    print("检测到验证 Token，Turnstile 已自动通过或手动识别成功。")
                    turnstile_solved = True
                    break
                
                # 如果没通过，尝试寻找 iframe 并点击
                for frame in page.frames:
                    if "cloudflare.com" in frame.url:
                        target = frame.locator('#checkbox, .ctp-checkbox-label')
                        if target.is_visible():
                            print("发现复选框，执行点击...")
                            target.click()
                            time.sleep(2)
                
                print(f"等待验证中... ({_}/10)")
                time.sleep(2)

            # --- 最终提交 ---
            page.screenshot(path="before_final_submit.png")
            
            # 使用更稳健的选择器：尝试 ID 或特定的 Submit 按钮属性
            # 根据 Xserver VPS 面板，通常是一个 submit 类型的 input 或 button
            submit_btn = page.locator('input[type="submit"], button[type="submit"]').get_by_text('無料VPSの利用を継続する')
            
            print("尝试执行最终点击...")
            # 增加 force=True 以防按钮被不可见的元素遮挡
            submit_btn.click(timeout=10000, force=True)
            
            page.wait_for_load_state('networkidle')
            print("任务成功完成！")

        except Exception as e:
            print(f"执行异常: {e}")
            page.screenshot(path="error_debug.png")
            # 打印当前所有 frame 方便调试
            print("Frames:", [f.url for f in page.frames])
            raise e
        finally:
            video = page.video
            context.close() 
            if video:
                video_path = video.path()
                if os.path.exists(video_path):
                    shutil.copy(video_path, 'recording.webm')


if __name__ == "__main__":
    run_automation()
