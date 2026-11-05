//go:build windows

package main

import (
	"os/exec"
	"syscall"
)

// hideWindow — 백그라운드 서비스가 powershell/tasklist 를 띄울 때 콘솔 창이 깜빡이지 않게 한다.
func hideWindow(cmd *exec.Cmd) {
	const createNoWindow = 0x08000000
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: createNoWindow}
}
