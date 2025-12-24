import os
import time
import shutil
import json
import requests
from urllib.parse import urlparse
from camoufox.sync_api import Camoufox
from playwright.sync_api import TimeoutError

# --- 新增：Telegram 通知函数 ---
def send_notification(message):
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    
    if not token or not chat_id:
        print(">>> 缺少 Telegram 配置，跳过通知发送。")
        return

    print(f">>> 正在发送 Telegram 通知: {message}")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": f"🤖 [Xserver VPS 自动化]\n\n{message}",
        "parse_mode": "Markdown"
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            print(">>> 通知发送成功！")
        else:
            print(f">>> 通知发送失败: {resp.text}")
    except Exception as e:
        print(f">>> 发送通知时发生网络错误: {e}")

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

            # --- 导航 ---
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

            # --- 检测点 1：是否无需续期 ---
            if page.get_by_text("利用期限の1日前から更新手続きが可能です").is_visible():
                msg = "✅ **检测完毕**\n当前无需续期 (未到期限)。"
                print(f">>> {msg}")
                send_notification(msg) # 发送通知
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

                    # 重置后再次检测无需续期
                    if page.get_by_text("利用期限の1日前から更新手続きが可能です").is_visible():
                        msg = "✅ **检测完毕**\n当前无需续期 (未到期限)。"
                        print(f">>> {msg}")
                        send_notification(msg) # 发送通知
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
                    
                    for _ in range(10):
                        time.sleep(1)
                        token = page.evaluate("() => document.querySelector('[name=\"cf-turnstile-response\"]')?.value")
                        if token:
                            print(">>> Token 获取成功！")
                            break
                    else:
                        print(">>> 警告: 未检测到 Token...")

                # 3. 提交
                print(">>> 提交中...")
                submit_btn = page.locator('input[type="submit"][value*="継続"], input[type="submit"][value*="利用"], button:has-text("継続")')
                if not submit_btn.is_visible():
                     submit_btn = page.get_by_text('無料VPSの利用を継続する')
                
                try:
                    submit_btn.click(force=True, timeout=60000)
                except Exception as e:
                    print(f"点击异常(可忽略): {e}")

                # 4. 结果分析
                print(">>> 等待结果...")
                try:
                    for i in range(60):
                        # --- 检测点 2：明确的续期成功 ---
                        if page.get_by_text("利用期限の更新手続きが完了しました。").is_visible():
                            msg = "🎉 **续期成功！**\nVPS 使用期限已延长。"
                            print(f">>> {msg}")
                            send_notification(msg) # 发送通知
                            return
                        
                        # --- 检测点 3：无需续期 (可能在点击后才跳出来) ---
                        if page.get_by_text("利用期限の1日前から更新手続きが可能です").is_visible():
                            msg = "✅ **检测完毕**\n当前无需续期 (未到期限)。"
                            print(f">>> {msg}")
                            send_notification(msg) # 发送通知
                            return

                        # 兜底 URL 检查
                        if "complete" in page.url or "finish" in page.url:
                            msg = "🎉 **续期成功！**\n(检测到 URL 变更)"
                            print(f">>> {msg}")
                            send_notification(msg)
                            return 

                        # 错误处理
                        if page.locator('text=入力された認証コードが正しくありません').is_visible():
                            print(">>> 【验证码数字错误】。")
                            raise Exception("WrongCode")

                        if page.locator('text=認証に失敗しました').is_visible():
                            print(">>> 【认证失败/Token拒绝】。")
                            raise Exception("AuthFailed") 
                        
                        if page.locator('text=期限切れ').is_visible():
                             raise Exception("PageExpired")

                        time.sleep(1)
                    
                    raise Exception("Timeout")
                    
                except Exception as e:
                    if str(e) == "WrongCode":
                        print(">>> 重试验证码...")
                        input_box = page.locator('[placeholder="上の画像の数字を入力"]')
                        input_box.fill("")
                        continue

                    if str(e) in ["AuthFailed", "PageExpired"]:
                        print(">>> 执行页面回退...")
                        page.goto(detail_url if detail_url else 'https://secure.xserver.ne.jp', wait_until='networkidle')
                        continue
                        
                    print(f"重试: {e}")
                    page.goto(detail_url if detail_url else 'https://secure.xserver.ne.jp', wait_until='networkidle')
                    continue
            
            raise Exception("所有重试均未成功。")

        except Exception as e:
            # --- 检测点 4：最终失败通知 ---
            error_msg = f"❌ **任务失败**\n请检查 GitHub Actions 日志。\n原因: {str(e)}"
            print(error_msg)
            send_notification(error_msg) # 发送错误通知
            
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
