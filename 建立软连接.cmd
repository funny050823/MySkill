@echo off

set "desPath=d:\QCBase\trunk\SourceCode\Tool\HDTools\KResourceReader\.claude\skills"

call :Main
pause
goto :eof

:Main
    if exist "%desPath%" (
        echo ¡¾¾¯¸æ¡¿path exist : %desPath%
    ) else (
        mklink /d /j "%desPath%" "%cd%\skills"
    )
    goto :eof
