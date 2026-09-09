' Unified Load Board - hidden launcher (no console window).
' Point Task Scheduler at this file. Double-click also works.
Option Explicit
Dim sh, fso, root, ps1
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
ps1 = root & "\scanner\silent_start.ps1"
Set sh = CreateObject("WScript.Shell")
sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & ps1 & """", 0, False
