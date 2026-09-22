# 教育技术期刊雷达 - Windows PowerShell 5.1 / WPF
$ErrorActionPreference = 'Stop'
trap {
    try {
        $folder = if ($script:storage -and (Test-Path -LiteralPath $script:storage)) { $script:storage } else { $env:TEMP }
        $message = [string]$_.Exception.Message
        [System.IO.File]::WriteAllText((Join-Path $folder 'EdTechRadar-error.txt'), $message, [System.Text.UTF8Encoding]::new($false))
        Add-Type -AssemblyName PresentationFramework -ErrorAction SilentlyContinue
        [void][System.Windows.MessageBox]::Show('期刊雷达无法启动：' + $message, '教育技术期刊雷达')
    } catch { }
    break
}
Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase, System.Net.Http
Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
public class RadarPaper : INotifyPropertyChanged {
    public string Title { get; set; }
    public string Meta { get; set; }
    public string Url { get; set; }
    public string Key { get; set; }
    public string CacheKey { get; set; }
    public string SortDate { get; set; }
    public bool Required { get; set; }
    public bool Chinese { get; set; }
    private string translation = "";
    public string Translation {
        get { return translation; }
        set { translation = value; var h = PropertyChanged; if (h != null) h(this, new PropertyChangedEventArgs("Translation")); }
    }
    public event PropertyChangedEventHandler PropertyChanged;
}
'@

$script:storage = Join-Path $env:APPDATA 'EdTechRadar'
[void][System.IO.Directory]::CreateDirectory($script:storage)
$script:feedsPath = Join-Path $script:storage 'feeds.json'
$script:configPath = Join-Path $script:storage 'config.json'
$script:keyPath = Join-Path $script:storage 'api-key.dat'
$script:cachePath = Join-Path $script:storage 'translations.json'
$script:networkPath = Join-Path $script:storage 'network.json'
$script:sourcePath = Join-Path $script:storage 'source-status.json'
$script:defaultsPath = Join-Path $PSScriptRoot 'feeds.default.json'

function Read-JsonFile($path, $fallback) {
    if (-not (Test-Path -LiteralPath $path)) { return $fallback }
    try { return (Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json) }
    catch { return $fallback }
}
function Save-JsonFile($path, $value) {
    $json = ConvertTo-Json -InputObject $value -Depth 8
    [System.IO.File]::WriteAllText($path, $json, [System.Text.UTF8Encoding]::new($false))
}
function Read-ApiKey {
    if (-not (Test-Path -LiteralPath $script:keyPath)) { return '' }
    try {
        $secure = Get-Content -LiteralPath $script:keyPath -Raw | ConvertTo-SecureString
        $credential = New-Object System.Management.Automation.PSCredential('api', $secure)
        return $credential.GetNetworkCredential().Password
    } catch { return '' }
}
function Save-ApiKey($key) {
    if ([string]::IsNullOrWhiteSpace($key)) {
        Remove-Item -LiteralPath $script:keyPath -ErrorAction SilentlyContinue
    } else {
        $secure = ConvertTo-SecureString $key -AsPlainText -Force
        $encrypted = ConvertFrom-SecureString $secure
        [System.IO.File]::WriteAllText($script:keyPath, $encrypted, [System.Text.UTF8Encoding]::new($false))
    }
}
function Test-Endpoint($value) {
    $uri = $null
    if (-not [System.Uri]::TryCreate($value, [System.UriKind]::Absolute, [ref]$uri)) { return $false }
    if ($uri.Scheme -eq 'https') { return $true }
    return ($uri.Scheme -eq 'http' -and $uri.Host -in @('localhost', '127.0.0.1', '::1'))
}
function Get-CacheKey($title) {
    $raw = $script:llm.Endpoint + '|' + $script:llm.Model + '|' + $title
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { return -join ($sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($raw)) | ForEach-Object { $_.ToString('x2') }) }
    finally { $sha.Dispose() }
}

$script:feeds = @(Read-JsonFile $script:feedsPath (Read-JsonFile $script:defaultsPath @()))
$script:llm = Read-JsonFile $script:configPath ([pscustomobject]@{ Enabled = $false; Endpoint = ''; Model = '' })
$script:network = Read-JsonFile $script:networkPath ([pscustomobject]@{ Proxy = '' })
$script:lastFeedResults = @(Read-JsonFile $script:sourcePath @())
$script:cache = @{}
$loadedCache = Read-JsonFile $script:cachePath $null
if ($null -ne $loadedCache) {
    foreach ($property in $loadedCache.PSObject.Properties) { $script:cache[$property.Name] = [string]$property.Value }
}
$script:allPapers = @()
$script:visiblePapers = @()
$script:refreshJob = $null
$script:refreshAgain = $false
$script:lastRefresh = [datetime]::MinValue
$script:translationQueue = New-Object System.Collections.Queue
$script:queuedKeys = @{}
$script:translationJobs = @{}

[xml]$mainXaml = @'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" Title="教育技术期刊雷达" Width="420" Height="650" MinWidth="360" MinHeight="470" WindowStartupLocation="CenterScreen" Topmost="True" Background="#F5F8FB" FontFamily="Microsoft YaHei UI">
  <Grid Margin="18">
    <Grid.RowDefinitions><RowDefinition Height="Auto"/><RowDefinition Height="Auto"/><RowDefinition Height="Auto"/><RowDefinition Height="Auto"/><RowDefinition Height="*"/><RowDefinition Height="Auto"/></Grid.RowDefinitions>
    <Grid Grid.Row="0"><Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="Auto"/><ColumnDefinition Width="Auto"/><ColumnDefinition Width="Auto"/></Grid.ColumnDefinitions>
      <StackPanel><TextBlock Text="教育技术期刊雷达" FontSize="21" FontWeight="Bold"/><TextBlock x:Name="SourceCount" FontSize="11" Foreground="#687782" Margin="0,3,0,0"/></StackPanel>
      <Button x:Name="SourceButton" Grid.Column="1" Content="来源" Padding="10,5" Margin="0,0,7,0"/>
      <Button x:Name="SettingsButton" Grid.Column="2" Content="设置" Padding="10,5" Margin="0,0,7,0"/>
      <Button x:Name="RefreshButton" Grid.Column="3" Content="刷新" Padding="10,5"/>
    </Grid>
    <TextBlock x:Name="StatusText" Grid.Row="1" Foreground="#687782" FontSize="11" Margin="0,12,0,11" TextTrimming="CharacterEllipsis"/>
    <Grid Grid.Row="2"><Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="10"/><ColumnDefinition Width="*"/></Grid.ColumnDefinitions>
      <ComboBox x:Name="RequirementFilter" SelectedIndex="0" Padding="4"><ComboBoxItem Content="全部期刊"/><ComboBoxItem Content="必读"/><ComboBoxItem Content="选读"/></ComboBox>
      <ComboBox x:Name="LanguageFilter" Grid.Column="2" SelectedIndex="0" Padding="4"><ComboBoxItem Content="中英"/><ComboBoxItem Content="中文"/><ComboBoxItem Content="英文"/></ComboBox>
    </Grid>
    <Grid Grid.Row="3" Margin="0,16,0,7"><Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="Auto"/></Grid.ColumnDefinitions><TextBlock Text="近期论文" FontWeight="SemiBold" FontSize="13"/><TextBlock x:Name="PaperCount" Grid.Column="1" Foreground="#687782" FontSize="11"/></Grid>
    <ListBox x:Name="PaperList" Grid.Row="4" BorderThickness="0" Background="Transparent" ScrollViewer.HorizontalScrollBarVisibility="Disabled" ScrollViewer.CanContentScroll="True" VirtualizingStackPanel.IsVirtualizing="True" VirtualizingStackPanel.VirtualizationMode="Recycling">
      <ListBox.ItemTemplate><DataTemplate><Border BorderBrush="#DCE4EA" BorderThickness="0,0,0,1" Padding="5,10"><StackPanel>
        <TextBlock Text="{Binding Title}" TextWrapping="Wrap" FontSize="13" FontWeight="SemiBold" Foreground="#202D36"/>
        <TextBlock Text="{Binding Translation}" TextWrapping="Wrap" FontSize="12" Foreground="#235D83" Margin="0,4,0,0"/>
        <TextBlock Text="{Binding Meta}" FontSize="10" Foreground="#74838E" Margin="0,5,0,0" TextTrimming="CharacterEllipsis"/>
      </StackPanel></Border></DataTemplate></ListBox.ItemTemplate>
    </ListBox>
    <TextBlock Grid.Row="5" Text="每 30 分钟自动刷新 · 双击论文打开原文" FontSize="10" Foreground="#85939D" Margin="0,10,0,0"/>
  </Grid>
</Window>
'@
$reader = New-Object System.Xml.XmlNodeReader($mainXaml)
$script:window = [System.Windows.Markup.XamlReader]::Load($reader)
$script:SourceCount = $script:window.FindName('SourceCount')
$script:StatusText = $script:window.FindName('StatusText')
$script:RefreshButton = $script:window.FindName('RefreshButton')
$script:SettingsButton = $script:window.FindName('SettingsButton')
$script:SourceButton = $script:window.FindName('SourceButton')
$script:RequirementFilter = $script:window.FindName('RequirementFilter')
$script:LanguageFilter = $script:window.FindName('LanguageFilter')
$script:PaperList = $script:window.FindName('PaperList')
$script:PaperCount = $script:window.FindName('PaperCount')

function Update-SourceCount { $script:SourceCount.Text = '培养方案 · ' + $script:feeds.Count + ' 本 RSS' }
function Update-PaperList {
    $requiredFilter = $script:RequirementFilter.SelectedIndex
    $languageFilter = $script:LanguageFilter.SelectedIndex
    $script:visiblePapers = @($script:allPapers | Where-Object {
        ($requiredFilter -eq 0 -or ($requiredFilter -eq 1 -and $_.Required) -or ($requiredFilter -eq 2 -and -not $_.Required)) -and
        ($languageFilter -eq 0 -or ($languageFilter -eq 1 -and $_.Chinese) -or ($languageFilter -eq 2 -and -not $_.Chinese))
    })
    $script:PaperList.ItemsSource = $script:visiblePapers
    $script:PaperCount.Text = $script:visiblePapers.Count.ToString() + ' 条'
}
function Start-Refresh {
    if ($null -ne $script:refreshJob) { $script:refreshAgain = $true; return }
    if ($script:feeds.Count -eq 0) { $script:allPapers = @(); Update-PaperList; $script:StatusText.Text = '请到设置中添加 RSS 地址。'; return }
    $script:StatusText.Text = '正在更新 ' + $script:feeds.Count + ' 本期刊…'
    $script:RefreshButton.IsEnabled = $false
    $feedJson = ConvertTo-Json -InputObject @($script:feeds) -Depth 5 -Compress
    $refreshArguments = @($feedJson, [string]$script:network.Proxy)
    $script:refreshJob = Start-Job -ArgumentList $refreshArguments -ScriptBlock {
        param($json, $proxyAddress)
        Add-Type -AssemblyName System.Net.Http
        [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
        # Windows PowerShell 5.1 already returns a JSON array as an array here.
        # Wrapping it in @() creates one nested item, so the whole feed list is
        # fetched as one URL and inherits the first feed's Chinese flag.
        $feeds = ConvertFrom-Json -InputObject $json
        $handler = [System.Net.Http.HttpClientHandler]::new()
        $handler.AutomaticDecompression = [System.Net.DecompressionMethods]::GZip -bor [System.Net.DecompressionMethods]::Deflate
        $client = [System.Net.Http.HttpClient]::new($handler)
        $client.Timeout = [timespan]::FromSeconds(24)
        $client.DefaultRequestHeaders.UserAgent.ParseAdd('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36')
        $client.DefaultRequestHeaders.Accept.ParseAdd('application/rss+xml, application/atom+xml, application/xml, text/xml, */*')
        $foreignClient = $client
        if (-not [string]::IsNullOrWhiteSpace($proxyAddress)) {
            $foreignHandler = [System.Net.Http.HttpClientHandler]::new()
            $foreignHandler.AutomaticDecompression = [System.Net.DecompressionMethods]::GZip -bor [System.Net.DecompressionMethods]::Deflate
            $foreignHandler.Proxy = [System.Net.WebProxy]::new($proxyAddress)
            $foreignHandler.UseProxy = $true
            $foreignClient = [System.Net.Http.HttpClient]::new($foreignHandler)
            $foreignClient.Timeout = [timespan]::FromSeconds(24)
            $foreignClient.DefaultRequestHeaders.UserAgent.ParseAdd('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36')
            $foreignClient.DefaultRequestHeaders.Accept.ParseAdd('application/rss+xml, application/atom+xml, application/xml, text/xml, */*')
        }
        $pending = @()
        foreach ($feed in $feeds) {
            $currentClient = if ($feed.Chinese) { $client } else { $foreignClient }
            try { $pending += [pscustomobject]@{ Feed = $feed; Task = $currentClient.GetStringAsync([string]$feed.Url) } }
            catch { $pending += [pscustomobject]@{ Feed = $feed; Task = $null } }
        }
        $papers = New-Object System.Collections.ArrayList
        $sources = New-Object System.Collections.ArrayList
        $ok = 0; $bad = 0
        foreach ($entry in $pending) {
            try {
                if ($null -eq $entry.Task) { throw '请求未启动' }
                try { $raw = $entry.Task.GetAwaiter().GetResult() }
                catch {
                    if ([string]$_.Exception.Message -notmatch '40[0369]|Forbidden|Not Acceptable') { throw }
                    $parameters = @{ Uri = [string]$entry.Feed.Url; UseBasicParsing = $true; TimeoutSec = 12; UserAgent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36' }
                    if (-not $entry.Feed.Chinese -and -not [string]::IsNullOrWhiteSpace($proxyAddress)) { $parameters.Proxy = $proxyAddress }
                    $raw = (Invoke-WebRequest @parameters).Content
                }
                [xml]$xml = $raw
                $nodes = $xml.SelectNodes("//*[local-name()='item' or local-name()='entry']")
                if ($null -eq $nodes -or $nodes.Count -eq 0) { throw '没有 RSS 条目' }
                $count = 0
                foreach ($node in $nodes) {
                    $title = ''; $link = ''; $dateText = ''
                    foreach ($child in $node.ChildNodes) {
                        switch ($child.LocalName.ToLowerInvariant()) {
                            'title' { $title = $child.InnerText.Trim() }
                            'link' {
                                if ($child.Attributes -and $child.Attributes['href']) { $link = $child.Attributes['href'].Value }
                                elseif ([string]::IsNullOrWhiteSpace($link)) { $link = $child.InnerText.Trim() }
                            }
                            { $_ -in @('pubdate','date','published','updated') } { if ([string]::IsNullOrWhiteSpace($dateText)) { $dateText = $child.InnerText.Trim() } }
                        }
                    }
                    $uri = $null
                    if ([string]::IsNullOrWhiteSpace($title) -or -not [uri]::TryCreate($link, [uriKind]::Absolute, [ref]$uri) -or $uri.Scheme -notin @('http','https')) { continue }
                    $when = [DateTimeOffset]::MinValue
                    [void][DateTimeOffset]::TryParse($dateText, [ref]$when)
                    [void]$papers.Add([pscustomobject]@{ Title = $title; Url = $link; Journal = [string]$entry.Feed.Name; Required = [bool]$entry.Feed.Required; Chinese = [bool]$entry.Feed.Chinese; SortDate = $when.UtcDateTime.ToString('o'); DateLabel = $(if ($when -eq [DateTimeOffset]::MinValue) { '' } else { $when.ToString('MM/dd') }) })
                    $count++
                }
                if ($count -eq 0) { throw 'RSS 中没有可用的论文标题和链接' }
                $ok++
                [void]$sources.Add([pscustomobject]@{ Name = [string]$entry.Feed.Name; Chinese = [bool]$entry.Feed.Chinese; Ok = $true; Count = $count; Error = '' })
            } catch {
                $bad++
                [void]$sources.Add([pscustomobject]@{ Name = [string]$entry.Feed.Name; Chinese = [bool]$entry.Feed.Chinese; Ok = $false; Count = 0; Error = [string]$_.Exception.Message })
            }
        }
        $client.Dispose()
        if ($foreignClient -ne $client) { $foreignClient.Dispose() }
        [pscustomobject]@{ Papers = @($papers.ToArray()); Sources = @($sources.ToArray()); Ok = $ok; Bad = $bad }
    }
}
function Finish-Refresh {
    $job = $script:refreshJob
    if ($null -eq $job -or $job.State -notin @('Completed','Failed','Stopped')) { return }
    $result = @(Receive-Job -Job $job -ErrorAction SilentlyContinue | Select-Object -Last 1)
    Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
    $script:refreshJob = $null
    $script:RefreshButton.IsEnabled = $true
    if ($result.Count -eq 0 -or $null -eq $result[0]) { $script:StatusText.Text = 'RSS 更新失败，请检查网络后重试。'; return }
    $data = $result[0]
    $script:lastFeedResults = @($data.Sources)
    Save-JsonFile $script:sourcePath $script:lastFeedResults
    $seen = @{}
    $items = New-Object System.Collections.ArrayList
    foreach ($raw in @($data.Papers | Sort-Object SortDate -Descending)) {
        if ($null -eq $raw) { continue }
        $key = [string]$raw.Journal + '|' + [string]$raw.Url
        if ($seen.ContainsKey($key)) { continue }
        $seen[$key] = $true
        $paper = [RadarPaper]::new()
        $paper.Title = [string]$raw.Title
        $paper.Url = [string]$raw.Url
        $paper.Key = $key
        $paper.SortDate = [string]$raw.SortDate
        $paper.Required = [bool]$raw.Required
        $paper.Chinese = [bool]$raw.Chinese
        $paper.Meta = $(if ($paper.Required) { '必读' } else { '选读' }) + ' · ' + [string]$raw.Journal + '  ' + [string]$raw.DateLabel
        $paper.CacheKey = Get-CacheKey $paper.Title
        if ($script:llm.Enabled -and $script:cache.ContainsKey($paper.CacheKey)) { $paper.Translation = $script:cache[$paper.CacheKey] }
        [void]$items.Add($paper)
    }
    $script:allPapers = @($items.ToArray())
    Update-PaperList
    $script:lastRefresh = Get-Date
    $englishOk = @($script:lastFeedResults | Where-Object { -not $_.Chinese -and $_.Ok }).Count
    $script:StatusText.Text = '已更新 ' + $data.Ok + ' 本（英文 ' + $englishOk + ' 本）' + $(if ($data.Bad -gt 0) { '，' + $data.Bad + ' 本暂不可用' } else { '' }) + ' · ' + $script:lastRefresh.ToString('HH:mm')
    if ($script:refreshAgain) { $script:refreshAgain = $false; Start-Refresh }
}
function Stop-Translations {
    foreach ($state in @($script:translationJobs.Values)) { Stop-Job -Job $state.Job -ErrorAction SilentlyContinue; Remove-Job -Job $state.Job -Force -ErrorAction SilentlyContinue }
    $script:translationJobs.Clear(); $script:queuedKeys.Clear(); $script:translationQueue.Clear()
}
function Queue-VisibleTranslations {
    if (-not $script:llm.Enabled -or -not (Test-Endpoint ([string]$script:llm.Endpoint)) -or [string]::IsNullOrWhiteSpace([string]$script:llm.Model)) { return }
    for ($i = 0; $i -lt $script:visiblePapers.Count; $i++) {
        if ($null -eq $script:PaperList.ItemContainerGenerator.ContainerFromIndex($i)) { continue }
        $paper = $script:visiblePapers[$i]
        if ($paper.Chinese -or $script:cache.ContainsKey($paper.CacheKey) -or $script:queuedKeys.ContainsKey($paper.Key) -or $script:translationJobs.ContainsKey($paper.Key) -or -not [string]::IsNullOrWhiteSpace($paper.Translation)) { continue }
        $script:queuedKeys[$paper.Key] = $true
        $script:translationQueue.Enqueue($paper)
    }
}
function Start-TranslationJobs {
    if (-not $script:llm.Enabled) { return }
    while ($script:translationJobs.Count -lt 2 -and $script:translationQueue.Count -gt 0) {
        $paper = $script:translationQueue.Dequeue()
        $script:queuedKeys.Remove($paper.Key)
        $key = Read-ApiKey
        $translationArguments = @([string]$paper.Title, [string]$script:llm.Endpoint, [string]$script:llm.Model, [string]$key)
        $job = Start-Job -ArgumentList $translationArguments -ScriptBlock {
            param($title, $endpoint, $model, $apiKey)
            [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
            $bodyArgs = @{ model = $model; temperature = 0; max_tokens = 120; messages = @(@{ role = 'system'; content = '将英文教育技术学术论文标题准确翻译成简体中文。只返回中文译题，不加引号、注释或原文。' }, @{ role = 'user'; content = $title }) }
            if (([uri]$endpoint).Host -eq 'api.deepseek.com') { $bodyArgs.thinking = @{ type = 'disabled' }; $bodyArgs.max_tokens = 256 }
            $body = $bodyArgs | ConvertTo-Json -Depth 6
            $headers = @{}
            if (-not [string]::IsNullOrWhiteSpace($apiKey)) { $headers['Authorization'] = 'Bearer ' + $apiKey }
            try {
                $reply = Invoke-RestMethod -Uri $endpoint -Method Post -Body ([System.Text.Encoding]::UTF8.GetBytes($body)) -ContentType 'application/json; charset=utf-8' -Headers $headers -TimeoutSec 30
                $translated = [string]$reply.choices[0].message.content
                if ([string]::IsNullOrWhiteSpace($translated)) { throw '响应中没有译题' }
                [pscustomobject]@{ Translation = $translated.Trim(); Error = '' }
            } catch { [pscustomobject]@{ Translation = ''; Error = [string]$_.Exception.Message } }
        }
        $script:translationJobs[$paper.Key] = [pscustomobject]@{ Job = $job; Paper = $paper; Endpoint = [string]$script:llm.Endpoint; Model = [string]$script:llm.Model }
    }
}
function Finish-TranslationJobs {
    foreach ($key in @($script:translationJobs.Keys)) {
        $state = $script:translationJobs[$key]
        if ($state.Job.State -notin @('Completed','Failed','Stopped')) { continue }
        $reply = @(Receive-Job -Job $state.Job -ErrorAction SilentlyContinue | Select-Object -Last 1)
        Remove-Job -Job $state.Job -Force -ErrorAction SilentlyContinue
        $script:translationJobs.Remove($key)
        if ($state.Endpoint -ne [string]$script:llm.Endpoint -or $state.Model -ne [string]$script:llm.Model -or -not $script:llm.Enabled) { continue }
        if ($reply.Count -gt 0 -and -not [string]::IsNullOrWhiteSpace([string]$reply[0].Translation)) {
            $state.Paper.Translation = [string]$reply[0].Translation
            $script:cache[$state.Paper.CacheKey] = $state.Paper.Translation
            Save-JsonFile $script:cachePath $script:cache
        } else { $state.Paper.Translation = '翻译暂不可用，请在设置中测试接口。' }
    }
}

function Show-SourceStatus {
    $dialog = [System.Windows.Window]::new()
    $dialog.Title = 'RSS 来源状态'
    $dialog.Width = 640; $dialog.Height = 490; $dialog.MinWidth = 480
    $dialog.WindowStartupLocation = [System.Windows.WindowStartupLocation]::CenterOwner
    $dialog.Owner = $script:window
    $dialog.FontFamily = [System.Windows.Media.FontFamily]::new('Microsoft YaHei UI')
    $box = [System.Windows.Controls.TextBox]::new()
    $box.IsReadOnly = $true; $box.TextWrapping = [System.Windows.TextWrapping]::Wrap
    $box.VerticalScrollBarVisibility = [System.Windows.Controls.ScrollBarVisibility]::Auto
    $box.Padding = [System.Windows.Thickness]::new(12)
    $lines = New-Object System.Collections.ArrayList
    if ($script:lastFeedResults.Count -eq 0) { [void]$lines.Add('尚无结果，请等待本次更新完成。') }
    foreach ($entry in $script:lastFeedResults) {
        $line = $(if ($entry.Ok) { '✓ ' + $entry.Name + '：' + $entry.Count + ' 条' } else { '× ' + $entry.Name + '：' + $entry.Error })
        [void]$lines.Add($line)
    }
    $box.Text = $lines -join [Environment]::NewLine
    $dialog.Content = $box
    [void]$dialog.ShowDialog()
}

function Show-Settings {
    [xml]$settingsXaml = @'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" Title="期刊雷达设置" Width="680" Height="510" MinWidth="610" MinHeight="440" WindowStartupLocation="CenterOwner" Background="#F5F8FB" FontFamily="Microsoft YaHei UI">
 <Grid Margin="18"><Grid.RowDefinitions><RowDefinition Height="Auto"/><RowDefinition Height="*"/><RowDefinition Height="Auto"/></Grid.RowDefinitions>
  <TextBlock Text="期刊雷达设置" FontSize="20" FontWeight="Bold" Margin="0,0,0,12"/>
  <TabControl Grid.Row="1">
   <TabItem Header="RSS 订阅"><Grid Margin="10"><Grid.ColumnDefinitions><ColumnDefinition Width="220"/><ColumnDefinition Width="14"/><ColumnDefinition Width="*"/></Grid.ColumnDefinitions>
    <Grid Grid.Column="0"><Grid.RowDefinitions><RowDefinition Height="Auto"/><RowDefinition Height="*"/><RowDefinition Height="Auto"/></Grid.RowDefinitions><TextBlock x:Name="FeedCount" FontWeight="SemiBold" Margin="0,0,0,8"/><ListBox x:Name="FeedList" Grid.Row="1" DisplayMemberPath="Name"/><StackPanel Grid.Row="2" Orientation="Horizontal" Margin="0,9,0,0"><Button x:Name="AddFeed" Content="新增" Padding="10,4" Margin="0,0,7,0"/><Button x:Name="DeleteFeed" Content="删除" Padding="10,4"/></StackPanel></Grid>
    <StackPanel Grid.Column="2"><TextBlock Text="期刊名称"/><TextBox x:Name="FeedName" Margin="0,4,0,12" Padding="5"/><TextBlock Text="RSS 地址"/><TextBox x:Name="FeedUrl" Margin="0,4,0,12" Padding="5"/><CheckBox x:Name="FeedRequired" Content="培养方案必读" Margin="0,0,0,8"/><CheckBox x:Name="FeedChinese" Content="中文期刊" Margin="0,0,0,15"/><StackPanel Orientation="Horizontal"><Button x:Name="SaveFeed" Content="保存订阅" Padding="12,5" Margin="0,0,8,0"/><Button x:Name="ResetFeeds" Content="恢复预置 20 本" Padding="10,5"/></StackPanel><TextBlock x:Name="FeedMessage" TextWrapping="Wrap" Foreground="#667681" FontSize="11" Margin="0,10,0,0"/><TextBlock Text="外文 RSS 代理（可选；留空使用系统网络）" Margin="0,13,0,0" FontSize="11"/><StackPanel Orientation="Horizontal" Margin="0,4,0,0"><TextBox x:Name="ProxyBox" Width="225" Padding="4"/><Button x:Name="SaveProxy" Content="保存代理" Padding="8,4" Margin="7,0,0,0"/></StackPanel></StackPanel>
   </Grid></TabItem>
   <TabItem Header="大模型翻译"><StackPanel Margin="13"><CheckBox x:Name="TranslateEnabled" Content="启用英文标题中文翻译" Margin="0,0,0,14"/><TextBlock Text="接口地址（兼容 OpenAI Chat Completions 的完整地址）"/><TextBox x:Name="Endpoint" Margin="0,4,0,12" Padding="5"/><TextBlock Text="模型名称"/><TextBox x:Name="Model" Margin="0,4,0,12" Padding="5"/><TextBlock Text="API 密钥（保存在 Windows 当前用户加密存储中；本地模型可留空）"/><PasswordBox x:Name="ApiKey" Margin="0,4,0,12" Padding="5"/><TextBlock Text="只发送可见的英文论文标题；原题保留，中文译题显示在下一行。结果会缓存，接口可能收费。" FontSize="11" TextWrapping="Wrap" Foreground="#667681" Margin="0,0,0,15"/><StackPanel Orientation="Horizontal"><Button x:Name="SaveLlm" Content="保存配置" Padding="12,5" Margin="0,0,8,0"/><Button x:Name="TestLlm" Content="测试接口" Padding="10,5"/></StackPanel><TextBlock x:Name="LlmMessage" TextWrapping="Wrap" Foreground="#667681" FontSize="11" Margin="0,13,0,0"/></StackPanel></TabItem>
  </TabControl>
  <Button x:Name="DoneButton" Grid.Row="2" Content="完成" HorizontalAlignment="Right" Padding="13,5" Margin="0,12,0,0"/>
 </Grid>
</Window>
'@
    $xmlReader = New-Object System.Xml.XmlNodeReader($settingsXaml)
    $dialog = [System.Windows.Markup.XamlReader]::Load($xmlReader)
    $dialog.Owner = $script:window
    $feedList = $dialog.FindName('FeedList')
    $feedCount = $dialog.FindName('FeedCount')
    $feedName = $dialog.FindName('FeedName')
    $feedUrl = $dialog.FindName('FeedUrl')
    $feedRequired = $dialog.FindName('FeedRequired')
    $feedChinese = $dialog.FindName('FeedChinese')
    $feedMessage = $dialog.FindName('FeedMessage')
    $proxyBox = $dialog.FindName('ProxyBox')
    $deleteFeed = $dialog.FindName('DeleteFeed')
    $enabled = $dialog.FindName('TranslateEnabled')
    $endpoint = $dialog.FindName('Endpoint')
    $model = $dialog.FindName('Model')
    $apiKey = $dialog.FindName('ApiKey')
    $llmMessage = $dialog.FindName('LlmMessage')
    $feedState = [pscustomobject]@{ SelectedId = '' }
    $feedList.ItemsSource = @($script:feeds)
    $feedCount.Text = '订阅列表（' + $script:feeds.Count + '）'
    $deleteFeed.IsEnabled = $false
    $feedMessage.Text = '选择期刊修改，或填写新 RSS。'
    $proxyBox.Text = [string]$script:network.Proxy
    $enabled.IsChecked = [bool]$script:llm.Enabled
    $endpoint.Text = [string]$script:llm.Endpoint
    $model.Text = [string]$script:llm.Model
    $apiKey.Password = Read-ApiKey
    $llmMessage.Text = '只会把英文标题发送到你填写的接口。'
    $feedList.Add_SelectionChanged({
        param($sender, $eventArgs)
        if ($null -eq $sender.SelectedItem) { return }
        $feed = $sender.SelectedItem
        $feedState.SelectedId = [string]$feed.Id
        $feedName.Text = [string]$feed.Name
        $feedUrl.Text = [string]$feed.Url
        $feedRequired.IsChecked = [bool]$feed.Required
        $feedChinese.IsChecked = [bool]$feed.Chinese
        $deleteFeed.IsEnabled = $true
    })
    $dialog.FindName('AddFeed').Add_Click({
        $feedList.SelectedItem = $null; $feedState.SelectedId = ''
        $feedName.Text = ''; $feedUrl.Text = ''
        $feedRequired.IsChecked = $false; $feedChinese.IsChecked = $false
        $deleteFeed.IsEnabled = $false
        $feedMessage.Text = '填写新期刊资料后保存。'
    })
    $dialog.FindName('SaveFeed').Add_Click({
        $name = $feedName.Text.Trim(); $url = $feedUrl.Text.Trim(); $uri = $null
        if ([string]::IsNullOrWhiteSpace($name)) { $feedMessage.Text = '请填写期刊名称。'; return }
        if (-not [uri]::TryCreate($url, [uriKind]::Absolute, [ref]$uri) -or $uri.Scheme -notin @('http','https')) { $feedMessage.Text = '请输入完整的 HTTP 或 HTTPS RSS 地址。'; return }
        if (@($script:feeds | Where-Object { [string]$_.Id -ne $feedState.SelectedId -and [string]$_.Url -eq $url }).Count -gt 0) { $feedMessage.Text = '这个 RSS 地址已订阅。'; return }
        if ([string]::IsNullOrWhiteSpace($feedState.SelectedId)) { $feedState.SelectedId = [guid]::NewGuid().ToString() }
        $newFeed = [pscustomobject]@{ Id = $feedState.SelectedId; Name = $name; Url = $url; Required = [bool]$feedRequired.IsChecked; Chinese = [bool]$feedChinese.IsChecked }
        $script:feeds = @($script:feeds | Where-Object { [string]$_.Id -ne $feedState.SelectedId }) + @($newFeed)
        Save-JsonFile $script:feedsPath $script:feeds
        $feedList.ItemsSource = @($script:feeds); $feedList.SelectedItem = $newFeed
        $feedCount.Text = '订阅列表（' + $script:feeds.Count + '）'
        $feedMessage.Text = '已保存，正在更新。'
        Update-SourceCount; Start-Refresh
    })
    $deleteFeed.Add_Click({
        if ([string]::IsNullOrWhiteSpace($feedState.SelectedId)) { return }
        $script:feeds = @($script:feeds | Where-Object { [string]$_.Id -ne $feedState.SelectedId })
        Save-JsonFile $script:feedsPath $script:feeds
        $feedList.ItemsSource = @($script:feeds); $feedState.SelectedId = ''
        $feedName.Text = ''; $feedUrl.Text = ''; $deleteFeed.IsEnabled = $false
        $feedCount.Text = '订阅列表（' + $script:feeds.Count + '）'
        $feedMessage.Text = '已删除订阅。'
        Update-SourceCount; Start-Refresh
    })
    $dialog.FindName('ResetFeeds').Add_Click({
        $script:feeds = @(Read-JsonFile $script:defaultsPath @())
        Save-JsonFile $script:feedsPath $script:feeds
        $feedList.ItemsSource = @($script:feeds); $feedState.SelectedId = ''
        $feedName.Text = ''; $feedUrl.Text = ''; $deleteFeed.IsEnabled = $false
        $feedCount.Text = '订阅列表（' + $script:feeds.Count + '）'
        $feedMessage.Text = '已恢复预置订阅。'
        Update-SourceCount; Start-Refresh
    })
    $dialog.FindName('SaveProxy').Add_Click({
        $address = $proxyBox.Text.Trim()
        $uri = $null
        if ($address -and (-not [uri]::TryCreate($address, [uriKind]::Absolute, [ref]$uri) -or $uri.Scheme -notin @('http','https'))) { $feedMessage.Text = '代理地址示例：http://127.0.0.1:7890'; return }
        $script:network = [pscustomobject]@{ Proxy = $address }
        Save-JsonFile $script:networkPath $script:network
        $feedMessage.Text = '网络设置已保存，正在重试 RSS。'
        Start-Refresh
    })
    $dialog.FindName('SaveLlm').Add_Click({
        $candidate = [pscustomobject]@{ Enabled = [bool]$enabled.IsChecked; Endpoint = $endpoint.Text.Trim(); Model = $model.Text.Trim() }
        if ($candidate.Enabled -and -not (Test-Endpoint $candidate.Endpoint)) { $llmMessage.Text = '接口地址需为 HTTPS，或本机 HTTP 地址。'; return }
        if ($candidate.Enabled -and [string]::IsNullOrWhiteSpace($candidate.Model)) { $llmMessage.Text = '请填写模型名称。'; return }
        Stop-Translations
        $script:llm = $candidate
        Save-JsonFile $script:configPath $script:llm
        Save-ApiKey $apiKey.Password
        foreach ($paper in $script:allPapers) {
            $paper.CacheKey = Get-CacheKey $paper.Title
            $paper.Translation = $(if ($script:llm.Enabled -and $script:cache.ContainsKey($paper.CacheKey)) { $script:cache[$paper.CacheKey] } else { '' })
        }
        $llmMessage.Text = '配置已保存。'
    })
    $dialog.FindName('TestLlm').Add_Click({
        $address = $endpoint.Text.Trim(); $modelName = $model.Text.Trim()
        if (-not (Test-Endpoint $address) -or [string]::IsNullOrWhiteSpace($modelName)) { $llmMessage.Text = '请先填写 HTTPS 或本机 HTTP 接口地址和模型名称。'; return }
        $llmMessage.Text = '正在测试接口…'
        $payloadArgs = @{ model = $modelName; temperature = 0; max_tokens = 100; messages = @(@{ role = 'system'; content = '将英文标题翻译为简体中文，只返回译题。' }, @{ role = 'user'; content = 'Learning with technology' }) }
        if (([uri]$address).Host -eq 'api.deepseek.com') { $payloadArgs.thinking = @{ type = 'disabled' }; $payloadArgs.max_tokens = 256 }
        $payload = $payloadArgs | ConvertTo-Json -Depth 5
        $headers = @{}
        if (-not [string]::IsNullOrWhiteSpace($apiKey.Password)) { $headers['Authorization'] = 'Bearer ' + $apiKey.Password }
        try {
            $reply = Invoke-RestMethod -Uri $address -Method Post -Body ([System.Text.Encoding]::UTF8.GetBytes($payload)) -ContentType 'application/json; charset=utf-8' -Headers $headers -TimeoutSec 20
            $translated = [string]$reply.choices[0].message.content
            if ([string]::IsNullOrWhiteSpace($translated)) { throw '响应中没有译题' }
            $llmMessage.Text = '测试成功：' + $translated.Trim()
        } catch { $llmMessage.Text = '测试失败：请检查地址、模型、密钥和网络。' }
    })
    $dialog.FindName('DoneButton').Add_Click({ $dialog.Close() })
    [void]$dialog.ShowDialog()
}

$script:RefreshButton.Add_Click({ Start-Refresh })
$script:SettingsButton.Add_Click({ Show-Settings })
$script:SourceButton.Add_Click({ Show-SourceStatus })
$script:RequirementFilter.Add_SelectionChanged({ Update-PaperList })
$script:LanguageFilter.Add_SelectionChanged({ Update-PaperList })
$script:PaperList.Add_MouseDoubleClick({
    $paper = $script:PaperList.SelectedItem
    if ($null -ne $paper -and $paper.Url -match '^https?://') { Start-Process $paper.Url }
})
$timer = [System.Windows.Threading.DispatcherTimer]::new()
$timer.Interval = [timespan]::FromMilliseconds(500)
$timer.Add_Tick({
    Finish-Refresh
    Finish-TranslationJobs
    Queue-VisibleTranslations
    Start-TranslationJobs
    if ($script:lastRefresh -ne [datetime]::MinValue -and ((Get-Date) - $script:lastRefresh).TotalMinutes -ge 30 -and $null -eq $script:refreshJob) { Start-Refresh }
})
$script:window.Add_Closed({
    $timer.Stop()
    if ($null -ne $script:refreshJob) { Stop-Job -Job $script:refreshJob -ErrorAction SilentlyContinue; Remove-Job -Job $script:refreshJob -Force -ErrorAction SilentlyContinue }
    Stop-Translations
})
Update-SourceCount
$script:StatusText.Text = '正在连接期刊…'
$timer.Start()
Start-Refresh
[void]$script:window.ShowDialog()
