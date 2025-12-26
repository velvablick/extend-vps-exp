import os
import time
import shutil
import json
import requests
from urllib.parse import urlparse
from camoufox.sync_api import Camoufox
from playwright.sync_api import TimeoutError

# --- Telegram 通知函数 ---
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
        "text": f"🤖 [Xserver xmgame 自动化]\n\n{message}",
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
        
        # 定义变量存储详情页 URL
        dashboard_url = ""

        try:
            # --- 步骤 1: 登录 ---
            print(">>> [Step 1] 访问登录页面...")
            page.goto('https://secure.xserver.ne.jp/xapanel/login/xmgame/', wait_until='networkidle')

            print(">>> 检查登录状态...")
            try:
                page.wait_for_selector('#memberid, input[name="memberid"]', state='visible', timeout=10000)
                print(">>> 填充登录信息...")
                page.locator('#memberid, input[name="memberid"]').fill(os.getenv('EMAIL'))
                page.locator('#user_password, input[name="user_password"]').fill(os.getenv('PASSWORD'))
                page.get_by_text('ログインする').click()
                page.wait_for_load_state('networkidle')
            except:
                print(">>> 未检测到登录框，假设已登录...")

            # --- 步骤 2: サーバー管理 ---
            print(">>> [Step 2] 点击 'サーバー管理'...")
            try:
                server_manage_btn = page.locator('a[href*="/xapanel/xmgame/serverselect"][href*="server_management"]').first
                server_manage_btn.wait_for(state='visible', timeout=20000)
                server_manage_btn.click()
                page.wait_for_load_state('networkidle')
            except Exception as e:
                raise Exception(f"未找到 'サーバー管理' 按钮: {e}")

            # --- 步骤 3: 選択する (跳转 VPS 详情) ---
            print(">>> [Step 3] 点击 '選択する'...")
            try:
                select_btn = page.locator('a[href*="/xapanel/xmgame/jumpvps/"]').filter(has_text="選択する").first
                if not select_btn.is_visible():
                    select_btn = page.locator('a[href*="/xapanel/xmgame/jumpvps/"]').first
                
                select_btn.wait_for(state='visible', timeout=20000)
                select_btn.click()
                page.wait_for_load_state('networkidle')
                
                # 【关键】记录详情页 URL，用于后续跳回验证
                dashboard_url = page.url
                print(f">>> 已记录详情页 URL: {dashboard_url}")
                
            except Exception as e:
                raise Exception(f"未找到 '選択する' 按钮: {e}")

            # --- 步骤 4: 检查时间并决定是否进入下一页 ---
            print(">>> [Step 4] 检查剩余时间...")
            
            # 1. 执行时间检查逻辑
            try:
                limit_div = page.locator('.limitTxt').first
                if limit_div.is_visible():
                    hours_text = limit_div.locator('.numberTxt').first.inner_text().strip()
                    date_text = limit_div.locator('.dateLimit').first.inner_text().strip()
                    
                    print(f">>> 识别结果: 剩余 {hours_text} 小时, 有效期 {date_text}")
                    
                    if hours_text.isdigit() and int(hours_text) > 24:
                        msg = (
                            f"✅ **无需续期**\n"
                            f"XServer xmgame 当前剩余时长大于 24 小时，未到续期时间。\n\n"
                            f"⏳ **剩余时间**: {hours_text} 小时\n"
                            f"📅 **截止日期**: {date_text}"
                        )
                        print(f">>> {msg}")
                        send_notification(msg)
                        return # 正常退出
                    else:
                        print(">>> 剩余时间不足 24 小时，继续执行续期操作...")
                else:
                    print(">>> 未在页面找到时间提示元素 (.limitTxt)，默认尝试执行续期...")
            except Exception as e:
                print(f">>> 时间解析逻辑出现非致命错误 (继续尝试续期): {e}")

            # 2. 点击链接进入下一页
            print(">>> [Step 4] 点击 'アップグレード・期限延長'...")
            try:
                extend_index_btn = page.locator('a[href*="/xmgame/game/freeplan/extend/index"]').first
                extend_index_btn.wait_for(state='visible', timeout=20000)
                extend_index_btn.click()
                page.wait_for_load_state('networkidle')
            except Exception as e:
                raise Exception(f"未找到 'アップグレード・期限延長' 按钮: {e}")

            # --- 步骤 5: 期限を延長する (Input) ---
            print(">>> [Step 5] 点击 '期限を延長する' (Input)...")
            try:
                extend_input_btn = page.locator('a[href*="/xmgame/game/freeplan/extend/input"]').first
                extend_input_btn.wait_for(state='visible', timeout=15000)
                extend_input_btn.click()
                page.wait_for_load_state('networkidle')
            except Exception as e:
                msg = "✅ **检测完毕**\n未找到 '期限を延長する' 按钮，可能未到续期时间。"
                print(f">>> {msg}")
                send_notification(msg)
                return 

            # --- 步骤 6: 確認画面に進む ---
            print(">>> [Step 6] 点击 '確認画面に進む'...")
            try:
                confirm_btn = page.locator('button[formaction*="/xmgame/game/freeplan/extend/conf"]').first
                confirm_btn.wait_for(state='visible', timeout=20000)
                time.sleep(1) 
                confirm_btn.click()
                page.wait_for_load_state('networkidle')
            except Exception as e:
                raise Exception(f"未找到 '確認画面に進む' 按钮: {e}")

            # --- 步骤 7: 期限を延長する (最终提交) ---
            print(">>> [Step 7] 点击 '期限を延長する' (Do)...")
            try:
                final_submit_btn = page.locator('button[formaction*="/xmgame/game/freeplan/extend/do"]').first
                final_submit_btn.wait_for(state='visible', timeout=20000)
                page.screenshot(path="before_submit.png")
                final_submit_btn.click()
                page.wait_for_load_state('networkidle')
            except Exception as e:
                raise Exception(f"未找到最终提交按钮: {e}")

            # --- 步骤 8: 验证结果并获取最新日期 ---
            print(">>> [Step 8] 验证结果...")
            try:
                # 1. 确认续期成功文本
                success_text = page.locator('text=期限を延長しました').first
                success_text.wait_for(state='visible', timeout=20000)
                print(">>> 检测到续期成功文本。")

                # 2. 跳转回详情页获取最新日期
                if dashboard_url:
                    print(f">>> 正在跳转回详情页以获取最新日期: {dashboard_url}")
                    page.goto(dashboard_url, wait_until='networkidle')
                    
                    new_date_text = "（获取失败）"
                    try:
                        # 再次定位 .limitTxt 提取日期
                        limit_div_new = page.locator('.limitTxt').first
                        limit_div_new.wait_for(state='visible', timeout=15000)
                        new_date_text = limit_div_new.locator('.dateLimit').first.inner_text().strip()
                        print(f">>> 获取到最新截止日期: {new_date_text}")
                    except Exception as date_e:
                        print(f">>> 获取最新日期失败: {date_e}")
                        # 截图调试
                        page.screenshot(path="date_extract_fail.png")

                    # 3. 发送最终通知
                    msg = (
                        f"🎉 **续期成功！**\n"
                        f"XServer xmgame 使用期限已延长。\n\n"
                        f"📅 **最新截止日期**: {new_date_text}"
                    )
                    send_notification(msg)
                else:
                    # 如果 URL 丢失（理论上不会），发送基础通知
                    msg = "🎉 **续期成功！**\n(警告: 无法跳转回详情页，未获取最新日期)"
                    send_notification(msg)

            except TimeoutError:
                print(">>> 未检测到标准成功文本，截图保存状态...")
                page.screenshot(path="unknown_result.png")
                # 模糊匹配
                if page.locator('text=完了').is_visible() or page.locator('text=成功').is_visible():
                     msg = "🎉 **可能续期成功**\n(检测到模糊成功关键词，请手动检查)"
                     send_notification(msg)
                else:
                    raise Exception("续期后未找到成功提示信息。")

        except Exception as e:
            # --- 错误处理 ---
            error_msg = f"❌ **任务失败**\n步骤执行异常。\n原因: {str(e)}"
            print(error_msg)
            send_notification(error_msg)
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
