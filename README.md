# Kubernetes CIS Benchmark Security Scanner & Remediation System

Hệ thống quét và khắc phục bảo mật Kubernetes dựa trên CIS Benchmark, tích hợp với Ansible để tự động hóa việc kiểm tra và khắc phục các vấn đề bảo mật trên Kubernetes cluster.

## 📋 Tổng quan

Dự án này cung cấp một giải pháp toàn diện để:
- **Quét bảo mật**: Thực hiện các kiểm tra CIS Benchmark trên Kubernetes cluster
- **Khắc phục tự động**: Sử dụng Ansible để tự động khắc phục các vấn đề bảo mật
- **Báo cáo**: Tạo và xuất báo cáo chi tiết về tình trạng bảo mật
- **Quản lý chính sách**: Tích hợp với Gatekeeper và ArgoCD để quản lý chính sách bảo mật

## ✨ Tính năng chính

- ✅ **CIS Benchmark Scanning**: Quét toàn diện theo tiêu chuẩn CIS Kubernetes Benchmark
- ✅ **Automated Remediation**: Tự động khắc phục các vấn đề bảo mật thông qua Ansible
- ✅ **Multi-format Reports**: Xuất báo cáo dưới nhiều định dạng (HTML, JSON, PDF)
- ✅ **Remote Cluster Support**: Hỗ trợ quét cluster từ xa thông qua SSH và Ansible
- ✅ **Real-time Monitoring**: Dashboard theo dõi trạng thái quét và khắc phục
- ✅ **Policy Management**: Tích hợp với Gatekeeper và ArgoCD cho GitOps
- ✅ **AI-Powered Policy Generation (MCP Bot)**: Tự động sinh chính sách Gatekeeper từ mô tả bằng ngôn ngữ tự nhiên
- ✅ **Multi-LLM Support**: Hỗ trợ nhiều LLM providers (Qwen, Gemini, Ollama)
- ✅ **GitOps Integration**: Tự động tạo Pull Request với policies đã sinh

## 🏗️ Kiến trúc hệ thống

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend (React)                         │
│              Port: 3000                                     │
└────────────────────┬────────────────────────────────────────┘
                     │ HTTP/REST API
┌────────────────────▼────────────────────────────────────────┐
│            Unified Backend (Flask)                          │
│              Port: 3001                                     │
│  ┌──────────────┬──────────────┬──────────────┐            │
│  │   Kube-check │   Ansible   │   Storage    │            │
│  │   Service    │   Service   │   Service    │            │
│  └──────┬───────┴──────┬───────┴──────────────┘            │
└─────────┼──────────────┼────────────────────────────────────┘
          │              │
    ┌─────▼──────┐  ┌────▼─────┐
    │ Kubernetes │  │  SSH     │
    │  Cluster   │  │  Nodes   │
    └────────────┘  └──────────┘
```

### Các thành phần chính

1. **Frontend (React + TypeScript)**
   - Dashboard quản lý benchmark
   - Giao diện quét và khắc phục
   - Xem kết quả và báo cáo

2. **Unified Backend (Flask)**
   - API server tích hợp tất cả chức năng
   - Kube-check service: Thực hiện quét CIS Benchmark
   - Ansible service: Quản lý kết nối và khắc phục từ xa
   - Storage service: Lưu trữ kết quả quét và metadata

3. **Kube-check**
   - Tool quét bảo mật Kubernetes
   - Hỗ trợ CIS Benchmark v1.30
   - Xuất báo cáo đa định dạng

4. **Ansible**
   - Playbooks để kết nối và khắc phục trên cluster
   - Quản lý SSH keys và inventory
   - Tự động hóa các tác vụ bảo mật

5. **Policies & MCP Bot**
   - Gatekeeper policies và templates
   - **MCP Bot**: AI-powered tool để tự động sinh Gatekeeper policies
   - Hỗ trợ nhiều LLM providers (Qwen Cloud, Qwen Local/Ollama, Gemini)
   - Tự động tạo Pull Request với policies đã sinh
   - Tích hợp với ArgoCD cho GitOps workflow

## 📁 Cấu trúc thư mục

```
DACN/
├── Frontend/                 # React frontend application
│   ├── src/                  # Source code
│   ├── public/               # Static files
│   ├── Dockerfile            # Frontend Dockerfile
│   └── package.json          # Dependencies
│
├── unified-backend/          # Flask backend (main service)
│   ├── routes/               # API routes
│   │   ├── scans.py          # Scan endpoints
│   │   ├── remediation.py   # Remediation endpoints
│   │   ├── selections.py     # Selection management
│   │   ├── k8s.py            # K8s connection
│   │   └── ...
│   ├── services/             # Business logic
│   │   ├── kube_check.py     # Kube-check integration
│   │   ├── ansible_service.py # Ansible integration
│   │   └── storage.py        # Data storage
│   ├── app.py                # Flask application
│   ├── Dockerfile            # Backend Dockerfile
│   └── requirements.txt      # Python dependencies
│
├── Kube-check/               # CIS Benchmark scanner
│   ├── src/                  # Scanner source code
│   ├── config/               # CIS Benchmark configs
│   └── reports/              # Generated reports
│
├── ansible/                   # Ansible configuration
│   ├── playbooks/            # Ansible playbooks
│   │   ├── kube-check-scan.yml
│   │   ├── kube-check-remediate.yml
│   │   └── ...
│   ├── inventory/            # Cluster inventory
│   ├── ssh_keys/             # SSH keys
│   └── ansible.cfg           # Ansible config
│
├── policies/                  # Gatekeeper policies
│   └── mcp_bot/              # MCP Bot for policy generation
│
├── control-kltn/             # Kubernetes manifests
│   ├── base/                 # Base configurations
│   └── cluster/              # Cluster-specific configs
│       ├── argocd/           # ArgoCD applications
│       └── gatekeeper/       # Gatekeeper configs
│
├── demo-test-resources/       # Test resources and demos
│
├── scripts/                   # Utility scripts
│
└── docker-compose.unified.yml # Docker Compose configuration
```

## 🚀 Yêu cầu hệ thống

### Phần mềm cần thiết

- **Docker** >= 20.10
- **Docker Compose** >= 2.0
- **Python** >= 3.9 (cho development)
- **Node.js** >= 18 (cho frontend development)
- **Kubernetes** cluster (local hoặc remote)
- **SSH access** đến các nodes (cho remote mode)

### Quyền truy cập

- **Local mode**: Quyền đọc các file cấu hình Kubernetes trên master node
- **Remote mode**: SSH access với sudo privileges trên các nodes

## 📦 Cài đặt

### 1. Clone repository

```bash
git clone <repository-url>
cd DACN
```

### 2. Cấu hình Ansible Inventory

Tạo file `ansible/inventory/my-cluster_hosts.yml`:

```yaml
all:
  children:
    kube_control_plane:
      hosts:
        master1:
          ansible_host: 192.168.1.111
          ansible_user: ansible
    kube_node:
      hosts:
        node1:
          ansible_host: 192.168.1.112
          ansible_user: ansible
```

### 3. Cấu hình SSH Keys

Đảm bảo SSH keys đã được setup cho user `ansible` trên các nodes:

```bash
# Copy SSH key đến các nodes
./scripts/setup-ansible-user.sh
```

### 4. Tạo file `.env` (tùy chọn)

```bash
cp .env.example .env
# Chỉnh sửa các biến môi trường nếu cần
```

### 5. Chạy với Docker Compose

```bash
docker-compose -f docker-compose.unified.yml up -d
```

Services sẽ chạy tại:
- Frontend: http://localhost:3000
- Backend API: http://localhost:3001

## 🔧 Cấu hình

### Environment Variables

#### Backend (unified-backend)

| Biến | Mô tả | Mặc định |
|------|-------|----------|
| `K8S_MODE` | Chế độ kết nối: `local` hoặc `remote` | `local` |
| `CLUSTER_NAME` | Tên cluster | `default` |
| `KUBE_CHECK_PATH` | Đường dẫn đến Kube-check | `/app/Kube-check` |
| `ANSIBLE_DIR` | Đường dẫn đến Ansible | `/app/ansible` |
| `PORT` | Port của backend | `3001` |
| `FLASK_ENV` | Môi trường Flask | `production` |
| `GIT_REPO` | Git repository URL cho MCP Bot | - |
| `GIT_USER` | Git username | - |
| `GIT_PAT` | Git Personal Access Token | - |
| `LLM_PROVIDER` | LLM provider: `qwen`, `gemini`, `ollama` | - |
| `QWEN_API_KEY` | Qwen Cloud API key (nếu dùng Qwen Cloud) | - |
| `GEMINI_API_KEY` | Gemini API key (nếu dùng Gemini) | - |
| `QWEN_LOCAL_URL` | Local Qwen/Ollama URL | `http://localhost:11434/v1/chat/completions` |
| `QWEN_LOCAL_MODEL` | Local model name | `qwen2.5-coder` |
| `USE_LOCAL_QWEN` | Sử dụng local Qwen/Ollama | `false` |

#### Frontend

| Biến | Mô tả | Mặc định |
|------|-------|----------|
| `REACT_APP_API_URL` | URL của backend API | `http://unified-backend:3001` |

### Ansible Configuration

File `ansible/ansible.cfg` chứa cấu hình Ansible. Các thiết lập quan trọng:

- `inventory`: Đường dẫn đến inventory file
- `remote_user`: User để SSH vào nodes
- `become`: Sử dụng sudo khi cần

## 💻 Sử dụng

### 1. Truy cập Dashboard

Mở trình duyệt và truy cập: http://localhost:3000

### 2. Kết nối Kubernetes Cluster

- **Local mode**: Đảm bảo kubeconfig đã được mount vào container
- **Remote mode**: Cấu hình inventory và SSH keys trong `ansible/inventory/`

### 3. Chạy Scan

1. Chọn các checks cần quét từ dashboard
2. Chọn cluster và node (nếu remote mode)
3. Click "Run Scan"
4. Xem kết quả trong modal hoặc download báo cáo

### 4. Khắc phục tự động

1. Từ kết quả scan, chọn các checks cần khắc phục
2. Click "Remediate"
3. Xem kết quả khắc phục trong modal

### 5. Xem báo cáo

- Xem trực tiếp trên dashboard
- Download báo cáo HTML/JSON/PDF
- Xem lịch sử các lần scan

### 6. Sinh chính sách với MCP Bot (AI)

1. Truy cập trang "MCP Bot" trên dashboard
2. Nhập yêu cầu bằng ngôn ngữ tự nhiên, ví dụ:
   - "banish pods running as root user"
   - "require resource limits for all deployments"
   - "prevent privileged containers in production namespace"
3. MCP Bot sẽ:
   - Phân tích yêu cầu và tạo PolicySpec
   - Sinh Rego code, Schema và Constraint template
   - Validate policy
   - Tạo Pull Request với policies đã sinh
4. Review và merge PR để áp dụng policies vào cluster

## 🔌 API Endpoints

### Health Check

```http
GET /health
```

### Selections

```http
GET    /api/selections          # Lấy danh sách selections
POST   /api/selections          # Tạo selection mới
GET    /api/selections/:id      # Lấy selection theo ID
DELETE /api/selections/:id      # Xóa selection
```

### Scans

```http
POST   /api/scan                # Bắt đầu scan
GET    /api/scan/:id            # Lấy trạng thái scan
GET    /api/scans               # Lấy danh sách tất cả scans
```

### Remediation

```http
POST   /api/remediate           # Chạy remediation
```

### Reports

```http
GET    /api/reports             # Lấy danh sách reports
GET    /api/download-report/:filename  # Download report
POST   /api/generate-report     # Tạo report mới
```

### Kubernetes Connection

```http
POST   /api/k8s/connect         # Test kết nối K8s
GET    /api/k8s/nodes           # Lấy danh sách nodes
```

### Audit & MCP Bot

```http
GET    /api/audit               # Audit endpoints
POST   /api/mcp/chat            # Chat with MCP Bot to generate policies
```

#### MCP Bot API

**Generate Policy:**
```http
POST /api/mcp/chat
Content-Type: application/json

{
  "message": "banish pods running as root user"
}
```

**Response:**
```json
{
  "status": "success",
  "policy": {
    "policy_name": "no-root-containers",
    "intent": "create",
    "target_kinds": ["Pod", "Deployment", "StatefulSet"],
    "excluded_namespaces": ["kube-system", "gatekeeper-system"]
  },
  "pr_url": "https://github.com/your-org/repo/pull/123",
  "execution_time": 12.5
}
```

## 🐳 Docker Deployment

### Build Images

```bash
# Build frontend
docker build -f Frontend/Dockerfile -t kubecheck-frontend:latest ./Frontend

# Build backend
docker build -f unified-backend/Dockerfile -t kubecheck-backend:latest .
```

### Run với Docker Compose

```bash
# Start services
docker-compose -f docker-compose.unified.yml up -d

# View logs
docker-compose -f docker-compose.unified.yml logs -f

# Stop services
docker-compose -f docker-compose.unified.yml down
```

### Volumes

Các volumes được tạo tự động:
- `kube-check-reports`: Lưu trữ báo cáo scan
- `kube-check-data`: SQLite database
- `ansible-logs`: Logs từ Ansible

## 🛠️ Development

### Setup Development Environment

#### Backend

```bash
cd unified-backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export K8S_MODE=local
export KUBE_CHECK_PATH=../Kube-check
python app.py
```

#### Frontend

```bash
cd Frontend
npm install
npm start
```

### Running Tests

```bash
# Backend tests (nếu có)
cd unified-backend
pytest

# Frontend tests
cd Frontend
npm test
```

## 📊 Monitoring & Logs

### View Logs

```bash
# Backend logs
docker logs kube-check-unified-backend -f

# Frontend logs
docker logs kube-check-frontend -f

# Ansible logs (trong container)
docker exec kube-check-unified-backend cat /app/logs/ansible.log
```

### Database

SQLite database được lưu trong volume `kube-check-data`:
- Location: `/app/data/scans.db` (trong container)
- Có thể truy cập qua storage service API

## 🤖 MCP Bot - AI-Powered Policy Generation

MCP Bot là một tính năng AI cho phép tự động sinh Gatekeeper policies từ mô tả bằng ngôn ngữ tự nhiên.

### Tính năng

- **Intent Parsing**: Phân tích yêu cầu và trích xuất thông tin policy
- **Policy Generation**: Tự động sinh Rego code, Schema và Constraint template
- **Validation**: Validate policies trước khi commit
- **GitOps Integration**: Tự động tạo Pull Request
- **Multi-LLM Support**: Hỗ trợ nhiều LLM providers

### Cấu hình LLM Provider

#### Option 1: Qwen Cloud (Recommended)

```bash
export LLM_PROVIDER=qwen
export QWEN_API_KEY=your_qwen_api_key
export GIT_REPO=https://github.com/your-org/policies-repo.git
export GIT_USER=your_username
export GIT_PAT=your_github_token
```

#### Option 2: Gemini

```bash
export LLM_PROVIDER=gemini
export GEMINI_API_KEY=your_gemini_api_key
export GIT_REPO=https://github.com/your-org/policies-repo.git
export GIT_USER=your_username
export GIT_PAT=your_github_token
```

#### Option 3: Local Qwen/Ollama

```bash
export LLM_PROVIDER=ollama
export USE_LOCAL_QWEN=true
export QWEN_LOCAL_URL=http://localhost:11434/v1/chat/completions
export QWEN_LOCAL_MODEL=qwen2.5-coder
export GIT_REPO=https://github.com/your-org/policies-repo.git
export GIT_USER=your_username
export GIT_PAT=your_github_token
```

### Ví dụ sử dụng

**Tạo policy mới:**
```
"banish pods running as root user"
```

**Cập nhật policy hiện có:**
```
"exempt nginx:1.24.0 from no-root-containers policy"
```

**Tạo policy phức tạp:**
```
"require resource limits for all deployments in production namespace, exclude kube-system"
```

### Workflow

1. User nhập yêu cầu → MCP Bot phân tích intent
2. Tạo PolicySpec JSON từ intent
3. Sinh Rego code, Schema và Constraint template
4. Validate policy với kubeconform
5. Tạo Pull Request với các files đã sinh
6. User review và merge PR
7. ArgoCD tự động sync policies vào cluster

### Cấu trúc Policies Repository

```
policies-repo/
├── base/
│   └── cis_policies_v1.10.0/
│       ├── templates/
│       │   └── no-root-containers-template.yaml
│       └── constraints/
│           └── no-root-containers-constraint.yaml
└── cluster/
    └── gatekeeper/
        └── kustomization.yaml
```

## 🔒 Security Considerations

- **SSH Keys**: Đảm bảo SSH keys được bảo mật và chỉ user `ansible` có quyền truy cập
- **Sudo Access**: User `ansible` cần sudo privileges để thực hiện remediation
- **Network**: Đảm bảo network giữa containers và cluster được bảo mật
- **Secrets**: Không commit secrets vào git, sử dụng environment variables hoặc secrets management

## 🐛 Troubleshooting

### Backend không kết nối được với cluster

1. Kiểm tra kubeconfig đã được mount đúng chưa
2. Kiểm tra quyền truy cập của kubeconfig
3. Xem logs: `docker logs kube-check-unified-backend`

### Ansible không kết nối được nodes

1. Kiểm tra SSH keys trong `ansible/ssh_keys/`
2. Test SSH connection: `ssh ansible@<node-ip>`
3. Kiểm tra inventory file format
4. Xem Ansible logs trong container

### Scan không chạy được

1. Kiểm tra Kube-check path đã đúng chưa
2. Kiểm tra quyền đọc các file cấu hình K8s
3. Xem logs chi tiết trong backend

### Frontend không kết nối được backend

1. Kiểm tra `REACT_APP_API_URL` environment variable
2. Kiểm tra CORS settings trong backend
3. Kiểm tra network trong docker-compose

## 📚 Tài liệu thêm

- [Kube-check README](./Kube-check/README.md)
- [Unified Backend README](./unified-backend/README.md)
- [Ansible Configuration Guide](./docs/ANSIBLE_INTEGRATION.md)
- [Architecture Documentation](./docs/ARCHITECTURE.md)

## 🤝 Đóng góp

1. Fork repository
2. Tạo feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to branch (`git push origin feature/AmazingFeature`)
5. Tạo Pull Request

## 📝 License

[Specify license here]

## 👥 Authors

- [Your Name/Team]

## 🙏 Acknowledgments

- [CIS Kubernetes Benchmark](https://www.cisecurity.org/benchmark/kubernetes)
- [kube-bench](https://github.com/aquasecurity/kube-bench)
- [Open Policy Agent / Gatekeeper](https://open-policy-agent.github.io/gatekeeper/)
- [ArgoCD](https://argoproj.github.io/cd/)
