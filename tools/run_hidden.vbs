' Запускает autostart.bat без окна. Ярлык на этот файл лежит в автозагрузке Windows.
Set sh = CreateObject("WScript.Shell")
dir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
sh.Run """" & dir & "\autostart.bat""", 0, False
