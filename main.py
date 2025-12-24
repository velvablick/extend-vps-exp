import os
import time
import shutil
import json
import requests
from urllib.parse import urlparse
from camoufox.sync_api import Camoufox
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

    # 启动配置
    with Camoufox(
        proxy=proxy_config,
        geoip=True,
        headless=False, 
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
        page.on("dialog", lambda dialog: dialog.accept())
        
        try:
            print(">>> 开始访问页面...")
            page.goto('https://secure.xserver.ne.jp/xapanel/login/xvps/', wait_until='networkidle')

            # --- 登录 ---
            print(">>> 检查登录状态...")
            try:
                page.wait_for_selector('#memberid, input[name="memberid"]', state='visible', timeout=15000)
                print(">>> 填充登录信息...")
                page.locator('#memberid, input[name="memberid"]').fill(os.getenv('EMAIL'))
                page.locator('#user_password, input[name="user_password"]').fill(os.getenv('PASSWORD'))
                page.get_by_text('ログインする').click()
                page.wait_for_load_state('networkidle')
            except:
                print(">>> 未检测到登录框，假设已登录...")

            # --- 导航并保存详情页 URL ---
            detail_url = ""
            print(">>> 导航至 VPS 详情...")
            try:
                detail_link = page.locator('a[href^="/xapanel/xvps/server/detail?id="]').first
                detail_link.wait_for(state='visible', timeout=20000)
                href = detail_link.get_attribute("href")
                if href:
                    detail_url = "https://secure.xserver.ne.jp" + href
                detail_link.click()
            except:
                raise Exception("未找到 VPS 详情链接")

            print(">>> 点击更新...")
            page.get_by_text('更新する').first.click()
            print(">>> 点击继续利用...")
            page.get_by_text('引き続き無料VPSの利用を継続する').click()
            page.wait_for_load_state('networkidle')

            # --- 新增检测：是否无需续期 ---
            # 有时候还没进入验证码页面，就会提示还没到时间
            if page.get_by_text("利用期限の1日前から更新手続きが可能です").is_visible():
                print(">>> 任务完成：当前无需续期 (利用期限の1日前から更新手続きが可能です)。")
                return

            # --- 验证循环 ---
            max_retries = 10
            for attempt in range(max_retries):
                print(f"\n>>> 第 {attempt + 1} 次验证尝试...")
                
                # 0. 检查是否需要重置页面
                if not page.locator('[placeholder="上の画像の数字を入力"]').is_visible():
                    print(">>> 页面状态重置: 回到详情页重新发起请求...")
                    if detail_url:
                        page.goto(detail_url, wait_until='networkidle')
                    else:
                        page.goto('https://secure.xserver.ne.jp/xapanel/xvps/', wait_until='networkidle')
                        page.locator('a[href^="/xapanel/xvps/server/detail?id="]').first.click()
                    
                    page.get_by_text('更新する').first.click()
                    page.get_by_text('引き続き無料VPSの利用を継続する').click()
                    page.wait_for_load_state('networkidle')

                    # 重置页面后，再次检测是否无需续期
                    if page.get_by_text("利用期限の1日前から更新手続きが可能です").is_visible():
                        print(">>> 任务完成：当前无需续期 (利用期限の1日前から更新手続きが可能です)。")
                        return

                # 1. OCR 识别
                img_element = page.locator('img[src^="data:"]').first
                try:
                    img_element.wait_for(state='visible', timeout=10000)
                    time.sleep(1)
                    img_src = img_element.get_attribute('src')
                    
                    response = requests.post('https://captcha-120546510085.asia-northeast1.run.app', data=img_src, timeout=30)
                    code = response.text.strip()
                    print(f"验证码识别: {code}")
                    
                    input_box = page.locator('[placeholder="上の画像の数字を入力"]')
                    input_box.fill("")
                    input_box.fill(code)
                except Exception as e:
                    print(f"OCR 失败: {e}")
                    continue

                # 2. Turnstile 处理
                print(">>> 检测 Turnstile Token...")
                token = page.evaluate("() => document.querySelector('[name=\"cf-turnstile-response\"]')?.value")
                
                if not token:
                    print("Token 为空，尝试寻找 iframe 并点击...")
                    for frame in page.frames:
                        if "cloudflare.com" in frame.url or "turnstile" in frame.url:
                            box = frame.locator('body').bounding_box()
                            if box:
                                x = box['x'] + box['width'] / 2
                                y = box['y'] + box['height'] / 2
                                page.mouse.click(x, y)
                                break
                    
                    # 即使这里提示警告，流程也会继续往下走，交给结果分析来判断是否成功
                    print(">>> 等待 Token 生成 (最多10秒)...")
                    for _ in range(10):
                        time.sleep(1)
                        token = page.evaluate("() => document.querySelector('[name=\"cf-turnstile-response\"]')?.value")
                        if token:
                            print(">>> Token 获取成功！")
                            break
                    else:
                        print(">>> 警告: 未检测到 Token，尝试强行提交...")

                # 3. 提交
                print(">>> 提交中...")
                submit_btn = page.locator('input[type="submit"][value*="継続"], input[type="submit"][value*="利用"], button:has-text("継続")')
                if not submit_btn.is_visible():
                     submit_btn = page.get_by_text('無料VPSの利用を継続する')
                
                try:
                    submit_btn.click(force=True, timeout=60000)
                except Exception as e:
                    print(f"点击异常(可忽略): {e}")

                # 4. 结果分析 (关键修改)
                print(">>> 等待结果...")
                try:
                    for i in range(60):
                        # --- 成功判定逻辑修正 ---
                        
                        # A. 检查明确的成功文字 (修复 strict mode 错误)
                        # 使用 get_by_text 并指定确切内容，避免匹配到页脚的无关信息
                        if page.get_by_text("利用期限の更新手続きが完了しました。").is_visible():
                            print(">>> 任务成功！(检测到续期完成提示)")
                            return
                        
                        # B. 检查无需续期文字
                        if page.get_by_text("利用期限の1日前から更新手続きが可能です").is_visible():
                            print(">>> 任务完成：当前无需续期。")
                            return

                        # C. 检查 URL 变更 (作为兜底)
                        if "complete" in page.url or "finish" in page.url:
                            print(">>> 任务成功！(URL变更)")
                            return 

                        # --- 错误判定逻辑 ---

                        # 错误 A: 数字填错了
                        if page.locator('text=入力された認証コードが正しくありません').is_visible():
                            print(">>> 检测到【验证码数字错误】。")
                            raise Exception("WrongCode")

                        # 错误 B: 认证失败/Token无效
                        if page.locator('text=認証に失敗しました').is_visible():
                            print(">>> 检测到【认证失败/Token拒绝】。")
                            raise Exception("AuthFailed") 
                        
                        # 错误 C: 页面过期
                        if page.locator('text=期限切れ').is_visible():
                             raise Exception("PageExpired")

                        time.sleep(1)
                    
                    raise Exception("Timeout")
                    
                except Exception as e:
                    if str(e) == "WrongCode":
                        print(">>> 正在重试验证码...")
                        input_box = page.locator('[placeholder="上の画像の数字を入力"]')
                        input_box.fill("")
                        continue

                    if str(e) in ["AuthFailed", "PageExpired"]:
                        print(">>> 正在执行页面回退...")
                        page.goto(detail_url if detail_url else 'https://secure.xserver.ne.jp', wait_until='networkidle')
                        continue
                        
                    print(f"未知错误或重试: {e}")
                    # 如果不是明确的成功，为了保险起见，回退重试
                    page.goto(detail_url if detail_url else 'https://secure.xserver.ne.jp', wait_until='networkidle')
                    continue
            
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
