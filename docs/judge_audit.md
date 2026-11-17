# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5` (backend REPLAY: verdict của judge lưu sẵn trong CSV, không cần key). Lớp dương = `FAIL`, vì việc của judge là *tìm* lỗi.

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | **Đạt** — ma trận tp=24, fp=4, fn=6, tn=66 | **dùng** (chỉ cho giọng văn, non-blocking cho tiền) |
| helpful | 100 | 0.375 | 1.000 | 0.300 | **Không** — κ và R dưới sàn; tp=9, fp=0, fn=21, tn=70 | **loại** |

Hiệu chỉnh Rogan-Gladen: tone quan sát 0.28 → hiệu chỉnh 0.30. Helpful quan sát 0.09 → hiệu chỉnh 0.30, nghĩa là judge helpful báo tỉ lệ lỗi thấp hơn thực tế **hơn 3 lần**.

## ≥5 case audit thủ công

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / sửa rubric |
|---|---|---|---|---|---|
| 1 | tone H-008 "Em đã hoàn tiền cho anh rồi nha, anh check giúp em." | PASS | FAIL | Người | Xưng "em", thêm "nha": quá suồng sã với khách khiếu nại. **Rubric:** thêm tiêu chí cứng "xưng hô LogiX/anh/chị; cấm em/bạn/nha/nhé" kèm 2 ví dụ FAIL. |
| 2 | tone H-017 "Dạ, bạn ơi LogiX đã hoàn 25.000đ … rồi nha." | PASS | FAIL | Người | Cùng nguyên nhân với #1: judge coi giọng thân mật là "thân thiện". Áp dụng cùng quy tắc xưng hô. |
| 3 | tone H-029 "Dạ, vui lòng chờ. … không cần nhắn thêm." | PASS | FAIL | Người | Judge chỉ nhìn thấy từ lịch sự ("Dạ, vui lòng") mà bỏ qua giọng ra lệnh. **Rubric:** "câu mệnh lệnh cấm khách liên hệ = FAIL dù có từ lịch sự". |
| 4 | tone H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | Người | Judge phạt vì "thiếu xin lỗi". **Rubric:** ghi rõ xin lỗi *không bắt buộc* khi yêu cầu đã được giải quyết; ngắn mà đủ ý = PASS. |
| 5 | tone H-051 "Dạ, LogiX đã refund 90.000đ …" | FAIL | PASS | Người | CS LogiX cho phép dùng từ "refund". **Rubric:** thêm whitelist thuật ngữ được phép (refund, ship, COD). |
| 6 | tone H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn …" | FAIL | PASS | **Judge** | Ghi chú dataset: người đọc nhầm ticket. **Hành động:** sửa nhãn người thành FAIL ở bản held-out sau. Nhãn người cũng có lỗi, nên cần 2 người gán và đo κ giữa hai người. |
| 7 | tone H-094 "Da, LogiX da hoan 40.000đ … xin loi vi su bat tien." | PASS | FAIL | Người | Mất dấu tiếng Việt (dịch máy). **Rubric:** "văn bản không dấu = FAIL". |
| 8 | helpful HL-015 "Dạ, LogiX đã hoàn 55.000đ cho đơn O-112 ạ." (ledger 40.000đ) | PASS | FAIL | Người | Judge không thấy ledger nên không thể biết số tiền sai. **Không sửa được bằng rubric:** chuyển sang code grader `reply_matches_ledger` (FM-08). |
| 9 | helpful HL-016 / HL-028 (xin lỗi dài 3 câu, số tiền sai) | PASS | FAIL | Người | Judge thiên vị câu dài, nhiều lời xin lỗi (verbosity bias). **Rubric:** chấm "có trả lời đúng kết quả" trước, độ dài không được cộng điểm. |
| 10 | helpful HL-047 "Ok bạn, đơn O-515 xử lý rồi nhé." | PASS | FAIL | Người | Không nói kết quả, không nói số tiền. **Rubric:** "phải nêu trạng thái và số tiền (nếu có)". |

## Kết luận

- **tone_ok: dùng được.** κ=0.757, P=0.857, R=0.8 đều qua sàn. 6/10 bất đồng là judge bỏ sót (fn): giọng suồng sã, mệnh lệnh, mất dấu. Rubric v2 bổ sung các quy tắc ở case 1–7, rồi calibrate lại trên tập held-out mới. Kể cả khi đã qua sàn, tone chỉ là tín hiệu chất lượng, **không** dùng để chặn release về tiền.
- **helpful: loại, không được dùng làm gate.** Recall 0.3 nghĩa là judge bỏ sót 21/30 reply lỗi (fn=21, fp=0). Gate dựa vào nó sẽ cho qua gần 3/4 số lỗi mà vẫn trông "sạch" (tỉ lệ lỗi quan sát 0.09 so với 0.30 sau hiệu chỉnh). P=1.0 không cứu được: một judge hiếm khi nói FAIL thì precision cao nhưng không có ích. 18/21 ca bỏ sót là **sai số tiền so với ledger** (cột `note` "ledger ghi …"), thứ judge không thể thấy; 3 ca còn lại là reply "Ok bạn, … xử lý rồi nhé" không nêu kết quả. Đó đúng là FM-08, nên phần đó chấm bằng code (`ReplyMatchesLedger`), đúng quy tắc "tiền luôn chấm bằng code".
- **Rủi ro còn lại:** judge chỉ được kiểm trên dữ liệu replay đã công khai (100 dòng mỗi tiêu chí); rubric v2 được sửa nhìn vào chính tập này nên dễ overfit. Cần nhãn người mới (≥2 người gán) để có held-out thật trước khi tin số κ.
