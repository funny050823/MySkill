@echo off

set "desPath=d:\QCBase\trunk\SourceCode\Tool\HDTools\KResourceReader\.claude\skills"

call :MakePathLink Ani代码同步
call :MakePathLink kmsc代码同步
call :MakePathLink krl代码同步
call :MakePathLink tani代码同步
call :MakePathLink Pss代码同步
pause
goto :eof


:MakePathLink
    rem %1
    if not exist "%cd%\skills\%1" (
        mkdir "%cd%\skills\%1"
    )
    
    if not exist "%desPath%\%1" (
        mklink /d /j "%desPath%\%1" "%cd%\skills\%1"
    )
    goto :eof
    
