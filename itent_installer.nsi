!define APP_NAME "itent"
!define APP_VERSION "1.0.0"
!define APP_PUBLISHER "itent"
!define APP_EXE "itent.exe"
!define INSTALL_DIR "$PROGRAMFILES64\itent"

Name "${APP_NAME}"
OutFile "itent_setup.exe"
InstallDir "${INSTALL_DIR}"
RequestExecutionLevel admin

!include "MUI2.nsh"
!include "nsDialogs.nsh"

; 快捷方式选项变量
Var Dialog
Var CheckboxDesktop
Var CheckboxStartMenu
Var CheckboxDesktop_State
Var CheckboxStartMenu_State

; MUI Settings
!insertmacro MUI_SETUI_IOBHANDLERS

; Pages
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY

; 快捷方式选项页面
Page custom ShortcutPage_Show ShortcutPage_Leave

!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

; Languages
!insertmacro MUI_LANGUAGE "SimpChinese"

Section "主程序" SecMain
    SectionIn RO
    SetOutPath "$INSTDIR"
    
    ; 复制文件
    File /r "dist\itent\*.*"
    
    ; 桌面快捷方式（根据用户选择）
    ${If} $CheckboxDesktop_State == ${BST_CHECKED}
        CreateShortcut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"
    ${EndIf}
    
    ; 开始菜单（根据用户选择）
    ${If} $CheckboxStartMenu_State == ${BST_CHECKED}
        CreateDirectory "$SMPROGRAMS\${APP_NAME}"
        CreateShortcut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"
        CreateShortcut "$SMPROGRAMS\${APP_NAME}\卸载 ${APP_NAME}.lnk" "$INSTDIR\uninstall.exe"
    ${EndIf}
    
    ; 注册卸载信息
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" \
        "DisplayName" "${APP_NAME}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" \
        "DisplayVersion" "${APP_VERSION}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" \
        "Publisher" "${APP_PUBLISHER}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" \
        "UninstallString" '"$INSTDIR\uninstall.exe"'
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" \
        "QuietUninstallString" '"$INSTDIR\uninstall.exe" /S'
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" \
        "InstallLocation" "$INSTDIR"
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" \
        "NoModify" 1
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" \
        "NoRepair" 1
    
    ; 创建卸载程序
    WriteUninstaller "$INSTDIR\uninstall.exe"

    ; 创建计划任务：开机以管理员身份静默启动 itent（不触发 UAC）
    ; 触发器：用户登录时；权限：最高权限（以 SYSTEM 身份运行，不触发 UAC）
    ExecWait 'SchTasks /Create /TN "itent" /TR "\"$INSTDIR\${APP_EXE}\"" /SC ONLOGON /RL HIGHEST /F'
SectionEnd

Section "Uninstall"
    ; 删除文件
    RMDir /r "$INSTDIR"
    
    ; 删除快捷方式
    Delete "$DESKTOP\${APP_NAME}.lnk"
    RMDir /r "$SMPROGRAMS\${APP_NAME}"
    
    ; 删除注册表
    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"

    ; 删除计划任务
    ExecWait 'SchTasks /Delete /TN "itent" /F'
SectionEnd

; ============================================================
; 快捷方式选项页面
; ============================================================
Function ShortcutPage_Show
    nsDialogs::Create 1018
    Pop $Dialog
    ${If} $Dialog == error
        Abort
    ${EndIf}

    ; 标题
    ${NSD_CreateLabel} 0 0 100% 20u "请选择要创建的快捷方式："

    ; 桌面快捷方式勾选框（默认选中）
    ${NSD_CreateCheckbox} 20u 30u 100% 12u "创建桌面快捷方式"
    Pop $CheckboxDesktop
    ${NSD_SetState} $CheckboxDesktop ${BST_CHECKED}

    ; 开始菜单勾选框（默认选中）
    ${NSD_CreateCheckbox} 20u 50u 100% 12u "创建开始菜单快捷方式"
    Pop $CheckboxStartMenu
    ${NSD_SetState} $CheckboxStartMenu ${BST_CHECKED}

    nsDialogs::Show
FunctionEnd

Function ShortcutPage_Leave
    ${NSD_GetState} $CheckboxDesktop $CheckboxDesktop_State
    ${NSD_GetState} $CheckboxStartMenu $CheckboxStartMenu_State
FunctionEnd
