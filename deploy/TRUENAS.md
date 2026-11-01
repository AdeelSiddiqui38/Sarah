# Run Sarah 24/7 on the TrueNAS

Sarah Core runs on the NAS and is reachable only through Tailscale, from your phone, Mac or Windows PC, at home or away. Nothing is opened to the internet.

## 1. Push the latest code (Mac, once)
```
cd ~/Documents/brain/Sarah
git add .gitignore requirements.txt sarah_core.py sarah-grid.html "Sarah Grid.command" Sarah-Grid.bat deploy
git commit -m "Sarah Core: shield, approvals, audit, TRON grid, TrueNAS deploy"
git push
```
The NAS pulls the code from GitHub each time Sarah starts. Photos and `data/` are git-ignored.

## 2. Tailscale admin console (login.tailscale.com, 5 minutes)
1. **DNS**: turn on **MagicDNS** and **HTTPS Certificates**. Note your tailnet name (like `tail1a2b3c.ts.net`).
2. **Settings > Keys**: **Generate auth key** (one-off, not ephemeral). Copy it.

## 3. TrueNAS: storage for Sarah
1. **Datasets**: select your pool, **Add Dataset** named `sarah` (encryption on is recommended).
2. Inside `sarah`, add three child datasets: `data`, `projects`, `tailscale`.
3. **Data Protection > Periodic Snapshot Tasks > Add**: dataset `POOL/sarah`, recursive, every hour, keep 2 weeks.

## 4. TrueNAS: install Sarah
1. **Apps > Discover Apps > Custom App > ⋮ > Install via YAML**.
2. Name: `sarah`.
3. Paste `deploy/truenas-compose.yaml` and replace the 4 REPLACE values (pool name, auth key, tailnet, your Tailscale login email).
4. **Save**. Wait until both containers show Running.

## 5. Open Sarah
- On your phone (Tailscale switched on) or any device signed in to your tailnet: `https://sarah.TAILNET.ts.net`
- First visit: set your passphrase, then **Settings** to paste your Claude key (stored on the NAS in `sarah/data`, never on GitHub).
- Add it to your phone's home screen from the browser's Share menu.

## 6. Mac and Windows
Install Tailscale from tailscale.com/download and sign in with the same account. Then open the same address.

## Project files (later)
Share `POOL/sarah/projects` over SMB and copy each project's folder there (for example `Remedy Pills`). Sarah reads it read-only for the CRA checklist.

## If something fails
- Apps > sarah > Logs: the `tailscale` log shows login problems (expired or wrong auth key).
- Page loads but Unlock fails with "Blocked by the shield": the `SARAH_ORIGINS` address does not exactly match the address in your browser.
- "This Tailscale account is not allowed": `SARAH_ALLOWED_USERS` does not match your Tailscale login.
