' Sobe só o serviço da Central BP-MS, escondido e sem abrir o navegador.
' (A Inicialização do Windows e reinícios feitos pelo Claude usam este arquivo.)
Set objFSO = CreateObject("Scripting.FileSystemObject")
strPasta = objFSO.GetParentFolderName(WScript.ScriptFullName)
strPy = "C:\Users\SANKHERR\AppData\Local\Python\bin\pythonw.exe"
If Not objFSO.FileExists(strPy) Then strPy = "pythonw"
Set objShell = CreateObject("WScript.Shell")
objShell.CurrentDirectory = strPasta
objShell.Run """" & strPy & """ servico\servidor.py --sem-navegador", 0, False
