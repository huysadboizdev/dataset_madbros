$ErrorActionPreference = 'Continue'
$root = 'D:\OCR_Local\pdf-cleaner-tool\docs'
# JSON bi quet theo CAU TRUC: chi pattern duong dan tren GIA TRI (LaTeX '\frac'
# trong van ban tho JSON la escape, KHONG phai UNC) -> tranh duong tinh gia.
$re = '([A-Za-z]:[\\/]|/home/|/Users/)'
$reRaw = '([A-Za-z]:[\\/]|/home/|/Users/|\\\\)'
$exts = @('.md', '.txt', '.log', '.json', '.jsonl', '.csv', '.html', '.xml', '.yml', '.yaml', '.sha256', '.err')
$hits = @()
Get-ChildItem $root -Recurse -File | ForEach-Object {
    $f = $_
    if ($exts -notcontains $f.Extension.ToLower()) { return }
    if ($f.Extension.ToLower() -eq '.json') {
        try {
            $obj = Get-Content -Path $f.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
            $vals = @($obj.PSObject.Properties | Out-Null) # placeholder
        } catch { $obj = $null }
        $i = 0
        Get-Content -Path $f.FullName -Encoding UTF8 -ErrorAction SilentlyContinue | ForEach-Object {
            $i++
            if ($_ -match $re) {
                $rel = $f.FullName.Substring($root.Length + 1)
                $line = $_.Trim()
                if ($line.Length -gt 200) { $line = $line.Substring(0, 200) }
                $hits += [pscustomobject]@{ File = $rel; Line = $i; Text = $line }
            }
        }
        return
    }
    $i = 0
    Get-Content -Path $f.FullName -Encoding UTF8 -ErrorAction SilentlyContinue | ForEach-Object {
        $i++
        if ($_ -match $reRaw) {
            $rel = $f.FullName.Substring($root.Length + 1)
            $line = $_.Trim()
            if ($line.Length -gt 200) { $line = $line.Substring(0, 200) }
            $hits += [pscustomobject]@{ File = $rel; Line = $i; Text = $line }
        }
    }
}
$hits | ForEach-Object { "$($_.File) : line $($_.Line) : $($_.Text)" } |
    Out-File -FilePath 'D:\OCR_Local\pdf-cleaner-tool\_leak_scan_0915.txt' -Encoding utf8
"TONG SO DONG LEAK: $($hits.Count)"
$hits | Group-Object File | Sort-Object Count -Descending | ForEach-Object { "$($_.Count)`t$($_.Name)" }