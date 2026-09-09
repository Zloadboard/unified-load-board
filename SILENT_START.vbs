' Unified Load Board - hidden launcher (no console window).
' Starts scanner Chrome HIDDEN, serve_board.py, cdp_attach.py via silent_start.ps1.
' Point Task Scheduler at this file. Double-click also works.
' Sign into brokers from the board: http://localhost:8765/ → "Sign in brokers"
Option Explicit
Dim sh, fso, root, ps1
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
ps1 = root & "\scanner\silent_start.ps1"
Set sh = CreateObject("WScript.Shell")
sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & ps1 & """", 0, False
