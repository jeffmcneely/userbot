# set this to be the URL of a API gateway that is connected to a python lambda function
#$USERBOT = "https://or3f0e78k6.execute-api.us-east-1.amazonaws.com/default/userbot"
# set this to DC=something,DC=TLD
$SEARCHROOT = 'LDAP://DC=example,DC=com'
# set this line to how many previous days we should check Active Directory
$NUMBER_OF_DAYS=-3
# Authentication header for API requests
$AUTH_HEADER = "<your-uuid-here>"


$Earlier = (Get-Date).AddDays($NUMBER_OF_DAYS)
$Then = Get-Date -Date $Earlier  -UFormat "%Y%m%d%H%M%S"
$Then = "$Then.0Z"

# this is for finding recently added users
$LDAPSEARCH = New-Object System.DirectoryServices.DirectorySearcher -Property @{ SearchRoot = $SEARCHROOT; Filter = "(&(objectClass=user)(whenCreated>=$Then))"; PageSize = 0 }
foreach ($LINE in $LDAPSEARCH.FindAll()) {
    $LINE_ENTRY = $LINE.GetDirectoryEntry()
    $TITLE = $LINE_ENTRY | Select-Object -ExpandProperty title | Out-String
    $WHO = $LINE_ENTRY | Select-Object -ExpandProperty name | Out-String
    $MANAGER = $LINE_ENTRY | Select-Object -ExpandProperty manager | Out-String
    $SAM = $LINE_ENTRY | Select-Object -ExpandProperty samaccountname | Out-String

    $SAM2 = [string]::join("", ($SAM.Split("`n")))
    $SAM3 = [string]::join("", ($SAM2.Split("`r")))
    $WHO2 = [string]::join("", ($WHO.Split("`n")))
    $WHO3 = [string]::join("", ($WHO2.Split("`r")))
    $TITLE2 = [string]::join("", ($TITLE.Split("`n")))
    $TITLE3 = [string]::join("", ($TITLE2.Split("`r")))
    $MANAGER2 = [string]::join("", ($MANAGER.Split("`n")))
    $MANAGER3 = [string]::join("", ($MANAGER2.Split("`r")))

    $STRUCT = @"
{
 "event": "new",
 "sam": "$SAM3",
 "name": "$WHO3",
 "title": "$TITLE3",
 "manager": "$MANAGER3"
 }
"@
    $BYTES = [System.Text.Encoding]::UTF8.GetBytes($STRUCT)
    $FINAL = [System.Convert]::ToBase64String($BYTES)
    $FINAL_JSON = @"
{"data": "$FINAL" }
"@
    # for debugging
    #Write-Host $STRUCT
    #Write-Host $FINAL_JSON

    Invoke-WebRequest -Uri $USERBOT -ContentType 'application/json; charset=utf-8' -Headers @{"X-Auth-Header" = $AUTH_HEADER} -Method "POST" -Body $FINAL_JSON

}


# this is for finding recently changed users
$LDAPSEARCH = New-Object System.DirectoryServices.DirectorySearcher -Property @{SearchRoot = $SEARCHROOT; Filter = "(&(objectClass=user)(useraccountcontrol:1.2.840.113556.1.4.803:=2)(whenchanged>=$Then))"; PageSize = 0 }
foreach ($LINE in $LDAPSEARCH.FindAll()) {
    $LINE_ENTRY = $LINE.GetDirectoryEntry()
    $SAM = $LINE_ENTRY | Select-Object -ExpandProperty samaccountname | Out-String
    $WHO = $LINE_ENTRY | Select-Object -ExpandProperty name | Out-String
    $TITLE = $LINE_ENTRY | Select-Object -ExpandProperty title | Out-String
    $MANAGER = $LINE_ENTRY | Select-Object -ExpandProperty manager | Out-String
    $CREATED = $LINE_ENTRY | Select-Object -ExpandProperty whencreated | Out-String

    $SAM2 = [string]::join("", ($SAM.Split("`n")))
    $SAM3 = [string]::join("", ($SAM2.Split("`r")))
    $WHO2 = [string]::join("", ($WHO.Split("`n")))
    $WHO3 = [string]::join("", ($WHO2.Split("`r")))
    $TITLE2 = [string]::join("", ($TITLE.Split("`n")))
    $TITLE3 = [string]::join("", ($TITLE2.Split("`r")))
    $MANAGER2 = [string]::join("", ($MANAGER.Split("`n")))
    $MANAGER3 = [string]::join("", ($MANAGER2.Split("`r")))
    $CREATED2 = [string]::join("", ($CREATED.Split("`n")))
    $CREATED3 = [string]::join("", ($CREATED2.Split("`r")))

    $STRUCT = @"
{
 "event": "disable",
 "sam": "$SAM3",
 "name": "$WHO3",
 "title": "$TITLE3",
 "manager": "$MANAGER3",
 "created": "$CREATED3"
 }
"@
    $BYTES = [System.Text.Encoding]::UTF8.GetBytes($STRUCT)
    $FINAL = [System.Convert]::ToBase64String($BYTES)
    $FINAL_JSON = @"
{"data": "$FINAL" }
"@
    Invoke-WebRequest -Uri $USERBOT -ContentType 'application/json; charset=utf-8' -Headers @{"X-Auth-Header" = $AUTH_HEADER} -Method "POST" -Body $FINAL_JSON

}