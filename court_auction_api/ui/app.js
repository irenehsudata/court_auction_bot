const state = {
  slots: [],
  filteredSlots: [],
};

const elements = {
  userIdInput: document.getElementById("userIdInput"),
  playDateSelect: document.getElementById("playDateSelect"),
  adminTokenInput: document.getElementById("adminTokenInput"),
  viewModeSelect: document.getElementById("viewModeSelect"),
  refreshButton: document.getElementById("refreshButton"),
  pendingButton: document.getElementById("pendingButton"),
  statusBanner: document.getElementById("statusBanner"),
  slotCount: document.getElementById("slotCount"),
  openCount: document.getElementById("openCount"),
  pendingCount: document.getElementById("pendingCount"),
  reservedCount: document.getElementById("reservedCount"),
  slotsContainer: document.getElementById("slotsContainer"),
};

function setStatus(message, kind = "neutral") {
  elements.statusBanner.textContent = message;
  elements.statusBanner.className = `status-banner ${kind}`;
}

function formatDate(isoDate) {
  return new Date(`${isoDate}T00:00:00`).toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function formatDateTime(isoValue) {
  return new Date(isoValue).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatTime(timeValue) {
  return timeValue.slice(0, 5);
}

function detailMessage(detail) {
  if (!detail) {
    return "Request failed.";
  }
  if (typeof detail === "string") {
    return detail;
  }
  if (detail.message && detail.minimum_valid_bid) {
    return `${detail.message}. Minimum valid bid: £${detail.minimum_valid_bid}`;
  }
  if (detail.message) {
    return detail.message;
  }
  return JSON.stringify(detail);
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const text = await response.text();
  let data = null;

  if (text) {
    data = JSON.parse(text);
  }

  if (!response.ok) {
    throw new Error(detailMessage(data?.detail));
  }

  return data;
}

function groupByPlayDate(slots) {
  const groups = new Map();
  for (const slot of slots) {
    if (!groups.has(slot.play_date)) {
      groups.set(slot.play_date, []);
    }
    groups.get(slot.play_date).push(slot);
  }
  return Array.from(groups.entries()).sort((a, b) => a[0].localeCompare(b[0]));
}

function updatePlayDateOptions(slots) {
  const currentValue = elements.playDateSelect.value;
  const dates = Array.from(new Set(slots.map((slot) => slot.play_date))).sort();

  elements.playDateSelect.innerHTML = '<option value="">All upcoming dates</option>';
  for (const date of dates) {
    const option = document.createElement("option");
    option.value = date;
    option.textContent = formatDate(date);
    elements.playDateSelect.appendChild(option);
  }

  if (dates.includes(currentValue)) {
    elements.playDateSelect.value = currentValue;
  }
}

function applyFilters() {
  const playDate = elements.playDateSelect.value;
  const viewMode = elements.viewModeSelect.value;
  state.filteredSlots = state.slots.filter((slot) => {
    if (playDate && slot.play_date !== playDate) {
      return false;
    }
    if (viewMode === "pending" && slot.state !== "CLOSED_PENDING_ADMIN") {
      return false;
    }
    return true;
  });
}

function updateStats() {
  const source = state.filteredSlots;
  elements.slotCount.textContent = String(source.length);
  elements.openCount.textContent = String(source.filter((slot) => slot.state === "OPEN").length);
  elements.pendingCount.textContent = String(
    source.filter((slot) => slot.state === "CLOSED_PENDING_ADMIN").length
  );
  elements.reservedCount.textContent = String(source.filter((slot) => slot.state === "RESERVED").length);
}

function renderSlotCard(slot) {
  const userId = elements.userIdInput.value.trim();
  const adminToken = elements.adminTokenInput.value.trim();
  const card = document.createElement("article");
  card.className = "slot-card";

  const highestBid = slot.highest_bid
    ? `£${slot.highest_bid.amount_gbp} by ${slot.highest_bid.user_id}`
    : "No bids yet";
  const reservation = slot.reservation
    ? `£${slot.reservation.amount_gbp} won by ${slot.reservation.user_id}`
    : "No reservation";

  card.innerHTML = `
    <div class="slot-topline">
      <div>
        <div class="slot-time">${formatTime(slot.start_time)}-${formatTime(slot.end_time)}</div>
        <div class="slot-court">${slot.court.name}</div>
      </div>
      <span class="badge ${slot.state}">${slot.state.replaceAll("_", " ")}</span>
    </div>
    <div class="slot-info-grid">
      <div class="info-row">
        <span class="info-label">Play date</span>
        <span class="info-value">${formatDate(slot.play_date)}</span>
      </div>
      <div class="info-row">
        <span class="info-label">Bidding date</span>
        <span class="info-value">${formatDate(slot.bidding_date)}</span>
      </div>
      <div class="info-row">
        <span class="info-label">Window</span>
        <span class="info-value">${formatDateTime(slot.opens_at)} - ${formatDateTime(slot.closes_at)}</span>
      </div>
      <div class="info-row">
        <span class="info-label">Highest bid</span>
        <span class="info-value">${highestBid}</span>
      </div>
      <div class="info-row">
        <span class="info-label">Reservation</span>
        <span class="info-value">${reservation}</span>
      </div>
    </div>
  `;

  const bidForm = document.createElement("form");
  bidForm.className = "bid-form";
  const bidInput = document.createElement("input");
  bidInput.type = "text";
  bidInput.placeholder = "e.g. 10.50";

  const bidButton = document.createElement("button");
  bidButton.type = "submit";
  bidButton.className = "button primary";
  bidButton.textContent = "Place Bid";
  bidButton.disabled = !userId;

  bidForm.appendChild(bidInput);
  bidForm.appendChild(bidButton);
  bidForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!userId) {
      setStatus("Enter a user ID before placing bids.", "error");
      return;
    }
    const amount = bidInput.value.trim();
    if (!amount) {
      setStatus("Enter a bid amount first.", "error");
      return;
    }

    try {
      setStatus(`Submitting bid for slot ${slot.id}...`);
      await requestJson(`/slots/${slot.id}/bids`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-User-Id": userId,
        },
        body: JSON.stringify({ amount_gbp: amount }),
      });
      bidInput.value = "";
      setStatus(`Bid accepted for slot ${slot.id}.`, "success");
      await loadSlots();
    } catch (error) {
      setStatus(error.message, "error");
    }
  });
  card.appendChild(bidForm);

  if (slot.state === "CLOSED_PENDING_ADMIN") {
    const actions = document.createElement("div");
    actions.className = "slot-actions";

    const approveButton = document.createElement("button");
    approveButton.type = "button";
    approveButton.className = "button approve";
    approveButton.textContent = "Approve Winner";
    approveButton.disabled = !adminToken;
    approveButton.addEventListener("click", async () => runAdminAction(slot.id, "approve"));

    const rejectButton = document.createElement("button");
    rejectButton.type = "button";
    rejectButton.className = "button reject";
    rejectButton.textContent = "Reject Slot";
    rejectButton.disabled = !adminToken;
    rejectButton.addEventListener("click", async () => runAdminAction(slot.id, "reject"));

    actions.appendChild(approveButton);
    actions.appendChild(rejectButton);
    card.appendChild(actions);
  }

  return card;
}

function renderSlots() {
  elements.slotsContainer.innerHTML = "";

  if (state.filteredSlots.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "No slots match the current filters.";
    elements.slotsContainer.appendChild(empty);
    updateStats();
    return;
  }

  const groups = groupByPlayDate(state.filteredSlots);
  for (const [playDate, slots] of groups) {
    const section = document.createElement("section");
    const heading = document.createElement("div");
    heading.className = "group-heading";
    heading.innerHTML = `
      <div>
        <h3>${formatDate(playDate)}</h3>
        <p>Bidding opens ${formatDateTime(slots[0].opens_at)} and closes ${formatDateTime(slots[0].closes_at)}</p>
      </div>
      <p>${slots.length} slots shown</p>
    `;

    const grid = document.createElement("div");
    grid.className = "slots-grid";
    for (const slot of slots) {
      grid.appendChild(renderSlotCard(slot));
    }

    section.appendChild(heading);
    section.appendChild(grid);
    elements.slotsContainer.appendChild(section);
  }

  updateStats();
}

async function runAdminAction(slotId, action) {
  const adminToken = elements.adminTokenInput.value.trim();
  if (!adminToken) {
    setStatus("Enter the admin token first.", "error");
    return;
  }

  try {
    setStatus(`${action === "approve" ? "Approving" : "Rejecting"} slot ${slotId}...`);
    await requestJson(`/admin/slots/${slotId}/${action}`, {
      method: "POST",
      headers: {
        "X-Admin-Token": adminToken,
      },
    });
    setStatus(`Slot ${slotId} ${action}d successfully.`, "success");
    await loadSlots();
  } catch (error) {
    setStatus(error.message, "error");
  }
}

async function loadPendingOnly() {
  const adminToken = elements.adminTokenInput.value.trim();
  if (!adminToken) {
    setStatus("Enter the admin token before loading pending approvals.", "error");
    return;
  }

  try {
    setStatus("Loading slots that are pending admin approval...");
    state.slots = await requestJson("/admin/slots?state=CLOSED_PENDING_ADMIN", {
      headers: {
        "X-Admin-Token": adminToken,
      },
    });
    elements.viewModeSelect.value = "pending";
    updatePlayDateOptions(state.slots);
    applyFilters();
    renderSlots();
    setStatus("Pending slots loaded.", "success");
  } catch (error) {
    setStatus(error.message, "error");
  }
}

async function loadSlots() {
  try {
    setStatus("Loading slot data...");
    state.slots = await requestJson("/slots");
    updatePlayDateOptions(state.slots);
    applyFilters();
    renderSlots();
    setStatus("Slots loaded.", "success");
  } catch (error) {
    setStatus(error.message, "error");
  }
}

elements.refreshButton.addEventListener("click", loadSlots);
elements.pendingButton.addEventListener("click", loadPendingOnly);
elements.playDateSelect.addEventListener("change", () => {
  applyFilters();
  renderSlots();
});
elements.viewModeSelect.addEventListener("change", () => {
  applyFilters();
  renderSlots();
});
elements.userIdInput.addEventListener("input", renderSlots);
elements.adminTokenInput.addEventListener("input", renderSlots);

loadSlots();
