import os
import time
import shutil
import json
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

    # 读取并解析本地 Cookie (这是关键！)
    cookies_json = os.getenv('COOKIES_JSON')
    cookies_list = []
    if cookies_json:
        try:
            cookies_list = json.loads(cookies_json)
            print(f"成功加载 {len(cookies_list)} 个本地 Cookies")
        except:
            print("Cookie JSON 解析失败，将尝试裸奔...")

    # 启动配置
    with Camoufox(
        proxy=proxy_config,
        geoip=True,
        # 关键修改：改为 False，配合 YAML 中的 xvfb-run 使用
        # Cloudflare 对 Headless: False 的宽容度高很多
        headless=False, 
        humanize=True,
    ) as browser:
        
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080}, 
            record_video_dir="./videos/"
        )
        
        # --- 注入本地 Cookie ---
        if cookies_list:
            # 确保 cookie domain 匹配
            formatted_cookies = []
            for c in cookies_list:
                # 过滤掉无关字段，确保格式符合 Playwright 要求
                new_cookie = {
                    "name": c.get("name"),
                    "value": c.get("value"),
                    "domain": c.get("domain", ".xserver.ne.jp"),
                    "path": c.get("path", "/")
                }
                formatted_cookies.append(new_cookie)
            try:
                context.add_cookies(formatted_cookies)
                print(">>> 已注入本地 Cookies，尝试绕过验证...")
            except Exception as e:
                print(f"Cookie 注入部分失败: {e}")

        page = context.new_page()
        
        try:
            print(">>> 开始访问页面...")
            page.goto('https://secure.xserver.ne.jp/xapanel/login/xvps/', wait_until='networkidle')

            # 检查是否直接登录成功（如果 Session Cookie 有效）
            if "login" not in page.url and "xvps" in page.url:
                print(">>> 利用 Cookie 直接登录成功！跳过登录步骤。")
            else:
                # 正常登录流程
                if page.locator('#memberid').is_visible():
                    page.locator('#memberid').fill(os.getenv('EMAIL'))
                    page.locator('#user_password').fill(os.getenv('PASSWORD'))
                    page.get_by_text('ログインする').click()
                    page.wait_for_load_state('networkidle')

            # --- 导航逻辑 ---
            print(">>> 导航至 VPS 详情...")
            # 增加容错：如果找不到详情链接，打印页面源码摘要
            try:
                page.locator('a[href^="/xapanel/xvps/server/detail?id="]').first.click(timeout=10000)
            except:
                print("未找到详情链接，当前 URL:", page.url)
                page.screenshot(path="nav_fail.png")
                raise Exception("导航失败")

            print(">>> 点击更新...")
            page.get_by_text('更新する').first.click()
            
            print(">>> 点击继续利用...")
            page.get_by_text('引き続き無料VPSの利用を継続する').click()
            page.wait_for_load_state('networkidle')

            # --- OCR 验证码 ---
            print(">>> 处理验证码...")
            img_element = page.locator('img[src^="data:"]')
            img_src = img_element.get_attribute('src')
            response = requests.post('https://captcha-120546510085.asia-northeast1.run.app', data=img_src, timeout=30)
            code = response.text.strip()
            page.locator('[placeholder="上の画像の数字を入力"]').fill(code)
            
            # --- Turnstile 处理 (带 Xvfb 后成功率应该极高) ---
            print(">>> 检测 Turnstile...")
            time.sleep(3)
            
            # 在 Headless=False 模式下，Turnstile 往往会自动通过
            # 如果没过，再尝试点击
            
            # 检测是否已经包含成功的 token
            has_token = page.evaluate("() => !!document.querySelector('[name=\"cf-turnstile-response\"]')?.value")
            
            if not has_token:
                print("Token 未生成，尝试寻找并点击 iframe...")
                for frame in page.frames:
                    if "cloudflare.com" in frame.url or "turnstile" in frame.url:
                         # 寻找 body 并点击中心
                        box = frame.locator('body').bounding_box()
                        if box:
                            x = box['x'] + box['width'] / 2
                            y = box['y'] + box['height'] / 2
                            print(f"点击 Iframe 中心: {x}, {y}")
                            page.mouse.click(x, y)
                            time.sleep(2)
            
            # --- 最终提交 ---
            print(">>> 提交...")
            page.screenshot(path="before_submit.png")
            
            # 尝试多种选择器
            submit_btn = page.locator('input[type="submit"][value*="継続"], input[type="submit"][value*="利用"], button:has-text("継続")')
            if not submit_btn.is_visible():
                 submit_btn = page.get_by_text('無料VPSの利用を継続する')
            
            submit_btn.click()
            
            # 等待成功跳转
            time.sleep(5)
            print(">>> 流程结束")

        except Exception as e:
            print(f"执行异常: {e}")
            page.screenshot(path="error_debug.png")
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
