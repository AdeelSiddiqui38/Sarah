' Sarah launcher (Windows).
' Starts the local server if it isn't already running, then opens the avatar.
' Double-click this file, or put a shortcut to it on your Desktop.
' Runs silently - no console window.

Set fso     = CreateObject("Scripting.FileSystemObject")
Set shell   = CreateObject("WScript.Shell")
scriptDir   = fso.GetParentFolderName(WScript.ScriptFullName)
avatarURL   = "http://127.0.0.1:8765/"

' --- Is sarah_server.py already running? ---
alreadyRunning = False
Set wmi = GetObject("winmgmts:\\.\root\cimv2")
Set procs = wmi.ExecQuery("SELECT CommandLine FROM Win32_Process WHERE Name='pythonw.exe' OR Name='python.exe'")
For Each p In procs
  If Not IsNull(p.CommandLine) Then
    If InStr(LCase(p.CommandLine), "sarah_server.py") > 0 Then alreadyRunning = True
  End If
Next

' --- Start it if needed ---
If Not alreadyRunning Then
  shell.CurrentDirectory = scriptDir
  shell.Run "pythonw.exe sarah_server.py", 0, False
  WScript.Sleep 2500
End If

' --- Open the avatar ---
shell.Run avatarURL, 1, False
