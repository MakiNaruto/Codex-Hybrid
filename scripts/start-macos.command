#!/bin/sh
cd -- "$(dirname -- "$0")" || exit 1
./codex-hybrid.sh install
result=$?
printf '\n按回车关闭窗口…'
read -r answer
exit "$result"
