#!/usr/bin/env python3
"""
Figma Image Exporter TUI
FigmaのURLから画像を取得してassetsフォルダに保存するTUIアプリケーション
"""

import os
import json
import sys
import argparse
import warnings
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
import requests
import re

# SSL関連の警告を抑制
warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*Event loop is closed.*")
warnings.filterwarnings("ignore", category=ResourceWarning, message=".*unclosed.*")

# TUI用ライブラリ
import curses
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, TextColumn, BarColumn, TimeRemainingColumn
from rich.prompt import Prompt, Confirm
from rich.text import Text
from rich.panel import Panel
from rich.layout import Layout
from rich.live import Live
from rich.align import Align

# クロスプラットフォーム対応の一文字入力
def getch():
    """一文字入力を取得（クロスプラットフォーム対応）"""
    try:
        # Windows
        import msvcrt
        return msvcrt.getch().decode('utf-8')
    except ImportError:
        try:
            # Unix/Linux/Mac
            import termios, tty
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            try:
                tty.setcbreak(fd)
                ch = sys.stdin.read(1)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            return ch
        except Exception:
            # フォールバック: 通常の入力
            return input().strip()[:1] if input().strip() else '\n'

def get_single_key_input(prompt):
    """一文字入力のラッパー関数（エラーハンドリング付き）"""
    print(prompt, end="", flush=True)
    try:
        return getch().lower()
    except Exception:
        # エラー時はEnter待ちの通常入力にフォールバック
        print("\n[一文字入力に失敗しました。Enterキーを押してください]")
        response = input().strip().lower()
        return response[0] if response else '\n'


class FigmaImageExporter:
    def __init__(self, figma_token: str = None, urls_file: str = "figma_urls.json", 
                 output_file: str = "figma_images.json", assets_dir: str = "assets"):
        self.figma_token = figma_token
        self.urls_file = urls_file
        self.output_file = output_file
        self.assets_dir = assets_dir
        self.console = Console()
        self.config_file = "figma_config.json"
        
        # アセットディレクトリを作成
        Path(self.assets_dir).mkdir(exist_ok=True)
        
        # 設定を読み込み
        self.load_config()
    
    def load_config(self):
        """設定ファイルを読み込む"""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
                if not self.figma_token:
                    self.figma_token = config.get('figma_token', '')
                self.urls_file = config.get('urls_file', self.urls_file)
                self.output_file = config.get('output_file', self.output_file)
                self.assets_dir = config.get('assets_dir', self.assets_dir)
        except FileNotFoundError:
            # 設定ファイルがない場合はデフォルト値を使用
            pass
        except json.JSONDecodeError:
            self.console.print(f"[yellow]警告: {self.config_file} のJSONフォーマットが正しくありません[/yellow]")
    
    def save_config(self):
        """設定ファイルを保存"""
        config = {
            'figma_token': self.figma_token,
            'urls_file': self.urls_file,
            'output_file': self.output_file,
            'assets_dir': self.assets_dir
        }
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.console.print(f"[red]エラー: 設定の保存に失敗しました: {e}[/red]")
        
    def load_urls(self) -> List[Dict[str, str]]:
        """URLsファイルからFigma URLsを読み込む"""
        try:
            with open(self.urls_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            self.console.print(f"[red]エラー: {self.urls_file} が見つかりません[/red]")
            return []
        except json.JSONDecodeError:
            self.console.print(f"[red]エラー: {self.urls_file} のJSONフォーマットが正しくありません[/red]")
            return []
    
    def save_image_urls(self, image_data: List[Dict[str, str]]):
        """画像URLsをJSONファイルに保存"""
        try:
            with open(self.output_file, 'w', encoding='utf-8') as f:
                json.dump(image_data, f, ensure_ascii=False, indent=2)
            self.console.print(f"[green]画像URLsを {self.output_file} に保存しました[/green]")
        except Exception as e:
            self.console.print(f"[red]エラー: 画像URLsの保存に失敗しました: {e}[/red]")
    
    def extract_file_id_from_url(self, figma_url: str) -> tuple[Optional[str], Optional[str]]:
        """FigmaのURLからFile IDとNode IDを抽出"""
        file_pattern = r"figma\.com/(?:file|design)/([a-zA-Z0-9]{22})"
        file_match = re.search(file_pattern, figma_url)
        
        node_pattern = r"node-id=([^&]+)"
        node_match = re.search(node_pattern, figma_url)
        
        file_id = file_match.group(1) if file_match else None
        node_id = node_match.group(1) if node_match else None
        
        return file_id, node_id
    
    def get_image_url(self, file_id: str, node_id: str, format: str = "png", scale: int = 1) -> Optional[str]:
        """指定したノードの画像URLを取得"""
        url = f"https://api.figma.com/v1/images/{file_id}"
        headers = {"X-Figma-Token": self.figma_token}
        
        formatted_node_id = node_id.replace("-", ":")
        params = {"ids": formatted_node_id, "format": format, "scale": scale}
        
        try:
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            
            if data.get("err"):
                self.console.print(f"[red]Figma APIエラー: {data['err']}[/red]")
                return None
                
            images = data.get("images", {})
            
            if node_id in images:
                return images[node_id]
            elif formatted_node_id in images:
                return images[formatted_node_id]
            else:
                return None
                
        except requests.exceptions.RequestException as e:
            self.console.print(f"[red]画像URL取得エラー: {e}[/red]")
            return None
    
    def download_image(self, url: str, filename: str) -> bool:
        """画像をダウンロード"""
        try:
            response = requests.get(url, stream=True)
            response.raise_for_status()
            
            filepath = Path(self.assets_dir) / filename
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            return True
        except Exception as e:
            self.console.print(f"[red]画像ダウンロードエラー: {e}[/red]")
            return False
    
    def process_urls(self) -> List[Dict[str, str]]:
        """URLsを処理して画像URLsを取得"""
        urls_data = self.load_urls()
        if not urls_data:
            return []
        
        image_data = []
        
        with Progress(
            TextColumn("[bold blue]{task.fields[name]}[/bold blue]"),
            BarColumn(),
            "[progress.percentage]{task.percentage:>3.1f}%",
            "•",
            TimeRemainingColumn(),
            console=self.console
        ) as progress:
            
            task = progress.add_task("画像URL取得中", total=len(urls_data), name="Processing")
            
            for item in urls_data:
                name = item.get("name", "Unknown")
                url = item.get("url", "")
                
                progress.update(task, name=f"Processing: {name}")
                
                file_id, node_id = self.extract_file_id_from_url(url)
                
                if file_id and node_id:
                    image_url = self.get_image_url(file_id, node_id)
                    if image_url:
                        image_data.append({
                            "name": name,
                            "url": image_url,
                            "original_url": url
                        })
                    else:
                        self.console.print(f"[yellow]⚠ {name}: 画像URL取得失敗[/yellow]")
                else:
                    self.console.print(f"[red]✗ {name}: 無効なFigma URL[/red]")
                
                progress.advance(task)
        
        # 結果サマリーを表示
        if image_data:
            self.console.print(f"\n[green]✓ {len(image_data)}/{len(urls_data)} 個の画像URL取得完了[/green]")
        else:
            self.console.print(f"\n[red]✗ 画像URL取得に失敗しました[/red]")
        
        return image_data
    
    def download_images(self, image_data: List[Dict[str, str]]):
        """画像をダウンロード"""
        if not image_data:
            self.console.print("[yellow]ダウンロードする画像がありません[/yellow]")
            return
        
        success_count = 0
        
        with Progress(
            TextColumn("[bold blue]{task.fields[name]}[/bold blue]"),
            BarColumn(),
            "[progress.percentage]{task.percentage:>3.1f}%",
            "•",
            TimeRemainingColumn(),
            console=self.console
        ) as progress:
            
            task = progress.add_task("画像ダウンロード中", total=len(image_data), name="Downloading")
            
            for item in image_data:
                name = item.get("name", "Unknown")
                url = item.get("url", "")
                
                progress.update(task, name=f"Downloading: {name}")
                
                # ファイル名を生成（安全な文字のみ）
                safe_name = re.sub(r'[^\w\-_\.]', '_', name)
                filename = f"{safe_name}.png"
                
                if self.download_image(url, filename):
                    success_count += 1
                
                progress.advance(task)
        
        # 結果サマリーを表示
        if success_count > 0:
            self.console.print(f"\n[green]✓ {success_count}/{len(image_data)} 個の画像ダウンロード完了[/green]")
        else:
            self.console.print(f"\n[red]✗ 画像ダウンロードに失敗しました[/red]")
    
    def show_main_menu_curses(self, stdscr):
        """メインメニューを表示（curses版）"""
        curses.curs_set(0)  # カーソルを非表示
        stdscr.keypad(1)    # 特殊キーを有効化
        
        menu_items = [
            ("URLsから画像リンクを取得", "get_urls"),
            ("選択して画像をダウンロード", "download_selected"),
            ("すべてをダウンロード", "download_all"),
            ("設定を変更", "settings"),
            ("終了", "quit")
        ]
        
        current_pos = 0
        
        while True:
            stdscr.clear()
            height, width = stdscr.getmaxyx()
            
            # タイトル
            title = "🎨 Figma Image Exporter TUI"
            stdscr.addstr(1, (width - len(title)) // 2, title, curses.A_BOLD)
            
            # メニュー表示
            for i, (label, _) in enumerate(menu_items):
                y = 5 + i * 2
                if i == current_pos:
                    stdscr.addstr(y, 4, f"► {label}", curses.A_REVERSE)
                else:
                    stdscr.addstr(y, 4, f"  {label}")
            
            # 設定情報表示
            settings_y = 5 + len(menu_items) * 2 + 2
            stdscr.addstr(settings_y, 4, "⚙️ Current Settings:", curses.A_BOLD)
            stdscr.addstr(settings_y + 1, 6, f"URLs File: {self.urls_file}")
            stdscr.addstr(settings_y + 2, 6, f"Output File: {self.output_file}")
            stdscr.addstr(settings_y + 3, 6, f"Assets Directory: {self.assets_dir}")
            stdscr.addstr(settings_y + 4, 6, f"Figma Token: {'設定済み' if self.figma_token else '未設定'}")
            
            # キー操作ヘルプ
            help_y = height - 3
            stdscr.addstr(help_y, 4, "j/k: 上下移動, Space/Enter: 決定, q: 終了", curses.A_DIM)
            
            stdscr.refresh()
            
            # キー入力処理
            key = stdscr.getch()
            
            if key == ord('q') or key == ord('Q'):
                break
            elif key == curses.KEY_DOWN or key == ord('j') or key == ord('J'):
                current_pos = (current_pos + 1) % len(menu_items)
            elif key == curses.KEY_UP or key == ord('k') or key == ord('K'):
                current_pos = (current_pos - 1) % len(menu_items)
            elif key == ord('\n') or key == 10 or key == ord(' '):
                selected_action = menu_items[current_pos][1]
                if selected_action == "quit":
                    break
                elif selected_action == "get_urls":
                    self.curses_get_urls(stdscr)
                elif selected_action == "download_selected":
                    self.curses_download_selected(stdscr)
                elif selected_action == "download_all":
                    self.curses_download_all(stdscr)
                elif selected_action == "settings":
                    self.curses_settings(stdscr)
    
    def curses_get_urls(self, stdscr):
        """URLsから画像リンクを取得（curses版）"""
        # cursesモードを一時的に終了してRichコンソールを使用
        curses.endwin()
        
        try:
            self.console.clear()
            self.console.print("[bold cyan]URLsから画像リンクを取得中...[/bold cyan]")
            
            image_data = self.process_urls()
            if image_data:
                self.save_image_urls(image_data)
                self.console.print(f"[green]✓ {len(image_data)} 個の画像リンクを取得しました[/green]")
            else:
                self.console.print("[red]✗ 画像リンクの取得に失敗しました[/red]")
            
            input("\nエンターキーで続行...")
        finally:
            # cursesモードを再開
            stdscr.refresh()
    
    def curses_download_selected(self, stdscr):
        """選択して画像をダウンロード（curses版）"""
        try:
            with open(self.output_file, 'r', encoding='utf-8') as f:
                image_data = json.load(f)
        except FileNotFoundError:
            stdscr.clear()
            stdscr.addstr(1, 4, f"エラー: {self.output_file} が見つかりません", curses.A_BOLD)
            stdscr.addstr(2, 4, "まず画像リンクを取得してください")
            stdscr.addstr(4, 4, "エンターキーで続行...")
            stdscr.refresh()
            while stdscr.getch() not in [ord('\n'), 10]:
                pass
            return
        except json.JSONDecodeError:
            stdscr.clear()
            stdscr.addstr(1, 4, f"エラー: {self.output_file} のJSONフォーマットが正しくありません", curses.A_BOLD)
            stdscr.addstr(3, 4, "エンターキーで続行...")
            stdscr.refresh()
            while stdscr.getch() not in [ord('\n'), 10]:
                pass
            return
        
        # チェックボックス選択画面
        selected_items = self.curses_checkbox_selection(stdscr, image_data)
        
        if selected_items:
            # cursesモードを一時的に終了してRichコンソールを使用
            curses.endwin()
            
            try:
                self.console.clear()
                self.console.print(f"[bold cyan]選択された {len(selected_items)} 個の画像をダウンロード中...[/bold cyan]")
                
                self.download_images(selected_items)
                
                self.console.print(f"[green]✓ {len(selected_items)} 個の画像をダウンロードしました[/green]")
                input("\nエンターキーで続行...")
            finally:
                # cursesモードを再開
                stdscr.refresh()
    
    def curses_download_all(self, stdscr):
        """すべての画像をダウンロード（curses版）"""
        try:
            with open(self.output_file, 'r', encoding='utf-8') as f:
                image_data = json.load(f)
        except FileNotFoundError:
            stdscr.clear()
            stdscr.addstr(1, 4, f"エラー: {self.output_file} が見つかりません", curses.A_BOLD)
            stdscr.addstr(2, 4, "まず画像リンクを取得してください")
            stdscr.addstr(4, 4, "エンターキーで続行...")
            stdscr.refresh()
            while stdscr.getch() not in [ord('\n'), 10]:
                pass
            return
        except json.JSONDecodeError:
            stdscr.clear()
            stdscr.addstr(1, 4, f"エラー: {self.output_file} のJSONフォーマットが正しくありません", curses.A_BOLD)
            stdscr.addstr(3, 4, "エンターキーで続行...")
            stdscr.refresh()
            while stdscr.getch() not in [ord('\n'), 10]:
                pass
            return
        
        if not image_data:
            stdscr.clear()
            stdscr.addstr(1, 4, "ダウンロードする画像がありません", curses.A_BOLD)
            stdscr.addstr(3, 4, "エンターキーで続行...")
            stdscr.refresh()
            while stdscr.getch() not in [ord('\n'), 10]:
                pass
            return
        
        # 確認ダイアログを表示
        stdscr.clear()
        height, width = stdscr.getmaxyx()
        
        # 確認メッセージ
        msg1 = f"{len(image_data)} 個すべての画像をダウンロードしますか？"
        msg2 = "y: はい, n: いいえ"
        
        stdscr.addstr(height // 2 - 1, (width - len(msg1)) // 2, msg1, curses.A_BOLD)
        stdscr.addstr(height // 2 + 1, (width - len(msg2)) // 2, msg2)
        stdscr.refresh()
        
        # 確認入力
        while True:
            key = stdscr.getch()
            if key == ord('y') or key == ord('Y'):
                break
            elif key == ord('n') or key == ord('N') or key == ord('q') or key == ord('Q'):
                return
        
        # cursesモードを一時的に終了してRichコンソールを使用
        curses.endwin()
        
        try:
            self.console.clear()
            self.console.print(f"[bold cyan]{len(image_data)} 個すべての画像をダウンロード中...[/bold cyan]")
            
            self.download_images(image_data)
            
            input("\nエンターキーで続行...")
        finally:
            # cursesモードを再開
            stdscr.refresh()
    
    def curses_checkbox_selection(self, stdscr, items):
        """チェックボックス選択画面（curses版）"""
        curses.curs_set(0)
        stdscr.keypad(1)
        
        selected = [False] * len(items)
        current_pos = 0
        scroll_offset = 0
        
        while True:
            stdscr.clear()
            height, width = stdscr.getmaxyx()
            
            # タイトル
            title = "画像を選択してください"
            stdscr.addstr(1, (width - len(title)) // 2, title, curses.A_BOLD)
            
            # 表示可能な行数を計算
            display_height = height - 8  # ヘッダー・フッター用の余白
            
            # スクロール処理
            if current_pos < scroll_offset:
                scroll_offset = current_pos
            elif current_pos >= scroll_offset + display_height:
                scroll_offset = current_pos - display_height + 1
            
            # アイテム表示
            for i in range(min(display_height, len(items) - scroll_offset)):
                item_index = scroll_offset + i
                if item_index >= len(items):
                    break
                
                y = 4 + i
                item = items[item_index]
                name = item.get('name', 'Unknown')
                
                # チェックボックス
                checkbox = "[✓]" if selected[item_index] else "[ ]"
                
                # 現在選択中の項目をハイライト
                if item_index == current_pos:
                    stdscr.addstr(y, 4, f"► {checkbox} {name}", curses.A_REVERSE)
                else:
                    stdscr.addstr(y, 4, f"  {checkbox} {name}")
            
            # 選択済み数を表示
            selected_count = sum(selected)
            status_y = height - 4
            stdscr.addstr(status_y, 4, f"選択済み: {selected_count}/{len(items)}")
            
            # キー操作ヘルプ
            help_y = height - 3
            stdscr.addstr(help_y, 4, "j/k: 上下移動, Space: 選択切替, a: 全選択/解除, Enter: 決定, q: キャンセル", curses.A_DIM)
            
            stdscr.refresh()
            
            # キー入力処理
            key = stdscr.getch()
            
            if key == ord('q') or key == ord('Q'):
                return []
            elif key == curses.KEY_DOWN or key == ord('j') or key == ord('J'):
                current_pos = (current_pos + 1) % len(items)
            elif key == curses.KEY_UP or key == ord('k') or key == ord('K'):
                current_pos = (current_pos - 1) % len(items)
            elif key == ord(' '):
                selected[current_pos] = not selected[current_pos]
            elif key == ord('a') or key == ord('A'):
                # 全選択/全解除の切り替え
                all_selected = all(selected)
                selected = [not all_selected] * len(items)
            elif key == ord('\n') or key == 10:
                # 選択された項目を返す
                return [items[i] for i, sel in enumerate(selected) if sel]
    
    def curses_settings(self, stdscr):
        """設定画面（curses版）"""
        curses.curs_set(0)
        stdscr.keypad(1)
        
        settings_items = [
            ("Figma Token", "figma_token"),
            ("URLs File", "urls_file"),
            ("Output File", "output_file"),
            ("Assets Directory", "assets_dir"),
            ("設定を保存", "save"),
            ("戻る", "back")
        ]
        
        current_pos = 0
        
        while True:
            stdscr.clear()
            height, width = stdscr.getmaxyx()
            
            # タイトル
            title = "⚙️ 設定"
            stdscr.addstr(1, (width - len(title)) // 2, title, curses.A_BOLD)
            
            # 設定項目表示
            for i, (label, key) in enumerate(settings_items):
                y = 4 + i * 2
                if i == current_pos:
                    stdscr.addstr(y, 4, f"► {label}", curses.A_REVERSE)
                else:
                    stdscr.addstr(y, 4, f"  {label}")
                
                # 現在の値を表示
                if key == "figma_token":
                    value = "設定済み" if self.figma_token else "未設定"
                elif key == "urls_file":
                    value = self.urls_file
                elif key == "output_file":
                    value = self.output_file
                elif key == "assets_dir":
                    value = self.assets_dir
                elif key in ["save", "back"]:
                    value = ""
                else:
                    value = ""
                
                if value:
                    stdscr.addstr(y, 30, f": {value}")
            
            # キー操作ヘルプ
            help_y = height - 3
            stdscr.addstr(help_y, 4, "j/k: 上下移動, Space/Enter: 選択, q: 戻る", curses.A_DIM)
            
            stdscr.refresh()
            
            # キー入力処理
            key = stdscr.getch()
            
            if key == ord('q') or key == ord('Q'):
                break
            elif key == curses.KEY_DOWN or key == ord('j') or key == ord('J'):
                current_pos = (current_pos + 1) % len(settings_items)
            elif key == curses.KEY_UP or key == ord('k') or key == ord('K'):
                current_pos = (current_pos - 1) % len(settings_items)
            elif key == ord('\n') or key == 10 or key == ord(' '):
                selected_key = settings_items[current_pos][1]
                if selected_key == "back":
                    break
                elif selected_key == "save":
                    self.save_config()
                    stdscr.addstr(height - 5, 4, "✓ 設定を保存しました", curses.A_BOLD)
                    stdscr.refresh()
                    stdscr.getch()
                else:
                    # 設定値を変更
                    new_value = self.curses_input_dialog(stdscr, f"{settings_items[current_pos][0]}を入力してください:")
                    if new_value is not None:
                        if selected_key == "figma_token":
                            self.figma_token = new_value
                        elif selected_key == "urls_file":
                            self.urls_file = new_value
                        elif selected_key == "output_file":
                            self.output_file = new_value
                        elif selected_key == "assets_dir":
                            self.assets_dir = new_value
                            Path(self.assets_dir).mkdir(exist_ok=True)
    
    def curses_input_dialog(self, stdscr, prompt):
        """入力ダイアログ（curses版）"""
        curses.curs_set(1)  # カーソルを表示
        curses.echo()       # 入力を表示
        
        stdscr.clear()
        height, width = stdscr.getmaxyx()
        
        # ダイアログボックスの描画
        dialog_height = 7
        dialog_width = min(width - 8, 70)
        dialog_y = (height - dialog_height) // 2
        dialog_x = (width - dialog_width) // 2
        
        # 枠線を描画
        try:
            # 上下の線
            stdscr.hline(dialog_y, dialog_x, curses.ACS_HLINE, dialog_width)
            stdscr.hline(dialog_y + dialog_height - 1, dialog_x, curses.ACS_HLINE, dialog_width)
            
            # 左右の線
            stdscr.vline(dialog_y, dialog_x, curses.ACS_VLINE, dialog_height)
            stdscr.vline(dialog_y, dialog_x + dialog_width - 1, curses.ACS_VLINE, dialog_height)
            
            # 角
            stdscr.addch(dialog_y, dialog_x, curses.ACS_ULCORNER)
            stdscr.addch(dialog_y, dialog_x + dialog_width - 1, curses.ACS_URCORNER)
            stdscr.addch(dialog_y + dialog_height - 1, dialog_x, curses.ACS_LLCORNER)
            stdscr.addch(dialog_y + dialog_height - 1, dialog_x + dialog_width - 1, curses.ACS_LRCORNER)
        except:
            # 枠線描画に失敗した場合は簡単な線で代替
            for i in range(dialog_width):
                stdscr.addch(dialog_y, dialog_x + i, '-')
                stdscr.addch(dialog_y + dialog_height - 1, dialog_x + i, '-')
            for i in range(dialog_height):
                stdscr.addch(dialog_y + i, dialog_x, '|')
                stdscr.addch(dialog_y + i, dialog_x + dialog_width - 1, '|')
        
        # プロンプト表示（枠内に表示）
        prompt_y = dialog_y + 2
        prompt_x = dialog_x + 2
        
        # プロンプトテキストが長すぎる場合は切り詰める
        max_prompt_width = dialog_width - 4
        if len(prompt) > max_prompt_width:
            prompt = prompt[:max_prompt_width - 3] + "..."
        
        stdscr.addstr(prompt_y, prompt_x, prompt)
        
        # 入力フィールドの表示
        input_y = dialog_y + 4
        input_x = dialog_x + 2
        input_label = "入力: "
        stdscr.addstr(input_y, input_x, input_label)
        
        # 入力フィールドの背景を描画
        input_field_x = input_x + len(input_label)
        input_field_width = dialog_width - len(input_label) - 4
        
        # 入力フィールドの背景を描画
        for i in range(input_field_width):
            stdscr.addch(input_y, input_field_x + i, '_')
        
        # キャンセル方法を表示
        stdscr.addstr(input_y + 1, input_x, "(空でキャンセル)")
        
        # カーソルを入力位置に移動
        stdscr.move(input_y, input_field_x)
        stdscr.refresh()
        
        # 入力を受け取る
        try:
            input_str = stdscr.getstr(input_y, input_field_x, input_field_width).decode('utf-8')
            return input_str.strip() if input_str.strip() else None
        except:
            return None
        finally:
            curses.noecho()  # 入力表示を無効化
            curses.curs_set(0)  # カーソルを非表示
    
    def run(self):
        """メインループ（curses版）"""
        try:
            curses.wrapper(self.show_main_menu_curses)
        except KeyboardInterrupt:
            self.console.print("\n[bold red]終了します。[/bold red]")
        except Exception as e:
            self.console.print(f"\n[red]エラーが発生しました: {e}[/red]")
            # フォールバック: 通常のメニューに切り替え
            self.run_fallback()
    
    def run_fallback(self):
        """フォールバック: 通常のメニュー"""
        self.console.print("[yellow]TUIモードでエラーが発生しました。CLIモードに切り替えます。[/yellow]")
        
        while True:
            self.console.clear()
            
            # タイトル
            title = Text("Figma Image Exporter", style="bold magenta")
            self.console.print(Panel(Align.center(title), title="🎨 Welcome"))
            
            # メニュー表示
            table = Table(show_header=False, box=None, padding=(0, 2))
            table.add_column("Option", style="cyan")
            table.add_column("Description", style="white")
            
            table.add_row("1", "URLsから画像リンクを取得")
            table.add_row("2", "選択して画像をダウンロード")
            table.add_row("3", "すべてをダウンロード")
            table.add_row("4", "設定を変更")
            table.add_row("5", "終了")
            
            self.console.print(Panel(table, title="📋 Menu"))
            
            # 現在の設定を表示
            config_table = Table(show_header=False, box=None, padding=(0, 1))
            config_table.add_column("Setting", style="yellow")
            config_table.add_column("Value", style="green")
            
            config_table.add_row("URLs File", self.urls_file)
            config_table.add_row("Output File", self.output_file)
            config_table.add_row("Assets Directory", self.assets_dir)
            config_table.add_row("Figma Token", "設定済み" if self.figma_token else "未設定")
            
            self.console.print(Panel(config_table, title="⚙️ Current Settings"))
            
            try:
                choice = Prompt.ask("\n選択してください", choices=["1", "2", "3", "4", "5"], default="1")
                
                if choice == "1":
                    self.console.print("\n[bold cyan]URLsから画像リンクを取得中...[/bold cyan]")
                    image_data = self.process_urls()
                    if image_data:
                        self.save_image_urls(image_data)
                    
                    input("\nエンターキーで続行...")
                    
                elif choice == "2":
                    # 選択して画像をダウンロード
                    try:
                        with open(self.output_file, 'r', encoding='utf-8') as f:
                            image_data = json.load(f)
                        
                        if not image_data:
                            self.console.print("[yellow]画像データがありません[/yellow]")
                            input("\nエンターキーで続行...")
                            continue
                        
                        # 簡単な選択インターフェース
                        self.console.print("\n[bold cyan]画像を選択してください:[/bold cyan]")
                        selected_items = []
                        
                        for i, item in enumerate(image_data):
                            name = item.get('name', 'Unknown')
                            select = Confirm.ask(f"  {i+1}. {name} をダウンロードしますか？", default=False)
                            if select:
                                selected_items.append(item)
                        
                        if selected_items:
                            self.console.print(f"\n[bold cyan]{len(selected_items)} 個の画像をダウンロード中...[/bold cyan]")
                            self.download_images(selected_items)
                        else:
                            self.console.print("[yellow]画像が選択されませんでした[/yellow]")
                    
                    except FileNotFoundError:
                        self.console.print(f"[red]エラー: {self.output_file} が見つかりません。まず画像リンクを取得してください。[/red]")
                    except json.JSONDecodeError:
                        self.console.print(f"[red]エラー: {self.output_file} のJSONフォーマットが正しくありません。[/red]")
                    
                    input("\nエンターキーで続行...")
                    
                elif choice == "3":
                    # すべてをダウンロード
                    try:
                        with open(self.output_file, 'r', encoding='utf-8') as f:
                            image_data = json.load(f)
                        
                        if not image_data:
                            self.console.print("[yellow]ダウンロードする画像がありません[/yellow]")
                            input("\nエンターキーで続行...")
                            continue
                        
                        # 確認
                        if Confirm.ask(f"{len(image_data)} 個すべての画像をダウンロードしますか？", default=True):
                            self.console.print(f"\n[bold cyan]{len(image_data)} 個すべての画像をダウンロード中...[/bold cyan]")
                            self.download_images(image_data)
                        else:
                            self.console.print("[yellow]ダウンロードをキャンセルしました[/yellow]")
                    
                    except FileNotFoundError:
                        self.console.print(f"[red]エラー: {self.output_file} が見つかりません。まず画像リンクを取得してください。[/red]")
                    except json.JSONDecodeError:
                        self.console.print(f"[red]エラー: {self.output_file} のJSONフォーマットが正しくありません。[/red]")
                    
                    input("\nエンターキーで続行...")
                    
                elif choice == "4":
                    # 設定変更
                    self.console.print("\n[bold cyan]設定を変更します[/bold cyan]")
                    
                    new_token = Prompt.ask("Figma Token", default=self.figma_token if self.figma_token else "")
                    if new_token:
                        self.figma_token = new_token
                    
                    new_urls_file = Prompt.ask("URLs File", default=self.urls_file)
                    if new_urls_file:
                        self.urls_file = new_urls_file
                    
                    new_output_file = Prompt.ask("Output File", default=self.output_file)
                    if new_output_file:
                        self.output_file = new_output_file
                    
                    new_assets_dir = Prompt.ask("Assets Directory", default=self.assets_dir)
                    if new_assets_dir:
                        self.assets_dir = new_assets_dir
                        Path(self.assets_dir).mkdir(exist_ok=True)
                    
                    if Confirm.ask("設定を保存しますか？", default=True):
                        self.save_config()
                        self.console.print("[green]✓ 設定を保存しました[/green]")
                    
                    input("\nエンターキーで続行...")
                    
                elif choice == "5":
                    self.console.print("\n[bold green]終了します。お疲れ様でした！[/bold green]")
                    break
                    
            except KeyboardInterrupt:
                self.console.print("\n\n[bold red]終了します。[/bold red]")
                break
            except Exception as e:
                self.console.print(f"\n[red]エラーが発生しました: {e}[/red]")
                input("\nエンターキーで続行...")


def main():
    """メイン関数"""
    parser = argparse.ArgumentParser(description="Figma Image Exporter TUI")
    parser.add_argument("--urls-file", default="figma_urls.json", help="URLsファイルのパス")
    parser.add_argument("--output-file", default="figma_images.json", help="出力ファイルのパス")
    parser.add_argument("--assets-dir", default="assets", help="アセットディレクトリのパス")
    parser.add_argument("--token", help="Figma Token (環境変数 FIGMA_TOKEN または設定ファイルからも取得可能)")
    
    args = parser.parse_args()
    
    # 環境変数からトークンを取得
    figma_token = args.token or os.getenv("FIGMA_TOKEN")
    
    # TUIアプリケーションを起動
    app = FigmaImageExporter(
        figma_token=figma_token,
        urls_file=args.urls_file,
        output_file=args.output_file,
        assets_dir=args.assets_dir
    )
    
    # トークンが設定されていない場合の警告
    if not app.figma_token:
        console = Console()
        console.print("[yellow]⚠️  FIGMA_TOKENが設定されていません[/yellow]")
        console.print("[yellow]TUIの設定画面で設定するか、以下の方法で設定してください:[/yellow]")
        console.print("[cyan]1. 環境変数: export FIGMA_TOKEN=your_token_here[/cyan]")
        console.print("[cyan]2. 引数: --token your_token_here[/cyan]")
        console.print("[cyan]3. 設定ファイル: figma_config.json[/cyan]")
        console.print()
    
    try:
        app.run()
    except KeyboardInterrupt:
        console = Console()
        console.print("\n[bold red]アプリケーションを終了します。[/bold red]")
    except Exception as e:
        console = Console()
        console.print(f"\n[red]予期しないエラーが発生しました: {e}[/red]")


if __name__ == "__main__":
    main()