Unicode true
!include "MUI2.nsh"
!include "x64.nsh"
!include "WinVer.nsh"
Name "Syntra Slash"
OutFile "${OUTFILE}"
InstallDir "$LOCALAPPDATA\Programs\Syntra Slash"
InstallDirRegKey HKCU "Software\SyntraSlash" "InstallPath"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 64
BrandingText "Syntra Slash · Created by Rithvikyada"
Icon "${APPICON}"
UninstallIcon "${APPICON}"
VIProductVersion "1.1.0.0"
VIAddVersionKey "ProductName" "Syntra Slash"
VIAddVersionKey "FileDescription" "Syntra Slash Setup"
VIAddVersionKey "FileVersion" "1.1.0"
VIAddVersionKey "ProductVersion" "1.1.0"
VIAddVersionKey "CompanyName" "Rithvikyada"
VIAddVersionKey "LegalCopyright" "Rithvikyada"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TEXT "Install Syntra Slash on your computer.$\r$\n$\r$\nAfter installation, open Syntra to download Syntra Max Aperion (8.99 GB) from inside the app. Downloads can be paused and resumed.$\r$\n$\r$\nThe model runs locally on your computer.$\r$\n$\r$\nWindows 10/11 x64, Microsoft Edge WebView2, 10 GB free for the model, and 24 GB RAM recommended."
!define MUI_FINISHPAGE_RUN "$INSTDIR\Syntra.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Open Syntra Slash to install the AI model"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"
Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "Syntra Slash requires 64-bit Windows."
    Abort
  ${EndIf}
  ${IfNot} ${AtLeastWin10}
    MessageBox MB_ICONSTOP "Syntra Slash requires Windows 10 or later."
    Abort
  ${EndIf}
FunctionEnd
Section "Syntra Slash" SEC_MAIN
  SetShellVarContext current
  SetOutPath "$INSTDIR"
  File /r "${STAGE}\*.*"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateDirectory "$SMPROGRAMS\Syntra Slash"
  CreateShortcut "$SMPROGRAMS\Syntra Slash\Syntra Slash.lnk" "$INSTDIR\Syntra.exe"
  CreateShortcut "$DESKTOP\Syntra Slash.lnk" "$INSTDIR\Syntra.exe"
  WriteRegStr HKCU "Software\SyntraSlash" "InstallPath" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\SyntraSlash" "DisplayName" "Syntra Slash"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\SyntraSlash" "DisplayVersion" "1.1.0"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\SyntraSlash" "Publisher" "Rithvikyada"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\SyntraSlash" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\SyntraSlash" "DisplayIcon" "$INSTDIR\Syntra.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\SyntraSlash" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\SyntraSlash" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\SyntraSlash" "NoRepair" 1
SectionEnd
Section "Uninstall"
  SetShellVarContext current
  !include "${REMOVEFILES}"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  Delete "$DESKTOP\Syntra Slash.lnk"
  Delete "$SMPROGRAMS\Syntra Slash\Syntra Slash.lnk"
  RMDir "$SMPROGRAMS\Syntra Slash"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\SyntraSlash"
  DeleteRegKey HKCU "Software\SyntraSlash"
  ; Personal models and conversations in LocalAppData/SyntraSlashes are preserved.
SectionEnd

