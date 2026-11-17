# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

## Case: `seeded_regression` C-002@11 (FM-03)

```
== seeded_regression C-002@11  lab8 grader: FAIL (status resolved != denied)
   1 handoff            {"claim_id": "C-002", "request_id": "REQ-C-002", "allowed_tools": [...]}
   2 investigator       {"lookup_order": {"visible": true, "order": {"order_id": "O-202", "delay_days": 2, ...}}}
   3 model_override     {"delay_days": 5}
   4 quote              {"amount_vnd": 20000, "reason": "entitled", "clause_ids": ["SHIP-LATE-03"]}
   5 refund_history     {"refund_count": 0, "refunded_vnd": 0}
   6 reply              {"text": "Dạ, LogiX đã hoàn 20.000đ cho đơn O-202."}
-- ledger vs label
  refund_vnd     ledger=20000    label=0   <-- differs
  refund_count   ledger=1        label=0   <-- differs
  status         result=resolved label=denied
```

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@11`, report `reports/eval_seeded_regression.json`, run ID `E-seeded_regression-20261117-fd35` |
| Triệu chứng | `pass_rate` fail (`status resolved != denied`), `refund_amount_correct` fail (ledger 20.000 ≠ nhãn 0), `db_fact_kept` fail, `proposal_correct` fail (20.000 ≠ 0). Reply nói "đã hoàn 20.000đ", và ledger cũng ghi 20.000: reply khớp ledger nhưng cả hai đều sai so với nhãn. |
| Bước sai đầu tiên | event 3 `model_override` — `{"delay_days": 5}` |
| Vì sao là bước *đầu tiên* | event 1 `handoff` đúng hợp đồng (`allowed_tools` chỉ đọc). Event 2 `investigator` đọc DB đúng: O-202 `delay_days=2`, mức trễ này không được hoàn. Từ event 3, agent lấy con số 5 ngày khách tự khai trong ticket ("Đơn giao trễ 5 ngày") đè lên DB, nên quote ở event 4 áp `SHIP-LATE-03` 20.000. Event 5–6 chỉ là hệ quả. |
| Failure mode | FM-03 ticket_trust |
| Đối chứng | `fixed C-002@11`: event 1–2 giống hệt, **không có** `model_override`, event 3 quote `{"amount_vnd": 0, "reason": "no_entitlement"}`, reply "chưa đủ điều kiện hoàn", ledger 0, Lab 8 grader PASS. Baseline `swarm` mắc đúng lỗi này ở C-002@55 (seed % 5 == 0). |
| Regression test | `src/tests/test_lab9_trace_case.py`: `test_first_wrong_step_is_the_override` (bước sai = event 3, các bước trước đúng), `test_graders_catch_the_buggy_trial` (`DbFactKept`, `RefundAmountCorrect`, `ProposalCorrect`, `TrialPass` đều fail trên variant lỗi), `test_graders_pass_on_fixed` (tất cả pass trên `fixed`). Đã chạy: fail đúng chỗ trên `seeded_regression`, pass trên `fixed`. Chạy: `python -m pytest -q -m student -o addopts= -k trace_case`. |
| Chưa chắc chắn | Trace chỉ ghi *rằng* agent override, không ghi *vì sao* (MockLLM không có chuỗi suy luận). Với LLM thật, cùng triệu chứng có thể đến từ prompt hoặc từ parser. Một biến thể tin ticket mà không ghi `model_override` (`quiet_override`) sẽ qua `db_fact_kept`. Vì vậy outcome grader (`refund_amount_correct`, `proposal_correct`) và slice `denial` / `adversarial` mới là lớp chặn chính, còn `db_fact_kept` chỉ giúp chẩn đoán (non-blocking). |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
