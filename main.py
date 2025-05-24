from playwright.sync_api import sync_playwright
import json
import time
import re
from typing import List, Dict, Optional
from urllib.parse import quote

class GitHubLicenseChecker:
    def __init__(self, headless: bool = True, slow_mo: int = 100):
        """
        PlaywrightでGitHubリポジトリのライセンスをチェックするクラス
        
        Args:
            headless: ヘッドレスモードで実行するか
            slow_mo: 操作間の待機時間（ミリ秒）
        """
        self.headless = headless
        self.slow_mo = slow_mo
        self.browser = None
        self.page = None
    
    def __enter__(self):
        """コンテキストマネージャーのエントリ"""
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(
            headless=self.headless, 
            slow_mo=self.slow_mo
        )
        self.page = self.browser.new_page()
        
        # GitHubにアクセスしやすくするためのヘッダー設定
        self.page.set_extra_http_headers({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """コンテキストマネージャーのエグジット"""
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
    
    def search_repositories(self, keyword: str, sort: str = "stars", count: int = 10) -> List[Dict]:
        """
        指定したキーワードでリポジトリを検索
        
        Args:
            keyword: 検索キーワード
            sort: ソート方法 ('stars', 'forks', 'updated', 'best-match')
            count: 取得するリポジトリ数
        
        Returns:
            リポジトリ情報のリスト
        """
        print(f"'{keyword}'でリポジトリを検索中...")
        
        # GitHub検索ページに移動
        search_url = f"https://github.com/search?q={quote(keyword)}&type=repositories&s={sort}&o=desc"
        
        try:
            self.page.goto(search_url, wait_until="networkidle")
            time.sleep(2)  # ページの完全な読み込みを待機
            
            repositories = []
            
            # 検索結果のリポジトリ要素を取得
            repo_elements = self.page.query_selector_all('[data-testid="results-list"] .search-title')
            
            for i, element in enumerate(repo_elements[:count]):
                try:
                    # リポジトリ名とURLを取得
                    link_element = element.query_selector('a')
                    if not link_element:
                        continue
                    
                    repo_url = link_element.get_attribute('href')
                    repo_full_name = link_element.inner_text().strip()
                    
                    if not repo_url or not repo_full_name:
                        continue
                    
                    # 完全なURLに変換
                    if repo_url.startswith('/'):
                        repo_url = f"https://github.com{repo_url}"
                    
                    print(f"({i+1}/{min(count, len(repo_elements))}) {repo_full_name} を処理中...")
                    
                    # リポジトリの詳細情報を取得
                    repo_info = self._get_repository_details(repo_url, repo_full_name)
                    
                    if repo_info:
                        repositories.append(repo_info)
                    
                    # レート制限を避けるため待機
                    time.sleep(1)
                    
                except Exception as e:
                    print(f"リポジトリ情報の取得でエラー: {e}")
                    continue
            
            return repositories
            
        except Exception as e:
            print(f"検索エラー: {e}")
            return []
    
    def _get_repository_details(self, repo_url: str, repo_full_name: str) -> Optional[Dict]:
        """
        個別のリポジトリページから詳細情報を取得
        
        Args:
            repo_url: リポジトリURL
            repo_full_name: リポジトリのフルネーム
        
        Returns:
            リポジトリ詳細情報の辞書
        """
        try:
            # リポジトリページに移動
            self.page.goto(repo_url, wait_until="networkidle")
            time.sleep(1)
            
            # 基本情報を取得
            repo_info = {
                "repository": repo_full_name,
                "url": repo_url,
                "description": self._get_description(),
                "language": self._get_primary_language(),
                "stars": self._get_stars_count(),
                "forks": self._get_forks_count(),
                "license": self._get_license_info()
            }
            
            return repo_info
            
        except Exception as e:
            print(f"リポジトリ詳細取得エラー ({repo_full_name}): {e}")
            return None
    
    def _get_description(self) -> str:
        """リポジトリの説明を取得"""
        try:
            desc_element = self.page.query_selector('[data-pjax="#repo-content-pjax-container"] p')
            if desc_element:
                return desc_element.inner_text().strip()
        except:
            pass
        return "No description"
    
    def _get_primary_language(self) -> str:
        """主要言語を取得"""
        try:
            # 言語の統計バーから主要言語を取得
            lang_element = self.page.query_selector('[data-view-component="true"] .Progress-item')
            if lang_element:
                aria_label = lang_element.get_attribute('aria-label')
                if aria_label:
                    # "Python 85.2%" のような形式から言語名を抽出
                    match = re.match(r'^([^0-9]+)', aria_label)
                    if match:
                        return match.group(1).strip()
            
            # 別の方法で言語を取得
            lang_span = self.page.query_selector('[data-view-component="true"] .ml-0 .color-fg-default')
            if lang_span:
                return lang_span.inner_text().strip()
                
        except:
            pass
        return "Unknown"
    
    def _get_stars_count(self) -> int:
        """スター数を取得"""
        try:
            # スターボタンを探す
            star_selectors = [
                '#repo-stars-counter-star',
                '[data-view-component="true"] #repo-stars-counter-star',
                'a[href$="/stargazers"] strong',
                '.js-social-count'
            ]
            
            for selector in star_selectors:
                element = self.page.query_selector(selector)
                if element:
                    text = element.inner_text().strip()
                    return self._parse_count(text)
                    
        except:
            pass
        return 0
    
    def _get_forks_count(self) -> int:
        """フォーク数を取得"""
        try:
            # フォークボタンを探す
            fork_selectors = [
                '#repo-network-counter',
                '[data-view-component="true"] #repo-network-counter',
                'a[href$="/forks"] strong'
            ]
            
            for selector in fork_selectors:
                element = self.page.query_selector(selector)
                if element:
                    text = element.inner_text().strip()
                    return self._parse_count(text)
                    
        except:
            pass
        return 0
    
    def _parse_count(self, count_text: str) -> int:
        """数値文字列を解析（1.2k -> 1200等）"""
        if not count_text:
            return 0
            
        count_text = count_text.lower().replace(',', '')
        
        try:
            if 'k' in count_text:
                return int(float(count_text.replace('k', '')) * 1000)
            elif 'm' in count_text:
                return int(float(count_text.replace('m', '')) * 1000000)
            else:
                return int(count_text)
        except:
            return 0
    
    def _get_license_info(self) -> Dict:
        """ライセンス情報を取得"""
        try:
            # ライセンス情報を探す複数のセレクター
            license_selectors = [
                '[data-view-component="true"] .Link--muted[href*="license"]',
                '.octicon-law + .Link--muted',
                'a[href$="/blob/main/LICENSE"]',
                'a[href$="/blob/master/LICENSE"]',
                '.BorderGrid-cell .octicon-law + *'
            ]
            
            for selector in license_selectors:
                element = self.page.query_selector(selector)
                if element:
                    license_text = element.inner_text().strip()
                    if license_text and license_text != "View license":
                        return {
                            "name": license_text,
                            "key": license_text.lower().replace(' ', '-'),
                            "url": element.get_attribute('href') or ""
                        }
            
            # ライセンスファイルの存在確認
            license_files = ['LICENSE', 'LICENSE.md', 'LICENSE.txt', 'COPYING']
            for license_file in license_files:
                if self.page.query_selector(f'a[title="{license_file}"]'):
                    return {
                        "name": "License file found",
                        "key": "license-file",
                        "url": f"{self.page.url}/blob/main/{license_file}"
                    }
            
            return {"name": "No License", "key": "no-license", "url": ""}
            
        except Exception as e:
            print(f"ライセンス取得エラー: {e}")
            return {"name": "Error", "key": "error", "url": ""}
    
    def check_repositories_licenses(self, keyword: str, count: int = 10, sort: str = "stars") -> List[Dict]:
        """
        キーワードで検索したリポジトリのライセンスをチェック
        
        Args:
            keyword: 検索キーワード
            count: チェックするリポジトリ数
            sort: ソート方法
        
        Returns:
            リポジトリとライセンス情報のリスト
        """
        return self.search_repositories(keyword, sort, count)
    
    def display_results(self, results: List[Dict]):
        """結果を見やすく表示"""
        if not results:
            print("表示する結果がありません。")
            return
        
        print("\n" + "="*80)
        print("GitHub リポジトリ ライセンス チェック結果 (Playwright版)")
        print("="*80)
        
        for i, result in enumerate(results, 1):
            print(f"\n{i}. {result['repository']}")
            print(f"   説明: {result['description'][:100]}{'...' if len(result['description']) > 100 else ''}")
            print(f"   言語: {result['language']}")
            print(f"   スター: {result['stars']:,} | フォーク: {result['forks']:,}")
            print(f"   ライセンス: {result['license']['name']}")
            print(f"   URL: {result['url']}")
            
            if result['license']['key'] == 'no-license':
                print("   ⚠️  ライセンスが設定されていません")
            elif result['license']['key'] == 'error':
                print("   ❌ ライセンス情報の取得に失敗しました")
    
    def export_to_json(self, results: List[Dict], filename: str = "github_license_report_playwright.json"):
        """結果をJSONファイルに出力"""
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            print(f"\n結果を {filename} に保存しました。")
        except Exception as e:
            print(f"ファイル保存エラー: {e}")

def main():
    print("GitHub Repository License Checker (Playwright版)")
    print("=" * 50)
    
    keyword = input("検索キーワードを入力してください: ")
    count = int(input("チェックするリポジトリ数を入力してください (デフォルト: 10): ") or "10")
    
    sort_options = {
        "1": "stars",
        "2": "forks", 
        "3": "updated",
        "4": "best-match"
    }
    
    print("\nソート方法を選択してください:")
    print("1. スター数 (デフォルト)")
    print("2. フォーク数")
    print("3. 更新日時")
    print("4. 関連度")
    
    sort_choice = input("選択 (1-4): ") or "1"
    sort_method = sort_options.get(sort_choice, "stars")
    
    headless_choice = input("\nヘッドレスモードで実行しますか？ (Y/n): ").lower()
    headless = headless_choice != 'n'
    
    # ライセンスチェック実行
    with GitHubLicenseChecker(headless=headless, slow_mo=100) as checker:
        results = checker.check_repositories_licenses(keyword, count, sort_method)
        
        # 結果表示
        checker.display_results(results)
        
        # JSON出力
        if results:
            save_json = input("\n結果をJSONファイルに保存しますか？ (y/N): ")
            if save_json.lower() == 'y':
                checker.export_to_json(results)

if __name__ == "__main__":
    main()