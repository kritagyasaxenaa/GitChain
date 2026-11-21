/**
 * GitChain Dashboard Application Controller
 */

// State Management
const state = {
  status: {
    chain_id: "L1",
    tip_hash: "",
    tip_height: 0,
    chain_score: "0",
  },
  blocks: [],
  identities: [],
  activeIdentity: null,
  mempool: [],
  apiToken: localStorage.getItem("gitchain_api_token") || "",
  autoRefreshInterval: null,
  isMining: false,
};

// Utilities
function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  if (!container) return;
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.innerHTML = `<span>${type === "success" ? "✓" : type === "error" ? "⚠" : "ℹ"}</span> <span>${message}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

function truncateHash(hash, head = 10, tail = 8) {
  if (!hash || hash.length <= head + tail) return hash || "None";
  return `${hash.slice(0, head)}...${hash.slice(-tail)}`;
}

function copyToClipboard(text, label = "Copied to clipboard!") {
  navigator.clipboard.writeText(text).then(() => {
    showToast(label, "success");
  }).catch(() => {
    showToast("Failed to copy to clipboard", "error");
  });
}

function getAuthHeaders() {
  const headers = { "Content-Type": "application/json" };
  if (state.apiToken) {
    headers["Authorization"] = `Bearer ${state.apiToken}`;
  }
  return headers;
}

// API Calls
async function fetchChainStatus() {
  try {
    const res = await fetch("/chain/status");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    state.status = data;
    renderStatus();
  } catch (err) {
    console.error("Failed to fetch chain status:", err);
  }
}

async function fetchBlocks() {
  try {
    const res = await fetch("/api/chain/blocks?limit=100&reverse=true");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    state.blocks = await res.json();
    renderBlocks();
    renderTimeline();
  } catch (err) {
    console.error("Failed to fetch blocks:", err);
  }
}

async function refreshAll() {
  await fetchChainStatus();
  await fetchBlocks();
}

// Render Functions
function renderStatus() {
  const { chain_id, tip_hash, tip_height, chain_score } = state.status;

  const heightEl = document.getElementById("stat-tip-height");
  const hashEl = document.getElementById("stat-tip-hash");
  const scoreEl = document.getElementById("stat-chain-score");
  const chainIdEl = document.getElementById("stat-chain-id");
  const countEl = document.getElementById("stat-total-blocks");

  if (heightEl) heightEl.textContent = `#${tip_height}`;
  if (hashEl) {
    hashEl.textContent = tip_hash ? truncateHash(tip_hash, 8, 6) : "Genesis Empty";
    hashEl.title = tip_hash || "No tip block yet";
  }
  if (scoreEl) {
    // Format BigInt score compactly
    const scoreStr = String(chain_score);
    scoreEl.textContent = scoreStr.length > 12 ? `${scoreStr.slice(0, 6)}...e+${scoreStr.length - 1}` : scoreStr;
    scoreEl.title = `Exact score: ${scoreStr}`;
  }
  if (chainIdEl) chainIdEl.textContent = chain_id;
  if (countEl) countEl.textContent = state.blocks.length;

  const tipInput = document.getElementById("mine-prev-hash");
  const heightInput = document.getElementById("mine-height");
  if (tipInput && !state.isMining) {
    tipInput.value = tip_hash;
  }
  if (heightInput && !state.isMining) {
    heightInput.value = tip_hash ? tip_height + 1 : 0;
  }

  // Update empty state alert
  const emptyAlert = document.getElementById("empty-chain-alert");
  if (emptyAlert) {
    emptyAlert.style.display = !tip_hash && state.blocks.length === 0 ? "block" : "none";
  }
}

function renderTimeline() {
  const timelineEl = document.getElementById("chain-timeline");
  if (!timelineEl) return;

  if (state.blocks.length === 0) {
    timelineEl.innerHTML = `<div style="color:var(--text-muted); padding:1rem; font-size:0.85rem;">Chain is empty. Mine a genesis block to get started!</div>`;
    return;
  }

  // Render newest to oldest or oldest to newest
  const sorted = [...state.blocks].sort((a, b) => b.header.height - a.header.height);

  timelineEl.innerHTML = sorted.map((block, idx) => `
    <div class="chain-node ${idx === 0 ? 'active-tip' : ''}" onclick="viewBlockDetails('${block.hash_hex}')">
      <div class="node-height">Block #${block.header.height} ${idx === 0 ? '★ TIP' : ''}</div>
      <div class="node-hash">${truncateHash(block.hash_hex, 8, 6)}</div>
      <div class="node-tx-count">
        <span>${block.transactions ? block.transactions.length : 0} txs</span>
        <span>Nonce: ${block.header.nonce}</span>
      </div>
    </div>
  `).join("");
}

function renderBlocks() {
  const tbody = document.getElementById("blocks-table-body");
  if (!tbody) return;

  if (state.blocks.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:var(--text-muted); padding:2rem;">No blocks found on this chain.</td></tr>`;
    return;
  }

  const query = (document.getElementById("block-search-input")?.value || "").toLowerCase().trim();
  const filtered = state.blocks.filter(b => {
    if (!query) return true;
    return String(b.header.height) === query ||
           b.hash_hex.toLowerCase().includes(query) ||
           (b.header.previous_hash && b.header.previous_hash.toLowerCase().includes(query));
  });

  tbody.innerHTML = filtered.map(b => {
    const txCount = b.transactions ? b.transactions.length : 0;
    const dateStr = b.header.timestamp ? new Date(b.header.timestamp * 1000).toLocaleTimeString() : "-";
    return `
      <tr>
        <td><span class="badge badge-green">#${b.header.height}</span></td>
        <td class="mono" style="cursor:pointer;" onclick="viewBlockDetails('${b.hash_hex}')" title="Click to view block">
          ${truncateHash(b.hash_hex, 10, 8)}
        </td>
        <td class="mono" title="${b.header.previous_hash || 'Genesis'}">
          ${b.header.previous_hash ? truncateHash(b.header.previous_hash, 8, 6) : '<span style="color:var(--text-muted)">Genesis</span>'}
        </td>
        <td><span class="badge badge-purple">${txCount} txs</span></td>
        <td class="mono" style="font-size:0.75rem;">${b.header.nonce}</td>
        <td>
          <button class="btn btn-secondary btn-sm" onclick="viewBlockDetails('${b.hash_hex}')">Inspect</button>
        </td>
      </tr>
    `;
  }).join("");
}

// Modal View Block Details
async function viewBlockDetails(blockHash) {
  let block = state.blocks.find(b => b.hash_hex === blockHash);
  if (!block) {
    try {
      const res = await fetch(`/blocks/${blockHash}`);
      if (res.ok) block = await res.json();
    } catch (e) {
      console.error(e);
    }
  }

  if (!block) {
    showToast("Block not found", "error");
    return;
  }

  const modalBody = document.getElementById("block-modal-body");
  const modal = document.getElementById("block-modal");
  if (!modal || !modalBody) return;

  const header = block.header;
  const txs = block.transactions || [];

  modalBody.innerHTML = `
    <div class="kv-list" style="margin-bottom:1.25rem;">
      <div class="kv-item">
        <span class="kv-key">Block Height</span>
        <span class="kv-val badge badge-green">#${header.height}</span>
      </div>
      <div class="kv-item">
        <span class="kv-key">Block Hash</span>
        <span class="kv-val mono" style="font-size:0.75rem;">${block.hash_hex} <button class="btn btn-secondary btn-sm" onclick="copyToClipboard('${block.hash_hex}')">Copy</button></span>
      </div>
      <div class="kv-item">
        <span class="kv-key">Previous Hash</span>
        <span class="kv-val mono" style="font-size:0.75rem;">${header.previous_hash || 'None (Genesis)'}</span>
      </div>
      <div class="kv-item">
        <span class="kv-key">PoW Target</span>
        <span class="kv-val mono" style="font-size:0.75rem;">${header.target_hex}</span>
      </div>
      <div class="kv-item">
        <span class="kv-key">Nonce</span>
        <span class="kv-val mono">${header.nonce}</span>
      </div>
      <div class="kv-item">
        <span class="kv-key">Timestamp</span>
        <span class="kv-val">${new Date(header.timestamp * 1000).toLocaleString()}</span>
      </div>
      <div class="kv-item">
        <span class="kv-key">Producer Key</span>
        <span class="kv-val mono" style="font-size:0.7rem; max-width:380px;">${truncateHash(block.producer_public_key, 24, 20)}</span>
      </div>
    </div>

    <h4 style="margin-bottom:0.5rem; font-size:0.95rem;">Transactions (${txs.length})</h4>
    ${txs.length === 0 ? '<p style="color:var(--text-muted); font-size:0.8rem; margin-bottom:1rem;">No transactions in this block.</p>' : `
      <div style="display:flex; flex-direction:column; gap:0.5rem; margin-bottom:1.25rem;">
        ${txs.map((tx, idx) => `
          <div style="background:var(--bg-input); border:1px solid var(--border-color); border-radius:8px; padding:0.75rem;">
            <div style="display:flex; justify-content:space-between; margin-bottom:0.25rem;">
              <span class="badge badge-blue">${tx.operation}</span>
              ${tx.repository_id ? `<span class="badge badge-purple">Repo: ${tx.repository_id}</span>` : ''}
            </div>
            <pre class="code-block" style="margin-top:0.35rem; max-height:120px;">${JSON.stringify(tx.payload, null, 2)}</pre>
            <div style="font-size:0.7rem; color:var(--text-muted); margin-top:0.35rem;">
              Actor: ${truncateHash(tx.actor_public_key, 16, 12)}
            </div>
          </div>
        `).join('')}
      </div>
    `}

    <h4 style="margin-bottom:0.5rem; font-size:0.95rem;">Raw JSON</h4>
    <pre class="code-block">${JSON.stringify(block, null, 2)}</pre>
  `;

  modal.classList.add("open");
}

function closeModal() {
  const modal = document.getElementById("block-modal");
  if (modal) modal.classList.remove("open");
}

// Identities Management
function loadIdentities() {
  const raw = localStorage.getItem("gitchain_identities");
  if (raw) {
    try {
      state.identities = JSON.parse(raw);
    } catch (e) {
      state.identities = [];
    }
  }
  const activeRaw = localStorage.getItem("gitchain_active_identity");
  if (activeRaw && state.identities.find(i => i.username === activeRaw)) {
    state.activeIdentity = state.identities.find(i => i.username === activeRaw);
  } else if (state.identities.length > 0) {
    state.activeIdentity = state.identities[0];
  }
  renderIdentities();
  updateIdentityPill();
}

function saveIdentities() {
  localStorage.setItem("gitchain_identities", JSON.stringify(state.identities));
  if (state.activeIdentity) {
    localStorage.setItem("gitchain_active_identity", state.activeIdentity.username);
  }
  renderIdentities();
  updateIdentityPill();
}

function updateIdentityPill() {
  const nameEl = document.getElementById("active-identity-name");
  const avatarEl = document.getElementById("active-identity-avatar");
  if (nameEl && avatarEl) {
    if (state.activeIdentity) {
      nameEl.textContent = state.activeIdentity.username;
      avatarEl.textContent = state.activeIdentity.username.charAt(0).toUpperCase();
    } else {
      nameEl.textContent = "No Identity";
      avatarEl.textContent = "?";
    }
  }

  // Update signer / producer selects
  const actorSelect = document.getElementById("tx-actor-select");
  const minerSelect = document.getElementById("mine-producer-select");
  const options = state.identities.map(i => `<option value="${i.username}">${i.username} (${truncateHash(i.identity_id || i.keys.public_key_pem, 6, 4)})</option>`).join("");

  if (actorSelect) {
    actorSelect.innerHTML = `<option value="">-- Choose Identity --</option>` + options;
    if (state.activeIdentity) actorSelect.value = state.activeIdentity.username;
  }
  if (minerSelect) {
    minerSelect.innerHTML = options;
    if (state.activeIdentity) minerSelect.value = state.activeIdentity.username;
  }
}

function renderIdentities() {
  const container = document.getElementById("identities-list");
  if (!container) return;

  if (state.identities.length === 0) {
    container.innerHTML = `<div style="color:var(--text-muted); padding:1rem; text-align:center;">No identities generated yet. Create one below!</div>`;
    return;
  }

  container.innerHTML = state.identities.map(id => {
    const isActive = state.activeIdentity && state.activeIdentity.username === id.username;
    return `
      <div class="panel" style="margin-bottom:1rem; border-color:${isActive ? 'var(--accent)' : 'var(--border-color)'}">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.75rem;">
          <div style="display:flex; align-items:center; gap:0.5rem;">
            <div class="identity-avatar">${id.username.charAt(0).toUpperCase()}</div>
            <strong>${id.username}</strong>
            ${isActive ? '<span class="badge badge-green">ACTIVE</span>' : ''}
          </div>
          <div style="display:flex; gap:0.5rem;">
            ${!isActive ? `<button class="btn btn-secondary btn-sm" onclick="setActiveIdentity('${id.username}')">Select Active</button>` : ''}
            <button class="btn btn-secondary btn-sm" onclick="exportIdentity('${id.username}')">Export</button>
            <button class="btn btn-secondary btn-sm" style="color:var(--accent-red);" onclick="deleteIdentity('${id.username}')">Remove</button>
          </div>
        </div>
        <div class="kv-list">
          <div class="kv-item">
            <span class="kv-key">Identity ID</span>
            <span class="kv-val mono" style="font-size:0.75rem;">${id.identity_id || 'N/A'}</span>
          </div>
          <div class="kv-item">
            <span class="kv-key">Public Key</span>
            <span class="kv-val mono" style="font-size:0.75rem;">
              ${truncateHash(id.keys.public_key_pem, 20, 16)}
              <button class="btn btn-secondary btn-sm" onclick="copyToClipboard(\`${id.keys.public_key_pem}\`)">Copy PEM</button>
            </span>
          </div>
        </div>
      </div>
    `;
  }).join("");
}

function setActiveIdentity(username) {
  const id = state.identities.find(i => i.username === username);
  if (id) {
    state.activeIdentity = id;
    saveIdentities();
    showToast(`Active identity set to ${username}`, "success");
  }
}

function deleteIdentity(username) {
  if (!confirm(`Are you sure you want to remove identity '${username}'?`)) return;
  state.identities = state.identities.filter(i => i.username !== username);
  if (state.activeIdentity && state.activeIdentity.username === username) {
    state.activeIdentity = state.identities.length > 0 ? state.identities[0] : null;
  }
  saveIdentities();
  showToast(`Identity '${username}' removed`, "info");
}

function exportIdentity(username) {
  const id = state.identities.find(i => i.username === username);
  if (!id) return;
  const blob = new Blob([JSON.stringify(id, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${username}-identity.json`;
  a.click();
  URL.revokeObjectURL(url);
}

async function createNewIdentity() {
  const usernameInput = document.getElementById("new-identity-username");
  const username = usernameInput ? usernameInput.value.trim() : "";
  if (!username) {
    showToast("Please enter a username", "error");
    return;
  }

  if (state.identities.find(i => i.username.toLowerCase() === username.toLowerCase())) {
    showToast("An identity with that username already exists", "error");
    return;
  }

  try {
    const res = await fetch("/api/tools/create-identity", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username })
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    state.identities.push(data);
    state.activeIdentity = data;
    saveIdentities();
    if (usernameInput) usernameInput.value = "";
    showToast(`Created identity for '${username}'!`, "success");
  } catch (err) {
    console.error(err);
    showToast(`Failed to create identity: ${err.message}`, "error");
  }
}

// Transaction Studio
function onTxOperationChange() {
  const op = document.getElementById("tx-op-select")?.value;
  const fieldsContainer = document.getElementById("tx-dynamic-fields");
  if (!fieldsContainer) return;

  if (op === "USER_CREATE") {
    fieldsContainer.innerHTML = `
      <div class="form-group">
        <label class="form-label">Username to Register</label>
        <input type="text" id="tx-user-name" class="form-input" placeholder="e.g. alice" value="${state.activeIdentity ? state.activeIdentity.username : ''}">
      </div>
    `;
  } else if (op === "REPO_CREATE") {
    fieldsContainer.innerHTML = `
      <div class="form-group">
        <label class="form-label">Repository ID / Name</label>
        <input type="text" id="tx-repo-id" class="form-input" placeholder="e.g. gitchain-core">
      </div>
    `;
  } else if (op === "FILE_CHANGE") {
    fieldsContainer.innerHTML = `
      <div class="form-group">
        <label class="form-label">Repository ID</label>
        <input type="text" id="tx-file-repo" class="form-input" placeholder="e.g. gitchain-core">
      </div>
      <div class="form-group">
        <label class="form-label">File Path</label>
        <input type="text" id="tx-file-path" class="form-input" placeholder="e.g. src/main.rs">
      </div>
      <div class="form-group">
        <label class="form-label">Commit Message / Note</label>
        <input type="text" id="tx-file-message" class="form-input" placeholder="Initial commit">
      </div>
    `;
  } else if (op === "ACCESS_GRANT") {
    fieldsContainer.innerHTML = `
      <div class="form-group">
        <label class="form-label">Repository ID</label>
        <input type="text" id="tx-grant-repo" class="form-input" placeholder="e.g. gitchain-core">
      </div>
      <div class="form-group">
        <label class="form-label">Subject Public Key (PEM)</label>
        <textarea id="tx-grant-subject" class="form-textarea" placeholder="-----BEGIN PUBLIC KEY-----..."></textarea>
      </div>
      <div class="form-group">
        <label class="form-label">Granted Role</label>
        <select id="tx-grant-role" class="form-select">
          <option value="contributor">Contributor</option>
          <option value="admin">Admin</option>
        </select>
      </div>
    `;
  } else if (op === "ACCESS_REVOKE") {
    fieldsContainer.innerHTML = `
      <div class="form-group">
        <label class="form-label">Repository ID</label>
        <input type="text" id="tx-revoke-repo" class="form-input" placeholder="e.g. gitchain-core">
      </div>
      <div class="form-group">
        <label class="form-label">Subject Public Key (PEM)</label>
        <textarea id="tx-revoke-subject" class="form-textarea" placeholder="-----BEGIN PUBLIC KEY-----..."></textarea>
      </div>
    `;
  }
}

async function signAndStageTx() {
  const actorUsername = document.getElementById("tx-actor-select")?.value;
  const identity = state.identities.find(i => i.username === actorUsername);
  if (!identity) {
    showToast("Please choose an identity to sign the transaction", "error");
    return;
  }

  const op = document.getElementById("tx-op-select")?.value;
  let repository_id = "";
  let payload = {};

  if (op === "USER_CREATE") {
    const username = document.getElementById("tx-user-name")?.value.trim();
    if (!username) return showToast("Username is required", "error");
    repository_id = "";
    payload = {
      username: username,
      identity_id: identity.identity_id || ""
    };
  } else if (op === "REPO_CREATE") {
    const repo = document.getElementById("tx-repo-id")?.value.trim();
    if (!repo) return showToast("Repository ID is required", "error");
    repository_id = repo;
    payload = { repository_id: repo };
  } else if (op === "FILE_CHANGE") {
    const repo = document.getElementById("tx-file-repo")?.value.trim();
    const path = document.getElementById("tx-file-path")?.value.trim();
    const msg = document.getElementById("tx-file-message")?.value.trim() || "commit";
    if (!repo || !path) return showToast("Repository and file path are required", "error");
    repository_id = repo;
    payload = { path: path, message: msg, timestamp: Math.floor(Date.now() / 1000) };
  } else if (op === "ACCESS_GRANT") {
    const repo = document.getElementById("tx-grant-repo")?.value.trim();
    const subject = document.getElementById("tx-grant-subject")?.value.trim();
    const role = document.getElementById("tx-grant-role")?.value;
    if (!repo || !subject) return showToast("Repository and subject key are required", "error");
    repository_id = repo;
    payload = { subject_public_key: subject, role: role };
  } else if (op === "ACCESS_REVOKE") {
    const repo = document.getElementById("tx-revoke-repo")?.value.trim();
    const subject = document.getElementById("tx-revoke-subject")?.value.trim();
    if (!repo || !subject) return showToast("Repository and subject key are required", "error");
    repository_id = repo;
    payload = { subject_public_key: subject };
  }

  const unsignedTx = {
    operation: op,
    actor_public_key: identity.keys.public_key_pem,
    repository_id: repository_id,
    payload: payload,
    signature_hex: ""
  };

  try {
    const res = await fetch("/api/tools/sign-transaction", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        transaction: unsignedTx,
        private_key_pem: identity.keys.private_key_pem
      })
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    state.mempool.push(data.transaction);
    renderMempool();
    showToast(`Signed & staged ${op} transaction!`, "success");
  } catch (err) {
    console.error(err);
    showToast(`Signing failed: ${err.message}`, "error");
  }
}

function renderMempool() {
  const container = document.getElementById("mempool-list");
  const countBadge = document.getElementById("mempool-count");
  if (countBadge) countBadge.textContent = state.mempool.length;
  if (!container) return;

  if (state.mempool.length === 0) {
    container.innerHTML = `<div style="color:var(--text-muted); font-size:0.85rem; padding:1rem; text-align:center;">No pending transactions in mempool. Stage one on the left!</div>`;
    return;
  }

  container.innerHTML = state.mempool.map((tx, idx) => `
    <div style="background:var(--bg-input); border:1px solid var(--border-color); border-radius:8px; padding:0.75rem; margin-bottom:0.75rem;">
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <span class="badge badge-blue">${tx.operation}</span>
        <button class="btn btn-secondary btn-sm" style="color:var(--accent-red);" onclick="removeMempoolTx(${idx})">✕</button>
      </div>
      <div style="font-size:0.75rem; color:var(--text-dim); margin-top:0.4rem;">
        Repo: ${tx.repository_id || '(none)'}
      </div>
      <div class="mono" style="font-size:0.7rem; color:var(--accent); margin-top:0.25rem;">
        Sig: ${truncateHash(tx.signature_hex, 12, 10)}
      </div>
    </div>
  `).join("");
}

function removeMempoolTx(index) {
  state.mempool.splice(index, 1);
  renderMempool();
}

function clearMempool() {
  state.mempool = [];
  renderMempool();
}

// Mining & Block Production
async function startMining() {
  if (state.isMining) return;

  const producerUsername = document.getElementById("mine-producer-select")?.value;
  const producer = state.identities.find(i => i.username === producerUsername);
  if (!producer) {
    showToast("Please choose or create a block producer identity", "error");
    return;
  }

  const height = parseInt(document.getElementById("mine-height")?.value || "0", 10);
  const previousHash = document.getElementById("mine-prev-hash")?.value || "";
  const targetHex = document.getElementById("mine-target")?.value.trim() || "f".repeat(64);
  const maxAttempts = parseInt(document.getElementById("mine-attempts")?.value || "100000", 10);

  state.isMining = true;
  const reactor = document.getElementById("miner-reactor");
  const statusTicker = document.getElementById("mining-status-ticker");
  const gauge = document.getElementById("mining-gauge");
  const hashPreview = document.getElementById("mining-hash-preview");
  const btn = document.getElementById("btn-mine-block");

  if (reactor) reactor.classList.add("mining");
  if (btn) btn.disabled = true;
  if (statusTicker) statusTicker.textContent = "Building block template and hashing nonces...";
  if (gauge) gauge.textContent = "MINING...";

  try {
    // Step 1: Build block template
    const buildRes = await fetch("/api/tools/build-block", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chain_type: "L1",
        chain_id: state.status.chain_id || "L1",
        height: height,
        previous_hash: previousHash,
        target_hex: targetHex,
        transactions: state.mempool,
        producer_public_key: producer.keys.public_key_pem
      })
    });
    if (!buildRes.ok) throw new Error(await buildRes.text());
    const { block } = await buildRes.json();

    // Step 2: Mine block
    const mineRes = await fetch("/api/tools/mine-block", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        block: block,
        private_key_pem: producer.keys.private_key_pem,
        max_attempts: maxAttempts
      })
    });
    if (!mineRes.ok) throw new Error(await mineRes.text());
    const { mined_block, score } = await mineRes.json();

    if (gauge) gauge.textContent = "VALID NONCE!";
    if (hashPreview) hashPreview.textContent = `Hash: ${mined_block.hash_hex}\nScore: ${score}`;
    if (statusTicker) statusTicker.textContent = `Found nonce ${mined_block.header.nonce} in PoW! Submitting to chain...`;

    // Step 3: Submit to chain
    const submitRes = await fetch("/blocks", {
      method: "POST",
      headers: getAuthHeaders(),
      body: JSON.stringify({ block: mined_block })
    });
    if (!submitRes.ok) {
      const errData = await submitRes.json().catch(() => ({}));
      throw new Error(errData.detail || `HTTP ${submitRes.status}`);
    }
    const submitData = await submitRes.json();

    showToast(`Block #${height} mined & accepted onto GitChain!`, "success");
    clearMempool();
    await refreshAll();

  } catch (err) {
    console.error(err);
    if (gauge) gauge.textContent = "FAILED";
    if (statusTicker) statusTicker.textContent = `Error: ${err.message}`;
    showToast(`Mining / submission failed: ${err.message}`, "error");
  } finally {
    state.isMining = false;
    if (reactor) reactor.classList.remove("mining");
    if (btn) btn.disabled = false;
  }
}

// Seed Demo Chain Quickstart
async function seedDemoChain() {
  if (!confirm("Initialize this chain with demo data (Alice, genesis, repo, commit)?")) return;
  showToast("Seeding demo chain, please wait...", "info");
  try {
    const res = await fetch("/api/chain/seed-demo", {
      method: "POST",
      headers: getAuthHeaders()
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    if (data.alice_identity) {
      state.identities.push(data.alice_identity);
      state.activeIdentity = data.alice_identity;
      saveIdentities();
    }
    showToast("Chain successfully initialized with blocks!", "success");
    await refreshAll();
  } catch (err) {
    console.error(err);
    showToast(`Failed to seed chain: ${err.message}`, "error");
  }
}

// API Token Configuration
function openTokenModal() {
  const currentToken = state.apiToken || "";
  const token = prompt("Enter GitChain Bearer API Token (leave empty for unauthenticated dev mode):", currentToken);
  if (token !== null) {
    state.apiToken = token.trim();
    localStorage.setItem("gitchain_api_token", state.apiToken);
    showToast(state.apiToken ? "API Token saved" : "API Token cleared", "info");
  }
}

// Tabs navigation
function switchTab(tabId) {
  document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.classList.toggle("active", btn.getAttribute("data-tab") === tabId);
  });
  document.querySelectorAll(".tab-content").forEach(pane => {
    pane.classList.toggle("active", pane.id === `tab-${tabId}`);
  });
}

// Initialization
document.addEventListener("DOMContentLoaded", () => {
  // Nav Tab clicks
  document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      switchTab(btn.getAttribute("data-tab"));
    });
  });

  // Search input
  const searchInput = document.getElementById("block-search-input");
  if (searchInput) {
    searchInput.addEventListener("input", () => renderBlocks());
  }

  // Load state and initial data
  loadIdentities();
  refreshAll();

  // Polling every 5 seconds
  state.autoRefreshInterval = setInterval(() => {
    if (!state.isMining) {
      fetchChainStatus();
      fetchBlocks();
    }
  }, 5000);
});
