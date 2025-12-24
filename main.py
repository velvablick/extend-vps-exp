import os
import time
import requests
from urllib.parse import urlparse
from camoufox.sync_api import Camoufox
from playwright.sync_api import sync_playwright

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
    # 使用 record_video_dir 指定视频保存目录
    # Camoufox 会自动处理指纹，使 Turnstile 验证失效
    with Camoufox(
        proxy=proxy_config,
        headless=True,
        humanize=True,
        record_video_dir="./videos/", 
        record_video_size={"width": 1080, "height": 1024}
    ) as browser:
        # 创建页面上下文
        page = browser.new_page(viewport={"width": 1080, "height": 1024})
        
        try:
            print("正在访问登录页面...")
            page.goto('https://secure.xserver.ne.jp/xapanel/login/xvps/', wait_until='networkidle')

            # 3. 登录逻辑
            page.locator('#memberid').fill(os.getenv('EMAIL'))
            page.locator('#user_password').fill(os.getenv('PASSWORD'))
            page.get_by_text('ログインする').click()
            page.wait_for_load_state('networkidle')

            # 4. 导航至详情页并点击更新
            print("正在导航至 VPS 更新页面...")
            # 使用 first 防止匹配到多个相同的链接
            page.locator('a[href^="/xapanel/xvps/server/detail?id="]').first.click()
            page.get_by_text('更新する').click()
            page.get_by_text('引き続き無料VPSの利用を継続する').click()
            page.wait_for_load_state('networkidle')

            # 5. 处理图形验证码 (OCR)
            print("正在识别验证码...")
            img_element = page.locator('img[src^="data:"]')
            img_src = img_element.get_attribute('src')
            
            # 发送到您的 Google Cloud Run OCR 接口
            response = requests.post(
                'https://captcha-120546510085.asia-northeast1.run.app', 
                data=img_src,
                timeout=30
            )
            code = response.text.strip()
            print(f"识别结果: {code}")
            
            # 6. 填入验证码并提交
            page.locator('[placeholder="上の画像の数字を入力"]').fill(code)
            page.get_by_text('無料VPSの利用を継続する').click()
            
            # 等待确认操作完成
            time.sleep(5)
            print("任务成功完成！")

        except Exception as e:
            print(f"发生错误: {e}")
            # 即使报错也截图，方便通过 GitHub Artifacts 查看
            page.screenshot(path="error_debug.png")
            raise e
        finally:
            # 获取录制视频的路径并重命名（方便 YAML 文件上传）
            video_path = page.video.path()
            if os.path.exists(video_path):
                import shutil
                shutil.copy(video_path, 'recording.webm')
            browser.close()

if __name__ == "__main__":
    run_automation()
