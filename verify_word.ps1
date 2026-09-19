# 把生成的 .docx 与模板逐项对照
$tpl = 'C:\Users\花火\.dsh\attachments\v1\files\7b\7b47fa822207c9ab22daf6ec0f716369317e0bd47d6fdfe3ddefda5b204f1ccb\设计文档模板-2026年.doc'
$out = 'D:\MAX_xiangmu\docs\智座-设计文档.docx'

$w = New-Object -ComObject Word.Application; $w.Visible = $false; $w.DisplayAlerts = 0
$t = $w.Documents.Open($tpl, [ref]$false, [ref]$true)
$d = $w.Documents.Open($out, [ref]$false, [ref]$true)
$d.Repaginate()

function GetHeaderInfo($doc) {
    $sec = $doc.Sections.Item(1)
    $h = $sec.Headers.Item(1)
    return @{
        text = ($h.Range.Text -replace "[\r\a]", "").Trim()
        imgs = $h.Range.InlineShapes.Count
        font = $h.Range.Font.NameFarEast
        size = $h.Range.Font.Size
        align = $h.Range.ParagraphFormat.Alignment
        rule = $h.Range.ParagraphFormat.Borders.Item(-3).LineStyle
        width = $h.Range.ParagraphFormat.Borders.Item(-3).LineWidth
    }
}
$ht = GetHeaderInfo $t
$hd = GetHeaderInfo $d

Write-Output "=================================================================="
Write-Output "  模板 vs 生成的 Word（逐项）"
Write-Output "=================================================================="
Write-Output ""
Write-Output "  【页眉】"
Write-Output ("    文字      模板: {0}" -f $ht.text)
Write-Output ("              成品: {0}" -f $hd.text)
Write-Output ("    logo图片  模板: {0}   成品: {1}   {2}" -f $ht.imgs, $hd.imgs, $(if($hd.imgs -ge $ht.imgs){'OK'}else{'★ 丢了'}))
Write-Output ("    字体      模板: {0} {1}pt   成品: {2} {3}pt   {4}" -f $ht.font,$ht.size,$hd.font,$hd.size,$(if($hd.font -eq $ht.font -and $hd.size -eq $ht.size){'OK'}else{'★ 不同'}))
Write-Output ("    下划线    模板: 线型{0}/{1}   成品: 线型{2}/{3}   {4}" -f $ht.rule,$ht.width,$hd.rule,$hd.width,$(if($hd.rule -eq $ht.rule){'OK'}else{'★ 不同'}))
Write-Output ""

Write-Output "  【页面设置】"
$pt = $t.Sections.Item(1).PageSetup
$pd = $d.Sections.Item(1).PageSetup
Write-Output ("    上{0:N0} 下{1:N0} 左{2:N0} 右{3:N0} pt   成品: 上{4:N0} 下{5:N0} 左{6:N0} 右{7:N0}   {8}" -f `
    $pt.TopMargin,$pt.BottomMargin,$pt.LeftMargin,$pt.RightMargin,`
    $pd.TopMargin,$pd.BottomMargin,$pd.LeftMargin,$pd.RightMargin,`
    $(if([math]::Abs($pd.LeftMargin-$pt.LeftMargin) -lt 2){'OK'}else{'★ 不同'}))
Write-Output ""

Write-Output "  【封面逐段（成品）】"
$n=0
foreach ($p in $d.Paragraphs) {
    $s = ($p.Range.Text -replace "[\r\a]","").Trim()
    if (-not $s) { continue }
    $n++; if ($n -gt 11) { break }
    Write-Output ("    {0,-16} {1,4}pt  {2}" -f $p.Range.Font.NameFarEast, $p.Range.Font.Size, $s.Substring(0,[Math]::Min(40,$s.Length)))
}
Write-Output ""

Write-Output "  【内容与结构】"
Write-Output ("    页数 {0}   字数 {1}   表格 {2}   图片 {3}" -f `
    $d.ComputeStatistics(2), $d.ComputeStatistics(0), $d.Tables.Count, $d.InlineShapes.Count)
$txt = $d.Content.Text
foreach ($k in @('【项目名称】','zhinengzuo.site','核心代码与解析','第三方开源','SuperAdmin@123','泄漏式最小值','原创')) {
    Write-Output ("    {0,-18} {1}" -f $k, $(if($txt -like "*$k*"){'有'}else{'★ 无'}))
}
Write-Output ""
Write-Output "  【目录域】"
$nf = 0
foreach ($f in $d.Fields) { if ($f.Type -eq 13) { $nf++; Write-Output ("    TOC 域: " + $f.Code.Text) } }
if ($nf -eq 0) { Write-Output "    ★ 没有目录域" }

$d.Close([ref]$false); $t.Close([ref]$false); $w.Quit()
