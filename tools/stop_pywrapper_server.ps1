$ErrorActionPreference = "Stop"

$hostAddress = "127.0.0.1"
$port = 30415
$password = "31415"
$requestLine = "SHUTDOWN;$password"

$client = $null
$stream = $null
$reader = $null
$writer = $null

try {
    $client = [System.Net.Sockets.TcpClient]::new()
    $client.Connect($hostAddress, $port)
    $stream = $client.GetStream()
    $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8, $false, 1024, $true)
    $writer = [System.IO.StreamWriter]::new($stream, [System.Text.Encoding]::UTF8, 1024, $true)
    $writer.NewLine = "`n"
    $writer.WriteLine($requestLine)
    $writer.Flush()

    $response = $reader.ReadLine()
    if ([string]::IsNullOrWhiteSpace($response)) {
        throw "Server returned an empty shutdown response."
    }

    Write-Host "[INFO] Shutdown response: $response"
}
finally {
    if ($writer -ne $null) {
        $writer.Dispose()
    }
    if ($reader -ne $null) {
        $reader.Dispose()
    }
    if ($stream -ne $null) {
        $stream.Dispose()
    }
    if ($client -ne $null) {
        $client.Close()
    }
}
