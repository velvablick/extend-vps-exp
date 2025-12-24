import os
import time
import shutil
import json
import requests
import random # 新增随机库
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

            # --- 验证循环 ---
            max_retries = 10
            for attempt in range(max_retries):
                print(f"\n>>> 第 {attempt + 1} 次验证尝试...")
                
                # 0. 页面状态检查与回退
                if not page.locator('[placeholder="上の画像の数字を入力"]').is_visible():
                    print(">>> 页面状态重置: 回到详情页...")
                    if detail_url:
                        page.goto(detail_url, wait_until='networkidle')
                    else:
                        page.goto('https://secure.xserver.ne.jp/xapanel/xvps/', wait_until='networkidle')
                        page.locator('a[href^="/xapanel/xvps/server/detail?id="]').first.click()
                    
                    page.get_by_text('更新する').first.click()
                    page.get_by_text('引き続き無料VPSの利用を継続する').click()
                    page.wait_for_load_state('networkidle')

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

                # 2. Turnstile 处理 (核心升级)
                print(">>> 检测 Turnstile...")
                
                # 循环检查 + 动态点击
                token = None
                # 最多尝试交互 3 次
                for click_attempt in range(3):
                    # 先检查 Token 是否已存在
                    token = page.evaluate("() => document.querySelector('[name=\"cf-turnstile-response\"]')?.value")
                    if token:
                        print(f">>> Token 已获取 (尝试 {click_attempt})")
                        break
                    
                    print(f"Token 为空，执行第 {click_attempt + 1} 次点击策略...")
                    
                    # 寻找 iframe
                    target_frame = None
                    for frame in page.frames:
                        if "cloudflare.com" in frame.url or "turnstile" in frame.url:
                            target_frame = frame
                            break
                    
                    if target_frame:
                        box = target_frame.locator('body').bounding_box()
                        if box:
                            # 策略 A: 计算中心点，并加入随机偏移
                            x = box['x'] + box['width'] / 2 + random.uniform(-10, 10)
                            y = box['y'] + box['height'] / 2 + random.uniform(-10, 10)
                            
                            # 策略 B: 拟人化移动鼠标 (steps=10 表示分10步滑过去)
                            print(f"模拟鼠标滑动至: ({x:.1f}, {y:.1f})")
                            page.mouse.move(x, y, steps=15)
                            time.sleep(random.uniform(0.3, 0.7)) # 悬停
                            
                            page.mouse.down()
                            time.sleep(random.uniform(0.1, 0.3)) # 模拟按压时长
                            page.mouse.up()
                            
                            # 点击后等待一阵，给 Turnstile 反应时间
                            print("点击完成，等待反应...")
                            for _ in range(5): # 等待 5 秒
                                time.sleep(1)
                                token = page.evaluate("() => document.querySelector('[name=\"cf-turnstile-response\"]')?.value")
                                if token: 
                                    break
                            if token: break
                    else:
                        print("未找到 Turnstile iframe")
                        time.sleep(2)
                
                if not token:
                    print(">>> 严重警告: 多次尝试点击后仍未获取 Token，本次大概率失败。")

                # 3. 提交
                print(">>> 提交中...")
                submit_btn = page.locator('input[type="submit"][value*="継続"], input[type="submit"][value*="利用"], button:has-text("継続")')
                if not submit_btn.is_visible():
                     submit_btn = page.get_by_text('無料VPSの利用を継続する')
                
                try:
                    submit_btn.click(force=True, timeout=60000)
                except:
                    pass

                # 4. 结果分析
                print(">>> 等待结果...")
                try:
                    for i in range(60):
                        if "complete" in page.url or "finish" in page.url or page.locator('text=完了').is_visible():
                            print(">>> 任务成功！")
                            return 

                        if page.locator('text=入力された認証コードが正しくありません').is_visible():
                            print(">>> 【验证码数字错误】，重试 OCR...")
                            raise Exception("WrongCode")

                        if page.locator('text=認証に失敗しました').is_visible():
                            print(">>> 【认证失败/Token拒绝】，重置页面...")
                            raise Exception("AuthFailed") 
                        
                        if page.locator('text=期限切れ').is_visible():
                             raise Exception("PageExpired")

                        time.sleep(1)
                    
                    raise Exception("Timeout")
                    
                except Exception as e:
                    if str(e) == "WrongCode":
                        continue
                    if str(e) in ["AuthFailed", "PageExpired"]:
                        page.goto(detail_url if detail_url else 'https://secure.xserver.ne.jp', wait_until='networkidle')
                        continue
                    
                    print(f"未知错误: {e}")
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
