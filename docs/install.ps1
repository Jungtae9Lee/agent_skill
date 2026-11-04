param(
    [Parameter(Mandatory = $true)]
    [string[]]$Skills,
    [ValidateSet("opencode", "claude", "cursor")]
    [string]$Target = "opencode",
    [string]$Project = ""
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$known = @("confidence", "discernment-nudge", "doc-coauthoring", "skill-creator")
$Skills = @($Skills | ForEach-Object { $_ -split "," } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
foreach ($skill in $Skills) {
    if ($known -notcontains $skill) {
        throw "Unknown skill: $skill. Choose from: $($known -join ', ')"
    }
}

if ($Project) {
    $projectPath = (Resolve-Path -LiteralPath $Project).Path
    $dest = Join-Path $projectPath ".opencode\skills"
} else {
    switch ($Target) {
        "opencode" { $dest = Join-Path $HOME ".config\opencode\skills" }
        "claude"   { $dest = Join-Path $HOME ".claude\skills" }
        "cursor"   { $dest = Join-Path $HOME ".cursor\skills" }
    }
}

$work = Join-Path ([IO.Path]::GetTempPath()) ("agent-skill-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $work | Out-Null

function Get-RepoFolder([string]$Owner, [string]$Name, [string]$Ref) {
    $zip = Join-Path $work "$Name.zip"
    $out = Join-Path $work $Name
    Invoke-WebRequest -UseBasicParsing -Uri "https://codeload.github.com/$Owner/$Name/zip/refs/heads/$Ref" -OutFile $zip
    Expand-Archive -LiteralPath $zip -DestinationPath $out -Force
    return (Get-ChildItem -LiteralPath $out -Directory | Select-Object -First 1).FullName
}

try {
    $own = Get-RepoFolder "Jungtae9Lee" "agent_skill" "main"
    $anthropic = $null
    New-Item -ItemType Directory -Force -Path $dest | Out-Null

    foreach ($skill in $Skills) {
        if ($skill -eq "doc-coauthoring") {
            if (-not $anthropic) { $anthropic = Get-RepoFolder "anthropics" "skills" "main" }
            $source = Join-Path $anthropic "skills\doc-coauthoring"
        } else {
            $source = Join-Path $own $skill
        }
        if (-not (Test-Path -LiteralPath (Join-Path $source "SKILL.md"))) {
            Write-Host "[fail] $skill : SKILL.md not found"
            continue
        }
        $skillDest = Join-Path $dest $skill
        $action = "installed"
        if (Test-Path -LiteralPath $skillDest) {
            Remove-Item -LiteralPath $skillDest -Recurse -Force
            $action = "replaced"
        }
        Copy-Item -LiteralPath $source -Destination $skillDest -Recurse
        Get-ChildItem -LiteralPath $skillDest -Recurse -Force -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
        Write-Host "[$action] $skill -> $skillDest"
    }
    Write-Host ""
    Write-Host "Done. Restart OpenCode, Claude Code, or Cursor if it is already running."
} finally {
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}
