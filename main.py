import os
import re

import requests

# 環境変数からトークンを取得
FIGMA_TOKEN = os.getenv("FIGMA_TOKEN")


def extract_file_id_from_url(figma_url):
    """FigmaのURLからFile IDとNode IDを抽出"""
    # File IDを抽出
    file_pattern = r"figma\.com/(?:file|design)/([a-zA-Z0-9]{22})"
    file_match = re.search(file_pattern, figma_url)

    # Node IDを抽出（node-id=があれば）
    node_pattern = r"node-id=([^&]+)"
    node_match = re.search(node_pattern, figma_url)

    file_id = file_match.group(1) if file_match else None
    node_id = node_match.group(1) if node_match else None

    return file_id, node_id


def get_file_info(file_id):
    """ファイル情報を取得してノードIDを確認"""
    url = f"https://api.figma.com/v1/files/{file_id}"
    headers = {"X-Figma-Token": FIGMA_TOKEN}

    print(f"📡 APIリクエスト中... URL: {url}")

    try:
        response = requests.get(url, headers=headers, timeout=30)
        print(f"📊 レスポンスステータス: {response.status_code}")

        if response.status_code != 200:
            print(f"❌ エラーレスポンス: {response.text}")
            return None

        response.raise_for_status()
        data = response.json()

        print(f"✅ ファイル名: {data['name']}")
        print("📋 ページ一覧:")

        # ページとフレームの情報を表示
        for page in data["document"]["children"]:
            print(f"  📄 ページ: {page['name']}")
            print(f"     ページID: {page['id']}")

            # フレームがあれば表示
            if "children" in page:
                frame_count = 0
                for child in page["children"]:
                    if child["type"] == "FRAME":
                        print(f"    🖼️  フレーム: {child['name']}")
                        print(f"       フレームID: {child['id']}")
                        frame_count += 1

                        # フレームが多すぎる場合は省略
                        if frame_count >= 10:
                            remaining = (
                                len(
                                    [
                                        c
                                        for c in page["children"]
                                        if c["type"] == "FRAME"
                                    ]
                                )
                                - frame_count
                            )
                            if remaining > 0:
                                print(f"    ... 他 {remaining} 個のフレーム")
                            break

        return data

    except requests.exceptions.Timeout:
        print("⏰ タイムアウト: サーバーからの応答が遅すぎます")
        return None
    except requests.exceptions.RequestException as e:
        print(f"❌ APIリクエストエラー: {e}")
        return None
    except Exception as e:
        print(f"❌ 予期しないエラー: {e}")
        return None


def get_image_url(file_id, node_id, format="png", scale=1):
    """指定したノードの画像URLを取得"""
    url = f"https://api.figma.com/v1/images/{file_id}"
    headers = {"X-Figma-Token": FIGMA_TOKEN}

    # Node IDのフォーマットを統一（ハイフンをコロンに変換）
    formatted_node_id = node_id.replace("-", ":")

    params = {"ids": formatted_node_id, "format": format, "scale": scale}

    print(f"📡 画像URL取得中... Node ID: {formatted_node_id}")

    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()

        print(f"📊 レスポンス: {data}")

        # エラーチェック
        if data.get("err"):
            print(f"❌ Figma APIエラー: {data['err']}")
            return None

        # 画像URLを確認（複数の形式で確認）
        images = data.get("images", {})

        # 元のnode_idで確認
        if node_id in images:
            image_url = images[node_id]
        # フォーマット済みnode_idで確認
        elif formatted_node_id in images:
            image_url = images[formatted_node_id]
        else:
            print("❌ 画像URLが見つかりません")
            print(f"利用可能なNode ID: {list(images.keys())}")
            return None

        if image_url:
            print(f"✅ 画像URL: {image_url}")
            return image_url
        else:
            print("❌ 画像URLが空です")
            return None

    except requests.exceptions.RequestException as e:
        print(f"❌ 画像URL取得エラー: {e}")
        return None


def main():
    """メイン処理"""
    if not FIGMA_TOKEN:
        print("❌ FIGMA_TOKEN環境変数が設定されていません")
        exit(1)

    # 1. FigmaファイルのURLを手動で取得
    figma_url = input("FigmaファイルのURLを入力してください: ")

    # 2. File IDとNode IDを抽出
    file_id, url_node_id = extract_file_id_from_url(figma_url)

    if file_id:
        print(f"✅ 抽出されたFile ID: {file_id}")
        if url_node_id:
            print(f"✅ URLからNode ID検出: {url_node_id}")
        print()

        # 3. ファイル情報を取得
        file_data = get_file_info(file_id)

        if file_data:
            print()

            # 4. Node IDの決定
            if url_node_id:
                use_url_node = (
                    input(f"URLのNode ID ({url_node_id}) を使用しますか？ (y/n): ")
                    .lower()
                    .strip()
                )
                if use_url_node in ["y", "yes", ""]:
                    node_id = url_node_id
                else:
                    node_id = input(
                        "画像化したいページまたはフレームのIDを入力してください: "
                    )
            else:
                node_id = input(
                    "画像化したいページまたはフレームのIDを入力してください: "
                )

            if node_id:
                print()
                # 5. 画像URLを取得
                image_url = get_image_url(file_id, node_id)

                if image_url:
                    print(f"\n🎉 成功！画像URL: {image_url}")
                    print(
                        "\n💡 このURLをブラウザで開くか、ダウンロードして使用できます。"
                    )
            else:
                print("❌ ノードIDが入力されていません")

    else:
        print("❌ 有効なFigma URLではありません")


if __name__ == "__main__":
    main()
