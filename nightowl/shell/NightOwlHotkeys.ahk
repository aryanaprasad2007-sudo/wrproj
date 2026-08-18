#Requires AutoHotkey v2.0
; NightOwl global hotkeys.
;
; Everything routes through nohidden.vbs so nothing flashes a console window.
; Ctrl+Alt+<key> avoids collisions with games (which grab plain keys) and with
; Windows' own Win+<key> shortcuts.
;
;   Ctrl+Alt+W   work mode          Ctrl+Alt+G   game mode
;   Ctrl+Alt+A   anime mode         Ctrl+Alt+D   wind-down
;   Ctrl+Alt+0   reset to defaults  Ctrl+Alt+H   open the Hub
;   Ctrl+Alt+[   warmer screen      Ctrl+Alt+]   cooler screen
;   Ctrl+Alt+\   clear warmth bias  Ctrl+Alt+B   take a break now
;   Ctrl+Alt+P   pause/resume hotkeys

#SingleInstance Force
SetWorkingDir A_ScriptDir

global ROOT := "C:\Users\aware\OneDrive\Desktop\wrproj\nightowl"
global VBS  := ROOT "\bin\nohidden.vbs"

No(args) {
    Run('wscript.exe "' VBS '" ' args, , "Hide")
}

Flash(text) {
    ; Tiny transient confirmation so a hotkey never feels like it did nothing.
    g := Gui("+AlwaysOnTop -Caption +ToolWindow +E0x20")   ; E0x20 = click-through
    g.BackColor := "2A1E36"
    g.SetFont("s11 cFFEAF7", "Segoe UI")
    g.Add("Text", "x20 y13 w250 Center", text)
    g.Show("NoActivate AutoSize y90")
    WinSetTransparent(235, g.Hwnd)
    SetTimer(() => g.Destroy(), -1100)
}

Mode(name, label) {
    No("mode " name)
    Flash(label)
}

Do(verb, label) {
    No(verb)
    Flash(label)
}

^!w:: Mode("work", "Work mode")
^!g:: Mode("game", "Game mode")
^!a:: Mode("anime", "Anime mode")
^!d:: Mode("winddown", "Wind-down")
^!0:: Mode("reset", "Reset to defaults")

^!h:: Do("hub", "Opening the Hub")
^!b:: Do("break eye", "Break")
^![:: Do("warmer", "Warmer")
^!]:: Do("cooler", "Cooler")
^!\:: Do("warmthreset", "Warmth on auto")

; SuspendExempt keeps this one live while suspended, otherwise there would be
; no way to switch the hotkeys back on.
#SuspendExempt
^!p:: TogglePause()
#SuspendExempt False

TogglePause() {
    Suspend(-1)
    if (A_IsSuspended)
        Flash("Hotkeys paused")
    else
        Flash("Hotkeys active")
}
