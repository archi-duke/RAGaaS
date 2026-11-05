package main

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"
)

type fakeConv struct {
	req     map[string]bool
	gotFile []byte
	gotFmt  string
	result  *ConvertResult
	err     error
	sleep   time.Duration
}

func (f *fakeConv) Convert(ctx context.Context, src, format string) (*ConvertResult, error) {
	f.gotFile, _ = os.ReadFile(src)
	f.gotFmt = format
	if f.sleep > 0 {
		select {
		case <-time.After(f.sleep):
		case <-ctx.Done():
			return nil, ctx.Err()
		}
	}
	return f.result, f.err
}

func (f *fakeConv) Requirements() map[string]bool {
	if f.req != nil {
		return f.req
	}
	return map[string]bool{"powershell": true, "word": true, "powerpoint": true}
}

func newTestServer(t *testing.T, cfg *Config, conv Converter) http.Handler {
	t.Helper()
	if cfg.DataDir == "" {
		cfg.DataDir = t.TempDir()
	}
	if cfg.MaxBytes == 0 {
		cfg.MaxBytes = 1 << 20
	}
	if cfg.Timeout == 0 {
		cfg.Timeout = 5 * time.Second
	}
	return NewServer(cfg, conv).Handler()
}

func doReq(h http.Handler, method, path string, body []byte, hdr map[string]string) *httptest.ResponseRecorder {
	r := httptest.NewRequest(method, path, bytes.NewReader(body))
	for k, v := range hdr {
		r.Header.Set(k, v)
	}
	w := httptest.NewRecorder()
	h.ServeHTTP(w, r)
	return w
}

func decode(t *testing.T, w *httptest.ResponseRecorder) map[string]any {
	t.Helper()
	var m map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &m); err != nil {
		t.Fatalf("응답 JSON 파싱 실패: %v (%s)", err, w.Body.String())
	}
	return m
}

var (
	ooxml  = append([]byte("PK\x03\x04"), bytes.Repeat([]byte{1}, 64)...)
	drmDoc = append([]byte("<## NASCA DRM FILE - VER1.00 ##>"), bytes.Repeat([]byte{2}, 64)...)
	secret = map[string]string{"X-Svc-Secret": "s3cret"}
)

func TestDetectKind(t *testing.T) {
	cases := []struct {
		in   []byte
		want contentKind
	}{
		{ooxml, kindOOXML},
		{drmDoc, kindDRM},
		{[]byte("<## NASCA DRM FILE - VER2.00 ##>"), kindDRM},
		{[]byte("%PDF-1.7"), kindUnknown},
		{[]byte("PK"), kindUnknown},
		{nil, kindUnknown},
	}
	for _, c := range cases {
		if got := detectKind(c.in); got != c.want {
			t.Errorf("detectKind(%q) = %v, want %v", c.in, got, c.want)
		}
	}
}

func TestSecretRequired(t *testing.T) {
	h := newTestServer(t, &Config{Secret: "s3cret"}, &fakeConv{result: &ConvertResult{Text: "x"}})
	if w := doReq(h, "POST", "/v1/docs/docx/text", ooxml, nil); w.Code != http.StatusUnauthorized {
		t.Fatalf("시크릿 없음: got %d", w.Code)
	}
	if w := doReq(h, "POST", "/v1/docs/docx/text", ooxml, map[string]string{"X-Svc-Secret": "wrong"}); w.Code != http.StatusUnauthorized {
		t.Fatalf("시크릿 불일치: got %d", w.Code)
	}
	if w := doReq(h, "GET", "/health", nil, nil); w.Code != http.StatusOK {
		t.Fatalf("/health 는 시크릿 불필요: got %d", w.Code)
	}
}

func TestBrowserOriginRejectedInServiceMode(t *testing.T) {
	h := newTestServer(t, &Config{Secret: "s3cret"}, &fakeConv{})
	hdr := map[string]string{"X-Svc-Secret": "s3cret", "Origin": "http://evil.example"}
	if w := doReq(h, "POST", "/v1/docs/docx/text", ooxml, hdr); w.Code != http.StatusForbidden {
		t.Fatalf("got %d", w.Code)
	}
}

func TestConvertOK(t *testing.T) {
	conv := &fakeConv{result: &ConvertResult{Text: "안녕 slide", Units: 3, Unit: "slide"}}
	h := newTestServer(t, &Config{Secret: "s3cret"}, conv)
	w := doReq(h, "POST", "/v1/docs/pptx/text", ooxml, secret)
	if w.Code != http.StatusOK {
		t.Fatalf("got %d %s", w.Code, w.Body.String())
	}
	m := decode(t, w)
	if m["text"] != "안녕 slide" || m["format"] != "pptx" || m["drm"] != false || m["chars"].(float64) != 8 || m["units"].(float64) != 3 {
		t.Fatalf("응답 불일치: %v", m)
	}
	if conv.gotFmt != "pptx" || !bytes.Equal(conv.gotFile, ooxml) {
		t.Fatalf("변환기에 전달된 파일/형식 불일치: fmt=%s len=%d", conv.gotFmt, len(conv.gotFile))
	}
}

func TestConvertDRMFlag(t *testing.T) {
	conv := &fakeConv{result: &ConvertResult{Text: "decrypted"}}
	h := newTestServer(t, &Config{Secret: "s3cret"}, conv)
	w := doReq(h, "POST", "/v1/docs/docx/text", drmDoc, secret)
	if w.Code != http.StatusOK || decode(t, w)["drm"] != true {
		t.Fatalf("got %d %s", w.Code, w.Body.String())
	}
	if !bytes.Equal(conv.gotFile, drmDoc) {
		t.Fatal("DRM 원본 바이트가 그대로 전달돼야 함")
	}
}

func TestConvertFailureDRMHint(t *testing.T) {
	conv := &fakeConv{err: &ConvertError{Msg: "파일이 손상되었습니다."}}
	h := newTestServer(t, &Config{Secret: "s3cret"}, conv)
	w := doReq(h, "POST", "/v1/docs/docx/text", drmDoc, secret)
	m := decode(t, w)
	if w.Code != http.StatusUnprocessableEntity || m["code"] != "convert_failed" || m["drm"] != true || m["hint"] == nil {
		t.Fatalf("got %d %v", w.Code, m)
	}
}

func TestRejects(t *testing.T) {
	h := newTestServer(t, &Config{Secret: "s3cret", MaxBytes: 128}, &fakeConv{result: &ConvertResult{}})
	cases := []struct {
		name, path string
		body       []byte
		code       int
	}{
		{"형식 미지원", "/v1/docs/xlsx/text", ooxml, http.StatusNotFound},
		{"OOXML 아님", "/v1/docs/docx/text", []byte("%PDF-1.7 hello"), http.StatusUnsupportedMediaType},
		{"빈 본문", "/v1/docs/docx/text", nil, http.StatusBadRequest},
		{"크기 초과", "/v1/docs/docx/text", append([]byte("PK\x03\x04"), bytes.Repeat([]byte{0}, 512)...), http.StatusRequestEntityTooLarge},
	}
	for _, c := range cases {
		if w := doReq(h, "POST", c.path, c.body, secret); w.Code != c.code {
			t.Errorf("%s: got %d want %d (%s)", c.name, w.Code, c.code, w.Body.String())
		}
	}
}

func TestRequirementMissing(t *testing.T) {
	conv := &fakeConv{req: map[string]bool{"powershell": true, "word": false}}
	h := newTestServer(t, &Config{Secret: "s3cret"}, conv)
	w := doReq(h, "POST", "/v1/docs/docx/text", ooxml, secret)
	if w.Code != http.StatusFailedDependency {
		t.Fatalf("got %d", w.Code)
	}
}

func TestTimeout(t *testing.T) {
	conv := &fakeConv{sleep: 2 * time.Second, result: &ConvertResult{}}
	h := newTestServer(t, &Config{Secret: "s3cret", Timeout: 100 * time.Millisecond}, conv)
	w := doReq(h, "POST", "/v1/docs/docx/text", ooxml, secret)
	if w.Code != http.StatusGatewayTimeout {
		t.Fatalf("got %d", w.Code)
	}
}

func TestDevModeCORSAndStubs(t *testing.T) {
	h := newTestServer(t, &Config{Dev: true, DevOrigins: []string{"http://localhost:5173"}}, &fakeConv{result: &ConvertResult{Text: "ok"}})

	w := doReq(h, "OPTIONS", "/v1/docs/docx/text", nil, map[string]string{
		"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
		"Access-Control-Request-Private-Network": "true",
	})
	if w.Code != http.StatusNoContent || w.Header().Get("Access-Control-Allow-Private-Network") != "true" ||
		w.Header().Get("Access-Control-Allow-Origin") != "http://localhost:5173" {
		t.Fatalf("preflight: %d %v", w.Code, w.Header())
	}
	if w := doReq(h, "OPTIONS", "/v1/docs/docx/text", nil, map[string]string{"Origin": "http://other"}); w.Code != http.StatusForbidden {
		t.Fatalf("허용 안 된 origin: %d", w.Code)
	}

	w = doReq(h, "GET", "/launcher/health", nil, map[string]string{"Origin": "http://localhost:5173"})
	if w.Code != http.StatusOK || decode(t, w)["token"] != "dev" {
		t.Fatalf("launcher health stub: %d %s", w.Code, w.Body.String())
	}
	w = doReq(h, "GET", "/launcher/capabilities", nil, nil)
	if w.Code != http.StatusOK || !strings.Contains(w.Body.String(), "/v1/docs/pptx") {
		t.Fatalf("capabilities stub: %d %s", w.Code, w.Body.String())
	}
	w = doReq(h, "POST", "/v1/docs/docx/text", ooxml, map[string]string{"Origin": "http://localhost:5173"})
	if w.Code != http.StatusOK {
		t.Fatalf("dev convert: %d %s", w.Code, w.Body.String())
	}
}

func TestLoadConfig(t *testing.T) {
	t.Setenv("SVC_PORT", "")
	t.Setenv("SVC_SECRET", "")
	if _, _, err := loadConfig(nil); err == nil {
		t.Fatal("SVC_PORT 없이 서비스 모드 기동은 실패해야 함")
	}
	t.Setenv("SVC_PORT", "40123")
	if _, _, err := loadConfig(nil); err == nil {
		t.Fatal("SVC_SECRET 없이 서비스 모드 기동은 실패해야 함")
	}
	t.Setenv("SVC_SECRET", "x")
	cfg, _, err := loadConfig(nil)
	if err != nil || cfg.Port != 40123 {
		t.Fatalf("cfg=%+v err=%v", cfg, err)
	}
	t.Setenv("SVC_PORT", "")
	t.Setenv("SVC_SECRET", "")
	cfg, _, err = loadConfig([]string{"-dev", "-dev-origin", "http://a, http://b/"})
	if err != nil || cfg.Port != defaultDevPort || len(cfg.DevOrigins) != 2 || cfg.DevOrigins[1] != "http://b" {
		t.Fatalf("dev cfg=%+v err=%v", cfg, err)
	}
}
