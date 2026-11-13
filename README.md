# Blockchain Lab 01: Layer 1 Blockchain Simulator with BFT Consensus

## Nhóm thực hiện

- Nguyễn Gia Huy — `23120273`
- Bùi Duy Khánh — `231204281`
- Nguyễn Đăng Khoa — `23120315`
- Nguyễn Ngọc Nhân Trọng — `23120382`

## Cấu trúc

```text
src/
  crypto/       Ed25519, SHA-256, canonical encoding
  execution/    Transactions, blocks, key-value state
  consensus/    Prevote/Precommit, quorum counting, locking
  network/      Event loop, header/body framing, fault simulator and logger
  node.py       Validator node and block proposal/finalization
run_simulation.py  Run one deterministic block simulation
tests/
  unit/         Crypto, state, and consensus checks
  e2e/          Named Lab scenarios T1–T8
config/         Example network configuration
logs/           Placeholder for generated logs
.github/workflows/tests.yml  CI test workflow
README.md
REPORT.tex      Report source
REPORT.pdf      Report submitted with the project
requirements.txt
package_submission.py
```

## Cài đặt

Yêu cầu Python 3.10 trở lên.

```bash
python -m venv .venv
```

PowerShell:

```powershell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Chạy kiểm thử

Từ thư mục gốc của repository, chạy entry point chung:

```bash
python -m tests.run_all_tests
```

Hoặc chạy trực tiếp bằng pytest:

```bash
pytest -v tests/
```

Các kịch bản dùng `NetworkRunner` cùng `NetworkSimulator`; header, yêu cầu body, body và vote đều đi qua transport mô phỏng. T1–T8 kiểm tra:

- **T1** chạy proposal đến finalization qua mạng bình thường; các node phải chốt cùng block và state root.
- **T2** bật duplicate và delay/reorder; vote lặp không được đếm lại và không được split finality.
- **T3–T4** gửi transaction sai domain và replay qua message handler; node từ chối và log lý do.
- **T5** gây drop/delay trước thời điểm ổn định; không xuất hiện hai finality khác nhau và các node cuối cùng chốt cùng block.
- **T6** làm proposer round 0 im lặng; timeout chuyển sang round 1 và đồng thuận tiếp tục.
- **T7** chuyển các vote PREVOTE mâu thuẫn có chữ ký thật từ hai validator; mỗi node chỉ tính một vote cho mỗi validator/phase.
- **T8** chạy lại cùng seed, so sánh state root, chuỗi block, log của từng node và log transport.

`tests/run_all_tests.py` là entry point dùng cả cục bộ và CI. GitHub Actions chạy workflow khi push hoặc mở pull request. Bộ suite hiện có 21 unit/scenario tests.

## Chạy simulator

Chạy một mô phỏng một block với cấu hình mặc định:

```bash
python run_simulation.py
```

In thêm đường dẫn log canonical vào một thư mục mới:

```bash
python run_simulation.py --write-logs logs/run-42
```

Script từ chối dùng lại thư mục log đã tồn tại. Khóa validator được tạo xác định để tái lập kết quả, chỉ dùng cho simulator học tập.

## Đóng gói bài nộp

Từ thư mục gốc, truyền MSSV của các thành viên theo thứ tự mong muốn:

```bash
python package_submission.py --ids 23120273 231204281 23120315 23120382
```

Script tạo thư mục `Lab01_ID1_ID2_...` và file ZIP cùng tên, chứa `src/`, `tests/`, `logs/`, `config/`, `run_simulation.py`, `README.md` và `REPORT.pdf`. Script từ chối ghi đè gói đã tồn tại; xóa hoặc đổi tên gói cũ trước khi tạo lại.
