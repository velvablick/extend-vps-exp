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

    # 启动配置：使用 xvfb (headless=False)
    with Camoufox(
        proxy=proxy_config,
        geoip=True,
        headless=False, # 配合 YAML 中的 xvfb-run 使用
        humanize=True,
    ) as browser:
        
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080}, 
            record_video_dir="./videos/"
        )
        
        # --- 关键修正：使用 Firefox 的 UA，避免指纹冲突 ---
        # Camoufox 本身就是 Firefox，这里显式声明一个较新的 Windows Firefox 版本即可
        context.set_extra_http_headers({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0"
        })

        page = context.new_page()
        
        try:
            print(">>> 开始访问页面...")
            page.goto('https://secure.xserver.ne.jp/xapanel/login/xvps/', wait_until='networkidle')

            # --- 登录流程 ---
            if page.locator('#memberid').is_visible():
                page.locator('#memberid').fill(os.getenv('EMAIL'))
                page.locator('#user_password').fill(os.getenv('PASSWORD'))
                page.get_by_text('ログインする').click()
                page.wait_for_load_state('networkidle')

            # --- 导航逻辑 ---
            print(">>> 导航至 VPS 详情...")
            try:
                page.locator('a[href^="/xapanel/xvps/server/detail?id="]').first.click(timeout=10000)
            except:
                print("未找到详情链接，尝试直接访问或检查登录状态")
                raise Exception("导航失败，可能登录未成功")

            print(">>> 点击更新...")
            page.get_by_text('更新する').first.click()
            print(">>> 点击继续利用...")
            page.get_by_text('引き続き無料VPSの利用を継続する').click()
            page.wait_for_load_state('networkidle')

            # --- 核心改进：验证重试循环 ---
            # 如果认证失败，最多重试 5 次
            max_retries = 5
            for attempt in range(max_retries):
                print(f"\n>>> 开始第 {attempt + 1} 次验证尝试...")
                
                # 1. 处理 OCR 验证码
                print(">>> 识别图形验证码...")
                # 确保找到最新的图片（如果页面刷新了）
                img_element = page.locator('img[src^="data:"]').first
                img_src = img_element.get_attribute('src')
                
                response = requests.post('https://captcha-120546510085.asia-northeast1.run.app', data=img_src, timeout=30)
                code = response.text.strip()
                print(f"验证码识别结果: {code}")
                
                input_box = page.locator('[placeholder="上の画像の数字を入力"]')
                input_box.fill("") # 清空旧内容
                input_box.fill(code)
                
                # 2. 处理 Turnstile (Iframe 中心点击法)
                print(">>> 检测 Turnstile...")
                time.sleep(3)
                
                # 检查 Token 是否已存在 (上次点击可能还有效)
                has_token = page.evaluate("() => !!document.querySelector('[name=\"cf-turnstile-response\"]')?.value")
                
                if not has_token:
                    print("Token 未生成，尝试寻找 iframe 并点击...")
                    turnstile_clicked = False
                    for frame in page.frames:
                        if "cloudflare.com" in frame.url or "turnstile" in frame.url:
                            # 获取 iframe 尺寸并点击中心
                            box = frame.locator('body').bounding_box()
                            if box:
                                x = box['x'] + box['width'] / 2
                                y = box['y'] + box['height'] / 2
                                print(f"点击 Iframe 中心: ({x}, {y})")
                                page.mouse.click(x, y)
                                turnstile_clicked = True
                                time.sleep(3) # 等待验证通过
                                break
                    
                    if not turnstile_clicked:
                        print("未找到 Turnstile iframe，可能已自动通过。")
                else:
                    print("Turnstile Token 已存在，跳过点击。")

                # 3. 提交
                print(">>> 尝试提交...")
                # 寻找提交按钮
                submit_btn = page.locator('input[type="submit"][value*="継続"], input[type="submit"][value*="利用"], button:has-text("継続")')
                if not submit_btn.is_visible():
                     submit_btn = page.get_by_text('無料VPSの利用を継続する')
                
                submit_btn.click()
                page.wait_for_load_state('networkidle')
                time.sleep(3) # 等待错误消息出现

                # 4. 检查结果
                # 检测是否出现“認証に失敗しました”错误
                if page.locator('text=認証に失敗しました').is_visible() or page.locator('.error-message').is_visible():
                    print("!!! 检测到【认证失败】错误 (OCR错误或Turnstile拒绝) !!!")
                    print(">>> 正在刷新页面重试...")
                    page.reload()
                    page.wait_for_load_state('networkidle')
                    time.sleep(2)
                    continue # 进入下一次循环
                
                # 检测是否成功跳转 (URL 变更或没有错误)
                if "complete" in page.url or "finish" in page.url:
                    print(">>> 页面 URL 包含完成标识，任务成功！")
                    break
                
                # 如果没有错误提示，也没有跳转，可能是卡住了，再次尝试
                print(">>> 未检测到错误，也未跳转，检查页面状态...")
                # 有时候成功了但 URL 没变太快，再等一下
                time.sleep(5)
                if page.locator('text=認証に失敗しました').is_visible():
                     print("延迟后检测到认证失败，重试...")
                     page.reload()
                     continue
                
                # 假设成功
                print(">>> 未发现错误，任务视为完成。")
                break
            
            else:
                raise Exception(f"重试 {max_retries} 次后依然失败，请检查 OCR 服务或代理质量。")

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
