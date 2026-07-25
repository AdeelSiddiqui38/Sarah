' Launches the Rencho wake-word listener completely silently (no console
' window). Used both for manual double-click starts and for Windows Startup.
Set objShell = CreateObject("WScript.Shell")
strPath = "C:\Users\asid3\Documents\BRAIN\Rencho"
objShell.CurrentDirectory = strPath
objShell.Run "pythonw.exe rencho_listener.py", 0, False
