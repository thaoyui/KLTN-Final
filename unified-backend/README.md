# Unified Flask Backend

**Gộp Backend Node.js + Kube-check + Ansible thành một Flask server duy nhất**

## 📋 Tổng quan

Unified Flask Backend **thay thế**:
- ❌ **Backend Node.js** (Express.js) → ✅ **Flask Backend**
- ❌ **Kube-check container riêng** → ✅ **Import trực tiếp vào Flask**
- ❌ **Ansible Service container riêng** → ✅ **Tích hợp vào Flask**

**Lưu ý quan trọng:**
- ✅ **Kube-check code vẫn cần** (mount volume `/app/Kube-check`)
- ✅ **Ansible playbooks vẫn cần** (mount volume `/app/ansible`)
- ❌ **Không cần containers riêng** cho Kube-check và Ansible nữa

## 🏗️ Kiến trúc

```
Frontend (React)
    ↓ HTTP
Unified Flask Backend
    ├─→ Kube-check (import trực tiếp từ /app/Kube-check)
    │   - Code: mount volume
    │   - Config: mount volume
    │   - Không container riêng
    │
    └─→ Ansible (tích hợp trực tiếp)
        - Playbooks: mount volume
        - Configs: mount volume
        - Không container riêng
```

**Chi tiết:**
- Kube-check code được **mount như volume** (`./Kube-check:/app/Kube-check`)
- Ansible configs được **mount như volume** (`./ansible:/app/ansible`)
- **Import trực tiếp** vào Python, không spawn processes
- **Tích hợp** vào Flask, không HTTP calls

## 🚀 Setup

### 1. Install dependencies
un
```bash
cd unified-backend
pip install -r requirements.txt
```

### 2. Environment variables

```bash
export K8S_MODE=local  # or 'remote'
export CLUSTER_NAME=default
export KUBE_CHECK_PATH=/app/Kube-check
export PORT=3001
export IP=0.0.0.0
```

### 3. Run

```bash
python app.py
```

Server sẽ chạy tại `http://localhost:3001`

## 📦 Docker

### Build

```bash
docker build -f unified-backend/Dockerfile -t unified-backend .
```

### Run với Docker Compose

Xem `docker-compose.unified.yml` (sẽ tạo)

## 🔗 API Endpoints

Tất cả endpoints giữ nguyên như Node.js backend:

- `GET /health` - Health check
- `GET /api/selections` - Get all selections
- `POST /api/selections` - Create selection
- `GET /api/selections/:id` - Get selection
- `POST /api/scan` - Start scan
- `GET /api/scan/:id` - Get scan status
- `GET /api/scans` - Get all scans
- `POST /api/remediate` - Run remediation
- `POST /api/generate-report` - Generate report
- `GET /api/download-report/:filename` - Download report
- `GET /api/reports` - List reports
- `POST /api/k8s/connect` - Test K8s connection

## ✅ Ưu điểm

1. **Đơn giản hơn**: 1 service thay vì 2
2. **Performance tốt hơn**: Import trực tiếp, không spawn processes
3. **Dễ maintain**: Tất cả Python, không cần Node.js
4. **Tích hợp Ansible**: Cùng ngôn ngữ, dễ share code

## ⚠️ Lưu ý

- Cần test kỹ với Frontend
- In-memory storage (có thể thay bằng Redis)
- Một số edge cases có thể cần fix

## 🔄 Migration từ Node.js

1. **Backup**: Giữ Node.js version làm backup
2. **Test**: Test từng endpoint
3. **Switch**: Update Frontend API URL
4. **Remove**: Xóa Node.js backend khi đã stable

