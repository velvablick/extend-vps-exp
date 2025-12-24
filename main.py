import os
import time
import shutil
import json
import requests
from urllib.parse import urlparse
from camoufox.sync_api import Camoufox
# 修正：从 playwright.sync_api 导入 TimeoutError
from playwright.sync_api import TimeoutError

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
        headless=False, # 配合 xvfb 使用
        humanize=True,
    ) as browser:
        
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080}, 
            record_video_dir="./videos/",
            ignore_https_errors=True 
        )
        
        context.set_extra_http_headers({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0"
        })

        page = context.new_page()
        
        try:
            print(">>> 开始访问页面...")
            page.goto('https://secure.xserver.ne.jp/xapanel/login/xvps/', wait_until='networkidle')

            # --- 登录 ---
            print(">>> 检查登录状态...")
            try:
                # 强制等待输入框出现
                page.wait_for_selector('#memberid, input[name="memberid"]', state='visible', timeout=15000)
                print(">>> 填充登录信息...")
                page.locator('#memberid, input[name="memberid"]').fill(os.getenv('EMAIL'))
                page.locator('#user_password, input[name="user_password"]').fill(os.getenv('PASSWORD'))
                page.get_by_text('ログインする').click()
                page.wait_for_load_state('networkidle')
            except:
                print(">>> 未检测到登录框，假设已登录或页面结构变更...")

            # --- 导航 ---
            print(">>> 导航至 VPS 详情...")
            try:
                detail_link = page.locator('a[href^="/xapanel/xvps/server/detail?id="]').first
                detail_link.wait_for(state='visible', timeout=20000)
                detail_link.click()
            except:
                print("当前 URL:", page.url)
                raise Exception("未找到 VPS 详情链接")

            print(">>> 点击更新...")
            page.get_by_text('更新する').first.click()
            
            print(">>> 点击继续利用...")
            page.get_by_text('引き続き無料VPSの利用を継続する').click()
            page.wait_for_load_state('networkidle')

            # --- 验证循环 ---
            max_retries = 5
            for attempt in range(max_retries):
                print(f"\n>>> 第 {attempt + 1} 次验证尝试...")
                
                # 1. OCR
                img_element = page.locator('img[src^="data:"]').first
                img_element.wait_for(state='visible')
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
                
                # 3. 提交 (核心修复逻辑)
                print(">>> 提交中...")
                submit_btn = page.locator('input[type="submit"][value*="継続"], input[type="submit"][value*="利用"], button:has-text("継続")')
                if not submit_btn.is_visible():
                     submit_btn = page.get_by_text('無料VPSの利用を継続する')
                
                try:
                    # force=True 无视遮罩层, timeout=60000 延长等待
                    print(">>> 执行强制点击...")
                    submit_btn.click(force=True, timeout=60000)
                except TimeoutError:
                    print(">>> 点击超时(TimeoutError)，可能因页面转圈导致，继续检查结果...")
                except Exception as e:
                    print(f"点击时发生其他错误: {e}")

                # 4. 等待结果
                print(">>> 等待服务器响应 (最多 60 秒)...")
                try:
                    # 轮询检查结果
                    for i in range(60):
                        if "complete" in page.url or "finish" in page.url:
                            print(">>> 检测到 URL 变更，任务成功！")
                            return 
                        
                        if page.locator('text=完了').is_visible():
                            print(">>> 检测到完成文字，任务成功！")
                            return

                        if page.locator('text=認証に失敗しました').is_visible() or page.locator('.error-message').is_visible():
                            print(">>> 错误：认证失败。")
                            raise Exception("AuthFailed") 
                        
                        time.sleep(1)
                    
                    print(">>> 60秒后仍在处理，可能已经成功或卡死，截屏保存。")
                    page.screenshot(path="timeout_check.png")
                    
                except Exception as e:
                    if str(e) == "AuthFailed":
                        print(">>> 捕获到认证失败，刷新页面重试...")
                        page.reload()
                        page.wait_for_load_state('networkidle')
                        continue 
                    else:
                        print(f"等待结果时出错: {e}")
            
            raise Exception("所有重试均未成功。")

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
