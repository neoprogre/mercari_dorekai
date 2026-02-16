$taskName = "DailyAutomation_AutoRun"
$scriptPath = "C:\Users\progr\Desktop\Python\mercari_dorekai\全部実行.bat"
$time = "09:10"

$action = New-ScheduledTaskAction -Execute $scriptPath
$trigger = New-ScheduledTaskTrigger -Daily -At $time
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -TaskName $taskName -Description "Daily Automation" -RunLevel Highest

Write-Host "Task registered successfully"
