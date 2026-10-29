# Receives one JSON object on stdin: {language, png: base64}.
# Uses only installed Windows OCR components; returns line boxes as JSON.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$memory = $null
$stream = $null
$bitmap = $null

try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
    [Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
    [Windows.Globalization.Language, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
    [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
    [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null

    $asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and
        $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    } | Select-Object -First 1
    function Await-WinRT($operation, [type]$resultType) {
        $task = $asTask.MakeGenericMethod($resultType).Invoke($null, @($operation))
        $task.GetAwaiter().GetResult()
    }

    $request = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $language = [Windows.Globalization.Language]::new([string]$request.language)
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($language)
    if ($null -eq $engine) {
        $available = @([Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages | ForEach-Object { $_.LanguageTag }) -join ', '
        throw "OCR language '$($request.language)' is unavailable. Installed: $available"
    }
    $bytes = [Convert]::FromBase64String([string]$request.png)
    $memory = [System.IO.MemoryStream]::new($bytes, $false)
    $stream = [System.IO.WindowsRuntimeStreamExtensions]::AsRandomAccessStream($memory)
    $decoder = Await-WinRT ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    if ($decoder.PixelWidth -gt [Windows.Media.Ocr.OcrEngine]::MaxImageDimension -or
        $decoder.PixelHeight -gt [Windows.Media.Ocr.OcrEngine]::MaxImageDimension) {
        throw "Image exceeds Windows OCR maximum dimension: $([Windows.Media.Ocr.OcrEngine]::MaxImageDimension)"
    }
    $bitmap = Await-WinRT ($decoder.GetSoftwareBitmapAsync(
        [Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8,
        [Windows.Graphics.Imaging.BitmapAlphaMode]::Ignore
    )) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $recognized = Await-WinRT ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    $lines = @(
        foreach ($line in $recognized.Lines) {
            if (-not $line.Text.Trim() -or $line.Words.Count -eq 0) { continue }
            $left = [double]::PositiveInfinity
            $top = [double]::PositiveInfinity
            $right = 0.0
            $bottom = 0.0
            foreach ($word in $line.Words) {
                $box = $word.BoundingRect
                $left = [Math]::Min($left, $box.X)
                $top = [Math]::Min($top, $box.Y)
                $right = [Math]::Max($right, $box.X + $box.Width)
                $bottom = [Math]::Max($bottom, $box.Y + $box.Height)
            }
            [PSCustomObject]@{
                text = $line.Text
                left = $left
                top = $top
                right = $right
                bottom = $bottom
            }
        }
    )
    if ($lines.Count -eq 0) { throw 'No text recognized in the supplied image.' }
    [PSCustomObject]@{ ok = $true; language = $engine.RecognizerLanguage.LanguageTag; lines = $lines } |
        ConvertTo-Json -Depth 5 -Compress
} catch {
    [PSCustomObject]@{ ok = $false; error = $_.Exception.Message } | ConvertTo-Json -Compress
    exit 1
} finally {
    if ($null -ne $bitmap) { $bitmap.Dispose() }
    if ($null -ne $stream) { $stream.Dispose() }
    if ($null -ne $memory) { $memory.Dispose() }
}
