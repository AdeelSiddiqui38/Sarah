' Silently serves the BRAIN folder over http://127.0.0.1:8765 (fixes Chrome
' re-asking for microphone permission every time, which happens on file://
' pages) and proxies OpenAI calls server-side (see rencho_server.py).
' Loopback-only — not reachable from other devices on your network.
Set objShell = CreateObject("WScript.Shell")
strPath = "C:\Users\asid3\Documents\BRAIN\Rencho"
objShell.CurrentDirectory = strPath
objShell.Run "pythonw.exe rencho_server.py", 0, False
