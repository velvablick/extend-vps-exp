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

    # 启动配置
    with Camoufox(
        proxy=proxy_config,
        geoip=True,
        headless=False, # 配合 xvfb 使用
        humanize=True,
    ) as browser:
        
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080}, 
            record_video_dir="./videos/",
            # 忽略 HTTPS 证书错误（防止部分代理导致的加载问题）
            ignore_https_errors=True 
        )
        
        # 伪装 UA 为 Firefox Windows 版
        context.set_extra_http_headers({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0"
        })

        page = context.new_page()
        
        try:
            print(">>> 开始访问页面...")
            page.goto('https://secure.xserver.ne.jp/xapanel/login/xvps/', wait_until='networkidle')

            # --- 登录流程 (关键修复) ---
            print(">>> 正在等待登录框加载...")
            try:
                # 强制等待输入框出现 (最多等 15 秒)
                # 同时支持 id 和 name 属性，防止网页改版
                page.wait_for_selector('#memberid, input[name="memberid"]', state='visible', timeout=15000)
                
                print(">>> 登录框已就绪，开始填充...")
                # 使用更稳健的选择器
                page.locator('#memberid, input[name="memberid"]').fill(os.getenv('EMAIL'))
                page.locator('#user_password, input[name="user_password"]').fill(os.getenv('PASSWORD'))
                
                # 截图记录登录前的状态（调试用）
                page.screenshot(path="before_login_click.png")
                
                # 点击登录
                page.get_by_text('ログインする').click()
                page.wait_for_load_state('networkidle')
                
            except Exception as e:
                # 如果超时还没找到登录框，说明可能已经在后台了，或者页面结构变了
                print(f"未检测到登录框: {e}")
                # 检查当前 URL 是否还在登录页
                if "login" in page.url:
                    page.screenshot(path="login_page_error.png")
                    raise Exception("脚本卡在登录页，且无法找到账号输入框，请检查录像或选择器。")

            # --- 导航逻辑 ---
            print(">>> 导航至 VPS 详情...")
            try:
                # 等待详情链接出现
                detail_link = page.locator('a[href^="/xapanel/xvps/server/detail?id="]').first
                detail_link.wait_for(state='visible', timeout=15000)
                detail_link.click()
            except:
                print("!!! 未找到详情链接 !!!")
                print("当前 URL:", page.url)
                # 如果还在登录后的首页，可能需要二次确认或其他弹窗
                if "login" in page.url:
                     raise Exception("登录失败，依然停留在登录页")
                else:
                     raise Exception("登录似乎成功，但未找到 VPS 详情链接，可能页面布局变更。")

            print(">>> 点击更新...")
            page.get_by_text('更新する').first.click()
            
            print(">>> 点击继续利用...")
            page.get_by_text('引き続き無料VPSの利用を継続する').click()
            page.wait_for_load_state('networkidle')

            # --- 验证重试循环 ---
            max_retries = 5
            for attempt in range(max_retries):
                print(f"\n>>> 开始第 {attempt + 1} 次验证尝试...")
                
                # 1. OCR
                print(">>> 识别验证码...")
                img_element = page.locator('img[src^="data:"]').first
                img_element.wait_for(state='visible') # 确保图片已加载
                img_src = img_element.get_attribute('src')
                
                response = requests.post('https://captcha-120546510085.asia-northeast1.run.app', data=img_src, timeout=30)
                code = response.text.strip()
                print(f"验证码: {code}")
                
                page.locator('[placeholder="上の画像の数字を入力"]').fill(code)
                
                # 2. Turnstile
                print(">>> 检测 Turnstile...")
                time.sleep(3)
                
                has_token = page.evaluate("() => !!document.querySelector('[name=\"cf-turnstile-response\"]')?.value")
                
                if not has_token:
                    print("尝试点击 Turnstile...")
                    for frame in page.frames:
                        if "cloudflare.com" in frame.url or "turnstile" in frame.url:
                            box = frame.locator('body').bounding_box()
                            if box:
                                x = box['x'] + box['width'] / 2
                                y = box['y'] + box['height'] / 2
                                page.mouse.click(x, y)
                                time.sleep(3)
                                break
                
                # 3. 提交
                print(">>> 提交...")
                submit_btn = page.locator('input[type="submit"][value*="継続"], input[type="submit"][value*="利用"], button:has-text("継続")')
                if not submit_btn.is_visible():
                     submit_btn = page.get_by_text('無料VPSの利用を継続する')
                
                submit_btn.click()
                page.wait_for_load_state('networkidle')
                time.sleep(3)

                # 4. 检查结果
                if page.locator('text=認証に失敗しました').is_visible() or page.locator('.error-message').is_visible():
                    print(">>> 认证失败，刷新重试...")
                    page.reload()
                    page.wait_for_load_state('networkidle')
                    continue
                
                if "complete" in page.url or "finish" in page.url:
                    print(">>> 任务成功！")
                    break
                
                # 兜底检测：如果既没报错也没跳转，可能是URL没变但内容变了
                if page.locator('text=完了').is_visible():
                    print(">>> 检测到完成文字，任务成功！")
                    break
            else:
                raise Exception("重试多次后失败")

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
