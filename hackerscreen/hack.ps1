$Host.UI.RawUI.WindowTitle = "SYSTEM::" + (Get-Random -Maximum 9999)
$esc = [char]27
$purple = "$esc[38;5;135m"
$purpleBright = "$esc[38;5;171m"
$reset = "$esc[0m"

try {
    $Host.UI.RawUI.BackgroundColor = "Black"
    $Host.UI.RawUI.ForegroundColor = "Magenta"
    Clear-Host
} catch {}

$hexChars = "0123456789ABCDEF"
$words = @("ACCESS","DECRYPT","BYPASS","INJECT","ROOTKIT","PAYLOAD","EXPLOIT","FIREWALL","KERNEL","HANDSHAKE","TUNNEL","SPOOF","TRACE","OVERRIDE","PROXY","SHELL","TOKEN","CIPHER","NODE","PACKET")

function Get-RandomHex($len) {
    $s = ""
    for ($i = 0; $i -lt $len; $i++) { $s += $hexChars[(Get-Random -Maximum 16)] }
    return $s
}

function Get-RandomBinary($len) {
    $s = ""
    for ($i = 0; $i -lt $len; $i++) { $s += (Get-Random -Maximum 2) }
    return $s
}

while ($true) {
    $r = Get-Random -Maximum 5
    $color = if ((Get-Random -Maximum 3) -eq 0) { $purpleBright } else { $purple }

    switch ($r) {
        0 { Write-Host "$color[0x$(Get-RandomHex 8)] $(Get-RandomBinary 32)$reset" }
        1 { Write-Host "$color> $($words[(Get-Random -Maximum $words.Count)])_MODULE :: $(Get-RandomHex 12) :: STATUS_OK$reset" }
        2 { Write-Host "$color$(Get-RandomHex 4)-$(Get-RandomHex 4)-$(Get-RandomHex 4)-$(Get-RandomHex 4)  addr=0x$(Get-RandomHex 6)$reset" }
        3 { Write-Host "$color$('#' * (Get-Random -Minimum 5 -Maximum 40)) $(Get-Random -Minimum 0 -Maximum 100)%$reset" }
        4 { Write-Host "$color$(Get-RandomBinary 48)$reset" }
    }

    Start-Sleep -Milliseconds (Get-Random -Minimum 10 -Maximum 60)
}
