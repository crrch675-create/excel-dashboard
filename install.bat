@echo off
chcp 65001 > nul
echo ==========================================
echo  経営ダッシュボード - インストールスクリプト
echo ==========================================
echo.
echo 必要なライブラリをインストールします...
echo.

pip install streamlit openpyxl pandas "streamlit-aggrid>=0.3.4" xlwings

echo.
echo ==========================================
echo  インストール完了！
echo  run.bat を実行するとアプリが起動します。
echo ==========================================
pause
