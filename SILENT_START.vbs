' Unified Load Board - hidden launcher (no console window).
' Default: serve_board.py only (extension mode). CDP Chrome is off unless ULB_ENABLE_CDP=1.
' Point Task Scheduler at this file. Double-click also works.
' Install extension once (see EXTENSION.md / board Download section), sign into brokers in normal Chrome.
Option Explicit
Dim sh, fso, root, ps1
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
ps1 = root & "\scanner\silent_start.ps1"
Set sh = CreateObject("WScript.Shell")
sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & ps1 & """", 0, False
