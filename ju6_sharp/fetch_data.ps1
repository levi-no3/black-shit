# Re-fetch raw training data on a new machine (saves carrying 160MB in the zip).
$tmp = "$env:TEMP\ju6data"
$dst = Join-Path $PSScriptRoot "data"
New-Item -ItemType Directory -Path $tmp -Force | Out-Null
New-Item -ItemType Directory -Path $dst -Force | Out-Null
Invoke-WebRequest -Uri "https://dl.fbaipublicfiles.com/parlai/empatheticdialogues/empatheticdialogues.tar.gz" `
  -OutFile "$tmp\empathetic.tar.gz"
tar -xzf "$tmp\empathetic.tar.gz" -C $dst
Invoke-WebRequest -Uri "http://parl.ai/downloads/personachat/personachat.tgz" `
  -OutFile "$tmp\personachat.tgz"
tar -xzf "$tmp\personachat.tgz" -C $dst "personachat/train_self_original.txt"
Write-Output "data ready"
