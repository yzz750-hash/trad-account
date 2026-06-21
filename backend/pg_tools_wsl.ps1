# WSL2 pg_dump / psql / pg_restore wrapper for Windows dev environment.
# Usage: pg_tools_wsl.ps1 pg_dump --dbname $env:DATABASE_URL --file dump.sql
#
# Set in .env:
#   PG_DUMP_PATH=powershell -File backend\pg_tools_wsl.ps1 pg_dump
#   PSQL_PATH=powershell -File backend\pg_tools_wsl.ps1 psql
#   PG_RESTORE_PATH=powershell -File backend\pg_tools_wsl.ps1 pg_restore
param($tool)

# Collect remaining args, translating Windows paths to WSL paths
$argsList = @()
for ($i = 1; $i -lt $args.Count; $i++) {
    $arg = $args[$i]
    # Translate --file / -f arguments
    if ($arg -eq "--file" -or $arg -eq "-f") {
        $i++
        $winPath = $args[$i]
        $wslPath = ($winPath -replace '\\', '/' -replace '^([A-Za-z]):', '/mnt/$1').ToLower()
        $argsList += $arg
        $argsList += $wslPath
    } else {
        $argsList += $arg
    }
}

wsl $tool @argsList
