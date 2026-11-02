# Dashboard

Next.js dashboard for the local Phase 3 prototype.

It shows:

- Global vs average local accuracy per round.
- Client participation and skipped-client history.
- Patient input form that calls the local `POST /predict` API.

Run the local FL loop and API first:

```powershell
python scripts/run_local_fl.py
python scripts/run_api_server.py
```

Then start the dashboard:

```powershell
cd dashboard
npm install
npm run dev
```

The dashboard expects the API at `http://127.0.0.1:8000` unless `NEXT_PUBLIC_API_BASE_URL` is set.
