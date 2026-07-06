# 로컬 환경 설치 가이드

## 필수 설치 항목

### 1. Python 3.11+ 설치

#### macOS (Homebrew)
```bash
# Homebrew 설치 (없는 경우)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Python 설치
brew install python@3.11

# 확인
python3.11 --version
```

#### 또는 pyenv 사용 (권장)
```bash
# pyenv 설치
brew install pyenv

# Python 3.11 설치
pyenv install 3.11.9
pyenv global 3.11.9

# 셸 설정 추가 (zsh)
echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.zshrc
echo 'command -v pyenv >/dev/null || export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.zshrc
echo 'eval "$(pyenv init -)"' >> ~/.zshrc

# 셸 재시작
exec "$SHELL"

# 확인
python --version  # Python 3.11.9
```

### 2. Node.js 20+ 설치 (@module-federation/vite 요구)

#### macOS (Homebrew)
```bash
# Node.js 설치
brew install node

# 확인
node --version  # v18.x.x 이상
npm --version
```

#### 또는 nvm 사용 (권장)
```bash
# nvm 설치
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash

# 셸 재시작
exec "$SHELL"

# Node.js LTS 설치
nvm install --lts
nvm use --lts

# 확인
node --version
npm --version
```

---

## 프로젝트 의존성 설치

### 1. Backend 설정

```bash
cd /Users/dukekimm/Works/RAGaaS/backend

# 가상환경 생성 (선택사항이지만 권장)
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 의존성 설치
pip install --upgrade pip
pip install -r requirements.txt

# 확인
python -m pip show uvicorn fastapi
```

### 2. Ingest Service 설정

```bash
cd /Users/dukekimm/Works/RAGaaS/ingest_service

# 가상환경 생성 (선택사항)
python3 -m venv venv
source venv/bin/activate

# 의존성 설치
pip install --upgrade pip
pip install -r requirements.txt

# 확인
python -m pip show uvicorn llama-index
```

### 3. Frontend 설정

```bash
cd /Users/dukekimm/Works/RAGaaS/frontend

# 의존성 설치
npm install

# 확인
npm list react vite
```

---

## 실행 방법

설치가 완료되면 3개의 터미널을 열어서 각각 실행:

### 터미널 1: Backend
```bash
cd /Users/dukekimm/Works/RAGaaS/backend
source venv/bin/activate  # 가상환경 사용 시
uvicorn app.main:app --reload --port 8000
```

### 터미널 2: Ingest Service
```bash
cd /Users/dukekimm/Works/RAGaaS/ingest_service
source venv/bin/activate  # 가상환경 사용 시
uvicorn app.main:app --reload --port 8001
```

### 터미널 3: Frontend
```bash
cd /Users/dukekimm/Works/RAGaaS/frontend
npm run dev
```

---

## 접속 URL

- Frontend: http://localhost:3002
- Backend API: http://localhost:8000/docs
- Ingest Service: http://localhost:8001/docs

---

## 문제 해결

### Python 관련

#### "command not found: python"
```bash
# Python 경로 확인
which python3

# 심볼릭 링크 생성 (선택)
sudo ln -s /usr/bin/python3 /usr/local/bin/python
```

#### "ModuleNotFoundError"
```bash
# 가상환경이 활성화되어 있는지 확인
which python  # venv 경로여야 함

# 의존성 재설치
pip install -r requirements.txt
```

#### "Permission denied" 에러
```bash
# pip 업그레이드
python -m pip install --upgrade pip

# 또는 --user 플래그 사용
pip install --user -r requirements.txt
```

### Node.js 관련

#### "EACCES: permission denied"
```bash
# npm 캐시 정리
npm cache clean --force

# node_modules 재설치
rm -rf node_modules package-lock.json
npm install
```

#### "Port 3002 is already in use"
```bash
# 포트 사용 프로세스 찾기
lsof -i :3002

# 프로세스 종료
kill -9 <PID>
```

---

## 빠른 설치 스크립트

전체를 한 번에 설치하려면:

```bash
# 1. Python & Node.js 설치 (Homebrew)
brew install python@3.11 node

# 2. Backend 설정
cd /Users/dukekimm/Works/RAGaaS/backend
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 3. Ingest Service 설정
cd /Users/dukekimm/Works/RAGaaS/ingest_service
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 4. Frontend 설정
cd /Users/dukekimm/Works/RAGaaS/frontend
npm install

echo "설치 완료! DEV_RUN.md를 참고하여 실행하세요."
```

---

## 참고

- 자세한 실행 방법: `DEV_RUN.md`
- Docker 사용 시: `docker-compose.yml` 주석 해제 후 `docker-compose up -d`
