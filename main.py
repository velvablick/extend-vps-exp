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
    with Camoufox(
        proxy=proxy_config,
        geoip=True,
        headless=True,
        humanize=True,
    ) as browser:
        
        # 3. 创建上下文并配置录屏
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080}, 
            record_video_dir="./videos/"
        )
        page = context.new_page()
        
        # 伪装 User-Agent
        page.set_extra_http_headers({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0"
        })
        
        try:
            print("正在访问登录页面...")
            page.goto('https://secure.xserver.ne.jp/xapanel/login/xvps/', 
                      wait_until='networkidle', 
                      referer="https://www.google.com/")
    
            # 初始随机操作
            page.mouse.move(300, 300) 
            time.sleep(1)

            # --- 登录步骤 ---
            page.locator('#memberid').fill(os.getenv('EMAIL'))
            page.locator('#user_password').fill(os.getenv('PASSWORD'))
            page.get_by_text('ログインする').click()
            page.wait_for_load_state('networkidle')

            # --- 导航至更新页面 ---
            print("正在导航至 VPS 更新页面...")
            page.locator('a[href^="/xapanel/xvps/server/detail?id="]').first.click()
            page.get_by_text('更新する').click()
            page.get_by_text('引き続き無料VPSの利用を継続する').click()
            page.wait_for_load_state('networkidle')

            # --- 识别验证码 ---
            print("正在提取并识别图形验证码...")
            img_element = page.locator('img[src^="data:"]')
            img_src = img_element.get_attribute('src')
            
            response = requests.post(
                'https://captcha-120546510085.asia-northeast1.run.app', 
                data=img_src,
                timeout=30
            )
            code = response.text.strip()
            print(f"识别结果: {code}")
            
            # 填入验证码
            page.locator('[placeholder="上の画像の数字を入力"]').fill(code)
            
            # --- 核心改进：处理 Turnstile 验证框 ---
            print("检测到潜在的 Turnstile 验证，正在尝试穿透 iframe...")
            time.sleep(3) # 等待验证框加载完成

            # 遍历所有 iframe 寻找 Cloudflare 验证页面
            turnstile_frame = None
            for frame in page.frames:
                if "cloudflare.com" in frame.url or "turnstile" in frame.url:
                    turnstile_frame = frame
                    break

            if turnstile_frame:
                print("成功锁定 Turnstile iframe，准备点击...")
                # 尝试点击常见的复选框标识符
                checkbox = turnstile_frame.locator('#checkbox, .ctp-checkbox-container, input[type="checkbox"]')
                
                if checkbox.is_visible():
                    # 获取复选框的坐标位置进行物理点击
                    box = checkbox.bounding_box()
                    if box:
                        # 在复选框中心位置模拟点击
                        page.mouse.click(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
                        print("已模拟点击复选框。")
                    else:
                        # 如果无法获取 box，尝试直接点击元素
                        checkbox.click()
                        print("已直接点击复选框元素。")
                else:
                    print("复选框在 iframe 内不可见，可能已自动通过。")
            else:
                print("未发现匹配的 Turnstile iframe。")

            # 验证后的观察期，等待 Token 生效
            print("进入观察期，模拟人类阅读...")
            for _ in range(3):
                page.mouse.move(500, 500 + (_ * 20))
                time.sleep(1)
            
            # 提交前截屏以便调试
            page.screenshot(path="before_final_click.png")
            
            # --- 提交申请 ---
            print("尝试执行最终提交...")
            page.get_by_text('無料VPSの利用を継続する').click()
            
            # 等待结果跳转
            time.sleep(5)
            print("流程执行完毕。")

        except Exception as e:
            print(f"执行过程中发生异常: {e}")
            page.screenshot(path="error_debug.png")
            raise e
        finally:
            # 确保视频文件正确关闭并保存
            video = page.video
            context.close() 
            
            if video:
                video_path = video.path()
                if os.path.exists(video_path):
                    shutil.copy(video_path, 'recording.webm')
                    print(f"录屏已成功导出至 recording.webm")

if __name__ == "__main__":
    run_automation()
