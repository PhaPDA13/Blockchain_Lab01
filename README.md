# Blockchain Lab 01: Layer 1 Blockchain Simulator with BFT Consensus

## 1. Thông Tin Nhóm / Member Information
- **Nguyễn Gia Huy**: 23120273
- **Bùi Duy Khánh**: 231204281
- **Nguyễn Đăng Khoa**: 23120315
- **Nguyễn Ngọc Nhân Trọng**: 23120382

---

## 2. Cấu Trúc Dự Án / Project Structure


```text
Lab01_ID1_ID2_ID3_ID4_ID5/
├── src/
│   ├── crypto/           # Ed25519, hashing SHA-256, canonical encoding, domain separation
│   ├── execution/        # Key-value state transitions, anti-replay, block/header structures
│   ├── consensus/        # BFT 2-phase engine (Prevote & Precommit) với 7 quy tắc khóa khối
│   ├── network/          # Mô phỏng mạng không tin cậy (delay, drop, dup), deterministic logger
│   └── node.py           # Validator node tích hợp toàn bộ các tầng
├── tests/
│   ├── unit/             # Unit tests: crypto, state, consensus locking rules
│   ├── e2e/              # End-to-end tests: 8 kịch bản bắt buộc (T1 - T8)
│   └── run_all_tests.py  # Single entry point gọi toàn bộ test suites
├── config/
│   └── default_config.json # Cấu hình mạng (>= 8 nodes, delta, seed, round timeouts)
├── logs/                 # Thư mục lưu vết byte-identical logs
├── README.md             # Hướng dẫn build, chạy simulator và chạy test
├── REPORT.pdf            # Báo cáo kỹ thuật (tối đa 10 trang)
└── requirements.txt      # Thư viện phụ thuộc (cryptography, pytest)
```

---

## 3. Cài Đặt Môi Trường / Environment Setup

Yêu cầu: **Python >= 3.10**

```bash
# 1. Khởi tạo môi trường ảo (khuyến nghị)
python -m venv .venv
# Trên Windows PowerShell:
.venv\Scripts\Activate.ps1

# 2. Cài đặt các thư viện cần thiết
pip install -r requirements.txt
```

---

## 4. Chạy Kiểm Thử / Running Tests

Mục 9 của `Lab01.pdf` yêu cầu toàn bộ test phải tái lập được và gọi được từ một entry point duy nhất:

```bash
# Chạy toàn bộ test suites (Unit tests + End-to-End T1->T8)
python -m tests.run_all_tests
```

Hoặc dùng `pytest`:
```bash
pytest -v tests/
```

### Danh sách kịch bản E2E (T1 - T8):
- **T1**: Normal run, no faults -> Tất cả các node honest chốt cùng chain và state hash.
- **T2**: Duplicate/reordered messages -> Không tính trùng phiếu bầu, không xung đột kết quả chốt khối.
- **T3**: Invalid signature / wrong domain -> Từ chối thông điệp có context sai (ví dụ sai chain_id).
- **T4**: Replayed/duplicate transaction -> Áp dụng nhiều nhất 1 lần duy nhất nhờ nonce và tx hash check.
- **T5**: Drop/delay before synchrony -> Đảm bảo tính Safety (không có 2 khối khác nhau ở cùng height).
- **T6**: Proposer silent/crashed -> Kích hoạt round timeout, chuyển sang proposer kế tiếp.
- **T7**: Up to f Byzantine validators equivocate -> Chống gian lận phân thân (n=8, f=2).
- **T8**: Same seed rerun twice -> Tái lập chính xác từng byte log và state hash cuối cùng.

---

## 5. Đóng Gói Bài Nộp / Packaging Submission


Bạn có thể sử dụng script hỗ trợ `package_submission.py`:

```bash
python package_submission.py --ids 2310315
```
*(Nếu làm theo nhóm, truyền danh sách MSSV: `python package_submission.py --ids 2310315 2310316 ...`)*

Script sẽ tự động gom các thư mục `src/`, `tests/`, `logs/`, `config/`, `README.md`, `REPORT.pdf` vào đúng định dạng thư mục `Lab01_ID1_ID2_...` và nén thành `Lab01_ID1_ID2_....zip`.
