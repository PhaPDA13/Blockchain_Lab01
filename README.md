# Blockchain Lab 01 — Mô phỏng blockchain Layer 1 với BFT

## 1. Mục tiêu

Dự án mô phỏng một mạng validator Layer 1 tối giản theo đặc tả của **Lab 01 (Blockchain Course 2026)**. Các node nhận transaction và block qua mạng mô phỏng không tin cậy (unreliable network), xác minh chữ ký, kiểm tra quyền sở hữu và nonce, bỏ phiếu qua hai pha **PREVOTE / PRECOMMIT**, khóa khối (locking) và chốt block đạt tính tin cậy tuyệt đối (*reliable finality*).

Hệ thống hiện thực các thành phần cốt lõi của đề bài; các giới hạn của mô phỏng được nêu trong `REPORT.pdf`:

- **Cryptography layer (Mục 5):** Chữ ký Ed25519, hàm băm SHA-256, domain separation (`TX:chain_id`, `HEADER:chain_id`, `VOTE:chain_id`) và mã hóa canonical byte xác định.
- **Execution layer (Mục 7):** State key–value với quyền sở hữu khóa (`sender/key`), nonce chống replay, chuyển dịch trạng thái tất cả-hoặc-không và cam kết state root.
- **Consensus layer & Locking rules (Mục 6.1):** Đồng thuận BFT 2 pha tuân thủ nghiêm ngặt 7 quy tắc khóa khối, đếm quorum $2f + 1$ với $n = 3f + 1$.
- **Network layer (Mục 6):** Mô phỏng trễ ngẫu nhiên (delay), mất gói (drop), lặp gói (duplicate), đảo thứ tự (reorder), giới hạn tốc độ (rate limit) và chặn/mở chặn peer (block/unblock). Đóng gói header trước body (`HEADER` broadcast $\rightarrow$ `BODY_REQUEST` $\rightarrow$ `BODY`).
- **Determinism & Logging (Mục 8):** Ghi vết toàn bộ sự kiện mạng và đồng thuận thành log canonical byte-identical khi chạy cùng seed.
- **Testing requirements (Mục 9):** Bộ unit test và end-to-end scenarios T1–T8 có thể gọi từ một entry point duy nhất.

---

## 2. Thành viên nhóm

| STT | Họ và tên | MSSV |
|:---:|---|:---:|
| 1 | Nguyễn Gia Huy | `23120273` |
| 2 | Bùi Duy Khánh | `23120281` |
| 3 | Nguyễn Đăng Pha | `23120315` |
| 4 | Nguyễn Ngọc Nhân Trọng | `23120382` |

---

## 3. Cấu trúc thư mục dự án

Dự án được tổ chức chuẩn theo quy định tại **Mục 10 (Submission regulation)** của `Lab01.pdf`:

```text
Lab01_23120273_23120281_23120315_23120382/
├── src/
│   ├── crypto/                 # Tầng mật mã
│   │   ├── encoding.py         # Mã hóa canonical byte xác định (JSON sorted keys)
│   │   ├── hashing.py          # Băm SHA-256, tính state_root
│   │   └── identity.py         # Quản lý khóa Ed25519 & ký/xác minh domain separation
│   ├── execution/              # Tầng thực thi trạng thái
│   │   ├── transaction.py      # Cấu trúc transaction, kiểm tra quyền sở hữu & nonce
│   │   ├── block.py            # Cấu trúc Block & BlockHeader, transaction_root
│   │   └── state.py            # Key-value state, apply_transaction (all-or-nothing)
│   ├── consensus/              # Tầng đồng thuận BFT
│   │   ├── vote.py             # Cấu trúc Vote (PREVOTE / PRECOMMIT) & domain signing
│   │   ├── rules.py            # Quản lý 7 quy tắc khóa khối (ConsensusLockState)
│   │   └── engine.py           # Quản lý vòng đồng thuận, quorum n = 3f + 1, round-robin
│   ├── network/                # Tầng mạng mô phỏng
│   │   ├── message.py          # Định dạng thông điệp: TX, HEADER, BODY_REQUEST, BODY, VOTE
│   │   ├── simulator.py        # Hàng đợi delay, drop, duplicate, rate limit, peer block
│   │   ├── logger.py           # Bộ ghi vết sự kiện xác định (logical timestamp)
│   │   └── runner.py           # Vòng lặp sự kiện, timeout, retransmit, finality certificate
│   └── node.py                 # Full validator node tích hợp các tầng
├── tests/
│   ├── unit/                   # Unit tests
│   │   ├── test_crypto.py      # Kiểm tra canonical encoding, SHA-256, domain separation
│   │   ├── test_state.py       # Kiểm tra ownership, nonce ordering, state root
│   │   ├── test_consensus.py   # Kiểm tra quorum 2f+1, deduplication, locking
│   │   ├── test_block.py       # Kiểm tra hợp lệ proposal, sai chữ ký, parent, state root
│   │   └── test_network.py     # Kiểm tra rate limit, peer blocking, delivery callback
│   ├── e2e/                    # End-to-end scenarios T1–T8
│   │   └── test_scenarios.py   # Kịch bản T1–T8 và kiểm tra đa chiều / phục hồi mạng
│   └── run_all_tests.py        # Single entry point gọi toàn bộ suite
├── config/
│   └── default_config.json     # Cấu hình mạng (10 validator, f=3, quorum 2f+1=7, seed)
├── logs/                       # Thư mục lưu vết log mô phỏng (canonical byte logs)
├── README.md                   # Hướng dẫn build, chạy simulator và chạy test
├── REPORT.pdf                  # Báo cáo kỹ thuật chi tiết
├── requirements.txt            # Thư viện phụ thuộc (cryptography, pytest)
├── pytest.ini                  # Cấu hình pytest (tắt anyio plugin)
├── run_simulation.py           # Script chạy mô phỏng 1 block hoàn chỉnh
└── package_submission.py       # Script đóng gói bài nộp đúng quy cách
```

---

## 4. Yêu cầu môi trường & Cài đặt

### Yêu cầu
- **Python**: Phiên bản `3.10` trở lên (đã kiểm thử ổn định trên Python 3.11).
- **Thư viện**: `cryptography >= 42.0.0` và `pytest >= 8.0.0`.

### Cài đặt môi trường

Chạy các lệnh sau từ thư mục gốc của dự án:

**Trên Windows (PowerShell):**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

**Trên Linux / macOS:**
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

---

## 5. Cấu hình mạng & Tham số Quorum

Cấu hình mặc định được lưu tại [`config/default_config.json`](config/default_config.json). Hệ thống mặc định thiết lập **10 validator**, thỏa điều kiện $n = 3f + 1$ với $n \ge 8$:

| Đại lượng | Ký hiệu | Giá trị mặc định | Quy tắc kiểm tra |
|---|:---:|:---:|---|
| Số validator | $n$ | `10` | Hỗ trợ cấu hình $n \ge 8$ (chuẩn $n = 3f + 1$) |
| Số lỗi Byzantine tối đa | $f$ | `3` | $f = \lfloor(n - 1) / 3\rfloor$ |
| Kích thước Quorum | $Q$ | `7` | $Q = \lfloor 2n / 3 \rfloor + 1$ ($= 2f + 1$ khi $n = 3f + 1$) |

Bảng giải nghĩa các trường cấu hình:

| Trường cấu hình | Ý nghĩa & Đơn vị |
|---|---|
| `chain_id` | Chuỗi định danh chuỗi dùng trong context domain separation (`TX:chain_id`, `HEADER:chain_id`, `VOTE:chain_id`). |
| `num_nodes` | Số lượng validator tham gia mạng ($n \ge 8$). |
| `max_byzantine_faults` | Số lỗi Byzantine tối đa cho phép ($f$). |
| `drop_rate`, `duplicate_rate` | Xác suất làm rơi gói hoặc nhân bản gói trước thời điểm ổn định ($0.0 \le p \le 1.0$). |
| `min_delay_ticks`, `max_delay_ticks` | Khoảng trễ ngẫu nhiên trước khi mạng ổn định (tính theo tick). |
| `stabilization_time_ticks` | Thời điểm mạng chuyển sang trạng thái đồng bộ một phần (sau thời điểm này không drop/dup). |
| `delta_bound_ticks` | Cận trên trễ thông điệp $\Delta$ sau khi mạng ổn định. |
| `max_outbound_rate`, `rate_window_ticks` | Giới hạn số lượng gói tin một node được phép gửi trong một cửa sổ tick. |
| `timeout_round_ticks` | Thời gian timeout cơ sở của một round trước khi chuyển round. |
| `retransmit_interval_ticks` | Chu kỳ gửi lại (retransmit) header và vote còn hiệu lực. |
| `random_seed` | Hạt giống ngẫu nhiên tạo tính xác định (*deterministic*) cho toàn bộ mô phỏng. |

*Lưu ý: Thời gian trong simulator là số tick logic rời rạc (discrete logical ticks), không phụ thuộc vào đồng hồ thực.*

---

## 6. Kiến trúc hệ thống & Quy tắc đồng thuận

### Luồng thông điệp qua mạng mô phỏng
```text
Client Transaction
        │ Ký với context TX:chain_id
        ▼
NetworkSimulator ──► Ingress Node / mempool
                         │ Proposer đề xuất block ở height h, round r
                         ▼
                    HEADER broadcast (parent_hash, state_root, tx_root)
                         │ Node kiểm tra tính hợp lệ của Header
                         ▼
                    BODY_REQUEST ──► Gửi BODY (danh sách transaction)
                         │ Thực thi block trên bản sao State
                         ▼
                PREVOTE quorum (2f + 1 phiếu)
                         │ Khóa block (Locking Rule 4)
                         ▼
                PRECOMMIT quorum (2f + 1 phiếu)
                         │ Chốt block vào sổ cái (Finalization)
                         ▼
                  Finalize / Cập nhật trạng thái
                         │ Gửi Finality Certificate
                         └── Hỗ trợ các node chậm / trễ bắt kịp (Catch-up)
```

### 7 Quy tắc khóa khối & bỏ phiếu (Mục 6.1 đề bài)
1. Mỗi validator ký tối đa **1 PREVOTE** cho mỗi cặp `(height, round)`.
2. Mỗi validator ký tối đa **1 PRECOMMIT** cho mỗi cặp `(height, round)`.
3. Chỉ chấp nhận và PREVOTE cho block có parent hợp lệ, transaction hợp lệ, state root đúng, proposer đúng lượt và chữ ký hợp lệ.
4. Khi quan sát thấy quorum PREVOTE cho một block non-NIL, validator **khóa** block đó và ghi nhận round tương ứng.
5. Validator đã khóa khối $B$ chỉ được phép PREVOTE cho một khối $B'$ khác nếu quan sát thấy quorum PREVOTE hợp lệ cho $B'$ ở một round lớn hơn round đã khóa.
6. Validator không được ký vote sai chain, height, round, phase hoặc sai domain.
7. Node loại bỏ vote trùng lặp; mỗi validator chỉ được tính tối đa một phiếu hợp lệ cho mỗi `(height, round, phase)`.

---

## 7. Hướng dẫn chạy kiểm thử (Testing)

Đề bài yêu cầu toàn bộ kiểm thử phải tái lập được và gọi được từ **một entry point duy nhất**.

### 1. Chạy toàn bộ test suites (Single Entry Point)

```bash
python -m tests.run_all_tests
```

Hoặc gọi trực tiếp thông qua `pytest`:

```bash
python -m pytest -v tests/
```

*Hiện tại bộ kiểm thử gồm **35 test cases** (bao gồm 8 scenario T1–T8 bắt buộc, các unit tests và regression tests), kết quả đạt **35/35 PASSED**.*

### 2. Danh sách các kịch bản End-to-End (T1 – T8 theo Mục 9 đề bài)

| Test ID | Kịch bản mô phỏng | Kết quả bắt buộc |
|:---:|---|---|
| **T1** | Chạy bình thường, không lỗi mạng | Toàn bộ node honest chốt cùng chuỗi block và cùng state root. |
| **T2** | Thông điệp bị duplicate và đảo thứ tự | Không đếm trùng phiếu; không xảy ra phân rẽ chốt khối. |
| **T3** | Transaction có chữ ký sai hoặc sai domain | Node ingress từ chối giao dịch và ghi log lý do từ chối. |
| **T4** | Transaction bị replay qua mạng | Giao dịch chỉ được áp dụng tối đa 1 lần nhờ kiểm tra nonce và hash. |
| **T5** | Mạng bị drop và delay trước thời điểm ổn định | Đảm bảo tính Safety (không có 2 block khác nhau cùng height); hồi phục sau khi ổn định. |
| **T6** | Proposer vòng 0 bị im lặng (silent/crash) | Kích hoạt round timeout, chuyển sang round 1 và hoàn thành chốt khối. |
| **T7** | Tối đa $f=3$ Byzantine validator gửi vote mâu thuẫn | Mỗi node chỉ đếm 1 vote/validator; không thể tạo quorum giả cho 2 block khác nhau. |
| **T8** | Chạy lại cùng một seed ngẫu nhiên | State root, danh sách block và toàn bộ canonical log của node/mạng **giống nhau từng byte**. |

### 3. Chạy từng nhóm test riêng lẻ

- Chạy toàn bộ Unit Tests:
  ```bash
  python -m pytest -v tests/unit/
  ```

- Chạy riêng kịch bản kiểm tra tính xác định T8 (Mục 8 đề bài):
  ```bash
  python -m pytest -v tests/e2e/test_scenarios.py -k test_t8
  ```

- Chạy riêng kiểm tra tính hợp lệ của khối (Block validation):
  ```bash
  python -m pytest -v tests/unit/test_block.py
  ```

- Lọc test theo từ khóa:
  ```bash
  python -m pytest -v tests/ -k equivocation
  ```

---

## 8. Chạy Simulator & Kiểm tra tính xác định (Determinism)

### Chạy mô phỏng mặc định 1 block

```bash
python run_simulation.py
```

### Chạy với cấu hình tùy chọn hoặc số tick tối đa

```bash
python run_simulation.py --config config/default_config.json --max-ticks 10000
```

### Xuất log xác định (Canonical Byte Logs)

Mục 8 đề bài yêu cầu ghi nhận toàn bộ sự kiện đồng thuận và mạng để chứng minh tính đúng đắn. Để xuất log ra thư mục:

```bash
python run_simulation.py --write-logs logs/run-01
```

*(Lưu ý: Thư mục đích phải chưa tồn tại từ trước để đảm bảo tính an toàn dữ liệu).*

### Kiểm tra tính xác định (Re-running equality check)
Theo yêu cầu Mục 8: *"Provide a script that runs the same scenario twice and checks equality of logs and final state"*, bạn có thể kiểm chứng bằng 3 cách:
1. Dùng trực tiếp cờ `--check-determinism` của script mô phỏng (chạy tự động 2 lần kịch bản cấu hình và kiểm tra byte-identical cho `block_hash`, `state_root`, toàn bộ log từng node và log mạng):
   ```bash
   python run_simulation.py --check-determinism
   ```
2. Chạy test `T8`: `python -m pytest tests/e2e/test_scenarios.py -k test_t8 -v` (chạy tự động 2 lần cùng seed 999 và so khớp từng byte của state root, block hashes, node logs và simulator network log).
3. Chạy script mô phỏng ra 2 thư mục riêng biệt và so sánh:
   ```bash
   python run_simulation.py --write-logs logs/run-A
   python run_simulation.py --write-logs logs/run-B
   ```
   Sau đó so sánh byte bằng PowerShell:
   ```powershell
   Get-FileHash logs/run-A/*, logs/run-B/*
   ```

---

## 9. Đóng gói bài nộp

Thư mục `logs/` được giữ rỗng trong Git để tránh commit log phát sinh. Trước khi đóng gói, hãy tạo log mẫu tại chỗ; để lưu bằng chứng kiểm tra tính xác định, chạy mô phỏng hai lần:

```bash
python run_simulation.py --write-logs logs/run-A
python run_simulation.py --write-logs logs/run-B
```

`package_submission.py` yêu cầu `logs/` chứa ít nhất một tệp log và sẽ đưa các log hiện có vào gói nộp.

Sử dụng script đóng gói tự động `package_submission.py` từ thư mục gốc:

```bash
python package_submission.py --ids 23120273 23120281 23120315 23120382
```

Script sẽ tự động:
1. Kiểm tra tính đầy đủ của các thành phần bắt buộc (`src/`, `tests/`, `logs/`, `config/`, `run_simulation.py`, `requirements.txt`, `pytest.ini`, `README.md`, `REPORT.pdf`).
2. Bỏ qua các file rác và cache (`__pycache__`, `.pytest_cache`, `*.pyc`).
3. Tạo thư mục `Lab01_23120273_23120281_23120315_23120382` và file zip tương ứng sẵn sàng để nộp.
