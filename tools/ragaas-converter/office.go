package main

import (
	"context"
	"encoding/csv"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"sync"
)

// OfficeConverter — 임베드한 convert.ps1 을 powershell 로 실행해 Office COM 으로 텍스트를 뽑는다.
type OfficeConverter struct {
	scriptPath string
	workDir    string

	reqOnce sync.Once
	req     map[string]bool
}

func NewOfficeConverter(scriptPath, workDir string) *OfficeConverter {
	return &OfficeConverter{scriptPath: scriptPath, workDir: workDir}
}

// 형식별 Office 프로세스 이미지 — 시간 초과 시 이번 변환이 띄운 잔여 프로세스 정리에 쓴다.
var officeImage = map[string]string{"docx": "WINWORD.EXE", "pptx": "POWERPNT.EXE"}

// Requirements — powershell, Word/PowerPoint COM 등록 여부 (최초 1회 점검 후 캐시).
func (c *OfficeConverter) Requirements() map[string]bool {
	c.reqOnce.Do(func() {
		_, psErr := exec.LookPath("powershell")
		c.req = map[string]bool{
			"windows":    runtime.GOOS == "windows",
			"powershell": psErr == nil,
			"word":       comRegistered("Word.Application"),
			"powerpoint": comRegistered("PowerPoint.Application"),
		}
	})
	return c.req
}

func comRegistered(progID string) bool {
	if runtime.GOOS != "windows" {
		return false
	}
	cmd := exec.Command("reg", "query", `HKCR\`+progID+`\CLSID`)
	hideWindow(cmd)
	return cmd.Run() == nil
}

type scriptOutput struct {
	OK    bool   `json:"ok"`
	Text  string `json:"text"`
	Units int    `json:"units"`
	Unit  string `json:"unit"`
	Error string `json:"error"`
}

func (c *OfficeConverter) Convert(ctx context.Context, srcPath, format string) (*ConvertResult, error) {
	outPath := filepath.Join(filepath.Dir(srcPath), "result.json")
	before := officePIDs(officeImage[format])

	cmd := exec.CommandContext(ctx, "powershell",
		"-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
		"-File", c.scriptPath, "-Path", srcPath, "-Format", format, "-OutFile", outPath)
	cmd.Dir = c.workDir
	hideWindow(cmd)
	stderr, runErr := cmd.CombinedOutput()

	if ctx.Err() != nil {
		// powershell 은 CommandContext 가 죽였지만, 그 사이 띄운 Office 프로세스는 남는다.
		killNewOffice(officeImage[format], before)
		return nil, ctx.Err()
	}

	raw, readErr := os.ReadFile(outPath)
	if readErr != nil {
		msg := strings.TrimSpace(string(stderr))
		if msg == "" && runErr != nil {
			msg = runErr.Error()
		}
		return nil, fmt.Errorf("변환 스크립트 결과 없음: %s", truncate(msg, 500))
	}
	var out scriptOutput
	if err := json.Unmarshal(trimBOM(raw), &out); err != nil {
		return nil, fmt.Errorf("변환 결과 파싱 실패: %w", err)
	}
	if !out.OK {
		return nil, &ConvertError{Msg: out.Error}
	}
	return &ConvertResult{Text: out.Text, Units: out.Units, Unit: out.Unit}, nil
}

// officePIDs — 이미지 이름의 실행 중 PID 집합 (Windows tasklist).
func officePIDs(image string) map[int]bool {
	pids := map[int]bool{}
	if runtime.GOOS != "windows" || image == "" {
		return pids
	}
	cmd := exec.Command("tasklist", "/FO", "CSV", "/NH", "/FI", "IMAGENAME eq "+image)
	hideWindow(cmd)
	out, err := cmd.Output()
	if err != nil {
		return pids
	}
	recs, err := csv.NewReader(strings.NewReader(string(out))).ReadAll()
	if err != nil {
		return pids
	}
	for _, rec := range recs {
		if len(rec) >= 2 && strings.EqualFold(rec[0], image) {
			if pid, err := strconv.Atoi(rec[1]); err == nil {
				pids[pid] = true
			}
		}
	}
	return pids
}

// killNewOffice — 변환 시작 전에는 없던 Office 프로세스만 종료한다 (사용자가 띄운 창은 건드리지 않음).
func killNewOffice(image string, before map[int]bool) {
	for pid := range officePIDs(image) {
		if before[pid] {
			continue
		}
		cmd := exec.Command("taskkill", "/PID", strconv.Itoa(pid), "/F")
		hideWindow(cmd)
		if err := cmd.Run(); err != nil && !errors.Is(err, exec.ErrNotFound) {
			log.Printf("잔여 %s(pid=%d) 종료 실패: %v", image, pid, err)
		} else {
			log.Printf("시간 초과 — 잔여 %s(pid=%d) 종료", image, pid)
		}
	}
}

func trimBOM(b []byte) []byte {
	if len(b) >= 3 && b[0] == 0xEF && b[1] == 0xBB && b[2] == 0xBF {
		return b[3:]
	}
	return b
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n] + "…"
}
