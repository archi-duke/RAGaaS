// ragaas-converter — 로컬 Office 문서(docx/pptx) → 텍스트 변환 서비스.
//
// GoJIRA 런처 게이트웨이(설계: GoJIRA docs/design-launcher-gateway.md)의 로컬 서비스로 동작한다.
// 런처가 SVC_PORT/SVC_SECRET 을 주입해 기동하고, 브라우저 요청을
//
//	POST http://127.0.0.1:5599/v1/docs/{pptx|docx}/text
//
// 로 받아 이 서비스로 중계한다. 사내 DRM(NASCA) 문서는 DRM 에이전트가 붙은 로컬 Office 만
// 복호화할 수 있으므로, 서버가 아닌 사용자 PC 에서 Office COM 으로 텍스트를 뽑는다.
//
// 개발 모드(-dev): 런처 게이트웨이 없이 브라우저가 직접 호출할 수 있도록 CORS 와
// /launcher/health·/launcher/capabilities 스텁을 제공한다 (기본 포트 5601).
package main

import (
	_ "embed"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

//go:embed convert.ps1
var convertScript []byte

//go:embed service.json
var serviceJSON []byte

const (
	serviceName    = "ragaas-converter"
	defaultDevPort = 5601
	defaultMaxMB   = 200
	defaultTimeout = 240 * time.Second
)

type Config struct {
	Port       int
	Secret     string
	DataDir    string
	LogDir     string
	Dev        bool
	DevOrigins []string
	MaxBytes   int64
	Timeout    time.Duration
}

func serviceVersion() string {
	var m struct {
		Version string `json:"version"`
	}
	if err := json.Unmarshal(serviceJSON, &m); err != nil || m.Version == "" {
		return "0.0.0"
	}
	return m.Version
}

func loadConfig(args []string) (*Config, bool, error) {
	fs := flag.NewFlagSet(serviceName, flag.ContinueOnError)
	dev := fs.Bool("dev", false, "개발 모드: 브라우저 직접 호출 허용(CORS) + /launcher/* 스텁")
	devOrigin := fs.String("dev-origin", "http://localhost:3002,http://localhost:5173", "개발 모드에서 허용할 웹 origin (쉼표 구분)")
	port := fs.Int("port", 0, "listen 포트 (기본: SVC_PORT, 개발 모드는 5601)")
	showVersion := fs.Bool("version", false, "버전 출력")
	if err := fs.Parse(args); err != nil {
		return nil, false, err
	}
	if *showVersion {
		return nil, true, nil
	}

	cfg := &Config{
		Secret:   os.Getenv("SVC_SECRET"),
		DataDir:  os.Getenv("SVC_DATA_DIR"),
		LogDir:   os.Getenv("SVC_LOG_DIR"),
		Dev:      *dev,
		MaxBytes: defaultMaxMB << 20,
		Timeout:  defaultTimeout,
	}
	if v := os.Getenv("SVC_MAX_MB"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			cfg.MaxBytes = int64(n) << 20
		}
	}
	if v := os.Getenv("SVC_TIMEOUT_SEC"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			cfg.Timeout = time.Duration(n) * time.Second
		}
	}

	switch {
	case *port > 0:
		cfg.Port = *port
	case os.Getenv("SVC_PORT") != "":
		n, err := strconv.Atoi(os.Getenv("SVC_PORT"))
		if err != nil || n <= 0 {
			return nil, false, fmt.Errorf("SVC_PORT 값이 올바르지 않음: %q", os.Getenv("SVC_PORT"))
		}
		cfg.Port = n
	case cfg.Dev:
		cfg.Port = defaultDevPort
	default:
		return nil, false, fmt.Errorf("SVC_PORT 가 없음 — 런처가 기동해야 한다 (직접 실행은 -dev)")
	}

	if cfg.Dev {
		for _, o := range strings.Split(*devOrigin, ",") {
			if o = strings.TrimRight(strings.TrimSpace(o), "/"); o != "" {
				cfg.DevOrigins = append(cfg.DevOrigins, o)
			}
		}
	} else if cfg.Secret == "" {
		return nil, false, fmt.Errorf("SVC_SECRET 이 없음 — 런처 경유가 아니면 -dev 로 실행")
	}

	if cfg.DataDir == "" {
		cfg.DataDir = filepath.Join(os.TempDir(), serviceName)
	}
	return cfg, false, nil
}

func setupLog(cfg *Config) {
	log.SetFlags(log.LstdFlags | log.Lmicroseconds)
	if cfg.LogDir == "" {
		return
	}
	if err := os.MkdirAll(cfg.LogDir, 0o700); err != nil {
		return
	}
	f, err := os.OpenFile(filepath.Join(cfg.LogDir, serviceName+".log"), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		return
	}
	log.SetOutput(io.MultiWriter(os.Stderr, f))
}

func main() {
	cfg, versionOnly, err := loadConfig(os.Args[1:])
	if versionOnly {
		fmt.Println(serviceVersion())
		return
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "ragaas-converter:", err)
		os.Exit(2)
	}
	setupLog(cfg)

	if err := os.MkdirAll(cfg.DataDir, 0o700); err != nil {
		log.Fatalf("데이터 디렉터리 생성 실패: %v", err)
	}
	scriptPath := filepath.Join(cfg.DataDir, "convert.ps1")
	if err := os.WriteFile(scriptPath, convertScript, 0o600); err != nil {
		log.Fatalf("변환 스크립트 배치 실패: %v", err)
	}

	srv := NewServer(cfg, NewOfficeConverter(scriptPath, cfg.DataDir))
	addr := fmt.Sprintf("127.0.0.1:%d", cfg.Port)
	httpSrv := &http.Server{
		Addr:              addr,
		Handler:           srv.Handler(),
		ReadHeaderTimeout: 10 * time.Second,
	}
	srv.onShutdown = func() { _ = httpSrv.Close() }

	mode := "service"
	if cfg.Dev {
		mode = fmt.Sprintf("dev (origins=%v)", cfg.DevOrigins)
	}
	req := srv.conv.Requirements()
	log.Printf("%s v%s — http://%s [%s] requirements=%+v", serviceName, serviceVersion(), addr, mode, req)

	if err := httpSrv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatalf("서버 종료: %v", err)
	}
}
