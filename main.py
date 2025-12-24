import os
import time
import shutil
import requests
from urllib.parse import urlparse
from camoufox.sync_api import Camoufox

# 辅助函数：在视频中高亮显示操作元素（调试神器）
def highlight_element(page, element, color="red"):
    try:
        page.evaluate(f"""(element) => {{
            element.style.border = "5px solid {color}";
            element.style.backgroundColor = "rgba(255, 0, 0, 0.3)";
        }}""", element)
        time.sleep(0.5) # 暂停一下让人眼能在视频里看到
    except:
        pass

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

    # 启动配置：启用 GeoIP 和 Humanize
    with Camoufox(
        proxy=proxy_config,
        geoip=True,
        headless=True,
        humanize=True,
    ) as browser:
        
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080}, 
            record_video_dir="./videos/"
        )
        page = context.new_page()
        
        # 伪装成和普通桌面浏览器完全一致
        page.set_extra_http_headers({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        
        try:
            print(">>> 开始访问登录页面...")
            page.goto('https://secure.xserver.ne.jp/xapanel/login/xvps/', wait_until='networkidle')

            # --- 登录 ---
            page.locator('#memberid').fill(os.getenv('EMAIL'))
            page.locator('#user_password').fill(os.getenv('PASSWORD'))
            
            login_btn = page.get_by_text('ログインする')
            highlight_element(page, login_btn) # 调试：高亮登录按钮
            login_btn.click()
            page.wait_for_load_state('networkidle')

            # --- 导航 ---
            print(">>> 导航至详情页...")
            # 这里的 .first 可能会点错，建议用更精确的选择器，这里暂时保留
            link = page.locator('a[href^="/xapanel/xvps/server/detail?id="]').first
            link.wait_for(state="visible")
            link.click()
            
            print(">>> 点击更新按钮...")
            update_btn = page.locator('input[value="更新する"], button:has-text("更新する")')
            # 如果没找到，尝试纯文本
            if not update_btn.is_visible():
                update_btn = page.get_by_text('更新する')
            
            update_btn.first.click()
            
            print(">>> 点击继续利用...")
            continue_btn = page.get_by_text('引き続き無料VPSの利用を継続する')
            continue_btn.click()
            page.wait_for_load_state('networkidle')

            # --- OCR 验证码 ---
            print(">>> 处理图形验证码...")
            img_element = page.locator('img[src^="data:"]')
            img_src = img_element.get_attribute('src')
            response = requests.post('https://captcha-120546510085.asia-northeast1.run.app', data=img_src, timeout=30)
            code = response.text.strip()
            print(f"验证码: {code}")
            page.locator('[placeholder="上の画像の数字を入力"]').fill(code)
            
            # --- 核心改进：Turnstile 暴力交互 ---
            print(">>> 检测 Turnstile (Iframe 中心点击法)...")
            time.sleep(3) # 等待加载

            turnstile_found = False
            
            # 策略：直接寻找包含 Cloudflare 的 iframe 并点击其正中心
            for frame in page.frames:
                if "cloudflare.com" in frame.url or "turnstile" in frame.url:
                    print(f"锁定 iframe: {frame.url}")
                    
                    # 1. 尝试高亮整个 iframe 区域（在主页面视角）
                    try:
                        frame_element = page.frame_locator(f'iframe[src="{frame.url}"]')
                        # 注意：Playwright 很难直接给 frame 元素加边框，这里略过视觉调试，直接操作
                    except:
                        pass

                    # 2. 获取 iframe 的尺寸
                    box = frame.locator('body').bounding_box()
                    if box:
                        print(f"Iframe 尺寸: {box}")
                        # 3. 计算中心点
                        x = box['x'] + box['width'] / 2
                        y = box['y'] + box['height'] / 2
                        
                        # 4. 移动鼠标并点击 (物理点击)
                        print(f"尝试点击坐标: ({x}, {y})")
                        page.mouse.move(x, y)
                        time.sleep(0.5)
                        page.mouse.down()
                        time.sleep(0.2)
                        page.mouse.up()
                        turnstile_found = True
                        break
            
            if not turnstile_found:
                print("未发现 Turnstile iframe，可能已自动通过或未加载。")

            # 等待验证通过（观察 Token）
            print(">>> 等待验证生效...")
            is_verified = False
            for _ in range(10):
                # 检查隐藏域是否有值
                token = page.evaluate("() => document.querySelector('[name=\"cf-turnstile-response\"]')?.value")
                if token:
                    print("成功获取 Turnstile Token！验证通过。")
                    is_verified = True
                    break
                time.sleep(1)
            
            if not is_verified:
                print("警告：未检测到 Token，提交可能会失败。")

            # --- 最终提交与结果校验 ---
            print(">>> 执行最终提交...")
            page.screenshot(path="before_submit.png")
            
            # 这是一个关键点：提交按钮可能有多个，或者需要特定的 class
            final_submit = page.locator('input[type="submit"][value*="継続"], input[type="submit"][value*="利用"]')
            if not final_submit.is_visible():
                 final_submit = page.get_by_text('無料VPSの利用を継続する')

            highlight_element(page, final_submit)
            
            # 保存当前 URL 用于对比
            current_url = page.url
            
            final_submit.click()
            
            # 等待页面跳转或成功消息
            try:
                # 假设成功后 URL 会变，或者出现“完了”字样
                page.wait_for_url(lambda u: u != current_url, timeout=10000)
                print("页面 URL 已变更，推测提交成功。")
            except:
                print("页面 URL 未变更，检查是否有错误消息...")
                if page.locator('text=エラー').is_visible() or page.locator('.error').is_visible():
                    print("检测到错误消息！任务失败。")
                    raise Exception("页面提示提交错误")

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
