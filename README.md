# BEAVER-client

**BEAVER-client** は、Python 製のクライアントアプリケーションです。
ユーザーインターフェースは `tkinter` ベースで構成されています。
また、**BEAVER-server**がないと動作しません。

アプリ本体のソースコードは `config/` `services/` `state/` `ui/` に分割してルート直下へ配置しています。
起動エントリポイントは互換性のためにルートの `main.py` を残しつつ、実体は `app.py` です。

---

# Python アプリを EXE 化する手順

## 必須環境

* MinGW （ビルドに必要）
* Python 開発環境
* Git

## 手順

1. PyInstaller のソースを取得

   ```powershell
   git clone https://github.com/pyinstaller/pyinstaller.git
   ```

2. Bootloader のビルド

   ```powershell
   cd pyinstaller/bootloader
   python ./waf distclean all
   ```

3. Wheel をインストール

   ```powershell
   pip install wheel
   ```

4. PyInstaller をインストール

   ```powershell
   cd ..
   pip install .
   ```

## 実行方法

ビルドが完了したら、以下のコマンドで EXE 化できます。

```powershell
pyinstaller beaver.spec
```

生成された EXE は `dist` フォルダの中に出力されます。
