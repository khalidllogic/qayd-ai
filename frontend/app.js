(() => {
  "use strict";

  const state = {
    selectedFile: null,
    selectedTextFile: null,
    items: [],
  };

  // DOM Elements
  const statusDot = document.getElementById("statusDot");
  const statusText = document.getElementById("statusText");
  const apiKeyBanner = document.getElementById("apiKeyBanner");

  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("invoiceFileInput");
  const dropzonePlaceholder = document.getElementById("dropzonePlaceholder");
  const previewWrapper = document.getElementById("previewWrapper");
  const previewImg = document.getElementById("invoicePreviewImg");
  const changeImgBtn = document.getElementById("changeImgBtn");
  const zoomImgBtn = document.getElementById("zoomImgBtn");
  const extractBtn = document.getElementById("extractBtn");
  const loadDemoBtn = document.getElementById("loadDemoBtn");

  const loaderBox = document.getElementById("loaderBox");
  const errorBox = document.getElementById("errorBox");

  const auditCard = document.getElementById("auditCard");
  const auditBadge = document.getElementById("auditBadge");
  const auditSummaryTitle = document.getElementById("auditSummaryTitle");
  const timePill = document.getElementById("timePill");
  const tafqeetValPill = document.getElementById("tafqeetValPill");
  const auditErrorsList = document.getElementById("auditErrorsList");
  const auditWarningsList = document.getElementById("auditWarningsList");

  const vendorNameInput = document.getElementById("vendorName");
  const invoiceNumberInput = document.getElementById("invoiceNumber");
  const invoiceDateInput = document.getElementById("invoiceDate");
  const itemsTableBody = document.getElementById("itemsTableBody");
  const addItemBtn = document.getElementById("addItemBtn");
  const tafqeetTextInput = document.getElementById("tafqeetText");
  const expenseAccountInput = document.getElementById("expenseAccount");
  const subtotalInput = document.getElementById("subtotalInput");
  const discountInput = document.getElementById("discountInput");
  const taxInput = document.getElementById("taxInput");
  const grandTotalInput = document.getElementById("grandTotalInput");

  const reAuditBtn = document.getElementById("reAuditBtn");
  const copyJsonBtn = document.getElementById("copyJsonBtn");
  const exportOdooBtn = document.getElementById("exportOdooBtn");
  const exportExcelBtn = document.getElementById("exportExcelBtn");

  const textFileInput = document.getElementById("textFileInput");
  const extractTextBtn = document.getElementById("extractTextBtn");
  const copyPlainTextBtn = document.getElementById("copyPlainTextBtn");
  const textLoaderBox = document.getElementById("textLoaderBox");
  const textErrorBox = document.getElementById("textErrorBox");
  const plainTextOutput = document.getElementById("plainTextOutput");

  const toastEl = document.getElementById("toast");

  function showToast(message) {
    toastEl.textContent = message;
    toastEl.classList.remove("hidden");
    clearTimeout(toastEl._timer);
    toastEl._timer = setTimeout(() => toastEl.classList.add("hidden"), 3200);
  }

  async function checkSystemHealth() {
    try {
      const res = await fetch("/api/health");
      if (!res.ok) throw new Error("Server error");
      const data = await res.json();
      if (data.api_key_configured) {
        statusDot.className = "status-dot ok";
        statusText.textContent = `متصل (${data.gemini_model})`;
        apiKeyBanner.classList.add("hidden");
      } else {
        statusDot.className = "status-dot warn";
        statusText.textContent = "الخادم متصل (مفتاح API غير مضبوط)";
        apiKeyBanner.classList.remove("hidden");
      }
    } catch {
      statusDot.className = "status-dot err";
      statusText.textContent = "تعذر الاتصال بالخادم";
    }
  }

  // Tabs
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById(btn.dataset.tab).classList.add("active");
    });
  });

  // Image handling
  function handleSelectedFile(file) {
    if (!file) return;
    state.selectedFile = file;
    const reader = new FileReader();
    reader.onload = (e) => {
      previewImg.src = e.target.result;
      dropzonePlaceholder.classList.add("hidden");
      previewWrapper.classList.remove("hidden");
      extractBtn.disabled = false;
      errorBox.classList.add("hidden");
    };
    reader.readAsDataURL(file);
  }

  dropzone.addEventListener("click", (e) => {
    if (e.target.closest(".preview-actions")) return;
    fileInput.click();
  });

  changeImgBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    fileInput.click();
  });

  zoomImgBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    previewImg.classList.toggle("zoomed");
  });

  fileInput.addEventListener("change", (e) => handleSelectedFile(e.target.files[0]));

  dropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropzone.classList.add("dragover");
  });

  dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));

  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleSelectedFile(e.dataTransfer.files[0]);
    }
  });

  // Items table rendering
  function renderItemsTable() {
    if (!state.items.length) {
      itemsTableBody.innerHTML = `
        <tr class="empty-row">
          <td colspan="6">لا توجد أصناف حالياً. ارفع فاتورة أو أضف صنفاً يدوياً.</td>
        </tr>`;
      return;
    }

    itemsTableBody.innerHTML = state.items
      .map(
        (item, idx) => `
      <tr data-index="${idx}">
        <td>${idx + 1}</td>
        <td><input type="text" class="item-name" value="${escapeHtml(item.name)}" /></td>
        <td><input type="number" step="any" class="item-qty" value="${item.quantity}" dir="ltr" /></td>
        <td><input type="number" step="any" class="item-price" value="${item.unit_price}" dir="ltr" /></td>
        <td><input type="number" step="any" class="item-total" value="${item.line_total}" dir="ltr" /></td>
        <td><button type="button" class="btn btn-danger-icon item-del" title="حذف السطر">×</button></td>
      </tr>`
      )
      .join("");
  }

  function escapeHtml(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function syncItemsFromDOM() {
    const rows = itemsTableBody.querySelectorAll("tr[data-index]");
    state.items = Array.from(rows).map((row) => ({
      name: row.querySelector(".item-name").value.trim() || "صنف غير محدد",
      quantity: parseFloat(row.querySelector(".item-qty").value) || 0,
      unit_price: parseFloat(row.querySelector(".item-price").value) || 0,
      line_total: parseFloat(row.querySelector(".item-total").value) || 0,
    }));
  }

  itemsTableBody.addEventListener("input", (e) => {
    const row = e.target.closest("tr[data-index]");
    if (!row) return;
    const idx = Number(row.dataset.index);
    const qty = parseFloat(row.querySelector(".item-qty").value) || 0;
    const price = parseFloat(row.querySelector(".item-price").value) || 0;

    if (e.target.classList.contains("item-qty") || e.target.classList.contains("item-price")) {
      const autoTotal = Math.round(qty * price * 100) / 100;
      row.querySelector(".item-total").value = autoTotal;
    }

    state.items[idx] = {
      name: row.querySelector(".item-name").value,
      quantity: qty,
      unit_price: price,
      line_total: parseFloat(row.querySelector(".item-total").value) || 0,
    };
  });

  itemsTableBody.addEventListener("click", (e) => {
    if (!e.target.classList.contains("item-del")) return;
    syncItemsFromDOM();
    const idx = Number(e.target.closest("tr[data-index]").dataset.index);
    state.items.splice(idx, 1);
    renderItemsTable();
  });

  addItemBtn.addEventListener("click", () => {
    syncItemsFromDOM();
    state.items.push({ name: "", quantity: 1, unit_price: 0, line_total: 0 });
    renderItemsTable();
  });

  function collectInvoicePayload() {
    syncItemsFromDOM();
    return {
      vendor_name: vendorNameInput.value.trim() || null,
      invoice_date: invoiceDateInput.value.trim() || null,
      invoice_number: invoiceNumberInput.value.trim() || null,
      items: state.items,
      subtotal: parseFloat(subtotalInput.value) || 0,
      discount: parseFloat(discountInput.value) || 0,
      tax: parseFloat(taxInput.value) || 0,
      grand_total: parseFloat(grandTotalInput.value) || 0,
      tafqeet_text: tafqeetTextInput.value.trim() || null,
      missing_fields: [],
    };
  }

  function populateInvoiceForm(invoice) {
    vendorNameInput.value = invoice.vendor_name || "";
    invoiceNumberInput.value = invoice.invoice_number || "";
    invoiceDateInput.value = invoice.invoice_date || "";
    state.items = (invoice.items || []).map((i) => ({ ...i }));
    renderItemsTable();
    subtotalInput.value = invoice.subtotal ?? 0;
    discountInput.value = invoice.discount ?? 0;
    taxInput.value = invoice.tax ?? 0;
    grandTotalInput.value = invoice.grand_total ?? 0;
    tafqeetTextInput.value = invoice.tafqeet_text || "";
  }

  function renderAuditResult(audit, processingTimeMs = null) {
    auditCard.className = `card audit-card status-${audit.status}`;
    const labels = {
      valid: "معتمد ومتزن",
      manual_review: "مراجعة يدوية",
      error: "خطأ محاسبي / تعارض",
    };
    auditBadge.textContent = labels[audit.status] || audit.status;
    auditSummaryTitle.textContent = audit.summary_message;

    if (processingTimeMs !== null) {
      timePill.textContent = `⏱ ${processingTimeMs} ms`;
      timePill.classList.remove("hidden");
    }

    if (audit.tafqeet_parsed_value !== null && audit.tafqeet_parsed_value !== undefined) {
      tafqeetValPill.textContent = `التفقيط الرقمي: ${audit.tafqeet_parsed_value}`;
      tafqeetValPill.classList.remove("hidden");
    } else {
      tafqeetValPill.classList.add("hidden");
    }

    if (audit.math_errors && audit.math_errors.length) {
      auditErrorsList.innerHTML = audit.math_errors.map((e) => `<li>${escapeHtml(e)}</li>`).join("");
      auditErrorsList.classList.remove("hidden");
    } else {
      auditErrorsList.classList.add("hidden");
    }

    if (audit.warnings && audit.warnings.length) {
      auditWarningsList.innerHTML = audit.warnings.map((w) => `<li>${escapeHtml(w)}</li>`).join("");
      auditWarningsList.classList.remove("hidden");
    } else {
      auditWarningsList.classList.add("hidden");
    }
  }

  // Extract & Audit from image
  extractBtn.addEventListener("click", async () => {
    if (!state.selectedFile) return;
    extractBtn.disabled = true;
    loaderBox.classList.remove("hidden");
    errorBox.classList.add("hidden");

    const formData = new FormData();
    formData.append("file", state.selectedFile);

    try {
      const res = await fetch("/api/process-invoice", {
        method: "POST",
        body: formData,
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "حدث خطأ أثناء استخراج الفاتورة.");
      }

      populateInvoiceForm(data.invoice);
      renderAuditResult(data.audit_result, data.processing_time_ms);
      showToast("تم استخراج البيانات وتدقيقها بنجاح");
    } catch (err) {
      errorBox.textContent = err.message;
      errorBox.classList.remove("hidden");
    } finally {
      loaderBox.classList.add("hidden");
      extractBtn.disabled = false;
    }
  });

  // Re-audit after manual edits
  async function runReAudit() {
    const payload = collectInvoicePayload();
    try {
      const res = await fetch("/api/audit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error("فشل إعادة التدقيق");
      const audit = await res.json();
      renderAuditResult(audit);
      showToast("تم تحديث نتيجة التدقيق المحاسبي");
    } catch (err) {
      showToast(err.message);
    }
  }

  reAuditBtn.addEventListener("click", runReAudit);

  // Copy JSON
  copyJsonBtn.addEventListener("click", async () => {
    const payload = collectInvoicePayload();
    await navigator.clipboard.writeText(JSON.stringify(payload, null, 2));
    showToast("تم نسخ بيانات الفاتورة بصيغة JSON");
  });

  // Exports
  async function downloadExport(endpoint, defaultFilename) {
    const payload = {
      invoice: collectInvoicePayload(),
      expense_account: expenseAccountInput.value.trim() || "600000 Expenses",
    };

    try {
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error("فشل توليد ملف التصدير");

      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const ref = (payload.invoice.invoice_number || "invoice").replace(/\s+/g, "_");
      a.download = defaultFilename.replace("invoice", ref);
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      showToast("تم تنزيل الملف بنجاح");
    } catch (err) {
      showToast(err.message);
    }
  }

  exportOdooBtn.addEventListener("click", () =>
    downloadExport("/api/export/odoo-csv", "odoo_invoice.csv")
  );
  exportExcelBtn.addEventListener("click", () =>
    downloadExport("/api/export/excel", "qayd_audit_invoice.xlsx")
  );

  // Demo invoice loader
  loadDemoBtn.addEventListener("click", async () => {
    populateInvoiceForm({
      vendor_name: "مؤسسة النور للتوريدات التقنية",
      invoice_number: "INV-2026-104",
      invoice_date: "2026-11-24",
      items: [
        { name: "جهاز كمبيوتر محمول", quantity: 1, unit_price: 200000, line_total: 200000 },
        { name: "طابعة ليزر مكتبية", quantity: 2, unit_price: 45000, line_total: 90000 },
        { name: "حبر طابعة أصلي", quantity: 3, unit_price: 10000, line_total: 30000 },
      ],
      subtotal: 320000,
      discount: 20000,
      tax: 0,
      grand_total: 300000,
      tafqeet_text: "فقط ثلاثمائة ألف ريال لا غير",
    });
    await runReAudit();
  });

  // Plain Text OCR Tab
  textFileInput.addEventListener("change", (e) => {
    state.selectedTextFile = e.target.files[0] || null;
    extractTextBtn.disabled = !state.selectedTextFile;
  });

  extractTextBtn.addEventListener("click", async () => {
    if (!state.selectedTextFile) return;
    extractTextBtn.disabled = true;
    textLoaderBox.classList.remove("hidden");
    textErrorBox.classList.add("hidden");

    const formData = new FormData();
    formData.append("file", state.selectedTextFile);

    try {
      const res = await fetch("/api/extract-text", { method: "POST", body: formData });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "فشل استخراج النص");
      plainTextOutput.value = data.text;
      showToast(`تم استخراج النص (${data.processing_time_ms} ms)`);
    } catch (err) {
      textErrorBox.textContent = err.message;
      textErrorBox.classList.remove("hidden");
    } finally {
      textLoaderBox.classList.add("hidden");
      extractTextBtn.disabled = false;
    }
  });

  copyPlainTextBtn.addEventListener("click", async () => {
    if (!plainTextOutput.value) return;
    await navigator.clipboard.writeText(plainTextOutput.value);
    showToast("تم نسخ النص المستخرج");
  });

  // Init
  checkSystemHealth();
})();
