' Abre a Central BP-MS (HTML5) sem janela preta de terminal.
' Clique duas vezes NESTE arquivo. Se o servico ja estiver rodando, so abre a pagina.

Set objFSO = CreateObject("Scripting.FileSystemObject")
strPasta = objFSO.GetParentFolderName(WScript.ScriptFullName)

Set objShell = CreateObject("WScript.Shell")
objShell.Run "cmd /c """ & strPasta & "\Iniciar_Central.bat""", 0, False
