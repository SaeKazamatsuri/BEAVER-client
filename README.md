# BEAVER-client

**BEAVER-client** は、Python と HTML を使ったクライアントアプリケーションです。  
ユーザーインターフェース表示用の HTML ファイルと、それを表示／制御する Pythonで構成されています。
また、**BEAVER-server**がないと動作しません。

---

# Python アプリを EXE 化する手順

## 必須環境
- MinGW （ビルドに必要）
- Python 開発環境
- Git

## 手順

1. PyInstaller のソースを取得
   git clone https://github.com/pyinstaller/pyinstaller.git

2. Bootloader のビルド
   cd pyinstaller/bootloader
   python ./waf distclean all

3. Wheel をインストール
   pip install wheel

4. PyInstaller をインストール
   cd ..
   pip install .

## 実行方法
ビルドが完了したら、以下のコマンドで EXE 化できます。

   pyinstaller beaver.spec

生成された EXE は dist フォルダの中に出力されます。
