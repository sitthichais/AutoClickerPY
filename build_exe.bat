@echo off
REM ============================================
REM  Build script - แปลง auto_clicker.py เป็น .exe
REM  วางไฟล์นี้ไว้โฟลเดอร์เดียวกับ auto_clicker.py แล้วดับเบิลคลิก
REM ============================================

echo กำลังติดตั้งไลบรารีที่จำเป็น...
pip install customtkinter pyautogui pynput pyinstaller

echo.
echo กำลังติดตั้งไลบรารีเสริม (image recognition + window check)...
pip install opencv-python pygetwindow

echo.
echo กำลัง build .exe ...
pyinstaller --onefile --noconsole --name AutoClickerPro auto_clicker.py

echo.
echo เสร็จแล้ว! ไฟล์ .exe อยู่ที่ dist\AutoClickerPro.exe
echo หมายเหตุ: โฟลเดอร์ presets, combos, images, logs และไฟล์ config.json
echo จะถูกสร้างขึ้นข้างๆ ไฟล์ exe เมื่อรันครั้งแรก
pause
