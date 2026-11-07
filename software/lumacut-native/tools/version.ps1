# Version for local and CI builds: 0.<months since 12/2025>.<day * 1440 + minute of day>, UTC.
# MSI compares only the first three fields (build at most 65535), so this rises with every minute.
$d = (Get-Date).ToUniversalTime()
$minor = ($d.Year - 2025) * 12 + $d.Month - 12
$build = $d.Day * 1440 + $d.Hour * 60 + $d.Minute
"0.$minor.$build"
