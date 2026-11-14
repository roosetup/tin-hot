# Tool lọc tin hot (xem trên điện thoại)

1. Tạo repo GitHub (private/public đều được), upload toàn bộ thư mục này (giữ nguyên `.github/workflows/daily.yml`).
2. Settings → Secrets and variables → Actions → New secret: `ANTHROPIC_API_KEY`.
3. Settings → Pages → Source: Deploy from a branch → `main` / folder `/docs`.
4. Tab Actions → daily-news → Run workflow (chạy thử). Sau đó tự chạy 07:30 mỗi ngày.
5. Mở `https://<user>.github.io/<repo>/` trên điện thoại, thêm vào màn hình chính.

Chạy thử trên máy: `pip install feedparser requests anthropic` rồi `python news_hot.py` (hoặc `--demo`).
Nếu một báo không ra bài, kiểm tra lại URL RSS trong `FEEDS`.
Pages công khai: ai có link đều xem được (không chứa dữ liệu nhạy cảm, chỉ là link + caption).
