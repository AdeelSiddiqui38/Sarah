' Starts the Sarah agent backend (sarah_agent.py) with no console window.
' This is the brain — the avatar page is only the face, and falls back to the
' old in-page brain if this isn't running.
Set shell = CreateObject("WScript.Shell")
Set fso   = CreateObject("Scripting.FileSystemObject")
shell.CurrentDirectory = fso.GetParentFolderName(WScript.ScriptFullName)
shell.Run "pythonw.exe sarah_agent.py", 0, False
