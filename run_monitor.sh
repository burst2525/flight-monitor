#!/bin/bash
# 航空券定期監視スクリプト
cd "/Users/hiroki/Desktop/ツール/航空券通知" || exit 1
export PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$HOME/Library/Python/3.9/bin"
/usr/bin/python3 main.py >> flight_checker.log 2>&1
