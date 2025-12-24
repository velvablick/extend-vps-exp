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

    with Camoufox(
        proxy=proxy_config,
        geoip=True,
        headless=False, # 必须保持 False 以配合 xvfb
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

        # --- 关键修复 1：全局自动处理弹窗 ---
        # 当浏览器弹出 "是否重新提交表单" 或 alert 时，自动点击 "确定"
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
                print(">>> 未检测到登录框，假设已登录或页面结构变更...")

            # --- 导航 ---
            print(">>> 导航至 VPS 详情...")
            try:
                # 增加重试机制，防止网络波动找不到链接
                detail_link = page.locator('a[href^="/xapanel/xvps/server/detail?id="]').first
                detail_link.wait_for(state='visible', timeout=20000)
                detail_link.click()
            except:
                print(f"当前 URL: {page.url}")
                raise Exception("未找到 VPS 详情链接")

            print(">>> 点击更新...")
            page.get_by_text('更新する').first.click()
            
            print(">>> 点击继续利用...")
            page.get_by_text('引き続き無料VPSの利用を継続する').click()
            page.wait_for_load_state('networkidle')

            # --- 验证循环 ---
            max_retries = 10 # 增加重试次数，应对 OCR 准确率问题
            for attempt in range(max_retries):
                print(f"\n>>> 第 {attempt + 1} 次验证尝试...")
                
                # 1. OCR (增加图片等待)
                img_element = page.locator('img[src^="data:"]').first
                try:
                    img_element.wait_for(state='visible', timeout=10000)
                    # 稍微等待图片完全渲染
                    time.sleep(1) 
                    img_src = img_element.get_attribute('src')
                    
                    response = requests.post('https://captcha-120546510085.asia-northeast1.run.app', data=img_src, timeout=30)
                    code = response.text.strip()
                    print(f"验证码识别结果: {code}")
                    
                    input_box = page.locator('[placeholder="上の画像の数字を入力"]')
                    input_box.fill("") # 先清空
                    input_box.fill(code)
                except Exception as e:
                    print(f"验证码处理出错: {e}")
                    page.reload() # 如果图片都没加载出来，直接刷新
                    continue

                # 2. Turnstile
                print(">>> 检测 Turnstile...")
                time.sleep(2)
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
                print(">>> 提交中...")
                submit_btn = page.locator('input[type="submit"][value*="継続"], input[type="submit"][value*="利用"], button:has-text("継続")')
                if not submit_btn.is_visible():
                     submit_btn = page.get_by_text('無料VPSの利用を継続する')
                
                try:
                    print(">>> 执行强制点击...")
                    submit_btn.click(force=True, timeout=60000)
                except TimeoutError:
                    print(">>> 点击超时(可能是加载遮罩导致)，继续检查结果...")
                except Exception as e:
                    print(f"点击异常: {e}")

                # 4. 等待结果
                print(">>> 等待响应...")
                try:
                    for i in range(60):
                        if "complete" in page.url or "finish" in page.url:
                            print(">>> 任务成功！(URL变更)")
                            return 
                        
                        if page.locator('text=完了').is_visible():
                            print(">>> 任务成功！(发现完成文字)")
                            return

                        # 检测认证失败
                        if page.locator('text=認証に失敗しました').is_visible() or page.locator('.error-message').is_visible():
                            print(">>> 错误：认证失败 (OCR或Token错误)。")
                            raise Exception("AuthFailed") 
                        
                        time.sleep(1)
                    
                    print(">>> 等待超时，可能卡死。")
                    page.screenshot(path="timeout_check.png")
                    raise Exception("AuthFailed") # 超时也视作失败，触发刷新
                    
                except Exception as e:
                    if str(e) == "AuthFailed":
                        print(">>> 正在刷新页面以获取新验证码...")
                        # 关键修复 2：Reload 之前，Dialog 监听器会自动处理弹窗
                        # --- 核心修复：使用 goto() 代替 reload() ---
                        # goto() 发起的是 GET 请求，不会触发 "确认重新提交表单" 的弹窗
                        # 从而避免脚本卡死在阻塞弹窗上
                        page.goto(page.url, wait_until='networkidle')
                        
                        # 刷新后稍作等待，确保新验证码和 Turnstile 初始化
                        time.sleep(3)
                        continue 
                    else:
                        print(f"检查结果时发生未知错误: {e}")
                        # 这里也建议改用 goto
                        page.goto(page.url, wait_until='networkidle')
                        continue
            
            raise Exception("所有重试均未成功，请检查 OCR 服务准确率。")

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
