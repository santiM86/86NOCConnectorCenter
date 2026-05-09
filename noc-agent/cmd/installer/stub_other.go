// Stub for non-Windows builds. The installer is windows-only.
//go:build !windows

package main

import "fmt"

func main() {
	fmt.Println("86NocInstall is a Windows-only tool. Use install.sh on Linux/macOS.")
}
