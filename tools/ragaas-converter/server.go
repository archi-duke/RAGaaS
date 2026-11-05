package main

import (
	"bytes"
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"io"
	"log"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"sync/atomic"
	"time"
)

// DRM 파일 판정 — NASCA DRM 은 파일 선두가 "<## NASCA DRM FILE - VER1.00 ##>"(32바이트).
// 버전 표기가 바뀌어도 잡히도록 접두부만 비교한다.
var drmPrefix = []byte("<## NASCA DRM FILE")

// OOXML(docx/pptx)은 zip 컨테이너.
var zipMagic = []byte("PK\x03\x04")

const headerPeek = 32

type contentKind int

const (
	kindUnknown contentKind = iota
	kindOOXML
	kindDRM
)

func detectKind(head []byte) contentKind {
	switch {
	case bytes.HasPrefix(head, drmPrefix):
		return kindDRM
	case bytes.HasPrefix(head, zipMagic):
		return kindOOXML
	default:
		return kindUnknown
	}
}

// 지원 형식 — 경로 /v1/docs/{format}/text 의 {format}.
var supportedFormats = map[string]bool{"docx": true, "pptx": true}

// ConvertResult — 변환 스크립트 결과.
type ConvertResult struct {
	Text  string
	Units int
	Unit  string
}

// Converter — 실제 변환기(Office COM) 추상화. 테스트에서 가짜로 대체한다.
type Converter interface {
	Convert(ctx context.Context, srcPath, format string) (*ConvertResult, error)
	Requirements() map[string]bool
}

// ConvertError — 변환기가 문서를 처리하지 못함(손상, 암호, DRM 미복호화 등). 422 로 응답.
type ConvertError struct{ Msg string }

func (e *ConvertError) Error() string { return e.Msg }

type Server struct {
	cfg        *Config
	conv       Converter
	sem        chan struct{} // Office COM 자동화는 직렬화 (PowerPoint 는 단일 인스턴스)
	busy       atomic.Int32
	onShutdown func()
}

func NewServer(cfg *Config, conv Converter) *Server {
	return &Server{cfg: cfg, conv: conv, sem: make(chan struct{}, 1)}
}

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", s.handleHealth)
	mux.HandleFunc("POST /shutdown", s.handleShutdown)
	mux.HandleFunc("POST /v1/docs/{format}/text", s.handleConvert)
	if s.cfg.Dev {
		// 런처 게이트웨이 없이 프론트를 개발·검증하기 위한 스텁 (런처 §6 응답 형태와 동일).
		mux.HandleFunc("GET /launcher/health", s.handleDevLauncherHealth)
		mux.HandleFunc("GET /launcher/capabilities", s.handleDevCapabilities)
	}
	return s.guard(mux)
}

// guard — 런처↔서비스 인증 + (개발 모드) CORS.
//   - 서비스 모드: Origin 헤더가 있는 요청은 브라우저 직접 호출이므로 거부(런처는 Origin 을 제거해 중계).
//     X-Svc-Secret 이 SVC_SECRET 과 일치해야 한다.
//   - 개발 모드: Origin 허용목록 + preflight(PNA 포함). SVC_SECRET 이 설정돼 있으면 그것도 검사.
func (s *Server) guard(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		origin := r.Header.Get("Origin")
		if origin != "" {
			if !s.cfg.Dev || !s.originAllowed(origin) {
				writeErr(w, http.StatusForbidden, "origin_forbidden", "브라우저 직접 호출은 허용되지 않음 (런처 경유 필요)")
				return
			}
			h := w.Header()
			h.Set("Access-Control-Allow-Origin", origin)
			h.Set("Vary", "Origin")
			if r.Method == http.MethodOptions {
				h.Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
				h.Set("Access-Control-Allow-Headers", "Content-Type, X-File-Name, X-Gojira-Launcher-Token, X-Svc-Secret")
				h.Set("Access-Control-Allow-Private-Network", "true")
				h.Set("Access-Control-Max-Age", "600")
				w.WriteHeader(http.StatusNoContent)
				return
			}
		}
		if r.URL.Path == "/health" || (s.cfg.Dev && r.URL.Path == "/launcher/health") {
			next.ServeHTTP(w, r)
			return
		}
		if s.cfg.Secret != "" {
			got := r.Header.Get("X-Svc-Secret")
			if subtle.ConstantTimeCompare([]byte(got), []byte(s.cfg.Secret)) != 1 {
				writeErr(w, http.StatusUnauthorized, "unauthorized", "X-Svc-Secret 불일치")
				return
			}
		}
		next.ServeHTTP(w, r)
	})
}

func (s *Server) originAllowed(origin string) bool {
	for _, o := range s.cfg.DevOrigins {
		if o == "*" || o == origin {
			return true
		}
	}
	return false
}

func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {
	req := s.conv.Requirements()
	ready := true
	for _, ok := range req {
		ready = ready && ok
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"version":      serviceVersion(),
		"ready":        ready,
		"busy":         s.busy.Load() > 0,
		"requirements": req,
	})
}

func (s *Server) handleShutdown(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusAccepted, map[string]any{"status": "shutting_down"})
	if s.onShutdown != nil {
		go func() {
			// 진행 중 변환이 있으면 최대 10초 대기.
			for i := 0; i < 100 && s.busy.Load() > 0; i++ {
				time.Sleep(100 * time.Millisecond)
			}
			s.onShutdown()
		}()
	}
}

func (s *Server) handleDevLauncherHealth(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{
		"version": "dev-stub", "ready": true, "token": "dev",
	})
}

func (s *Server) handleDevCapabilities(w http.ResponseWriter, r *http.Request) {
	state := "available"
	req := s.conv.Requirements()
	for _, ok := range req {
		if !ok {
			state = "unsupported"
		}
	}
	routes := []map[string]any{}
	for f := range supportedFormats {
		routes = append(routes, map[string]any{
			"prefix": "/v1/docs/" + f, "methods": []string{"POST"}, "service": serviceName, "state": state,
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{"routes": routes})
}

type convertResponse struct {
	Text      string `json:"text"`
	Format    string `json:"format"`
	Units     int    `json:"units"`
	Unit      string `json:"unit"`
	DRM       bool   `json:"drm"`
	Chars     int    `json:"chars"`
	ElapsedMs int64  `json:"elapsedMs"`
}

func (s *Server) handleConvert(w http.ResponseWriter, r *http.Request) {
	start := time.Now()
	format := r.PathValue("format")
	if !supportedFormats[format] {
		writeErr(w, http.StatusNotFound, "unsupported_format", "지원 형식: docx, pptx")
		return
	}
	for name, ok := range s.conv.Requirements() {
		if !ok {
			writeJSON(w, http.StatusFailedDependency, map[string]any{
				"code": "requirement_missing", "error": "필수 구성요소 없음: " + name, "missing": []string{name},
			})
			return
		}
	}

	ctx, cancel := context.WithTimeout(r.Context(), s.cfg.Timeout)
	defer cancel()

	jobDir, err := os.MkdirTemp(s.cfg.DataDir, "job-*")
	if err != nil {
		writeErr(w, http.StatusInternalServerError, "internal", "임시 디렉터리 생성 실패")
		return
	}
	defer os.RemoveAll(jobDir)

	src := filepath.Join(jobDir, "source."+format)
	kind, size, err := saveBody(w, r, src, s.cfg.MaxBytes)
	if err != nil {
		var mbe *http.MaxBytesError
		if errors.As(err, &mbe) {
			writeErr(w, http.StatusRequestEntityTooLarge, "too_large", "파일이 너무 큼")
			return
		}
		writeErr(w, http.StatusBadRequest, "bad_body", "요청 본문을 읽지 못함")
		return
	}
	if size == 0 {
		writeErr(w, http.StatusBadRequest, "empty_body", "빈 파일")
		return
	}
	if kind == kindUnknown {
		writeErr(w, http.StatusUnsupportedMediaType, "unsupported_content", "docx/pptx(OOXML) 또는 DRM 문서가 아님")
		return
	}
	isDRM := kind == kindDRM

	// Office 자동화는 한 번에 하나만.
	select {
	case s.sem <- struct{}{}:
	case <-ctx.Done():
		writeErr(w, http.StatusGatewayTimeout, "timeout", "변환 대기 시간 초과")
		return
	}
	s.busy.Add(1)
	res, err := s.conv.Convert(ctx, src, format)
	s.busy.Add(-1)
	<-s.sem

	name := r.Header.Get("X-File-Name")
	if dec, derr := url.QueryUnescape(name); derr == nil {
		name = dec
	}
	elapsed := time.Since(start).Milliseconds()

	if err != nil {
		switch {
		case errors.Is(ctx.Err(), context.DeadlineExceeded):
			log.Printf("convert timeout format=%s drm=%v size=%d elapsed=%dms", format, isDRM, size, elapsed)
			writeErr(w, http.StatusGatewayTimeout, "timeout", "변환 시간 초과")
		default:
			var ce *ConvertError
			msg := err.Error()
			status, code := http.StatusInternalServerError, "internal"
			if errors.As(err, &ce) {
				status, code = http.StatusUnprocessableEntity, "convert_failed"
			}
			log.Printf("convert failed format=%s drm=%v size=%d elapsed=%dms err=%s", format, isDRM, size, elapsed, msg)
			body := map[string]any{"code": code, "error": msg, "drm": isDRM}
			if isDRM {
				body["hint"] = "DRM 문서는 DRM 에이전트가 설치·로그인된 PC 의 Office 에서만 열린다"
			}
			writeJSON(w, status, body)
		}
		return
	}

	log.Printf("convert ok format=%s drm=%v size=%d units=%d chars=%d elapsed=%dms name=%q",
		format, isDRM, size, res.Units, len([]rune(res.Text)), elapsed, filepath.Base(name))
	writeJSON(w, http.StatusOK, convertResponse{
		Text: res.Text, Format: format, Units: res.Units, Unit: res.Unit,
		DRM: isDRM, Chars: len([]rune(res.Text)), ElapsedMs: elapsed,
	})
}

// saveBody — 본문을 dst 로 스트리밍 저장하면서 선두 바이트로 내용 종류를 판정한다.
func saveBody(w http.ResponseWriter, r *http.Request, dst string, maxBytes int64) (contentKind, int64, error) {
	body := http.MaxBytesReader(w, r.Body, maxBytes)
	f, err := os.OpenFile(dst, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o600)
	if err != nil {
		return kindUnknown, 0, err
	}
	defer f.Close()

	head := make([]byte, headerPeek)
	n, err := io.ReadFull(body, head)
	if err != nil && !errors.Is(err, io.ErrUnexpectedEOF) && !errors.Is(err, io.EOF) {
		return kindUnknown, 0, err
	}
	head = head[:n]
	if _, err := f.Write(head); err != nil {
		return kindUnknown, 0, err
	}
	rest, err := io.Copy(f, body)
	if err != nil {
		return kindUnknown, 0, err
	}
	return detectKind(head), int64(n) + rest, nil
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func writeErr(w http.ResponseWriter, status int, code, msg string) {
	writeJSON(w, status, map[string]any{"code": code, "error": msg})
}
