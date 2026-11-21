# Free Hosting Deployment Guide for GitChain

GitChain comes with a C++20 consensus engine, RocksDB storage, and a FastAPI web studio. Because GitChain uses Docker for containerization, you can deploy it for **100% free** on multiple cloud platforms with zero native setup.

Here is an overview of the best free hosting services and exact step-by-step deployment instructions for each.

---

## Comparison of Free Hosting Platforms

| Platform | Free Tier Specs | Credit Card Required? | Persistent Storage? | Best For |
| :--- | :--- | :--- | :--- | :--- |
| **Render** | 512 MB RAM, 0.1 vCPU | **No** | Ephemeral | 🚀 Easiest 1-click web demo |
| **Hugging Face Spaces** | **16 GB RAM, 2 vCPU**, 50GB Disk | **No** | Ephemeral / Volume | ⚡ High resource headroom |
| **Fly.io** | 256–512 MB RAM, 1 vCPU | Yes (for verification) | **Yes (1GB free volume)** | 💾 Persistent blockchain ledger |
| **Koyeb** | 512 MB RAM, 0.1 vCPU | **No** | Ephemeral | 🌍 Global edge deployment |
| **Railway** | 512 MB RAM, $5 trial credit | **No** | Ephemeral / Volume | 🛠️ Rapid testing |

---

## 1. Deploy on Render (Recommended for Free Quickstart)

Render provides free Docker web services without requiring a credit card.

### Step-by-Step Instructions:
1. Push your repository to GitHub:
   ```bash
   git add .
   git commit -m "Add GitChain UI and Docker deployment setup"
   git push origin main
   ```
2. Go to [dashboard.render.com](https://dashboard.render.com/) and sign in.
3. Click **New +** → **Web Service**.
4. Select **Build and deploy from a Git repository** and connect your `GitChain` repository.
5. In the settings:
   - **Name**: `gitchain-demo` (or any name you prefer)
   - **Region**: Choose closest to you (e.g., Frankfurt, Oregon, Ohio)
   - **Language / Runtime**: **Docker** (Render will automatically detect the `Dockerfile`)
   - **Instance Type**: **Free** ($0/month)
6. Environment Variables (optional, defaults are pre-configured in `Dockerfile`):
   - `GOC_ENV` = `development`
   - `GOC_ALLOW_INSECURE_BIND` = `1`
7. Click **Deploy Web Service**.
8. Once the build finishes, your live GitChain explorer and studio will be accessible at:
   `https://<your-service-name>.onrender.com`

> **Note on Free Tier Inactivity**: Render free instances spin down after 15 minutes of inactivity. When a new visitor accesses your URL, Render wakes the container up within ~30–50 seconds. Since storage is ephemeral on Render free tier, you can use the **⚡ Seed Demo Chain** button in the header anytime to initialize demo blocks instantly.

---

## 2. Deploy on Hugging Face Spaces (Generous 16 GB RAM)

Hugging Face Spaces provides a completely free containerized environment with 2 vCPUs and 16 GB RAM with no credit card required.

### Step-by-Step Instructions:
1. Create a free account at [huggingface.co](https://huggingface.co/).
2. Go to **Spaces** → [New Space](https://huggingface.co/new-space).
3. Fill in the details:
   - **Space Name**: `gitchain`
   - **License**: `mit` or `apache-2.0`
   - **Space SDK**: Select **Docker** → **Blank**
   - **Space hardware**: Free (2 vCPU, 16 GB RAM)
4. Push your repository to the Space repository:
   ```bash
   git remote add space https://huggingface.co/spaces/<your-username>/gitchain
   git push space main
   ```
   *(Or connect your GitHub repository directly in the Space settings under "Repository Mirroring" / "Sync with GitHub")*
5. Hugging Face Spaces automatically builds the `Dockerfile` and maps port `7860`. The `Dockerfile` in this repo is pre-configured to bind to `${PORT:-8000}`, which automatically handles Hugging Face's port `7860`!
6. Your Space will build and launch your live GitChain Explorer at:
   `https://huggingface.co/spaces/<your-username>/gitchain`

---

## 3. Deploy on Fly.io (Best for Persistent Storage)

Fly.io gives you free persistent volumes (up to 3GB across your account), which allows RocksDB to keep all your mined blocks across restarts and redeploys.

### Step-by-Step Instructions:
1. Install `flyctl`:
   ```bash
   curl -L https://fly.io/install.sh | sh
   ```
2. Log in:
   ```bash
   fly auth login
   ```
3. Initialize the app (this repository already includes a pre-configured `fly.toml`):
   ```bash
   fly launch --no-deploy
   ```
4. Create a 1GB persistent volume in your chosen region (e.g., `iad` or `ord`):
   ```bash
   fly volumes create gitchain_data --size 1 --region iad
   ```
5. Deploy:
   ```bash
   fly deploy
   ```
6. Open your application:
   ```bash
   fly open
   ```
   Your app will be live at `https://<your-app-name>.fly.dev` with persistent blockchain storage mounted at `/data/l1`.

---

## 4. Deploy on Koyeb (Free Serverless Edge)

Koyeb offers a free Eco tier with 512 MB RAM and global CDN routing without a credit card.

### Step-by-Step Instructions:
1. Sign up at [koyeb.com](https://www.koyeb.com/).
2. Click **Create App** → **GitHub**.
3. Select your `GitChain` repository.
4. Builder: Select **Dockerfile**.
5. Port: Set to `8000`.
6. Click **Deploy**.
7. Your app will be live at `https://<app-name>.koyeb.app`.

---

## 5. Local Docker Deployment (Self-Hosted)

To run the containerized GitChain node and Web UI locally:

```bash
docker compose up --build
```

Then open your browser to `http://localhost:8000/`.
